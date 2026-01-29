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

# Initial zone name (used for migration)
INITIAL_ZONE_NAME = "Main"

# Default preset name (used for migration and fallback)
DEFAULT_PRESET = "Glo 1"

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


def reload() -> None:
    """Reload config from disk.

    This should be called when we need fresh glozone data, since the webserver
    may have updated the config file in a separate process.
    """
    global _config
    try:
        _config = load_config_from_files()
        logger.debug("GloZone config reloaded from disk")
    except Exception as e:
        logger.warning(f"Failed to reload glozone config from disk: {e}")


def get_glozones() -> Dict[str, Dict[str, Any]]:
    """Get all GloZone definitions from config.

    Returns:
        Dict of zone_name -> zone config (preset, areas, is_default)
    """
    if not _config:
        return {INITIAL_ZONE_NAME: {"preset": DEFAULT_PRESET, "areas": [], "is_default": True}}
    return _config.get("glozones", {INITIAL_ZONE_NAME: {"preset": DEFAULT_PRESET, "areas": [], "is_default": True}})


def get_presets() -> Dict[str, Dict[str, Any]]:
    """Get all Circadian Preset definitions from config.

    Returns:
        Dict of preset_name -> preset settings
    """
    if not _config:
        return {}
    return _config.get("circadian_presets", {})


def get_default_zone() -> str:
    """Get the name of the default zone.

    The default zone is where new areas are automatically added.
    Exactly one zone should have is_default=True.

    Returns:
        Name of the default zone
    """
    glozones = get_glozones()

    # Find zone with is_default=True
    for zone_name, zone_config in glozones.items():
        if zone_config.get("is_default", False):
            return zone_name

    # Fallback: if no zone has is_default, use first zone
    if glozones:
        first_zone = next(iter(glozones.keys()))
        logger.warning(f"No default zone set, using first zone: {first_zone}")
        return first_zone

    # Should never happen - there should always be at least one zone
    logger.error("No zones found!")
    return INITIAL_ZONE_NAME


def set_default_zone(zone_name: str, save: bool = True) -> bool:
    """Set which zone is the default.

    Args:
        zone_name: The zone to make default
        save: Whether to save config to disk after change

    Returns:
        True if successful, False if zone doesn't exist
    """
    if not _config or "glozones" not in _config:
        logger.error("Config not loaded")
        return False

    glozones = _config["glozones"]
    if zone_name not in glozones:
        logger.error(f"Zone '{zone_name}' does not exist")
        return False

    # Clear is_default from all zones, set on target
    for zn, zone_config in glozones.items():
        zone_config["is_default"] = (zn == zone_name)

    logger.info(f"Set default zone to '{zone_name}'")

    if save:
        save_config()

    return True


def add_area_to_zone(area_id: str, zone_name: str, area_name: Optional[str] = None) -> bool:
    """Add an area to a zone.

    If the area is already in another zone, it will be moved.

    Args:
        area_id: The area ID to add
        zone_name: The zone to add it to
        area_name: Optional area name for display

    Returns:
        True if successful
    """
    if not _config or "glozones" not in _config:
        logger.error("Config not loaded")
        return False

    glozones = _config["glozones"]
    if zone_name not in glozones:
        logger.error(f"Zone '{zone_name}' does not exist")
        return False

    # Remove from any existing zone first
    for zn, zone_config in glozones.items():
        areas = zone_config.get("areas", [])
        zone_config["areas"] = [
            a for a in areas
            if not (
                (isinstance(a, dict) and a.get("id") == area_id) or
                (isinstance(a, str) and a == area_id)
            )
        ]

    # Add to target zone
    area_entry = {"id": area_id, "name": area_name} if area_name else area_id
    glozones[zone_name].setdefault("areas", []).append(area_entry)

    logger.info(f"Added area '{area_id}' to zone '{zone_name}'")
    return True


def add_area_to_default_zone(area_id: str, area_name: Optional[str] = None) -> bool:
    """Add an area to the default zone.

    Args:
        area_id: The area ID to add
        area_name: Optional area name for display

    Returns:
        True if successful
    """
    default_zone = get_default_zone()
    result = add_area_to_zone(area_id, default_zone, area_name)
    if result:
        save_config()
    return result


def save_config() -> bool:
    """Save the current config to disk.

    Returns:
        True if successful
    """
    if not _config:
        logger.error("No config to save")
        return False

    data_dir = _get_data_directory()
    designer_path = os.path.join(data_dir, "designer_config.json")

    try:
        with open(designer_path, 'w') as f:
            json.dump(_config, f, indent=2)
        logger.debug(f"Saved config to {designer_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to save config: {e}")
        return False


def is_area_in_any_zone(area_id: str) -> bool:
    """Check if an area is explicitly in any zone.

    Args:
        area_id: The area ID to check

    Returns:
        True if area is in a zone
    """
    glozones = get_glozones()

    for zone_config in glozones.values():
        areas = zone_config.get("areas", [])
        for area in areas:
            if isinstance(area, dict):
                if area.get("id") == area_id:
                    return True
            elif area == area_id:
                return True

    return False


