#!/usr/bin/env python3
"""Outdoor brightness tracking with multi-source fallback chain.

Module-level singleton (same pattern as glozone.py). Encapsulates all outdoor
brightness state and provides get_outdoor_normalized() with a priority-based
fallback chain:

    Override > Lux sensor > Weather entity > Sun angle estimate

When no source is available, falls back to sun-angle-based estimation.
"""

import logging
import math
import time
from typing import Optional

import glozone

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
FULL_SUN_INTENSITY = 8.4  # log2(100000 / 300) — matches brain.py

CONDITION_MULTIPLIERS = {
    "sunny": 1.0,
    "partly_cloudy": 0.6,
    "cloudy": 0.3,
    "heavy_overcast": 0.15,
}

# ---------------------------------------------------------------------------
# Module state — lux sensor
# ---------------------------------------------------------------------------
_sensor_entity: Optional[str] = None
_smoothing_interval: float = 300.0  # seconds (EMA time constant)
_learned_ceiling: Optional[float] = None
_learned_floor: Optional[float] = None

_ema_lux: Optional[float] = None  # smoothed lux value
_last_update_time: Optional[float] = None  # monotonic timestamp of last update
_cached_sun_factor: float = 1.0  # always ready to read

# ---------------------------------------------------------------------------
# Module state — preferred source
# ---------------------------------------------------------------------------
_preferred_source: str = "weather"  # "lux", "weather", or "angle"

# ---------------------------------------------------------------------------
# Module state — weather entity (auto-detected at runtime)
# ---------------------------------------------------------------------------
_weather_entity: Optional[str] = None
_cloud_cover: Optional[float] = None  # 0-100 from weather entity

# ---------------------------------------------------------------------------
# Module state — manual override
# ---------------------------------------------------------------------------
_override_condition: Optional[str] = None  # "sunny", "partly_cloudy", etc.
_override_expires_at: Optional[float] = None  # monotonic timestamp

# ---------------------------------------------------------------------------
# Module state — sun elevation cache
# ---------------------------------------------------------------------------
_sun_elevation: float = 0.0


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
    global _preferred_source, _cloud_cover
    global _override_condition, _override_expires_at
    global _sun_elevation

    if config is None:
        config = glozone.load_config_from_files()

    _sensor_entity = config.get("outdoor_lux_sensor") or None
    _smoothing_interval = float(config.get("lux_smoothing_interval", 300))
    _learned_ceiling = config.get("lux_learned_ceiling")
    _learned_floor = config.get("lux_learned_floor")

    # Determine preferred source (backward compat with legacy configs)
    if "outdoor_brightness_source" in config:
        _preferred_source = config["outdoor_brightness_source"]
    elif _sensor_entity:
        _preferred_source = "lux"
    else:
        _preferred_source = "weather"

    # Weather entity is auto-detected at runtime via set_weather_entity()
    # (don't reset _weather_entity here — it may already be set by main.py)

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
    _cloud_cover = None
    _override_condition = None
    _override_expires_at = None
    _sun_elevation = 0.0

    logger.info(
        f"Lux tracker initialised: source={_preferred_source}, "
        f"sensor={_sensor_entity}, "
        f"smoothing={_smoothing_interval}s, "
        f"ceiling={_learned_ceiling}, floor={_learned_floor}"
    )


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
    """Return outdoor normalized intensity (0.0–1.0) using fallback chain.

    The chain respects _preferred_source:
      - "lux":     override → lux → weather → angle
      - "weather": override → weather → angle
      - "angle":   override → angle

    Always returns a float (the fallback chain guarantees a value).
    """
    # 1. Override always wins
    info = get_override_info()  # auto-clears expired
    if info:
        mult = CONDITION_MULTIPLIERS.get(_override_condition, 1.0)
        return _compute_angle_outdoor_norm() * mult

    # 2. Source-dependent chain
    if _preferred_source == "lux":
        if _sensor_entity and _learned_ceiling and _learned_floor and _ema_lux is not None:
            return _cached_sun_factor
        # fallthrough to weather, then angle
        weather_norm = _compute_weather_outdoor_norm()
        if weather_norm is not None:
            return weather_norm
        return _compute_angle_outdoor_norm()

    if _preferred_source == "weather":
        weather_norm = _compute_weather_outdoor_norm()
        if weather_norm is not None:
            return weather_norm
        return _compute_angle_outdoor_norm()

    # "angle"
    return _compute_angle_outdoor_norm()


