#!/usr/bin/env python3
"""State management for Circadian Light - per-area runtime state.

This module manages per-area runtime state that can diverge from the global
config through button presses (step up/down, bright up/down, etc.).

State is:
- Loaded from JSON at startup
- Held in memory for fast access
- Written to JSON immediately after changes
- Reset on phase changes (ascend/descend) and on config save
"""

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# In-memory state dict
_state: Dict[str, Dict[str, Any]] = {}

# Path to state file (set during init)
_state_file_path: Optional[str] = None


def _get_default_area_state() -> Dict[str, Any]:
    """Return default state for a new area.

    Only one phase (Ascend/Descend) is active at a time, so we only need
    one midpoint per axis rather than separate wake/bed values.
    """
    return {
        "is_circadian": False,  # Whether Circadian Light controls this area
        "is_on": False,  # Target light power state (only meaningful when is_circadian is True)
        # frozen_at: None = unfrozen, float = frozen at that hour (0-24)
        "frozen_at": None,
        # frozen_until: None = indefinite freeze (or unfrozen). ISO timestamp = auto-unfreeze at that moment.
        "frozen_until": None,
        # Midpoints (None = use config wake_time/bed_time based on phase)
        "brightness_mid": None,
        "color_mid": None,
        # Solar rule target offset (Kelvin) from color stepping/slider
        "color_override": None,
        # Per-axis overrides with time-based decay (additive deltas)
        "brightness_override": None,  # Brightness delta in % points
        "brightness_override_set_at": None,  # Hour when set (for decay calc)
        "color_override_set_at": None,  # Hour when color override set (for decay)
        # Last-sent values (for 2-step detection and state tracking)
        "last_sent_kelvin": None,  # Kelvin we last sent (persists through on/off)
        "last_sent_kelvin_at": None,  # Unix timestamp when last_sent_kelvin was last written. Diagnostic for stale-state debugging (e.g., cross-addon ZHA pollution).
        "last_sent_brightness": None,  # Area-level brightness % (post curve+boost+sun_bright+area_factor+override, pre-filter)
        # Boost state
        "boost_started_from_off": False,  # If true, turn off when boost ends; else restore circadian
        "boost_expires_at": None,  # ISO timestamp string when boost expires (None = not boosted, 0 = forever)
        "boost_brightness": None,  # Current boost brightness percentage (None = not boosted)
        # Auto-off timer (lights turn off when this expires; set by motion
        # sensors via motion_on_off OR by the user via set_auto_off picker).
        "auto_off_at": None,  # ISO timestamp; None = no timer; "forever" = no expiry
        # Motion warning state
        "motion_warning_at": None,  # ISO timestamp when warning was triggered (None = not warned)
        "motion_pre_warning_brightness": None,  # Brightness % before warning (to restore if motion detected)
        # Off enforcement (periodic loop optimization)
        "off_enforced": False,  # True once we've verified all lights are off; skip re-sending off commands
        "off_confirm_count": 0,  # Counter for consecutive off confirmations before setting off_enforced
        # Fade state (smooth transitions between any lighting states)
        "fade_start": None,  # ISO timestamp when fade began
        "fade_duration": None,  # Duration in seconds
        "fade_direction": None,  # "in" or "out"
        "fade_target_preset": None,  # "circadian", "nitelite", "britelite", or "off"
        "fade_start_brightness": None,  # Brightness % at fade start (0 if off)
        "fade_start_kelvin": None,  # Kelvin at fade start (warm default if off)
        # User interaction tracking (for auto-off "only if untouched" guard)
        "last_user_action_at": None,  # ISO timestamp of last user-initiated action
    }


def _get_data_directory() -> str:
    """Get the appropriate data directory based on environment."""
    # Prefer /config/circadian-light (visible in HA config folder, included in backups)
    if os.path.exists("/config"):
        data_dir = "/config/circadian-light"
        os.makedirs(data_dir, exist_ok=True)
        return data_dir
    elif os.path.exists("/data"):
        # Fallback to /data
        return "/data"
    else:
        # Running in development - use local .data directory
        data_dir = os.path.join(os.path.dirname(__file__), ".data")
        os.makedirs(data_dir, exist_ok=True)
        return data_dir