def get_zone_for_area(area_id: str) -> str:
    """Get the zone name for an area.

    Args:
        area_id: The area ID to look up

    Returns:
        Zone name, or the default zone if area is not explicitly assigned
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

    # Area not found in any zone - return the default zone
    return get_default_zone()


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

    Returns a complete config dict with defaults for any missing PRESET_SETTINGS
    keys, ensuring Config.from_dict() always gets the intended values rather than
    falling back to its own defaults.

    Args:
        preset_name: The preset name

    Returns:
        Preset config dict with defaults applied (empty dict if preset doesn't exist)
    """
    presets = get_presets()
    preset = presets.get(preset_name)
    if preset is None:
        return {}
    # Apply defaults for any missing preset settings
    defaults = {
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
        "warm_night_start": -60,
        "warm_night_end": 60,
        "warm_night_fade": 60,
        "cool_day_enabled": False,
        "cool_day_mode": "all",
        "cool_day_target": 6500,
        "cool_day_start": 0,
        "cool_day_end": 0,
        "cool_day_fade": 60,
        "activity_preset": "adult",
        "max_dim_steps": 10,
    }
    result = {**defaults, **preset}
    return result


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
    """Ensure at least one zone exists and exactly one is marked as default.

    Should be called after config migration/load.
    """
    if not _config:
        return

    if "glozones" not in _config:
        _config["glozones"] = {}

    glozones = _config["glozones"]

    # If no zones exist, create the initial zone
    if not glozones:
        glozones[INITIAL_ZONE_NAME] = {
            "preset": DEFAULT_PRESET,
            "areas": [],
            "is_default": True
        }
        logger.info(f"Created initial zone '{INITIAL_ZONE_NAME}'")
        return

    # Check if any zone has is_default=True
    has_default = any(zc.get("is_default", False) for zc in glozones.values())

    if not has_default:
        # No default set - make the first zone the default
        first_zone = next(iter(glozones.keys()))
        glozones[first_zone]["is_default"] = True
        logger.info(f"Set '{first_zone}' as default zone (no default was set)")


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
    "warm_night_start", "warm_night_end", "warm_night_fade",
    "cool_day_enabled", "cool_day_mode", "cool_day_target",
    "cool_day_start", "cool_day_end", "cool_day_fade",
    "activity_preset", "max_dim_steps",
}

# Settings that are global (not per-preset)
GLOBAL_SETTINGS = {
    "latitude", "longitude", "timezone", "use_ha_location", "month",
}


def _get_data_directory() -> str:
    """Get the appropriate data directory based on environment."""
    # Prefer /config/circadian-light (visible in HA config folder, included in backups)
    if os.path.exists("/config"):
        data_dir = "/config/circadian-light"
        os.makedirs(data_dir, exist_ok=True)
        return data_dir
    elif os.path.exists("/data"):
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
            INITIAL_ZONE_NAME: {
                "preset": DEFAULT_PRESET,
                "areas": [],
                "is_default": True
            }
        },
    }

    # Add global settings
    new_config.update(global_config)

    logger.info(f"Migration complete: created preset '{DEFAULT_PRESET}' "
                f"and zone '{INITIAL_ZONE_NAME}' (default)")

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
        "warm_night_start": -60,
        "warm_night_end": 60,
        "warm_night_fade": 60,
        "cool_day_enabled": False,
        "cool_day_mode": "all",
        "cool_day_target": 6500,
        "cool_day_start": 0,
        "cool_day_end": 0,
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
            except json.JSONDecodeError as e:
                # Try to repair corrupted JSON (e.g., "Extra data" from duplicate writes)
                if "Extra data" in str(e):
                    logger.warning(f"JSON error in {path}: {e}, attempting repair...")
                    try:
                        with open(path, 'r') as f:
                            content = f.read()
                        decoder = json.JSONDecoder()
                        repaired_data, end_idx = decoder.raw_decode(content)
                        if isinstance(repaired_data, dict):
                            # Backup and repair
                            with open(path + ".corrupted", 'w') as f:
                                f.write(content)
                            with open(path, 'w') as f:
                                json.dump(repaired_data, f, indent=2)
                            config.update(repaired_data)
                            logger.info(f"Repaired {path}")
                    except Exception as repair_err:
                        logger.error(f"Failed to repair {path}: {repair_err}")
                else:
                    logger.debug(f"Could not load config from {path}: {e}")
            except Exception as e:
                logger.debug(f"Could not load config from {path}: {e}")

    # Migrate to GloZone format if needed
    needs_migration = "circadian_presets" not in config or "glozones" not in config
    config = _migrate_config(config)

    # Ensure top-level preset settings are merged INTO the first preset.
    # This handles configs where settings exist at top level but not inside
    # the preset dict (e.g., added after initial migration, or partial saves).
    # Without this, Config.from_dict() would use defaults for missing keys,
    # causing solar rules and brightness limits to not be applied to lights.
    if "circadian_presets" in config and config["circadian_presets"]:
        first_preset_name = list(config["circadian_presets"].keys())[0]
        first_preset = config["circadian_presets"][first_preset_name]
        for key in list(config.keys()):
            if key in PRESET_SETTINGS:
                if key not in first_preset:
                    first_preset[key] = config[key]
                    logger.debug(f"Merged top-level key '{key}' into preset '{first_preset_name}'")
                del config[key]

    # Cache the config first so ensure_default_zone_exists can use it
    _config = config

    # Ensure at least one zone has is_default=True (handles existing configs)
    had_default = any(
        zc.get("is_default", False)
        for zc in config.get("glozones", {}).values()
    )
    ensure_default_zone_exists()
    needs_save = needs_migration or not had_default

    # Save config to disk if changes were made
    if needs_save:
        designer_path = os.path.join(data_dir, "designer_config.json")
        try:
            with open(designer_path, 'w') as f:
                json.dump(config, f, indent=2)
            logger.info(f"Saved config to {designer_path}")
        except Exception as e:
            logger.warning(f"Failed to save config: {e}")

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
