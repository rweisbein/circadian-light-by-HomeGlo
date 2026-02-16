#!/usr/bin/env python3
"""Outdoor lux sensor tracking for sun factor modulation.

Module-level singleton (same pattern as glozone.py). Encapsulates all lux
state and provides a cached sun_factor that modulates both natural light
brightness reduction and cool day color shifting.

When no outdoor lux sensor is configured, get_sun_factor() returns 1.0
(current behaviour preserved).
"""

import logging
import math
import time
from typing import Optional

import glozone

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module state
# ---------------------------------------------------------------------------
_sensor_entity: Optional[str] = None
_smoothing_interval: float = 300.0  # seconds (EMA time constant)
_learned_ceiling: Optional[float] = None
_learned_floor: Optional[float] = None

_ema_lux: Optional[float] = None  # smoothed lux value
_last_update_time: Optional[float] = None  # monotonic timestamp of last update
_cached_sun_factor: float = 1.0  # always ready to read


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------
def init(config: Optional[dict] = None):
    """Initialise from configuration.

    Called once at startup after config is loaded.  Safe to call multiple
    times (re-reads config).
    """
    global _sensor_entity, _smoothing_interval, _learned_ceiling, _learned_floor
    global _ema_lux, _last_update_time, _cached_sun_factor

    if config is None:
        config = glozone.load_config_from_files()

    _sensor_entity = config.get("outdoor_lux_sensor") or None
    _smoothing_interval = float(config.get("lux_smoothing_interval", 300))
    _learned_ceiling = config.get("lux_learned_ceiling")
    _learned_floor = config.get("lux_learned_floor")

    # Convert to float if present (may be stored as string from UI)
    if _learned_ceiling is not None:
        try:
            _learned_ceiling = float(_learned_ceiling)
        except (ValueError, TypeError):
            _learned_ceiling = None
    if _learned_floor is not None:
        try:
            _learned_floor = float(_learned_floor)
        except (ValueError, TypeError):
            _learned_floor = None

    # Reset runtime state
    _ema_lux = None
    _last_update_time = None
    _cached_sun_factor = 1.0

    if _sensor_entity:
        logger.info(
            f"Lux tracker initialised: sensor={_sensor_entity}, "
            f"smoothing={_smoothing_interval}s, "
            f"ceiling={_learned_ceiling}, floor={_learned_floor}"
        )
    else:
        logger.info("Lux tracker: no outdoor sensor configured (sun_factor=1.0)")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def get_sun_factor() -> float:
    """Return cached sun factor (0.0 = dark/storm, 1.0 = bright sun).

    Zero-cost read — no computation.  Returns 1.0 when no sensor is
    configured or no data has been received yet.
    """
    return _cached_sun_factor


def get_outdoor_normalized() -> Optional[float]:
    """Return outdoor normalized intensity (0.0–1.0), or None.

    Returns None when no sensor is configured or no data has been
    received yet.  This distinguishes 'no data' (None → caller should
    use angle fallback) from 'dark outside' (0.0).
    """
    if not _sensor_entity:
        return None
    if _learned_ceiling is None or _learned_floor is None:
        return None
    if _ema_lux is None:
        return None
    return _cached_sun_factor


def get_sensor_entity() -> Optional[str]:
    """Return configured outdoor lux sensor entity_id, or None."""
    return _sensor_entity


def update(raw_lux: float) -> float:
    """Process a new raw lux reading.

    Applies EMA smoothing and recomputes the cached sun_factor.

    Returns:
        The new smoothed lux value.
    """
    global _ema_lux, _last_update_time, _cached_sun_factor

    now = time.monotonic()

    if _ema_lux is None or _last_update_time is None:
        # First reading — seed directly
        _ema_lux = raw_lux
    elif _smoothing_interval <= 0:
        # No smoothing — use raw
        _ema_lux = raw_lux
    else:
        dt = now - _last_update_time
        if dt > 0:
            alpha = 1.0 - math.exp(-dt / _smoothing_interval)
            _ema_lux = _ema_lux + alpha * (raw_lux - _ema_lux)

    _last_update_time = now

    # Recompute sun_factor
    if _learned_ceiling is not None and _learned_floor is not None:
        _cached_sun_factor = compute_sun_factor(
            _ema_lux, _learned_ceiling, _learned_floor
        )
    else:
        # No baselines yet — pass through 1.0
        _cached_sun_factor = 1.0

    return _ema_lux


