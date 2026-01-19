#!/usr/bin/env python3
"""GloZone runtime state management.

This module manages in-memory runtime state for GloZones. Unlike area state,
GloZone runtime state is NOT persisted to disk - it resets on addon restart
and is reset twice daily at ascend/descend start times.

Runtime state includes:
- brightness_mid: Hour (0-24) or None (use preset default)
- color_mid: Hour (0-24) or None (use preset default)
- frozen_at: Hour (0-24) or None (not frozen)
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# In-memory state dict: zone_name -> runtime state
_zone_state: Dict[str, Dict[str, Any]] = {}

# Sync tolerance for comparing state values (0.1 = 6 minutes)
SYNC_TOLERANCE = 0.1


def _get_default_zone_state() -> Dict[str, Any]:
    """Return default runtime state for a zone."""
    return {
        "brightness_mid": None,  # None = use preset's wake_time/bed_time
        "color_mid": None,
        "frozen_at": None,
    }


def init() -> None:
    """Initialize the glozone state module.

    Clears any existing state. Called on addon startup.
    """
    global _zone_state
    _zone_state = {}
    logger.info("GloZone runtime state initialized (empty)")


def get_zone_state(zone_name: str) -> Dict[str, Any]:
    """Get runtime state for a zone.

    Args:
        zone_name: Name of the GloZone

    Returns:
        Dict with brightness_mid, color_mid, frozen_at (creates default if not exists)
    """
    if zone_name not in _zone_state:
        _zone_state[zone_name] = _get_default_zone_state()
    return _zone_state[zone_name].copy()


def set_zone_state(zone_name: str, updates: Dict[str, Any]) -> None:
    """Update runtime state for a zone.

    Args:
        zone_name: Name of the GloZone
        updates: Dict with keys to update (brightness_mid, color_mid, frozen_at)
    """
    if zone_name not in _zone_state:
        _zone_state[zone_name] = _get_default_zone_state()

    for key in ["brightness_mid", "color_mid", "frozen_at"]:
        if key in updates:
            _zone_state[zone_name][key] = updates[key]

    logger.debug(f"Zone '{zone_name}' state updated: {_zone_state[zone_name]}")


def reset_zone_state(zone_name: str) -> None:
    """Reset a zone's runtime state to defaults (None for all fields).

    Args:
        zone_name: Name of the GloZone
    """
    _zone_state[zone_name] = _get_default_zone_state()
    logger.info(f"Zone '{zone_name}' runtime state reset to defaults")


def reset_all_zones() -> None:
    """Reset all zones' runtime state to defaults.

    Called at ascend/descend start times. Preserves frozen zones.
    """
    for zone_name in list(_zone_state.keys()):
        if _zone_state[zone_name].get("frozen_at") is None:
            _zone_state[zone_name] = _get_default_zone_state()
            logger.debug(f"Zone '{zone_name}' reset (not frozen)")
        else:
            logger.debug(f"Zone '{zone_name}' preserved (frozen)")

    logger.info(f"Reset {len(_zone_state)} zone(s) (frozen zones preserved)")


def reset_all_zones_forced() -> None:
    """Reset all zones' runtime state, including frozen ones.

    Used for GloReset primitive.
    """
    for zone_name in list(_zone_state.keys()):
        _zone_state[zone_name] = _get_default_zone_state()

    logger.info(f"Force reset {len(_zone_state)} zone(s) (including frozen)")


def is_zone_frozen(zone_name: str) -> bool:
    """Check if a zone is frozen.

    Args:
        zone_name: Name of the GloZone

    Returns:
        True if zone has frozen_at set
    """
    state = get_zone_state(zone_name)
    return state.get("frozen_at") is not None


def get_all_zone_names() -> List[str]:
    """Get list of all zone names with runtime state.

    Returns:
        List of zone names
    """
    return list(_zone_state.keys())


def values_match(a: Optional[float], b: Optional[float]) -> bool:
    """Check if two state values match within tolerance.

    Args:
        a: First value (or None)
        b: Second value (or None)

    Returns:
        True if both None, or both within SYNC_TOLERANCE
    """
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(a - b) < SYNC_TOLERANCE


def is_state_synced(area_state: Dict[str, Any], zone_state: Dict[str, Any]) -> bool:
    """Check if an area's state is synced with its zone's state.

    Args:
        area_state: Area's runtime state dict
        zone_state: Zone's runtime state dict

    Returns:
        True if all values match within tolerance
    """
    return (
        values_match(area_state.get("brightness_mid"), zone_state.get("brightness_mid"))
        and values_match(area_state.get("color_mid"), zone_state.get("color_mid"))
        and values_match(area_state.get("frozen_at"), zone_state.get("frozen_at"))
    )
