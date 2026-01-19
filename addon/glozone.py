#!/usr/bin/env python3
"""GloZone configuration management.

This module handles GloZone configuration operations:
- Looking up which zone an area belongs to
- Getting the preset for a zone
- Getting all areas in a zone
- Managing zone membership

Zone configuration is stored in designer_config.json and cached in memory.
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Default zone name for unassigned areas
DEFAULT_ZONE = "Unassigned"

# Default preset name (used for migration and fallback)
DEFAULT_PRESET = "Preset 1"

# Cached config reference
_config: Optional[Dict[str, Any]] = None


def init(config: Optional[Dict[str, Any]] = None) -> None:
    """Initialize the glozone module with config.

    Args:
        config: The designer config dict. If None, will need to be set later.
    """
    global _config
    _config = config
    if config:
        logger.info("GloZone config initialized")
    else:
        logger.debug("GloZone config initialized (empty, awaiting config)")


def set_config(config: Dict[str, Any]) -> None:
    """Update the cached config.

    Args:
        config: The designer config dict
    """
    global _config
    _config = config
    logger.debug("GloZone config updated")


def get_config() -> Optional[Dict[str, Any]]:
    """Get the cached config.

    Returns:
        The designer config dict, or None if not set
    """
    return _config


def get_glozones() -> Dict[str, Dict[str, Any]]:
    """Get all GloZone definitions from config.

    Returns:
        Dict of zone_name -> zone config (preset, areas)
    """
    if not _config:
        return {DEFAULT_ZONE: {"preset": DEFAULT_PRESET, "areas": []}}
    return _config.get("glozones", {DEFAULT_ZONE: {"preset": DEFAULT_PRESET, "areas": []}})


def get_presets() -> Dict[str, Dict[str, Any]]:
    """Get all Circadian Preset definitions from config.

    Returns:
        Dict of preset_name -> preset settings
    """
    if not _config:
        return {}
    return _config.get("circadian_presets", {})


def get_zone_for_area(area_id: str) -> str:
    """Get the zone name for an area.

    Args:
        area_id: The area ID to look up

    Returns:
        Zone name, or DEFAULT_ZONE if area is not assigned
    """
    glozones = get_glozones()

    for zone_name, zone_config in glozones.items():
        areas = zone_config.get("areas", [])
        for area in areas:
            # Areas can be stored as {"id": "xxx", "name": "xxx"} or just "xxx"
            if isinstance(area, dict):
                if area.get("id") == area_id:
                    return zone_name
            elif area == area_id:
                return zone_name

    return DEFAULT_ZONE


def get_areas_in_zone(zone_name: str) -> List[str]:
    """Get all area IDs in a zone.

    Args:
        zone_name: The zone name

    Returns:
        List of area IDs
    """
    glozones = get_glozones()
    zone_config = glozones.get(zone_name, {})
    areas = zone_config.get("areas", [])

    result = []
    for area in areas:
        if isinstance(area, dict):
            result.append(area.get("id"))
        else:
            result.append(area)

    return [a for a in result if a]  # Filter out None


def get_preset_for_zone(zone_name: str) -> Optional[str]:
    """Get the preset name for a zone.

    Args:
        zone_name: The zone name

    Returns:
        Preset name, or None if zone doesn't exist
    """
    glozones = get_glozones()
    zone_config = glozones.get(zone_name, {})
    return zone_config.get("preset", DEFAULT_PRESET)


def get_preset_for_area(area_id: str) -> Optional[str]:
    """Get the preset name for an area (via its zone).

    Args:
        area_id: The area ID

    Returns:
        Preset name
    """
    zone_name = get_zone_for_area(area_id)
    return get_preset_for_zone(zone_name)


def get_preset_config(preset_name: str) -> Dict[str, Any]:
    """Get the full configuration for a preset.

    Args:
        preset_name: The preset name

    Returns:
        Preset config dict (empty dict if preset doesn't exist)
    """
    presets = get_presets()
    return presets.get(preset_name, {})


def get_preset_config_for_area(area_id: str) -> Dict[str, Any]:
    """Get the full preset configuration for an area.

    Args:
        area_id: The area ID

    Returns:
        Preset config dict
    """
    preset_name = get_preset_for_area(area_id)
    return get_preset_config(preset_name) if preset_name else {}


def get_all_zone_names() -> List[str]:
    """Get all zone names.

    Returns:
        List of zone names
    """
    return list(get_glozones().keys())


def ensure_default_zone_exists() -> None:
    """Ensure the default zone exists in config.

    Should be called after config migration/load.
    """
    if not _config:
        return

    if "glozones" not in _config:
        _config["glozones"] = {}

    if DEFAULT_ZONE not in _config["glozones"]:
        _config["glozones"][DEFAULT_ZONE] = {
            "preset": DEFAULT_PRESET,
            "areas": []
        }
        logger.info(f"Created default zone '{DEFAULT_ZONE}'")


def is_config_migrated() -> bool:
    """Check if config has been migrated to new GloZone format.

    Returns:
        True if config has circadian_presets and glozones keys
    """
    if not _config:
        return False
    return "circadian_presets" in _config and "glozones" in _config


def get_area_zone_and_preset(area_id: str) -> Tuple[str, str, Dict[str, Any]]:
    """Get zone name, preset name, and preset config for an area.

    Convenience function that returns all zone-related info for an area.

    Args:
        area_id: The area ID

    Returns:
        Tuple of (zone_name, preset_name, preset_config)
    """
    zone_name = get_zone_for_area(area_id)
    preset_name = get_preset_for_zone(zone_name) or DEFAULT_PRESET
    preset_config = get_preset_config(preset_name)
    return zone_name, preset_name, preset_config