# ---------------------------------------------------------------------------
# Pure computation
# ---------------------------------------------------------------------------
def compute_sun_factor(
    smoothed_lux: float,
    ceiling: float,
    floor: float,
) -> float:
    """Compute sun factor from smoothed lux on a log scale.

    Args:
        smoothed_lux: EMA-smoothed lux value
        ceiling: Bright-day baseline (e.g. 85th percentile)
        floor: Dark-day baseline (e.g. 5th percentile)

    Returns:
        Float clamped to [0.0, 1.0].
    """
    if ceiling <= floor or ceiling <= 0 or floor <= 0:
        return 1.0  # bad baselines — safe fallback

    log_lux = math.log(max(1.0, smoothed_lux))
    log_floor = math.log(max(1.0, floor))
    log_ceiling = math.log(ceiling)

    if log_ceiling <= log_floor:
        return 1.0

    factor = (log_lux - log_floor) / (log_ceiling - log_floor)
    return max(0.0, min(1.0, factor))


# ---------------------------------------------------------------------------
# Baseline learning
# ---------------------------------------------------------------------------
async def learn_baseline(ws_client) -> bool:
    """Query HA recorder for historical lux data and learn ceiling/floor.

    Uses recorder/statistics_during_period for 90 days of hourly-mean lux.
    Filters to daytime hours (sun elevation > 10 deg) using astral library.

    Args:
        ws_client: HomeAssistantWebSocketClient instance (has
                   send_message_wait_response, latitude, longitude, timezone)

    Returns:
        True if baselines were learned and saved.
    """
    global _learned_ceiling, _learned_floor

    if not _sensor_entity:
        return False

    # Skip if user already set explicit overrides
    if _learned_ceiling is not None and _learned_floor is not None:
        logger.info(
            f"Lux baselines already set: ceiling={_learned_ceiling}, "
            f"floor={_learned_floor} — skipping learn"
        )
        return True

    try:
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        lat = getattr(ws_client, "latitude", None)
        lon = getattr(ws_client, "longitude", None)
        tz_name = getattr(ws_client, "timezone", None)

        if not lat or not lon or not tz_name:
            logger.warning("Lux learn_baseline: no location data available")
            return False

        local_tz = ZoneInfo(tz_name)
        now = datetime.now(local_tz)
        start = now - timedelta(days=90)

        # Query recorder statistics
        result = await ws_client.send_message_wait_response(
            {
                "type": "recorder/statistics_during_period",
                "start_time": start.isoformat(),
                "end_time": now.isoformat(),
                "statistic_ids": [_sensor_entity],
                "period": "hour",
                "types": ["mean"],
            }
        )

        if not result or _sensor_entity not in result:
            logger.info(f"Lux learn_baseline: no recorder data for {_sensor_entity}")
            return False

        stats = result[_sensor_entity]

        # Filter to daytime hours (elevation > 10°)
        try:
            from astral import LocationInfo
            from astral.sun import elevation as solar_elevation
        except ImportError:
            logger.warning(
                "Lux learn_baseline: astral library not available — "
                "using all hours (no elevation filter)"
            )
            solar_elevation = None

        daytime_means = []
        for entry in stats:
            mean_val = entry.get("mean")
            if mean_val is None:
                continue
            mean_val = float(mean_val)

            start_str = entry.get("start")
            if not start_str:
                continue

            try:
                dt = datetime.fromisoformat(start_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=local_tz)
                else:
                    dt = dt.astimezone(local_tz)
            except (ValueError, TypeError):
                continue

            # Filter by sun elevation if astral is available
            if solar_elevation is not None:
                try:
                    loc = LocationInfo(latitude=lat, longitude=lon, timezone=tz_name)
                    elev = solar_elevation(loc.observer, dt)
                    if elev <= 10:
                        continue
                except Exception:
                    continue

            daytime_means.append(mean_val)

        if len(daytime_means) < 10:
            logger.info(
                f"Lux learn_baseline: only {len(daytime_means)} daytime "
                f"samples — need at least 10"
            )
            return False

        # Compute percentiles
        daytime_means.sort()
        n = len(daytime_means)
        floor_idx = int(n * 0.05)
        ceiling_idx = int(n * 0.85)
        floor_val = daytime_means[max(0, floor_idx)]
        ceiling_val = daytime_means[min(n - 1, ceiling_idx)]

        if ceiling_val <= floor_val or ceiling_val <= 0:
            logger.warning(
                f"Lux learn_baseline: bad percentiles "
                f"(floor={floor_val}, ceiling={ceiling_val})"
            )
            return False

        _learned_ceiling = ceiling_val
        _learned_floor = floor_val

        # Save back to config
        config = glozone.load_config_from_files()
        config["lux_learned_ceiling"] = _learned_ceiling
        config["lux_learned_floor"] = _learned_floor
        glozone.save_config(config)

        logger.info(
            f"Lux baselines learned from {len(daytime_means)} samples: "
            f"ceiling={_learned_ceiling:.0f}, floor={_learned_floor:.0f}"
        )
        return True

    except Exception as e:
        logger.warning(f"Lux learn_baseline failed: {e}")
        return False
