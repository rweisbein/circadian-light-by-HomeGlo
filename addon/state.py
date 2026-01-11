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
        # Solar rule limit (None = use config target for active rule)
        "solar_rule_color_limit": None,
        # Runtime bounds (None = use config bounds)
        "min_brightness": None,
        "max_brightness": None,
        "min_color_temp": None,
        "max_color_temp": None,
    }


def _get_data_directory() -> str:
    """Get the appropriate data directory based on environment."""
    if os.path.exists("/data"):
        # Running in Home Assistant
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
    """Reset runtime state for all areas.

    Called when config is saved. Preserves enabled and frozen status.
    """
    for area_id in list(_state.keys()):
        reset_area(area_id)
    logger.info(f"Reset runtime state for all {len(_state)} area(s)")


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
