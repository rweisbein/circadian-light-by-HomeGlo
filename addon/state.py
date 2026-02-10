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
        # Midpoints (None = use config wake_time/bed_time based on phase)
        "brightness_mid": None,
        "color_mid": None,
        # Solar rule target offset (Kelvin) from color stepping
        "color_override": None,
        # Last color temp when lights were turned off (for smart 2-step turn-on)
        "last_off_ct": None,
        # Boost state
        "boost_started_from_off": False,  # If true, turn off when boost ends; else restore circadian
        "boost_expires_at": None,  # ISO timestamp string when boost expires (None = not boosted, 0 = forever)
        "boost_brightness": None,  # Current boost brightness percentage (None = not boosted)
        # Motion on_off state (on_only has no timer, so doesn't need state)
        "motion_expires_at": None,  # ISO timestamp when on_off motion timer expires (None = not from motion)
        # Motion warning state
        "motion_warning_at": None,  # ISO timestamp when warning was triggered (None = not warned)
        "motion_pre_warning_brightness": None,  # Brightness % before warning (to restore if motion detected)
        # Off enforcement (periodic loop optimization)
        "off_enforced": False,  # True once we've verified all lights are off; skip re-sending off commands
        "off_confirm_count": 0,  # Counter for consecutive off confirmations before setting off_enforced
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

    This preserves all settings (midpoints, frozen_at, is_on, etc.).
    Settings persist across circadian_off → circadian_on cycles.

    Args:
        area_id: The area ID
        is_circadian_val: Whether Circadian Light should control this area
    """
    was_circadian = is_circadian(area_id)

    # Ensure area exists in state
    if area_id not in _state:
        _state[area_id] = _get_default_area_state()

    update_area(area_id, {"is_circadian": is_circadian_val})

    if is_circadian_val and not was_circadian:
        logger.info(f"Circadian Light enabled for area {area_id}")
    elif not is_circadian_val and was_circadian:
        logger.info(f"Circadian Light disabled for area {area_id}")


def set_frozen_at(area_id: str, frozen_at: Optional[float]) -> None:
    """Set the frozen time for an area.

    When frozen_at is set, calculations use that hour instead of current time.
    Periodic updates still run but output the same values.

    Args:
        area_id: The area ID
        frozen_at: Hour to freeze at (0-24), or None to unfreeze
    """
    update_area(area_id, {"frozen_at": frozen_at})
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


def set_last_off_ct(area_id: str, color_temp: int) -> None:
    """Store the color temperature when lights were turned off.

    Used to determine if 2-step turn-on is needed (to avoid color arc).
    """
    update_area(area_id, {"last_off_ct": color_temp})


def get_last_off_ct(area_id: str) -> Optional[int]:
    """Get the color temperature from when lights were last turned off."""
    return get_area(area_id).get("last_off_ct")


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
    for key in ["brightness_mid", "color_mid", "color_override", "frozen_at"]:
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
    to "motion" instead of a timestamp. The boost ends only when the motion
    timer ends (via end_motion_on_off), not independently.
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
# Motion on_off state management
# ============================================================================

def set_motion_expires(area_id: str, expires_at: str) -> None:
    """Set motion on_off timer for an area.

    Args:
        area_id: The area ID
        expires_at: ISO timestamp string when motion timer expires
    """
    update_area(area_id, {"motion_expires_at": expires_at})
    logger.info(f"Motion on_off timer set for area {area_id} (expires={expires_at})")


def clear_motion_expires(area_id: str) -> None:
    """Clear motion on_off timer for an area.

    Args:
        area_id: The area ID
    """
    if get_area(area_id).get("motion_expires_at") is not None:
        update_area(area_id, {"motion_expires_at": None})
        logger.info(f"Motion on_off timer cleared for area {area_id}")


def extend_motion_expires(area_id: str, expires_at: str) -> None:
    """Extend motion on_off timer for an area.

    Args:
        area_id: The area ID
        expires_at: New ISO timestamp string when motion timer expires
    """
    update_area(area_id, {"motion_expires_at": expires_at})
    logger.debug(f"Motion on_off timer extended for area {area_id} (expires={expires_at})")


def has_motion_timer(area_id: str) -> bool:
    """Check if an area has an active motion on_off timer."""
    return get_area(area_id).get("motion_expires_at") is not None


def get_motion_expires(area_id: str) -> Optional[str]:
    """Get the motion on_off timer expiry timestamp for an area.

    Returns:
        ISO timestamp string when motion timer expires, or None if not set
    """
    return get_area(area_id).get("motion_expires_at")


def get_expired_motion() -> List[str]:
    """Get list of areas with expired motion on_off timers.

    Returns:
        List of area_ids with expired motion timers (excludes "forever" timers)
    """
    from datetime import datetime

    now = datetime.now().isoformat()
    expired = []

    for area_id, s in _state.items():
        expires_at = s.get("motion_expires_at")
        # Skip if no timer, or if timer is "forever" (never expires)
        if not expires_at or expires_at == "forever":
            continue
        if expires_at <= now:
            expired.append(area_id)

    return expired


# -----------------------------------------------------------------------------
# Motion Warning State
# -----------------------------------------------------------------------------

def set_motion_warning(area_id: str, pre_warning_brightness: int) -> None:
    """Set motion warning state for an area.

    Args:
        area_id: The area ID
        pre_warning_brightness: The brightness % before warning (to restore later)
    """
    from datetime import datetime

    update_area(area_id, {
        "motion_warning_at": datetime.now().isoformat(),
        "motion_pre_warning_brightness": pre_warning_brightness
    })


def clear_motion_warning(area_id: str) -> None:
    """Clear motion warning state for an area."""
    area = get_area(area_id)
    if area.get("motion_warning_at") is not None:
        update_area(area_id, {
            "motion_warning_at": None,
            "motion_pre_warning_brightness": None
        })


def is_motion_warned(area_id: str) -> bool:
    """Check if area is in motion warning state."""
    return get_area(area_id).get("motion_warning_at") is not None


def get_motion_warning_state(area_id: str) -> dict:
    """Get motion warning state for an area.

    Returns:
        Dict with 'is_warned', 'warning_at', 'pre_warning_brightness'
    """
    area = get_area(area_id)
    return {
        "is_warned": area.get("motion_warning_at") is not None,
        "warning_at": area.get("motion_warning_at"),
        "pre_warning_brightness": area.get("motion_pre_warning_brightness")
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

        # Check motion timer
        motion_expires = s.get("motion_expires_at")
        if motion_expires and motion_expires != "forever":
            try:
                expiry_time = datetime.fromisoformat(motion_expires)
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
