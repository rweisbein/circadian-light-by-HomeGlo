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
        "enabled": False,
        # frozen_at: None = unfrozen, float = frozen at that hour (0-24)
        "frozen_at": None,
        # Midpoints (None = use config wake_time/bed_time based on phase)
        "brightness_mid": None,
        "color_mid": None,
        # Last color temp when lights were turned off (for smart 2-step turn-on)
        "last_off_ct": None,
        # Boost state
        "boost_started_from_off": False,  # If true, turn off when boost ends; else restore circadian
        "boost_expires_at": None,  # ISO timestamp string when boost expires (None = not boosted)
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


def set_enabled(area_id: str, enabled: bool) -> None:
    """Enable or disable Circadian Light for an area.

    Args:
        area_id: The area ID
        enabled: Whether to enable or disable
    """
    update_area(area_id, {"enabled": enabled})
    logger.info(f"Circadian Light {'enabled' if enabled else 'disabled'} for area {area_id}")


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


def is_enabled(area_id: str) -> bool:
    """Check if Circadian Light is enabled for an area."""
    return get_area(area_id).get("enabled", False)


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


def get_enabled_areas() -> List[str]:
    """Get list of all areas with Circadian Light enabled."""
    return [area_id for area_id, state in _state.items() if state.get("enabled", False)]


def get_unfrozen_enabled_areas() -> List[str]:
    """Get list of enabled areas that are not frozen (for periodic updates).

    Note: With frozen_at, frozen areas still get periodic updates but use
    frozen_at instead of current time. This function returns areas that
    are enabled, regardless of frozen status, since all enabled areas
    need periodic updates now.
    """
    return [
        area_id for area_id, state in _state.items()
        if state.get("enabled", False)
    ]


def reset_area(area_id: str) -> None:
    """Reset an area's runtime state to defaults (midpoints, bounds, frozen_at).

    Preserves only enabled status. Clears frozen_at (unfreezes).

    Args:
        area_id: The area ID
    """
    if area_id not in _state:
        return

    current = _state[area_id]
    preserved = {
        "enabled": current.get("enabled", False),
        # frozen_at is NOT preserved - reset clears it
    }

    _state[area_id] = _get_default_area_state()
    _state[area_id].update(preserved)
    _save()
    logger.info(f"Reset runtime state for area {area_id}")


def reset_all_areas() -> None:
    """Reset runtime state for all areas (midpoints only).

    Called at phase transitions (ascend/descend). Preserves enabled AND frozen status.
    Use reset_area() for explicit user resets that should clear frozen.
    """
    for area_id in list(_state.keys()):
        current = _state[area_id]
        preserved = {
            "enabled": current.get("enabled", False),
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

    This excludes 'enabled' which is not part of zone sync.

    Args:
        area_id: The area ID

    Returns:
        Dict with brightness_mid, color_mid, frozen_at
    """
    area = get_area(area_id)
    return {
        "brightness_mid": area.get("brightness_mid"),
        "color_mid": area.get("color_mid"),
        "frozen_at": area.get("frozen_at"),
    }


def set_runtime_state(area_id: str, runtime_state: Dict[str, Any]) -> None:
    """Set the runtime state (midpoints, frozen_at) for an area.

    This does NOT change 'enabled' status.

    Args:
        area_id: The area ID
        runtime_state: Dict with brightness_mid, color_mid, frozen_at
    """
    updates = {}
    for key in ["brightness_mid", "color_mid", "frozen_at"]:
        if key in runtime_state:
            updates[key] = runtime_state[key]

    if updates:
        update_area(area_id, updates)
        logger.debug(f"Set runtime state for area {area_id}: {updates}")


def copy_state_from_zone(area_id: str, zone_state: Dict[str, Any]) -> None:
    """Copy zone runtime state to an area.

    Used by GloDown and circadian_toggle (on enable).
    Does NOT change 'enabled' status.

    Args:
        area_id: The area ID
        zone_state: Zone's runtime state (brightness_mid, color_mid, frozen_at)
    """
    set_runtime_state(area_id, zone_state)
    logger.info(f"Copied zone state to area {area_id}")


def reset_area_to_defaults(area_id: str) -> None:
    """Reset an area's runtime state to defaults (None for midpoints and frozen_at).

    Preserves 'enabled' status. Used when resetting to preset defaults.

    Args:
        area_id: The area ID
    """
    if area_id not in _state:
        return

    enabled = _state[area_id].get("enabled", False)
    _state[area_id] = _get_default_area_state()
    _state[area_id]["enabled"] = enabled
    _save()
    logger.info(f"Reset area {area_id} runtime state to defaults (preserving enabled={enabled})")


# ============================================================================
# Boost state management
# ============================================================================

def set_boost(area_id: str, started_from_off: bool, expires_at: str) -> None:
    """Set boost state for an area.

    Args:
        area_id: The area ID
        started_from_off: Whether lights were off when boost started
        expires_at: ISO timestamp string when boost expires
    """
    update_area(area_id, {
        "boost_started_from_off": started_from_off,
        "boost_expires_at": expires_at,
    })
    logger.info(f"Boost activated for area {area_id} (started_from_off={started_from_off}, expires={expires_at})")


def clear_boost(area_id: str) -> None:
    """Clear boost state for an area.

    Args:
        area_id: The area ID
    """
    update_area(area_id, {
        "boost_started_from_off": False,
        "boost_expires_at": None,
    })
    logger.info(f"Boost cleared for area {area_id}")


def is_boosted(area_id: str) -> bool:
    """Check if an area is currently boosted."""
    return get_area(area_id).get("boost_expires_at") is not None


def get_boost_state(area_id: str) -> Dict[str, Any]:
    """Get boost state for an area.

    Returns:
        Dict with is_boosted, boost_started_from_off, boost_expires_at
    """
    area = get_area(area_id)
    expires_at = area.get("boost_expires_at")
    return {
        "is_boosted": expires_at is not None,
        "boost_started_from_off": area.get("boost_started_from_off", False),
        "boost_expires_at": expires_at,
    }


def get_boosted_areas() -> List[str]:
    """Get list of all areas with active boost."""
    return [area_id for area_id, s in _state.items() if s.get("boost_expires_at") is not None]


def get_expired_boosts() -> List[str]:
    """Get list of areas with expired boosts (boost_expires_at in the past).

    Returns:
        List of area_ids with expired boosts
    """
    from datetime import datetime

    now = datetime.now().isoformat()
    expired = []

    for area_id, s in _state.items():
        expires_at = s.get("boost_expires_at")
        if expires_at and expires_at <= now:
            expired.append(area_id)

    return expired
