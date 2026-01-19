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


# Settings that are per-preset (not global)
PRESET_SETTINGS = {
    "color_mode", "min_color_temp", "max_color_temp",
    "min_brightness", "max_brightness",
    "ascend_start", "descend_start", "wake_time", "bed_time",
    "wake_speed", "bed_speed",
    "warm_night_enabled", "warm_night_mode", "warm_night_target",
    "warm_night_sunset_start", "warm_night_sunrise_end", "warm_night_fade",
    "cool_day_enabled", "cool_day_mode", "cool_day_target",
    "cool_day_sunrise_start", "cool_day_sunset_end", "cool_day_fade",
    "activity_preset", "max_dim_steps",
}

# Settings that are global (not per-preset)
GLOBAL_SETTINGS = {
    "latitude", "longitude", "timezone", "use_ha_location", "month",
}


def _get_data_directory() -> str:
    """Get the appropriate data directory based on environment."""
    if os.path.exists("/data"):
        return "/data"
    else:
        # Development mode - use local .data directory
        data_dir = os.path.join(os.path.dirname(__file__), ".data")
        os.makedirs(data_dir, exist_ok=True)
        return data_dir


def _migrate_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Migrate old flat config to new GloZone format.

    Args:
        config: The loaded config dict

    Returns:
        Migrated config dict (or original if already migrated)
    """
    # Check if already migrated
    if "circadian_presets" in config and "glozones" in config:
        return config

    logger.info("Migrating config to GloZone format...")

    # Extract preset settings from flat config
    preset_config = {}
    for key in PRESET_SETTINGS:
        if key in config:
            preset_config[key] = config[key]

    # Extract global settings
    global_config = {}
    for key in GLOBAL_SETTINGS:
        if key in config:
            global_config[key] = config[key]

    # Build new config structure
    new_config = {
        "circadian_presets": {
            DEFAULT_PRESET: preset_config
        },
        "glozones": {
            DEFAULT_ZONE: {
                "preset": DEFAULT_PRESET,
                "areas": []
            }
        },
    }

    # Add global settings
    new_config.update(global_config)

    logger.info(f"Migration complete: created preset '{DEFAULT_PRESET}' "
                f"and zone '{DEFAULT_ZONE}'")

    return new_config


def load_config_from_files(data_dir: Optional[str] = None) -> Dict[str, Any]:
    """Load and migrate config from files.

    Loads options.json and designer_config.json, merges them,
    and migrates to GloZone format if needed.

    Args:
        data_dir: Optional data directory path. If None, auto-detected.

    Returns:
        The loaded and migrated config dict
    """
    global _config

    if data_dir is None:
        data_dir = _get_data_directory()

    # Start with defaults
    config: Dict[str, Any] = {
        "color_mode": "kelvin",
        "min_color_temp": 500,
        "max_color_temp": 6500,
        "min_brightness": 1,
        "max_brightness": 100,
        "ascend_start": 3.0,
        "descend_start": 12.0,
        "wake_time": 6.0,
        "bed_time": 22.0,
        "wake_speed": 8,
        "bed_speed": 6,
        "warm_night_enabled": False,
        "warm_night_mode": "all",
        "warm_night_target": 2700,
        "warm_night_sunset_start": -60,
        "warm_night_sunrise_end": 60,
        "warm_night_fade": 60,
        "cool_day_enabled": False,
        "cool_day_mode": "all",
        "cool_day_target": 6500,
        "cool_day_sunrise_start": 0,
        "cool_day_sunset_end": 0,
        "cool_day_fade": 60,
        "activity_preset": "adult",
        "latitude": 35.0,
        "longitude": -78.6,
        "timezone": "US/Eastern",
        "use_ha_location": True,
        "max_dim_steps": 10,
        "month": 6,
    }

    # Load and merge config files
    for filename in ["options.json", "designer_config.json"]:
        path = os.path.join(data_dir, filename)
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    part = json.load(f)
                    if isinstance(part, dict):
                        config.update(part)
            except Exception as e:
                logger.debug(f"Could not load config from {path}: {e}")

    # Migrate to GloZone format
    config = _migrate_config(config)

    # Cache the config
    _config = config

    return config


def get_effective_config_for_area(area_id: str, include_global: bool = True) -> Dict[str, Any]:
    """Get the effective configuration for an area.

    Combines the preset settings for the area's zone with global settings.
    This provides a flat config dict that can be used with existing code.

    Args:
        area_id: The area ID
        include_global: Whether to include global settings (latitude, etc.)

    Returns:
        Flat config dict with all settings merged
    """
    # Ensure config is loaded
    if _config is None:
        load_config_from_files()

    result = {}

    # Get preset config for this area
    preset_config = get_preset_config_for_area(area_id)
    result.update(preset_config)

    # Add global settings if requested
    if include_global and _config:
        for key in GLOBAL_SETTINGS:
            if key in _config:
                result[key] = _config[key]

    return result


def reload_config() -> Dict[str, Any]:
    """Reload config from files.

    Forces a fresh load from disk, useful after config changes.

    Returns:
        The reloaded config dict
    """
    global _config
    _config = None
    return load_config_from_files()