def get_outdoor_source() -> str:
    """Return which source is currently active in the fallback chain.

    Respects _preferred_source — e.g. if source is "weather", lux data
    is ignored even when available.
    """
    info = get_override_info()
    if info:
        return "override"

    if _preferred_source == "lux":
        if _sensor_entity and _learned_ceiling and _learned_floor and _ema_lux is not None:
            return "lux"
        if _weather_entity and _cloud_cover is not None:
            return "weather"
        return "angle"

    if _preferred_source == "weather":
        if _weather_entity and _cloud_cover is not None:
            return "weather"
        return "angle"

    return "angle"


def get_preferred_source() -> str:
    """Return the user-selected preferred source."""
    return _preferred_source


def get_sensor_entity() -> Optional[str]:
    """Return configured outdoor lux sensor entity_id, or None."""
    return _sensor_entity


def get_weather_entity() -> Optional[str]:
    """Return auto-detected weather entity_id, or None."""
    return _weather_entity


def set_weather_entity(entity_id: str):
    """Set the auto-detected weather entity (called by main.py at startup)."""
    global _weather_entity
    _weather_entity = entity_id


# ---------------------------------------------------------------------------
# Weather entity
# ---------------------------------------------------------------------------
def update_weather(cloud_cover: float):
    """Store cloud coverage from HA weather entity (0-100)."""
    global _cloud_cover
    _cloud_cover = max(0.0, min(100.0, cloud_cover))


def update_sun_elevation(elevation: float):
    """Cache sun elevation (degrees) for angle-based fallback."""
    global _sun_elevation
    _sun_elevation = elevation


# ---------------------------------------------------------------------------
# Manual override
# ---------------------------------------------------------------------------
def set_override(condition: str, duration_minutes: int = 60):
    """Set a temporary outdoor condition override."""
    global _override_condition, _override_expires_at
    if condition not in CONDITION_MULTIPLIERS:
        return
    _override_condition = condition
    _override_expires_at = time.monotonic() + duration_minutes * 60


def clear_override():
    """Clear the manual override."""
    global _override_condition, _override_expires_at
    _override_condition = None
    _override_expires_at = None


def get_override_info() -> Optional[dict]:
    """Return active override info, or None if expired/inactive."""
    global _override_condition, _override_expires_at
    if _override_condition is None or _override_expires_at is None:
        return None
    remaining = _override_expires_at - time.monotonic()
    if remaining <= 0:
        _override_condition = None
        _override_expires_at = None
        return None
    return {
        "condition": _override_condition,
        "expires_in_minutes": round(remaining / 60, 1),
    }


# ---------------------------------------------------------------------------
# Internal computation helpers
# ---------------------------------------------------------------------------
def _compute_weather_outdoor_norm() -> Optional[float]:
    """Compute outdoor normalized from weather entity cloud coverage."""
    if _weather_entity is None or _cloud_cover is None:
        return None
    cloud_fraction = _cloud_cover / 100.0
    condition_mult = 1.0 - cloud_fraction * 0.85  # 0% → 1.0, 100% → 0.15
    elev = _sun_elevation
    clear_sky_lux = 120000.0 * max(0.0, math.sin(math.radians(elev)))
    estimated_lux = clear_sky_lux * condition_mult
    if estimated_lux <= 0:
        return 0.0
    return min(1.0, math.log2(max(1, estimated_lux) / 300) / FULL_SUN_INTENSITY)


def _compute_angle_outdoor_norm() -> float:
    """Compute outdoor normalized from sun elevation (clear-sky model)."""
    elev = _sun_elevation
    est_lux = 120000.0 * max(0.0, math.sin(math.radians(elev)))
    if est_lux <= 0:
        return 0.0
    return min(1.0, math.log2(max(1, est_lux) / 300) / FULL_SUN_INTENSITY)


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

            start_val = entry.get("start")
            if not start_val:
                continue

            try:
                if isinstance(start_val, (int, float)):
                    dt = datetime.fromtimestamp(start_val, tz=local_tz)
                else:
                    dt = datetime.fromisoformat(start_val)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=local_tz)
                    else:
                        dt = dt.astimezone(local_tz)
            except (ValueError, TypeError, OSError):
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