def init(state_file: Optional[str] = None) -> None:
    """Initialize the state module and load state from disk.

    Args:
        state_file: Optional path to state file. If not provided, uses default location.
    """
    global _state_file_path, _state

    if state_file:
        _state_file_path = state_file
    else:
        _state_file_path = os.path.join(_get_data_directory(), "circadian_state.json")

    _state = {}

    if os.path.exists(_state_file_path):
        try:
            with open(_state_file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if isinstance(data, dict) and "areas" in data:
                _state = data.get("areas", {})
                logger.info(f"Loaded state for {len(_state)} area(s) from {_state_file_path}")
                # Migration: motion_expires_at → auto_off_at. Single unified
                # field for any auto-off timer regardless of source (motion
                # sensor or user-set picker). If both exist, prefer the later
                # timestamp (or "forever" beats any timestamp).
                migrated = 0
                for area_id, s in _state.items():
                    if "motion_expires_at" not in s:
                        continue
                    legacy = s.pop("motion_expires_at")
                    current = s.get("auto_off_at")
                    if legacy is None and current is None:
                        s["auto_off_at"] = None
                    elif current is None:
                        s["auto_off_at"] = legacy
                    elif legacy is None:
                        pass  # current wins
                    elif current == "forever" or legacy == "forever":
                        s["auto_off_at"] = "forever"
                    else:
                        s["auto_off_at"] = max(current, legacy)
                    migrated += 1
                if migrated:
                    logger.info(f"Migrated motion_expires_at → auto_off_at on {migrated} area(s)")
                    _save()
            else:
                logger.warning(f"Invalid state file format at {_state_file_path}, starting fresh")

        except Exception as e:
            logger.warning(f"Failed to load state from {_state_file_path}: {e}")
    else:
        logger.info(f"No state file found at {_state_file_path}, starting fresh")


def _save() -> None:
    """Save current state to disk."""
    if not _state_file_path:
        logger.error("State module not initialized, cannot save")
        return

    try:
        data = {"areas": _state}
        with open(_state_file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        logger.debug(f"Saved state to {_state_file_path}")
    except Exception as e:
        logger.error(f"Failed to save state to {_state_file_path}: {e}")


def get_area(area_id: str) -> Dict[str, Any]:
    """Get state for an area.

    Args:
        area_id: The area ID

    Returns:
        Dict with area state. If area doesn't exist, returns default state.
    """
    if area_id not in _state:
        return _get_default_area_state()

    # Merge with defaults to ensure all fields exist
    default = _get_default_area_state()
    default.update(_state[area_id])
    return default


def update_area(area_id: str, updates: Dict[str, Any]) -> None:
    """Update state for an area.

    Args:
        area_id: The area ID
        updates: Dict of fields to update
    """
    if area_id not in _state:
        _state[area_id] = _get_default_area_state()

    _state[area_id].update(updates)
    _save()
    logger.debug(f"Updated state for area {area_id}: {updates}")


def set_is_circadian(area_id: str, is_circadian_val: bool) -> None:
    """Set whether Circadian Light controls an area.

    Most settings persist across circadian_off → circadian_on cycles
    (midpoints, frozen_at, is_on, overrides, etc.). EXCEPTION:
    `last_sent_kelvin` (and its timestamp) is cleared on transition
    True → False, because turning circadian off explicitly signals
    "I'm giving up control of this area" — another addon, an
    automation, or a user might touch the bulb while we're not
    watching. On re-enable, the next 2-step gate sees prev_kelvin
    as unknown and forces 2-step to safely re-establish color
    (rather than skipping 2-step on a stale / now-wrong CT memory).

    Args:
        area_id: The area ID
        is_circadian_val: Whether Circadian Light should control this area
    """
    was_circadian = is_circadian(area_id)

    # Ensure area exists in state
    if area_id not in _state:
        _state[area_id] = _get_default_area_state()

    updates = {"is_circadian": is_circadian_val}
    if was_circadian and not is_circadian_val:
        # Forget the bulb's CT — see docstring.
        updates["last_sent_kelvin"] = None
        updates["last_sent_kelvin_at"] = None
    update_area(area_id, updates)

    if is_circadian_val and not was_circadian:
        logger.info(f"Circadian Light enabled for area {area_id}")
    elif not is_circadian_val and was_circadian:
        logger.info(
            f"Circadian Light disabled for area {area_id} "
            f"(cleared last_sent_kelvin so re-enable forces 2-step)"
        )


def set_frozen_at(area_id: str, frozen_at: Optional[float]) -> None:
    """Set the frozen time for an area.

    When frozen_at is set, calculations use that hour instead of current time.
    Periodic updates still run but output the same values. Unfreezing also
    clears frozen_until so a stale auto-expire doesn't reappear next freeze.

    Args:
        area_id: The area ID
        frozen_at: Hour to freeze at (0-24), or None to unfreeze
    """
    updates: Dict[str, Any] = {"frozen_at": frozen_at}
    if frozen_at is None:
        updates["frozen_until"] = None
    update_area(area_id, updates)
    if frozen_at is not None:
        logger.info(f"Area {area_id} frozen at hour {frozen_at:.2f}")
    else:
        logger.info(f"Area {area_id} unfrozen")


def get_frozen_at(area_id: str) -> Optional[float]:
    """Get the frozen time for an area.

    Returns:
        The frozen hour (0-24), or None if not frozen.
    """
    return get_area(area_id).get("frozen_at")


def set_frozen_until(area_id: str, frozen_until: Optional[str]) -> None:
    """Set the auto-unfreeze timestamp for an area.

    Args:
        area_id: The area ID
        frozen_until: ISO timestamp when freeze should auto-expire, or None for indefinite.
    """
    update_area(area_id, {"frozen_until": frozen_until})
    if frozen_until is not None:
        logger.info(f"Area {area_id} freeze auto-expires at {frozen_until}")


def get_frozen_until(area_id: str) -> Optional[str]:
    """Get the auto-unfreeze timestamp for an area (or None for indefinite)."""
    return get_area(area_id).get("frozen_until")


def get_expired_freezes() -> List[str]:
    """Return area_ids whose frozen_until has passed.

    Skips areas with frozen_until == None (indefinite freeze) or where the
    area isn't actually frozen.
    """
    from datetime import datetime

    now = datetime.now().isoformat()
    expired = []
    for area_id, s in _state.items():
        if s.get("frozen_at") is None:
            continue
        until = s.get("frozen_until")
        if not until:
            continue
        if until <= now:
            expired.append(area_id)
    return expired


def is_circadian(area_id: str) -> bool:
    """Check if Circadian Light controls an area."""
    return get_area(area_id).get("is_circadian", False)


def set_is_on(area_id: str, is_on: bool) -> None:
    """Set the target light power state for an area.

    When setting is_on=False, also resets off_enforced and off_confirm_count
    to enable the redundant off command grace period.

    Args:
        area_id: The area ID
        is_on: Whether lights should be on
    """
    updates = {"is_on": is_on}
    if not is_on:
        # Reset off enforcement so periodic update sends redundant offs
        updates["off_enforced"] = False
        updates["off_confirm_count"] = 0
        # Clear any auto-off timer — stale auto_off_at would otherwise
        # surface on the next power-on as a phantom "6d left" sub-line.
        updates["auto_off_at"] = None
    update_area(area_id, updates)
    logger.debug(f"Area {area_id} is_on set to {is_on}")


def get_is_on(area_id: str) -> bool:
    """Get the target light power state for an area."""
    return get_area(area_id).get("is_on", False)


def enable_circadian_and_set_on(area_id: str, is_on: bool) -> bool:
    """Enable Circadian control for an area and set is_on state.

    This is the main entry point for lights_on, lights_off, lights_toggle.
    Preserves all settings (midpoints, frozen_at, etc.) - no reset.

    Args:
        area_id: The area ID
        is_on: Target light power state

    Returns:
        True if is_circadian was already True, False if it was False
    """
    was_circadian = is_circadian(area_id)

    # Enable circadian control (preserves settings)
    set_is_circadian(area_id, True)

    # Set is_on to the desired value
    set_is_on(area_id, is_on)

    return was_circadian


def is_frozen(area_id: str) -> bool:
    """Check if an area is frozen."""
    return get_area(area_id).get("frozen_at") is not None


def set_last_sent_kelvin(area_id: str, kelvin: int) -> None:
    """Store the kelvin we last sent to this area (persists through on/off).
    Also stamps `last_sent_kelvin_at` so the 2-step diagnostic can show how
    fresh the tracked value is (helps spot stale state when cross-addon
    pollution or external commands have written to the bulbs since)."""
    update_area(area_id, {
        "last_sent_kelvin": kelvin,
        "last_sent_kelvin_at": time.time(),
    })


def get_last_sent_kelvin(area_id: str) -> Optional[int]:
    """Get the kelvin we last sent to this area."""
    return get_area(area_id).get("last_sent_kelvin")


def get_last_sent_kelvin_at(area_id: str) -> Optional[float]:
    """Get the Unix timestamp when last_sent_kelvin was last written, or
    None if never set. Used by the 2-step diagnostic log."""
    return get_area(area_id).get("last_sent_kelvin_at")


def format_age_short(timestamp: Optional[float]) -> str:
    """Compact age formatter for diagnostic logs: "5s ago", "3m ago",
    "2h ago", "4d ago". Returns "never" for None."""
    if timestamp is None:
        return "never"
    diff = time.time() - timestamp
    if diff < 0:
        return "future"
    if diff < 60:
        return f"{int(diff)}s ago"
    if diff < 3600:
        return f"{int(diff / 60)}m ago"
    if diff < 86400:
        return f"{int(diff / 3600)}h ago"
    return f"{int(diff / 86400)}d ago"


def set_last_sent_brightness(area_id: str, brightness: int) -> None:
    """Store area-level brightness (post curve+boost+sun_bright+area_factor+override, pre-filter)."""
    update_area(area_id, {"last_sent_brightness": brightness})


def get_last_sent_brightness(area_id: str) -> Optional[int]:
    """Get area-level brightness we last sent."""
    return get_area(area_id).get("last_sent_brightness")


# Per-purpose last-sent cache (in-memory only, not persisted to disk)
_purpose_cache: Dict[str, Dict[str, dict]] = {}  # area_id -> {purpose: {brightness, kelvin, is_off}}


def set_last_sent_purpose(
    area_id: str, purpose: str, brightness: int, kelvin: int, is_off: bool = False
) -> None:
    """Store per-purpose brightness/kelvin/off state after sending to lights."""
    if area_id not in _purpose_cache:
        _purpose_cache[area_id] = {}
    _purpose_cache[area_id][purpose] = {
        "brightness": brightness, "kelvin": kelvin, "is_off": is_off
    }


def get_last_sent_purpose(area_id: str, purpose: str) -> Optional[dict]:
    """Get per-purpose last-sent state: {brightness, kelvin, is_off}."""
    return _purpose_cache.get(area_id, {}).get(purpose)


def get_last_sent_purposes(area_id: str) -> dict:
    """Get all per-purpose last-sent states."""
    return _purpose_cache.get(area_id, {})


def get_circadian_areas() -> List[str]:
    """Get list of all areas under Circadian Light control."""
    return [area_id for area_id, s in _state.items() if s.get("is_circadian", False)]


def get_circadian_areas_for_update() -> List[str]:
    """Get list of areas under Circadian control for periodic updates.

    Returns all is_circadian=True areas regardless of frozen status,
    since all areas need periodic updates (frozen areas use frozen_at time).
    """
    return [
        area_id for area_id, s in _state.items()
        if s.get("is_circadian", False)
    ]


def get_circadian_on_areas() -> List[str]:
    """Get list of areas with is_circadian=True and is_on=True."""
    return [
        area_id for area_id, s in _state.items()
        if s.get("is_circadian", False) and s.get("is_on", False)
    ]


def reset_area(area_id: str) -> None:
    """Reset an area's runtime state to defaults (midpoints, bounds, frozen_at).

    Preserves is_circadian and is_on status. Clears frozen_at (unfreezes).

    Args:
        area_id: The area ID
    """
    if area_id not in _state:
        return

    current = _state[area_id]
    preserved = {
        "is_circadian": current.get("is_circadian", False),
        "is_on": current.get("is_on", False),
        # frozen_at is NOT preserved - reset clears it
        # last_sent_kelvin IS preserved - it's a physical bulb fact, not runtime state
        "last_sent_kelvin": current.get("last_sent_kelvin"),
        "last_sent_kelvin_at": current.get("last_sent_kelvin_at"),
    }

    _state[area_id] = _get_default_area_state()
    _state[area_id].update(preserved)
    _save()
    logger.info(f"Reset runtime state for area {area_id}")


def reset_all_areas() -> None:
    """Reset runtime state for all areas (midpoints only).

    Called at phase transitions (ascend/descend). Preserves is_circadian, is_on, and frozen status.
    Use reset_area() for explicit user resets that should clear frozen.
    """
    for area_id in list(_state.keys()):
        current = _state[area_id]
        preserved = {
            "is_circadian": current.get("is_circadian", False),
            "is_on": current.get("is_on", False),
            "frozen_at": current.get("frozen_at"),  # Preserve frozen state
            "last_sent_kelvin": current.get("last_sent_kelvin"),  # Physical bulb fact
            "last_sent_kelvin_at": current.get("last_sent_kelvin_at"),
        }
        _state[area_id] = _get_default_area_state()
        _state[area_id].update(preserved)
    _save()
    logger.info(f"Reset midpoints for all {len(_state)} area(s) (frozen state preserved)")


def remove_area(area_id: str) -> None:
    """Remove an area from state entirely.

    Args:
        area_id: The area ID
    """
    if area_id in _state:
        del _state[area_id]
        _save()
        logger.info(f"Removed area {area_id} from state")


def get_all_areas() -> Dict[str, Dict[str, Any]]:
    """Get state for all areas.

    Returns:
        Dict mapping area_id to state dict
    """
    return {area_id: get_area(area_id) for area_id in _state}


def get_all_area_ids() -> List[str]:
    """Return all tracked area IDs."""
    return list(_state.keys())


def get_runtime_state(area_id: str) -> Dict[str, Any]:
    """Get just the runtime state (midpoints, frozen_at) for an area.

    This excludes is_circadian and is_on which are not part of zone sync.

    Args:
        area_id: The area ID

    Returns:
        Dict with brightness_mid, color_mid, frozen_at
    """
    area = get_area(area_id)
    return {
        "brightness_mid": area.get("brightness_mid"),
        "color_mid": area.get("color_mid"),
        "color_override": area.get("color_override"),
        "brightness_override": area.get("brightness_override"),
        "brightness_override_set_at": area.get("brightness_override_set_at"),
        "color_override_set_at": area.get("color_override_set_at"),
        "frozen_at": area.get("frozen_at"),
    }


def set_runtime_state(area_id: str, runtime_state: Dict[str, Any]) -> None:
    """Set the runtime state (midpoints, frozen_at) for an area.

    This does NOT change is_circadian or is_on status.

    Args:
        area_id: The area ID
        runtime_state: Dict with brightness_mid, color_mid, frozen_at
    """
    updates = {}
    for key in ["brightness_mid", "color_mid", "color_override",
                "brightness_override", "brightness_override_set_at",
                "color_override_set_at", "frozen_at"]:
        if key in runtime_state:
            updates[key] = runtime_state[key]

    if updates:
        update_area(area_id, updates)
        logger.debug(f"Set runtime state for area {area_id}: {updates}")


def copy_state_from_zone(area_id: str, zone_state: Dict[str, Any]) -> None:
    """Copy zone runtime state to an area.

    Used by GloDown and lights_toggle (on enable).
    Does NOT change is_circadian or is_on status.

    Args:
        area_id: The area ID
        zone_state: Zone's runtime state (brightness_mid, color_mid, frozen_at)
    """
    set_runtime_state(area_id, zone_state)
    logger.info(f"Copied zone state to area {area_id}")


def reset_area_to_defaults(area_id: str) -> None:
    """Reset an area's runtime state to defaults (None for midpoints and frozen_at).

    Preserves is_circadian and is_on status. Used when resetting to preset defaults.

    Args:
        area_id: The area ID
    """
    if area_id not in _state:
        return

    is_circ = _state[area_id].get("is_circadian", False)
    is_on = _state[area_id].get("is_on", False)
    _state[area_id] = _get_default_area_state()
    _state[area_id]["is_circadian"] = is_circ
    _state[area_id]["is_on"] = is_on
    _save()
    logger.info(f"Reset area {area_id} runtime state to defaults (preserving is_circadian={is_circ}, is_on={is_on})")


# ============================================================================
# Boost state management
# ============================================================================

def set_boost(area_id: str, started_from_off: bool, expires_at: str, brightness: int) -> None:
    """Set boost state for an area.

    Args:
        area_id: The area ID
        started_from_off: Whether lights were off when boost started
        expires_at: ISO timestamp string when boost expires (None for forever)
        brightness: Boost brightness percentage
    """
    update_area(area_id, {
        "boost_started_from_off": started_from_off,
        "boost_expires_at": expires_at,
        "boost_brightness": brightness,
    })
    logger.info(f"Boost activated for area {area_id} (started_from_off={started_from_off}, brightness={brightness}%, expires={expires_at})")


def clear_boost(area_id: str) -> None:
    """Clear boost state for an area.

    Args:
        area_id: The area ID
    """
    update_area(area_id, {
        "boost_started_from_off": False,
        "boost_expires_at": None,
        "boost_brightness": None,
    })
    logger.info(f"Boost cleared for area {area_id}")


def is_boosted(area_id: str) -> bool:
    """Check if an area is currently boosted.

    Returns True if boost_expires_at is set (either a timestamp or "forever").
    """
    expires_at = get_area(area_id).get("boost_expires_at")
    return expires_at is not None


def is_boost_forever(area_id: str) -> bool:
    """Check if an area has a forever (non-timed) boost."""
    return get_area(area_id).get("boost_expires_at") == "forever"


def is_boost_motion_coupled(area_id: str) -> bool:
    """Check if an area's boost is coupled to its motion timer.

    When boost is triggered by a motion/contact sensor, boost_expires_at is set
    to "motion" instead of a timestamp. The boost ends only when the auto-off
    timer expires (via fire_auto_off), not independently.
    """
    return get_area(area_id).get("boost_expires_at") == "motion"


def get_boost_state(area_id: str) -> Dict[str, Any]:
    """Get boost state for an area.

    Returns:
        Dict with is_boosted, is_forever, boost_started_from_off, boost_expires_at, boost_brightness
    """
    area = get_area(area_id)
    expires_at = area.get("boost_expires_at")
    return {
        "is_boosted": expires_at is not None,
        "is_forever": expires_at == "forever",
        "is_motion_coupled": expires_at == "motion",
        "boost_started_from_off": area.get("boost_started_from_off", False),
        "boost_expires_at": expires_at,
        "boost_brightness": area.get("boost_brightness"),
    }


def update_boost_brightness(area_id: str, brightness: int) -> None:
    """Update just the boost brightness for an area (for MAX logic).

    Args:
        area_id: The area ID
        brightness: New boost brightness percentage
    """
    update_area(area_id, {"boost_brightness": brightness})
    logger.info(f"Boost brightness updated to {brightness}% for area {area_id}")


def update_boost_expires(area_id: str, expires_at: str) -> None:
    """Update just the boost expiry for an area (for MAX timer logic).

    Args:
        area_id: The area ID
        expires_at: New expiry timestamp (or "forever")
    """
    update_area(area_id, {"boost_expires_at": expires_at})
    logger.info(f"Boost expiry updated to {expires_at} for area {area_id}")


def get_boosted_areas() -> List[str]:
    """Get list of all areas with active boost."""
    return [area_id for area_id, s in _state.items() if s.get("boost_expires_at") is not None]


def get_expired_boosts() -> List[str]:
    """Get list of areas with expired boosts (boost_expires_at in the past).

    Skips "forever" boosts which never expire.

    Returns:
        List of area_ids with expired boosts
    """
    from datetime import datetime

    now = datetime.now().isoformat()
    expired = []

    for area_id, s in _state.items():
        expires_at = s.get("boost_expires_at")
        # Skip if not boosted, forever boost, or motion-coupled boost
        if not expires_at or expires_at == "forever" or expires_at == "motion":
            continue
        if expires_at <= now:
            expired.append(area_id)

    return expired


# ============================================================================
# Auto-off timer (single field; sources include motion sensors via motion_on_off
# and explicit user picks via set_auto_off). Reasons for one field across both:
# motion's MAX-extend semantics (primitives.bright_boost-style) preserve a
# longer user-set timer when sensor pings would otherwise shorten it. Storing
# only one timestamp keeps the periodic expiry tick simple.
# ============================================================================

def set_auto_off_at(area_id: str, expires_at: Optional[str]) -> None:
    """Set the auto-off timer for an area.

    Args:
        area_id: The area ID
        expires_at: ISO timestamp string when lights should turn off, "forever"
            for no expiry, or None to clear.
    """
    update_area(area_id, {"auto_off_at": expires_at})
    if expires_at is not None:
        logger.info(f"Auto-off timer set for area {area_id} (expires={expires_at})")
    else:
        logger.info(f"Auto-off timer cleared for area {area_id}")


def clear_auto_off_at(area_id: str) -> None:
    """Clear the auto-off timer for an area (no-op if not set)."""
    if get_area(area_id).get("auto_off_at") is not None:
        update_area(area_id, {"auto_off_at": None})
        logger.info(f"Auto-off timer cleared for area {area_id}")


def extend_auto_off_at(area_id: str, expires_at: str) -> None:
    """Extend / replace the auto-off timer (caller chose MAX semantics already)."""
    update_area(area_id, {"auto_off_at": expires_at})
    logger.debug(f"Auto-off timer extended for area {area_id} (expires={expires_at})")


def has_auto_off_timer(area_id: str) -> bool:
    """True when an auto-off timer is currently set."""
    return get_area(area_id).get("auto_off_at") is not None


def get_auto_off_at(area_id: str) -> Optional[str]:
    """Return the auto-off timer expiry ISO string (or "forever" or None)."""
    return get_area(area_id).get("auto_off_at")


# ----------------------------------------------------------------------------
# Transient 2-step marker — set by main.py:send_light when it fires the
# pre-color 2-step path, read+cleared by the calling primitive when it
# records its turn_on history entry. Purely in-memory; no disk persistence.
# Race-free in practice because each send_light call sets the flag and the
# caller awaits the same send_light before reading.
# ----------------------------------------------------------------------------

_last_2step: Dict[str, bool] = {}


def mark_last_2step(area_id: str, was_2step: bool) -> None:
    """Stamp whether the most recent send_light for this area used 2-step."""
    _last_2step[area_id] = bool(was_2step)


def pop_last_2step(area_id: str) -> bool:
    """Read+clear the 2-step marker. Returns False when unset."""
    return _last_2step.pop(area_id, False)


def get_expired_auto_off() -> List[str]:
    """Return area_ids whose auto_off_at has passed (excludes "forever")."""
    from datetime import datetime

    now = datetime.now().isoformat()
    expired = []

    for area_id, s in _state.items():
        expires_at = s.get("auto_off_at")
        if not expires_at or expires_at == "forever":
            continue
        if expires_at <= now:
            expired.append(area_id)

    return expired


# -----------------------------------------------------------------------------
# Motion Warning State
# -----------------------------------------------------------------------------

def set_motion_warning(area_id: str, pre_warning_brightness: int, dim_factor: float = 0.5) -> None:
    """Set motion warning state for an area.

    Sets a dim_factor that the pipeline uses to dim brightness.
    No direct light commands — the periodic tick applies the factor.

    Args:
        area_id: The area ID
        pre_warning_brightness: The brightness % before warning (for blink threshold check)
        dim_factor: Multiplier for brightness (0.5 = dim to 50%)
    """
    from datetime import datetime

    update_area(area_id, {
        "motion_warning_at": datetime.now().isoformat(),
        "motion_pre_warning_brightness": pre_warning_brightness,
        "dim_factor": dim_factor,
    })


def clear_motion_warning(area_id: str) -> None:
    """Clear motion warning state for an area."""
    area = get_area(area_id)
    if area.get("motion_warning_at") is not None:
        update_area(area_id, {
            "motion_warning_at": None,
            "motion_pre_warning_brightness": None,
            "dim_factor": None,
        })


def is_motion_warned(area_id: str) -> bool:
    """Check if area is in motion warning state."""
    return get_area(area_id).get("motion_warning_at") is not None


def get_dim_factor(area_id: str) -> float:
    """Get the warning factor for an area (1.0 = no warning)."""
    return get_area(area_id).get("dim_factor") or 1.0


def get_motion_warning_state(area_id: str) -> dict:
    """Get motion warning state for an area.

    Returns:
        Dict with 'is_warned', 'warning_at', 'pre_warning_brightness'
    """
    area = get_area(area_id)
    return {
        "is_warned": area.get("motion_warning_at") is not None,
        "warning_at": area.get("motion_warning_at"),
        "pre_warning_brightness": area.get("motion_pre_warning_brightness"),
    }


def get_areas_needing_warning(warning_seconds: int) -> List[str]:
    """Get areas that have timers approaching expiry and haven't been warned.

    Checks both motion timers AND boost timers (when boost will turn off lights).

    Args:
        warning_seconds: How many seconds before expiry to trigger warning

    Returns:
        List of area_ids that need warnings triggered (excludes "forever" timers)
    """
    from datetime import datetime, timedelta

    if warning_seconds <= 0:
        return []

    now = datetime.now()
    warning_threshold = now + timedelta(seconds=warning_seconds)
    needs_warning = []

    for area_id, s in _state.items():
        warning_at = s.get("motion_warning_at")

        # Skip if already warned
        if warning_at is not None:
            continue

        # Check auto-off timer (sensor or user-set; either way warning fires)
        auto_off = s.get("auto_off_at")
        if auto_off and auto_off != "forever":
            try:
                expiry_time = datetime.fromisoformat(auto_off)
                if now < expiry_time <= warning_threshold:
                    needs_warning.append(area_id)
                    continue  # Already added, skip boost check
            except (ValueError, TypeError):
                pass

        # Check boost timer (only if boost will turn off lights when it ends)
        # Skip motion-coupled boosts - their warning comes from the motion timer
        boost_expires = s.get("boost_expires_at")
        boost_started_from_off = s.get("boost_started_from_off", False)
        if boost_expires and boost_expires not in ("forever", "motion") and boost_started_from_off:
            try:
                expiry_time = datetime.fromisoformat(boost_expires)
                if now < expiry_time <= warning_threshold:
                    needs_warning.append(area_id)
            except (ValueError, TypeError):
                pass

    return needs_warning


# ============================================================================
# Fade State (auto on/off gradual transitions)
# ============================================================================

def set_fade(area_id: str, direction: str, duration_seconds: int,
             target_preset: str = None,
             start_brightness: int = None,
             start_kelvin: int = None) -> None:
    """Start a fade for an area.

    Captures current lighting state as the fade start point. Target is
    computed synthetically each tick (not stored) so circadian targets
    track the live curve.

    Args:
        area_id: The area ID
        direction: "in" (toward target preset) or "out" (toward off)
        duration_seconds: Fade duration in seconds
        target_preset: "circadian", "nitelite", "britelite", or "off"
        start_brightness: Brightness % at fade start (0 if lights are off)
        start_kelvin: Kelvin at fade start (warm default if lights are off)
    """
    from datetime import datetime

    update_area(area_id, {
        "fade_start": datetime.now().isoformat(),
        "fade_duration": duration_seconds,
        "fade_direction": direction,
        "fade_target_preset": target_preset or ("off" if direction == "out" else "circadian"),
        "fade_start_brightness": start_brightness or 0,
        "fade_start_kelvin": start_kelvin or 2000,
    })
    logger.info(
        f"Fade {direction} started for area {area_id}: "
        f"{start_brightness or 0}%/{start_kelvin or 2000}K → {target_preset or 'off'} "
        f"({duration_seconds}s)"
    )


def clear_fade(area_id: str) -> bool:
    """Clear fade state. Returns True if a fade was active."""
    area = get_area(area_id)
    if area.get("fade_start") is None:
        return False
    update_area(area_id, {
        "fade_start": None,
        "fade_duration": None,
        "fade_direction": None,
        "fade_target_preset": None,
        "fade_start_brightness": None,
        "fade_start_kelvin": None,
    })
    return True


def is_fading(area_id: str) -> bool:
    """Check if an area has an active fade."""
    return get_area(area_id).get("fade_start") is not None


def get_fade_progress(area_id: str) -> Optional[float]:
    """Return fade progress 0.0-1.0, or None if not fading."""
    from datetime import datetime

    area = get_area(area_id)
    fade_start = area.get("fade_start")
    if fade_start is None:
        return None
    start = datetime.fromisoformat(fade_start)
    elapsed = (datetime.now() - start).total_seconds()
    duration = area.get("fade_duration") or 1
    return min(1.0, max(0.0, elapsed / duration))


def get_fade_state(area_id: str) -> Optional[Dict[str, Any]]:
    """Get active fade state, or None if no fade active."""
    area = get_area(area_id)
    if area.get("fade_start") is None:
        return None
    return {
        "fade_start": area["fade_start"],
        "fade_duration": area.get("fade_duration"),
        "fade_direction": area.get("fade_direction"),
        "fade_target_preset": area.get("fade_target_preset"),
        "fade_start_brightness": area.get("fade_start_brightness"),
        "fade_start_kelvin": area.get("fade_start_kelvin"),
    }


# ============================================================================
# User Action Tracking
# ============================================================================


def mark_user_action(area_id: str) -> None:
    """Record that a user-initiated action occurred on this area."""
    from datetime import datetime
    update_area(area_id, {"last_user_action_at": datetime.now().isoformat()})


def get_last_user_action(area_id: str):
    """Get ISO timestamp of last user action, or None."""
    return get_area(area_id).get("last_user_action_at")


# ============================================================================
# Off Enforcement State
# ============================================================================

def set_off_enforced(area_id: str, value: bool) -> None:
    """Set the off_enforced flag for an area.

    When True, the periodic circadian tick skips sending redundant off commands
    because we've verified all lights in the area are actually off.

    Args:
        area_id: The area ID
        value: Whether off state has been verified/enforced
    """
    update_area(area_id, {"off_enforced": value})
    if not value:
        # Reset the confirmation counter when clearing off_enforced
        update_area(area_id, {"off_confirm_count": 0})


def is_off_enforced(area_id: str) -> bool:
    """Check if off state has been verified/enforced for an area."""
    return get_area(area_id).get("off_enforced", False)


def increment_off_confirm_count(area_id: str) -> int:
    """Increment and return the off confirmation counter for an area.

    Used to track consecutive periods where lights are confirmed off.
    After N confirmations, we can stop sending redundant off commands.

    Returns:
        The new counter value after incrementing
    """
    current = get_area(area_id).get("off_confirm_count", 0)
    new_count = current + 1
    update_area(area_id, {"off_confirm_count": new_count})
    return new_count


def reset_off_confirm_count(area_id: str) -> None:
    """Reset the off confirmation counter for an area."""
    update_area(area_id, {"off_confirm_count": 0})


def clear_all_off_enforced() -> None:
    """Clear off_enforced and off_confirm_count for all areas.

    Called at startup to force one enforcement pass after every reboot.
    """
    for area_id in list(_state.keys()):
        if _state[area_id].get("off_enforced", False) or _state[area_id].get("off_confirm_count", 0) > 0:
            _state[area_id]["off_enforced"] = False
            _state[area_id]["off_confirm_count"] = 0
    _save()
    logger.debug("Cleared off_enforced and off_confirm_count for all areas")
