#!/usr/bin/env python3
"""GloZone configuration management.

This module handles GloZone configuration operations:
- Looking up which zone an area belongs to
- Getting the rhythm for a zone
- Getting all areas in a zone
- Managing zone membership

Zone configuration is stored in designer_config.json and cached in memory.
"""

import json
import logging
import os
import tempfile
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Initial zone name (used for migration)
INITIAL_ZONE_NAME = "Main"

# Default rhythm name (used for migration and fallback)
DEFAULT_RHYTHM = "Daily Rhythm 1"

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
        Dict of zone_name -> zone config (rhythm, areas, is_default)
    """
    if not _config:
        return {INITIAL_ZONE_NAME: {"rhythm": DEFAULT_RHYTHM, "areas": [], "is_default": True}}
    return _config.get("glozones", {INITIAL_ZONE_NAME: {"rhythm": DEFAULT_RHYTHM, "areas": [], "is_default": True}})


def get_rhythms() -> Dict[str, Dict[str, Any]]:
    """Get all Circadian Rhythm definitions from config.

    Returns:
        Dict of rhythm_name -> rhythm settings
    """
    if not _config:
        return {}
    return _config.get("circadian_rhythms", {})


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
        # Use unique temp file to prevent concurrent write collisions
        fd, tmp_path = tempfile.mkstemp(dir=data_dir, suffix=".tmp", prefix=".designer_")
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump(_config, f, indent=2)
            os.replace(tmp_path, designer_path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
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


def get_rhythm_for_zone(zone_name: str) -> Optional[str]:
    """Get the rhythm name for a zone.

    Args:
        zone_name: The zone name

    Returns:
        Rhythm name, or None if zone doesn't exist
    """
    glozones = get_glozones()
    zone_config = glozones.get(zone_name, {})
    return zone_config.get("rhythm", DEFAULT_RHYTHM)


def get_rhythm_for_area(area_id: str) -> Optional[str]:
    """Get the rhythm name for an area (via its zone).

    Args:
        area_id: The area ID

    Returns:
        Rhythm name
    """
    zone_name = get_zone_for_area(area_id)
    return get_rhythm_for_zone(zone_name)


def get_rhythm_config(rhythm_name: str) -> Dict[str, Any]:
    """Get the full configuration for a rhythm.

    Returns a complete config dict with defaults for any missing RHYTHM_SETTINGS
    keys, ensuring Config.from_dict() always gets the intended values rather than
    falling back to its own defaults.

    Args:
        rhythm_name: The rhythm name

    Returns:
        Rhythm config dict with defaults applied (empty dict if rhythm doesn't exist)
    """
    rhythms = get_rhythms()
    rhythm = rhythms.get(rhythm_name)
    if rhythm is None:
        return {}
    # Apply defaults for any missing rhythm settings
    defaults = {
        "color_mode": "kelvin",
        "min_color_temp": 500,
        "max_color_temp": 6500,
        "min_brightness": 1,
        "max_brightness": 100,
        "ascend_start": 3.0,
        "descend_start": 12.0,
        "wake_time": 7.0,
        "bed_time": 21.0,
        "wake_speed": 6,
        "bed_speed": 4,
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
    result = {**defaults, **rhythm}
    logger.debug(f"[get_rhythm_config] rhythm_name={rhythm_name}, "
                 f"raw rhythm keys={list(rhythm.keys())}, "
                 f"warm_night_enabled={result.get('warm_night_enabled')}, "
                 f"max_brightness={result.get('max_brightness')}")
    return result


def get_rhythm_config_for_area(area_id: str) -> Dict[str, Any]:
    """Get the full rhythm configuration for an area.

    Args:
        area_id: The area ID

    Returns:
        Rhythm config dict
    """
    rhythm_name = get_rhythm_for_area(area_id)
    return get_rhythm_config(rhythm_name) if rhythm_name else {}


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
            "rhythm": DEFAULT_RHYTHM,
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
        True if config has circadian_rhythms and glozones keys
    """
    if not _config:
        return False
    return "circadian_rhythms" in _config and "glozones" in _config


def get_area_zone_and_rhythm(area_id: str) -> Tuple[str, str, Dict[str, Any]]:
    """Get zone name, rhythm name, and rhythm config for an area.

    Convenience function that returns all zone-related info for an area.

    Args:
        area_id: The area ID

    Returns:
        Tuple of (zone_name, rhythm_name, rhythm_config)
    """
    zone_name = get_zone_for_area(area_id)
    rhythm_name = get_rhythm_for_zone(zone_name) or DEFAULT_RHYTHM
    rhythm_config = get_rhythm_config(rhythm_name)
    return zone_name, rhythm_name, rhythm_config


# Default filter presets
DEFAULT_FILTER_PRESETS = {
    "Standard": {"at_bright": 100, "at_dim": 100, "off_threshold": 3},
    "Overhead": {"at_bright": 100, "at_dim": 0, "off_threshold": 3},
    "Lamp": {"at_bright": 30, "at_dim": 100, "off_threshold": 3},
    "Accent": {"at_bright": 50, "at_dim": 50, "off_threshold": 3},
    "Nightlight": {"at_bright": 0, "at_dim": 40, "off_threshold": 3},
}

DEFAULT_OFF_THRESHOLD = 3


def get_light_filter_presets() -> Dict[str, Dict[str, int]]:
    """Get light filter presets from config, falling back to defaults.

    Returns:
        Dict of preset_name -> {"at_bright": int, "at_dim": int}
    """
    if not _config:
        return dict(DEFAULT_FILTER_PRESETS)
    lf = _config.get("light_filters", {})
    presets = lf.get("presets")
    if presets and isinstance(presets, dict):
        return presets
    return dict(DEFAULT_FILTER_PRESETS)


def get_off_threshold() -> int:
    """Get the off threshold from config.

    Lights filtered below this brightness percentage receive an OFF command
    instead of being set to near-zero.

    Returns:
        Threshold percentage (default 3)
    """
    if not _config:
        return DEFAULT_OFF_THRESHOLD
    lf = _config.get("light_filters", {})
    return lf.get("off_threshold", DEFAULT_OFF_THRESHOLD)


def get_area_entry(area_id: str) -> Optional[Dict[str, Any]]:
    """Find the area dict entry in glozones by area_id.

    Args:
        area_id: The area ID to look up

    Returns:
        The area dict entry, or None if not found
    """
    glozones = get_glozones()
    for zone_config in glozones.values():
        for area in zone_config.get("areas", []):
            if isinstance(area, dict) and area.get("id") == area_id:
                return area
    return None


def get_area_brightness_factor(area_id: str) -> float:
    """Get the brightness factor for an area.

    Args:
        area_id: The area ID

    Returns:
        Brightness factor (default 1.0)
    """
    entry = get_area_entry(area_id)
    if entry is None:
        return 1.0
    return float(entry.get("brightness_factor", 1.0))


def get_area_natural_light_exposure(area_id: str) -> float:
    """Get the natural light exposure for an area.

    Represents how much outdoor natural light reaches this area
    (0.0 = no natural light / interior room, 1.0 = sunroom / lots of windows).
    Used with sun elevation to dynamically reduce artificial brightness during the day.

    Args:
        area_id: The area ID

    Returns:
        Exposure value 0.0–1.0 (default 0.0, meaning no natural light adjustment)
    """
    entry = get_area_entry(area_id)
    if entry is None:
        return 0.0
    return float(entry.get("natural_light_exposure", 0.0))


def get_area_light_filters(area_id: str) -> Dict[str, str]:
    """Get light filter assignments for an area.

    Args:
        area_id: The area ID

    Returns:
        Dict of entity_id -> filter_preset_name (empty dict if none)
    """
    entry = get_area_entry(area_id)
    if entry is None:
        return {}
    filters = entry.get("light_filters")
    if filters and isinstance(filters, dict):
        return filters
    return {}


# Settings that are per-rhythm (not global)
RHYTHM_SETTINGS = {
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

# Settings that are global (not per-rhythm)
GLOBAL_SETTINGS = {
    "latitude", "longitude", "timezone", "use_ha_location", "month",
    "light_filters",
    "daylight_saturation_deg",
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

    Also migrates circadian_presets → circadian_rhythms and
    zone preset → rhythm field names.

    Args:
        config: The loaded config dict

    Returns:
        Migrated config dict (or original if already migrated)
    """
    # Migrate circadian_presets → circadian_rhythms
    if "circadian_presets" in config and "circadian_rhythms" not in config:
        config["circadian_rhythms"] = config.pop("circadian_presets")

    # Migrate zone "preset" → "rhythm" field
    for zone in config.get("glozones", {}).values():
        if "preset" in zone and "rhythm" not in zone:
            zone["rhythm"] = zone.pop("preset")

    # Check if already migrated
    if "circadian_rhythms" in config and "glozones" in config:
        return config

    logger.info("Migrating config to GloZone format...")

    # Extract rhythm settings from flat config
    rhythm_config = {}
    for key in RHYTHM_SETTINGS:
        if key in config:
            rhythm_config[key] = config[key]

    # Extract global settings
    global_config = {}
    for key in GLOBAL_SETTINGS:
        if key in config:
            global_config[key] = config[key]

    # Build new config structure
    new_config = {
        "circadian_rhythms": {
            DEFAULT_RHYTHM: rhythm_config
        },
        "glozones": {
            INITIAL_ZONE_NAME: {
                "rhythm": DEFAULT_RHYTHM,
                "areas": [],
                "is_default": True
            }
        },
    }

    # Add global settings
    new_config.update(global_config)

    logger.info(f"Migration complete: created rhythm '{DEFAULT_RHYTHM}' "
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

    # Start with global-only defaults. RHYTHM_SETTINGS are intentionally NOT
    # included here so that after merging the config files, any RHYTHM_SETTINGS
    # at the top level must have come from the file (user's settings), not from
    # defaults. This lets the merge step below reliably move them into the rhythm.
    # Missing rhythm keys are handled by get_rhythm_config() and Config.from_dict().
    config: Dict[str, Any] = {
        "latitude": 35.0,
        "longitude": -78.6,
        "timezone": "US/Eastern",
        "use_ha_location": True,
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
                logger.warning(f"JSON error reading {path}: {e}")
                # Backup for diagnostics but don't attempt repair —
                # with atomic writes this indicates a serious issue
                try:
                    with open(path, 'r') as f:
                        content = f.read()
                    with open(path + ".corrupted", 'w') as f:
                        f.write(content)
                    logger.warning(f"Backed up corrupted file to {path}.corrupted")
                except Exception:
                    pass
            except Exception as e:
                logger.debug(f"Could not load config from {path}: {e}")

    # Migrate to GloZone format if needed
    needs_migration = "circadian_rhythms" not in config or "glozones" not in config
    config = _migrate_config(config)

    # Move any top-level RHYTHM_SETTINGS into the first rhythm.
    # Only set the key in the rhythm if it's not already there, to avoid
    # stale top-level values (e.g., warm_night_enabled=false from old saves)
    # overriding correct rhythm values. Always remove from top level either way.
    if "circadian_rhythms" in config and config["circadian_rhythms"]:
        first_rhythm_name = list(config["circadian_rhythms"].keys())[0]
        first_rhythm = config["circadian_rhythms"][first_rhythm_name]
        for key in list(config.keys()):
            if key in RHYTHM_SETTINGS:
                if key not in first_rhythm:
                    first_rhythm[key] = config[key]
                del config[key]

    # Log what ended up in the rhythms after loading + merging
    for rname, rdata in config.get("circadian_rhythms", {}).items():
        logger.debug(f"[load_config] Rhythm '{rname}': "
                     f"warm_night_enabled={rdata.get('warm_night_enabled', 'MISSING')}, "
                     f"max_brightness={rdata.get('max_brightness', 'MISSING')}, "
                     f"keys={list(rdata.keys())}")
    # Log any remaining top-level RHYTHM_SETTINGS (should be none)
    leftover = [k for k in config.keys() if k in RHYTHM_SETTINGS]
    if leftover:
        logger.warning(f"[load_config] Top-level RHYTHM_SETTINGS still present: {leftover}")

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
            # Use unique temp file to prevent concurrent write collisions
            fd, tmp_path = tempfile.mkstemp(dir=data_dir, suffix=".tmp", prefix=".designer_")
            try:
                with os.fdopen(fd, 'w') as f:
                    json.dump(config, f, indent=2)
                os.replace(tmp_path, designer_path)
            except BaseException:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
            logger.info(f"Saved config to {designer_path}")
        except Exception as e:
            logger.warning(f"Failed to save config: {e}")

    return config


def get_effective_config_for_area(area_id: str, include_global: bool = True) -> Dict[str, Any]:
    """Get the effective configuration for an area.

    Combines the rhythm settings for the area's zone with global settings.
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

    # Get rhythm config for this area
    rhythm_config = get_rhythm_config_for_area(area_id)
    result.update(rhythm_config)

    # Add global settings if requested
    if include_global and _config:
        for key in GLOBAL_SETTINGS:
            if key in _config:
                result[key] = _config[key]

    return result


def get_effective_config_for_zone(zone_name: str, include_global: bool = True) -> Dict[str, Any]:
    """Get the effective configuration for a zone.

    Combines the rhythm settings for the zone with global settings.

    Args:
        zone_name: The zone name
        include_global: Whether to include global settings (latitude, etc.)

    Returns:
        Flat config dict with all settings merged
    """
    if _config is None:
        load_config_from_files()

    result = {}

    rhythm_name = get_rhythm_for_zone(zone_name)
    if rhythm_name:
        rhythm_config = get_rhythm_config(rhythm_name)
        result.update(rhythm_config)

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
