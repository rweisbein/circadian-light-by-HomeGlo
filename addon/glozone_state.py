#!/usr/bin/env python3
"""GloZone runtime state management.

This module manages runtime state for GloZones, persisted to a JSON file
so it can be shared between the main process and webserver process.

Runtime state includes:
- brightness_mid: Hour (0-24) or None (use preset default)
- color_mid: Hour (0-24) or None (use preset default)
- frozen_at: Hour (0-24) or None (not frozen)
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Sync tolerance for comparing state values (0.1 = 6 minutes)
SYNC_TOLERANCE = 0.1

# State file path - shared between main.py and webserver.py processes
_STATE_FILE: Optional[Path] = None


def _get_state_file() -> Path:
    """Get the path to the state file."""
    global _STATE_FILE
    if _STATE_FILE is None:
        # Check for HA config directory first, then fallback
        if os.path.isdir("/config/circadian-light"):
            _STATE_FILE = Path("/config/circadian-light/glozone_runtime_state.json")
        elif os.path.isdir("/data"):
            _STATE_FILE = Path("/data/glozone_runtime_state.json")
        else:
            _STATE_FILE = Path("/app/.data/glozone_runtime_state.json")
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    return _STATE_FILE


def _load_all_state() -> Dict[str, Dict[str, Any]]:
    """Load all zone state from file."""
    state_file = _get_state_file()
    if state_file.exists():
        try:
            with open(state_file, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Failed to load zone state file: {e}")
    return {}


def _save_all_state(state: Dict[str, Dict[str, Any]]) -> None:
    """Save all zone state to file."""
    state_file = _get_state_file()
    try:
        with open(state_file, "w") as f:
            json.dump(state, f, indent=2)
    except IOError as e:
        logger.error(f"Failed to save zone state file: {e}")


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
    state_file = _get_state_file()
    if state_file.exists():
        state_file.unlink()
    logger.info(f"GloZone runtime state initialized (file: {state_file})")


def get_zone_state(zone_name: str) -> Dict[str, Any]:
    """Get runtime state for a zone.

    Args:
        zone_name: Name of the GloZone

    Returns:
        Dict with brightness_mid, color_mid, frozen_at (creates default if not exists)
    """
    all_state = _load_all_state()
    if zone_name not in all_state:
        result = _get_default_zone_state()
        logger.debug(f"[ZoneState] GET '{zone_name}': default (not in file)")
    else:
        result = all_state[zone_name]
        logger.debug(f"[ZoneState] GET '{zone_name}': {result}")
    return result


def set_zone_state(zone_name: str, updates: Dict[str, Any]) -> None:
    """Update runtime state for a zone.

    Args:
        zone_name: Name of the GloZone
        updates: Dict with keys to update (brightness_mid, color_mid, frozen_at)
    """
    all_state = _load_all_state()

    if zone_name not in all_state:
        all_state[zone_name] = _get_default_zone_state()

    for key in ["brightness_mid", "color_mid", "frozen_at"]:
        if key in updates:
            all_state[zone_name][key] = updates[key]

    _save_all_state(all_state)
    logger.info(f"[ZoneState] SET '{zone_name}': {all_state[zone_name]}")


def reset_zone_state(zone_name: str) -> None:
    """Reset a zone's runtime state to defaults (None for all fields).

    Args:
        zone_name: Name of the GloZone
    """
    all_state = _load_all_state()
    all_state[zone_name] = _get_default_zone_state()
    _save_all_state(all_state)
    logger.info(f"Zone '{zone_name}' runtime state reset to defaults")


def reset_all_zones() -> None:
    """Reset all zones' runtime state to defaults.

    Called at ascend/descend start times. Preserves frozen zones.
    """
    all_state = _load_all_state()
    for zone_name in list(all_state.keys()):
        if all_state[zone_name].get("frozen_at") is None:
            all_state[zone_name] = _get_default_zone_state()
            logger.debug(f"Zone '{zone_name}' reset (not frozen)")
        else:
            logger.debug(f"Zone '{zone_name}' preserved (frozen)")

    _save_all_state(all_state)
    logger.info(f"Reset {len(all_state)} zone(s) (frozen zones preserved)")


def reset_all_zones_forced() -> None:
    """Reset all zones' runtime state, including frozen ones.

    Used for GloReset primitive.
    """
    all_state = _load_all_state()
    for zone_name in list(all_state.keys()):
        all_state[zone_name] = _get_default_zone_state()

    _save_all_state(all_state)
    logger.info(f"Force reset {len(all_state)} zone(s) (including frozen)")


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
    all_state = _load_all_state()
    return list(all_state.keys())


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
