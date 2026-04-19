#!/usr/bin/env python3
"""Switch management for Circadian Light.

This module manages:
- Switch type definitions (button layouts, default mappings)
- Per-switch configuration (scopes, optional magic button assignments)
- Runtime state (current scope, last activity, pending detection)

Switch config is persisted to JSON. Runtime state is in-memory only.
Last action is persisted to a separate file for cross-process sharing.
"""

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import glozone

logger = logging.getLogger(__name__)

# =============================================================================
# Last Action File Persistence (shared between main.py and webserver.py)
# =============================================================================

_LAST_ACTION_FILE: Optional[Path] = None
_last_actions_cache: Optional[Dict[str, Any]] = None


def _get_last_action_file() -> Path:
    """Get the path to the last action file."""
    global _LAST_ACTION_FILE
    if _LAST_ACTION_FILE is None:
        if os.path.isdir("/config/circadian-light"):
            _LAST_ACTION_FILE = Path("/config/circadian-light/switch_last_actions.json")
        elif os.path.isdir("/data"):
            _LAST_ACTION_FILE = Path("/data/switch_last_actions.json")
        else:
            _LAST_ACTION_FILE = Path("/app/.data/switch_last_actions.json")
        _LAST_ACTION_FILE.parent.mkdir(parents=True, exist_ok=True)
    return _LAST_ACTION_FILE


def _load_last_actions() -> Dict[str, str]:
    """Load all last actions from file."""
    action_file = _get_last_action_file()
    if action_file.exists():
        try:
            with open(action_file, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Failed to load last actions file: {e}")
    return {}


def _save_last_actions(actions: Dict[str, str]) -> None:
    """Save all last actions to file."""
    action_file = _get_last_action_file()
    try:
        tmp_file = str(action_file) + ".tmp"
        with open(tmp_file, "w") as f:
            json.dump(actions, f, indent=2)
        os.replace(tmp_file, action_file)
    except IOError as e:
        logger.error(f"Failed to save last actions file: {e}")


def get_all_last_actions() -> Dict[str, Any]:
    """Return all last actions from in-memory cache (no disk I/O)."""
    global _last_actions_cache
    if _last_actions_cache is None:
        _last_actions_cache = _load_last_actions()
    return _last_actions_cache


def get_all_pause_states() -> Dict[str, Dict[str, Any]]:
    """Return pause state for all paused controls (no disk I/O)."""
    result = {}
    for switch_id, switch in _switches.items():
        if switch.inactive or switch.inactive_until:
            result[switch_id] = {
                "inactive": switch.inactive,
                "inactive_until": switch.inactive_until,
            }
    for sensor_id, sensor in _motion_sensors.items():
        key = sensor.device_id or sensor_id
        if sensor.inactive or sensor.inactive_until:
            result[key] = {
                "inactive": sensor.inactive,
                "inactive_until": sensor.inactive_until,
            }
    for sensor_id, sensor in _contact_sensors.items():
        key = sensor.device_id or sensor_id
        if sensor.inactive or sensor.inactive_until:
            result[key] = {
                "inactive": sensor.inactive,
                "inactive_until": sensor.inactive_until,
            }
    return result


# =============================================================================
# Custom Button Mappings (from designer_config.json)
# =============================================================================

# Cached custom mappings loaded from designer_config.json
_custom_mappings: Dict[str, Dict[str, Any]] = {}


def _get_designer_config_path() -> str:
    """Get the path to the designer_config.json file."""
    if os.path.isdir("/config/circadian-light"):
        return "/config/circadian-light/designer_config.json"
    elif os.path.isdir("/data"):
        return "/data/designer_config.json"
    else:
        return os.path.join(os.path.dirname(__file__), ".data", "designer_config.json")


def load_custom_mappings() -> Dict[str, Dict[str, Any]]:
    """Load custom switch mappings from designer_config.json.

    Returns:
        Dict of switch_type -> button_event -> action (or {action, when_off})
    """
    global _custom_mappings
    config_path = _get_designer_config_path()

    if not os.path.exists(config_path):
        _custom_mappings = {}
        return _custom_mappings

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        _custom_mappings = config.get("switch_mappings", {})
        logger.debug(
            f"Loaded custom switch mappings for types: {list(_custom_mappings.keys())}"
        )
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Failed to load custom switch mappings: {e}")
        _custom_mappings = {}

    return _custom_mappings


def get_custom_mappings() -> Dict[str, Dict[str, Any]]:
    """Get the cached custom mappings (reloads if empty)."""
    if not _custom_mappings:
        load_custom_mappings()
    return _custom_mappings


def get_effective_mapping(switch_type: str, button_event: str) -> Optional[Any]:
    """Get the effective action for a button event, merging custom over default.

    Args:
        switch_type: The switch type key (e.g., "hue_4button_v2")
        button_event: The button event (e.g., "on_short_release")

    Returns:
        The action - either a string action name, a dict with {action, when_off},
        or None for unmapped.
    """
    # Reload custom mappings to pick up changes
    load_custom_mappings()

    # Check custom mappings first
    if switch_type in _custom_mappings:
        custom = _custom_mappings[switch_type]
        if button_event in custom:
            return custom[button_event]

    # Fall back to default mapping
    switch_type_info = SWITCH_TYPES.get(switch_type)
    if switch_type_info:
        return switch_type_info.get("default_mapping", {}).get(button_event)

    return None


def save_custom_mappings(mappings: Dict[str, Dict[str, Any]]) -> bool:
    """Save custom switch mappings to designer_config.json.

    Args:
        mappings: Dict of switch_type -> button_event -> action

    Returns:
        True on success, False on failure.
    """
    global _custom_mappings
    config_path = _get_designer_config_path()

    # Load existing config
    config = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        except (json.JSONDecodeError, IOError):
            config = {}

    # Update switch mappings
    config["switch_mappings"] = mappings

    # Save atomically
    try:
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        tmp_path = config_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        os.replace(tmp_path, config_path)
        _custom_mappings = mappings
        logger.info(f"Saved custom switch mappings for types: {list(mappings.keys())}")
        return True
    except IOError as e:
        logger.error(f"Failed to save custom switch mappings: {e}")
        return False


# =============================================================================
# Switch Type Definitions (hardcoded)
# =============================================================================

# Available actions that can be mapped to buttons
# Note: Moment actions (set_sleep, set_exit, etc.) are also valid - see get_all_available_actions()
AVAILABLE_ACTIONS = [
    "circadian_on",  # Enable + apply circadian values
    "circadian_off",  # Disable circadian mode (lights unchanged)
    "toggle",  # Smart toggle based on state
    "step_up",  # Brighter + cooler along curve
    "step_down",  # Dimmer + warmer along curve
    "step_up_2",  # 2× step up
    "step_down_2",  # 2× step down
    "step_up_3",  # 3× step up
    "step_down_3",  # 3× step down
    "bright_up",  # Brightness only
    "bright_down",  # Brightness only
    "bright_up_2",  # 2× bright up
    "bright_down_2",  # 2× bright down
    "bright_up_3",  # 3× bright up
    "bright_down_3",  # 3× bright down
    "color_up",  # Color temp only
    "color_down",  # Color temp only
    "glo_reset",  # Reset area to Daily Rhythm
    "freeze_toggle",  # Toggle freeze at current position
    "glo_up",  # Push area settings to GloZone
    "glo_down",  # Pull GloZone settings to area
    "glozone_reset",  # Reset GloZone to Daily Rhythm
    "glozone_down",  # Push GloZone settings to all areas
    "full_send",  # glo_up + glozone_down (push area to zone to all)
    "glozone_reset_full",  # glozone_reset + glozone_down (reset zone + push to all)
    "cycle_scope",  # Cycle through scopes
    "set_britelite",  # 100% brightness, cool white (6500K)
    "set_nitelite",  # 5% brightness, warm (2200K)
    "toggle_wake_bed",  # Legacy alias for set_wake_or_bed
    "set_wake_or_bed",  # Wake (ascend) or Bed (descend) midpoint
    None,  # Unmapped / do nothing
]


def get_all_available_actions() -> list:
    """Get all available actions including moment actions.

    Returns a copy of AVAILABLE_ACTIONS plus any configured moments
    as set_{moment_id} actions.

    Returns:
        List of action names
    """
    actions = AVAILABLE_ACTIONS.copy()

    # Add moment actions dynamically
    try:
        import glozone

        raw_config = glozone.load_config_from_files()
        moments = raw_config.get("moments", {})
        for moment_id in moments.keys():
            action_name = f"set_{moment_id}"
            if action_name not in actions:
                actions.insert(-1, action_name)  # Insert before None
    except Exception:
        pass

    return actions


# Actions that support a when_off alternate action
ADJUSTMENT_ACTIONS = [
    "step_up",
    "step_down",
    "step_up_2",
    "step_down_2",
    "step_up_3",
    "step_down_3",
    "bright_up",
    "bright_down",
    "bright_up_2",
    "bright_down_2",
    "bright_up_3",
    "bright_down_3",
    "color_up",
    "color_down",
]

# Allowed alternate actions for when_off
WHEN_OFF_ACTIONS = [
    "circadian_on",
    "circadian_toggle",
    "set_nitelite",
    "set_britelite",
    "set_wake_or_bed",
    None,  # No alternate action
]


def get_categorized_actions() -> Dict[str, List[Dict[str, Any]]]:
    """Get all available actions organized by category.

    Returns:
        Dict of category name -> list of {id, label, supports_when_off} dicts
    """
    categories = {
        "_top": [
            {"id": None, "label": "No Action"},
            {"id": "magic", "label": "Magic"},
        ],
        "Adjust areas in Reach": [
            {"id": "circadian_on", "label": "On"},
            {"id": "circadian_off", "label": "Off"},
            {"id": "circadian_toggle", "label": "Toggle on/off"},
            {"id": "step_up", "label": "Step Up", "supports_when_off": True},
            {"id": "step_up_2", "label": "Step Up 2\u00d7", "supports_when_off": True},
            {"id": "step_up_3", "label": "Step Up 3\u00d7", "supports_when_off": True},
            {"id": "step_down", "label": "Step Down", "supports_when_off": True},
            {
                "id": "step_down_2",
                "label": "Step Down 2\u00d7",
                "supports_when_off": True,
            },
            {
                "id": "step_down_3",
                "label": "Step Down 3\u00d7",
                "supports_when_off": True,
            },
            {"id": "bright_up", "label": "Bright Up", "supports_when_off": True},
            {
                "id": "bright_up_2",
                "label": "Bright Up 2\u00d7",
                "supports_when_off": True,
            },
            {
                "id": "bright_up_3",
                "label": "Bright Up 3\u00d7",
                "supports_when_off": True,
            },
            {
                "id": "bright_up_4",
                "label": "Bright Up 4\u00d7",
                "supports_when_off": True,
            },
            {
                "id": "bright_up_5",
                "label": "Bright Up 5\u00d7",
                "supports_when_off": True,
            },
            {"id": "bright_down", "label": "Bright Down", "supports_when_off": True},
            {
                "id": "bright_down_2",
                "label": "Bright Down 2\u00d7",
                "supports_when_off": True,
            },
            {
                "id": "bright_down_3",
                "label": "Bright Down 3\u00d7",
                "supports_when_off": True,
            },
            {
                "id": "bright_down_4",
                "label": "Bright Down 4\u00d7",
                "supports_when_off": True,
            },
            {
                "id": "bright_down_5",
                "label": "Bright Down 5\u00d7",
                "supports_when_off": True,
            },
            {"id": "color_up", "label": "Color Up", "supports_when_off": True},
            {"id": "color_down", "label": "Color Down", "supports_when_off": True},
            {"id": "set_britelite", "label": "BriteLite"},
            {"id": "set_nitelite", "label": "NiteLite"},
            {"id": "set_wake_or_bed", "label": "Wake / Bed"},
            {"id": "freeze_toggle", "label": "Freeze"},
            {"id": "glo_reset", "label": "Reset to Circadian"},
            {"id": "glo_down", "label": "Reset to Rhythm Zone"},
        ],
        "Rhythm Zone": [
            {"id": "full_send", "label": "Push to whole Rhythm Zone"},
            {"id": "glozone_reset_full", "label": "Reset whole Rhythm Zone"},
        ],
        "Switch": [
            {"id": "cycle_scope", "label": "Advance to next Reach"},
        ],
        "Dial": [
            {"id": "set_position_step", "label": "Circadian (brightness + color)"},
            {"id": "set_position_brightness", "label": "Bright only"},
            {"id": "set_position_color", "label": "Color only"},
        ],
    }

    # Add moment actions dynamically
    try:
        import glozone

        raw_config = glozone.load_config_from_files()
        moments = raw_config.get("moments", {})
        if moments:
            moment_actions = []
            for moment_id, moment_data in moments.items():
                moment_name = moment_data.get("name", moment_id)
                moment_actions.append(
                    {
                        "id": f"set_{moment_id}",
                        "label": moment_name,
                    }
                )
            if moment_actions:
                categories["Moments"] = moment_actions
    except Exception:
        pass

    return categories


def get_when_off_options() -> List[Dict[str, Any]]:
    """Get available when_off options for adjustment actions.

    Returns:
        List of {id, label} dicts for when_off dropdown.
    """
    return [
        {"id": None, "label": "No Action"},
        {"id": "circadian_on", "label": "On"},
        {"id": "circadian_toggle", "label": "Toggle"},
        {"id": "set_nitelite", "label": "NiteLite"},
        {"id": "set_britelite", "label": "BriteLite"},
        {"id": "set_wake_or_bed", "label": "Wake / Bed"},
    ]


# Button action types (event suffixes from ZHA)
BUTTON_ACTION_TYPES = [
    "press",  # Immediately when pressed
    "hold",  # After ~0.5s if still held
    "short_release",  # Released quickly (short press)
    "long_release",  # Released after hold
    "double_press",  # Double click
    "triple_press",  # Triple click
    "quadruple_press",  # 4x click
    "quintuple_press",  # 5x click
]

# Switch type definitions
# Shared button mapping for Hue 4-button dimmers (v1 and v2 use same layout)
_HUE_4BUTTON_MAPPING = {
    # On button (top)
    "on_short_release": "circadian_toggle",  # 1x - on/off
    "on_double_press": "cycle_scope",  # 2x - advance to next reach
    "on_triple_press": "magic",  # 3x - magic
    "on_quadruple_press": None,  # 4x - not used
    "on_quintuple_press": None,  # 5x - not used
    "on_hold": "full_send",  # long - push to whole rhythm zone
    "on_long_release": None,
    # Up button
    "up_short_release": {"action": "bright_up", "when_off": "set_nitelite"},
    "up_double_press": {"action": "bright_up_2", "when_off": None},
    "up_triple_press": {"action": "bright_up_3", "when_off": None},
    "up_quadruple_press": {"action": "bright_up_4", "when_off": None},
    "up_quintuple_press": {"action": "bright_up_5", "when_off": None},
    "up_hold": {"action": "step_up", "when_off": "set_britelite"},
    "up_long_release": None,
    # Down button
    "down_short_release": {"action": "bright_down", "when_off": "set_nitelite"},
    "down_double_press": {"action": "bright_down_2", "when_off": None},
    "down_triple_press": {"action": "bright_down_3", "when_off": None},
    "down_quadruple_press": {"action": "bright_down_4", "when_off": None},
    "down_quintuple_press": {"action": "bright_down_5", "when_off": None},
    "down_hold": {"action": "step_down", "when_off": "set_nitelite"},
    "down_long_release": None,
    # Hue button (bottom)
    "off_short_release": "glo_reset",  # 1x - reset to rhythm zone
    "off_double_press": "glozone_reset_full",  # 2x - reset whole rhythm zone
    "off_triple_press": "magic",  # 3x - magic
    "off_quadruple_press": None,  # 4x - not used
    "off_quintuple_press": None,  # 5x - not used
    "off_hold": "magic",  # long - magic
    "off_long_release": None,
}

# Each type defines available buttons and default action mappings
SWITCH_TYPES: Dict[str, Dict[str, Any]] = {
    "hue_dimmer": {
        "name": "Hue 4-button switch",
        "manufacturers": ["Philips", "Signify", "Signify Netherlands B.V."],
        "models": ["RWL020", "RWL021", "RWL022"],  # v1, v1.5, v2
        "buttons": ["on", "up", "down", "off"],
        "action_types": [
            "press",
            "hold",
            "short_release",
            "long_release",
            "double_press",
            "triple_press",
            "quadruple_press",
            "quintuple_press",
        ],
        "default_mapping": _HUE_4BUTTON_MAPPING,
        "repeat_on_hold": ["up_hold", "down_hold"],
        "repeat_interval_ms": 300,
    },
    "hue_smart_button": {
        "name": "Hue Smart Button",
        "manufacturers": ["Philips", "Signify", "Signify Netherlands B.V."],
        "models": ["ROM001", "RDM003"],
        "buttons": ["on"],
        "action_types": [
            "press",
            "hold",
            "short_release",
            "long_release",
            "double_press",
            "triple_press",
            "quadruple_press",
            "quintuple_press",
        ],
        "default_mapping": {
            "on_short_release": "magic",  # 1x - magic button
            "on_double_press": None,
            "on_triple_press": None,
            "on_quadruple_press": None,
            "on_quintuple_press": None,
            "on_hold": "magic",  # long - magic button
            "on_long_release": None,
        },
        "repeat_on_hold": [],
        "repeat_interval_ms": 300,
    },
    "lutron_aurora": {
        "name": "Lutron Aurora Dimmer",
        "manufacturers": ["Lutron"],
        "models": ["Z3-1BRL"],
        "buttons": ["dial"],
        "action_types": ["press", "rotate"],
        "dial": True,  # Continuous input — rotation maps to set_position
        "default_mapping": {
            "dial_press": "toggle",
            "dial_rotate": "set_position_step",  # Dial controls Glo (step mode)
        },
        "repeat_on_hold": [],
        "repeat_interval_ms": 300,
    },
    "ikea_tradfri_remote": {
        "name": "IKEA Tradfri Remote",
        "manufacturer": "IKEA",
        "models": ["E1524", "E1810"],
        "buttons": [
            "toggle",
            "brightness_up",
            "brightness_down",
            "arrow_left",
            "arrow_right",
        ],
        "action_types": ["press", "hold", "release"],
        "default_mapping": {
            "toggle_press": "toggle",
            "brightness_up_press": {"action": "step_up", "when_off": "set_nitelite"},
            "brightness_up_hold": {"action": "bright_up", "when_off": None},
            "brightness_up_release": None,
            "brightness_down_press": "cycle_scope",
            "brightness_down_hold": {"action": "bright_down", "when_off": None},
            "brightness_down_release": None,
            "arrow_left_press": {"action": "color_down", "when_off": None},
            "arrow_left_hold": {"action": "color_down", "when_off": None},
            "arrow_right_press": {"action": "color_up", "when_off": None},
            "arrow_right_hold": {"action": "color_up", "when_off": None},
        },
        "repeat_on_hold": ["brightness_up_hold", "brightness_down_hold"],
        "repeat_interval_ms": 300,
    },
}


# =============================================================================
# Sensor Names (for display purposes)
# =============================================================================

# Maps (manufacturer_lower, model) to friendly display name
# Model matching is exact (case-insensitive), manufacturer is partial match
# Covers both motion sensors and contact sensors
SENSOR_NAMES: Dict[str, Dict[str, str]] = {
    # Philips Hue sensors
    "signify": {
        # Motion sensors
        "SML001": "Hue Indoor Motion",
        "SML002": "Hue Outdoor Motion",
        "SML003": "Hue Indoor Motion (new)",
        "SML004": "Hue Outdoor Motion (new)",
        # Contact sensors
        "SOC001": "Hue Secure Contact",
    },
    "philips": {
        "SML001": "Hue Indoor Motion",
        "SML002": "Hue Outdoor Motion",
    },
    # Add more manufacturers as needed
}


# =============================================================================
# Allowlist: Curated model dicts for opt-in controls discovery
# =============================================================================

MOTION_SENSOR_MODELS: Dict[str, Dict[str, Dict[str, Any]]] = {
    "signify": {
        "SML001": {"name": "Hue Indoor Motion"},
        "SML002": {"name": "Hue Outdoor Motion"},
        "SML003": {"name": "Hue Indoor Motion (new)"},
        "SML004": {"name": "Hue Outdoor Motion (new)"},
    },
    "philips": {
        "SML001": {"name": "Hue Indoor Motion"},
        "SML002": {"name": "Hue Outdoor Motion"},
    },
    "switchbot": {
        "Hub 3": {"name": "SwitchBot Hub 3"},
    },
    "gl technologies": {
        "40961": {"name": "Lafaer Presence"},
    },
    "lumi": {
        "lumi.motion.ac02": {"name": "Aqara P1 Motion"},
    },
}

CONTACT_SENSOR_MODELS: Dict[str, Dict[str, Dict[str, Any]]] = {
    "signify": {
        "SOC001": {"name": "Hue Secure Contact"},
    },
    "philips": {
        "SOC001": {"name": "Hue Secure Contact"},
    },
}

CAMERA_MODELS: Dict[str, Dict[str, Dict[str, Any]]] = {
    "eufy security": {
        "T8162": {
            "name": "Eufy Outdoor Camera",
            "trigger_patterns": [
                "_motion_detected",
                "_person_detected",
                "_pet_detected",
                "_vehicle_detected",
            ],
        },
        "T8214": {
            "name": "Eufy Video Doorbell",
            "trigger_patterns": [
                "_motion_detected",
                "_person_detected",
                "_pet_detected",
                "_vehicle_detected",
                "_ringing",
                "_package_delivered",
                "_package_stranded",
                "_package_taken",
            ],
        },
    },
}


def detect_control_type(
    manufacturer: Optional[str], model: Optional[str]
) -> Optional[Dict[str, Any]]:
    """Check all allowlist dicts and return control info or None.

    Searches: SWITCH_TYPES, MOTION_SENSOR_MODELS, CONTACT_SENSOR_MODELS, CAMERA_MODELS.
    Cameras return category "motion_sensor" since they use the same data model.
    """
    if not manufacturer or not model:
        return None

    # Check switches first (delegates to existing detect_switch_type)
    switch_type = detect_switch_type(manufacturer, model)
    if switch_type:
        type_info = SWITCH_TYPES.get(switch_type, {})
        return {
            "category": "switch",
            "type": switch_type,
            "name": type_info.get("name"),
        }

    manufacturer_lower = manufacturer.lower()

    # Check motion sensors
    for mfr_key, models_dict in MOTION_SENSOR_MODELS.items():
        if mfr_key in manufacturer_lower:
            for model_key, meta in models_dict.items():
                if model.upper() == model_key.upper():
                    return {"category": "motion_sensor", "name": meta["name"]}

    # Check contact sensors
    for mfr_key, models_dict in CONTACT_SENSOR_MODELS.items():
        if mfr_key in manufacturer_lower:
            for model_key, meta in models_dict.items():
                if model.upper() == model_key.upper():
                    return {"category": "contact_sensor", "name": meta["name"]}

    # Check cameras (map to motion_sensor category)
    for mfr_key, models_dict in CAMERA_MODELS.items():
        if mfr_key in manufacturer_lower:
            for model_key, meta in models_dict.items():
                if model.upper() == model_key.upper():
                    return {
                        "category": "motion_sensor",
                        "name": meta["name"],
                        "trigger_patterns": meta.get("trigger_patterns", []),
                    }

    return None


def get_sensor_name(manufacturer: Optional[str], model: Optional[str]) -> Optional[str]:
    """Get friendly display name for a sensor (motion or contact).

    Returns None if no matching name found (caller should fall back to model).
    """
    if not manufacturer or not model:
        return None

    manufacturer_lower = manufacturer.lower()

    # Check each known manufacturer (partial match)
    for mfr_key, models in SENSOR_NAMES.items():
        if mfr_key in manufacturer_lower:
            # Case-insensitive model lookup
            for model_key, name in models.items():
                if model.upper() == model_key.upper():
                    return name

    return None


# Backwards compatibility alias
def get_motion_sensor_name(
    manufacturer: Optional[str], model: Optional[str]
) -> Optional[str]:
    """Deprecated: Use get_sensor_name instead."""
    return get_sensor_name(manufacturer, model)


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class SwitchScope:
    """A scope defines which areas a switch controls."""

    areas: List[str] = field(default_factory=list)
    feedback_area: Optional[str] = None  # Area in this scope for feedback cues


@dataclass
class SwitchConfig:
    """Configuration for a single switch."""

    id: str  # IEEE address or unique identifier
    name: str  # User-friendly name
    type: str  # Switch type key (e.g., "hue_4button_v2")
    scopes: List[SwitchScope] = field(default_factory=list)
    magic_buttons: Dict[str, Optional[str]] = field(default_factory=dict)
    device_id: Optional[str] = None  # HA device_id for area lookup
    inactive: bool = False  # If True, switch won't trigger actions
    inactive_until: Optional[str] = None  # ISO timestamp or "forever"; None = no timer

    def get_button_action(self, button_event: str) -> Any:
        """Get the action for a button event, with magic button support.

        Resolution order:
        1. Per-switch magic_buttons (magic button assignments)
        2. Global custom mappings from designer_config.json (switchmap UI)
        3. Default mappings for the switch type

        Returns:
            Action string, dict {action, when_off}, or None for unmapped.
        """
        # Check for switch-level magic button assignment first
        if button_event in self.magic_buttons:
            return self.magic_buttons[button_event]
        # Use effective mapping (custom -> default)
        return get_effective_mapping(self.type, button_event)

    def get_areas_for_scope(self, scope_index: int) -> List[str]:
        """Get areas for a specific scope index."""
        if 0 <= scope_index < len(self.scopes):
            return self.scopes[scope_index].areas
        return []

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "scopes": [
                {
                    "areas": s.areas,
                    **({"feedback_area": s.feedback_area} if s.feedback_area else {}),
                }
                for s in self.scopes
            ],
            "magic_buttons": self.magic_buttons,
        }
        if self.device_id:
            result["device_id"] = self.device_id
        if self.inactive:
            result["inactive"] = True
        if self.inactive_until:
            result["inactive_until"] = self.inactive_until
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SwitchConfig":
        """Create from dictionary."""
        scopes = [
            SwitchScope(areas=s.get("areas", []), feedback_area=s.get("feedback_area"))
            for s in data.get("scopes", [])
        ]
        # Migrate old type names to new names
        switch_type = data.get("type", "hue_dimmer")
        type_migrations = {
            "hue_4button_v1": "hue_dimmer",  # Old names -> merged type
            "hue_4button_v2": "hue_dimmer",
        }
        switch_type = type_migrations.get(switch_type, switch_type)
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            type=switch_type,
            scopes=scopes,
            magic_buttons=data.get("magic_buttons", data.get("button_overrides", {})),
            device_id=data.get("device_id"),
            inactive=data.get("inactive", False),
            inactive_until=data.get("inactive_until"),
        )


@dataclass
class SwitchRuntimeState:
    """Runtime state for a switch (not persisted)."""

    current_scope: int = 0
    last_activity: float = 0.0
    hold_active: bool = False
    hold_action: Optional[str] = None
    last_action: Optional[str] = None  # Last button event (e.g., "on_short_release")


# =============================================================================
# Motion Sensor Data Classes
# =============================================================================


@dataclass
class MotionAreaConfig:
    """Runtime view of one area's motion config (expanded from a MotionScope).

    Used by event handlers to iterate per-area. Not stored directly —
    MotionSensorConfig stores MotionScope objects and expands them via
    the `areas` property.
    """

    area_id: str
    mode: str = "on_off"  # on_only, on_off, alert, disabled
    duration: int = 60  # seconds for on_off auto-off timer
    boost_enabled: bool = False  # whether to boost brightness
    boost_brightness: int = 50  # percentage points to add when boosting
    active_when: str = "always"  # always, sunset_to_sunrise, wake_to_bed
    active_offset: int = 0  # minutes: positive = widen window, negative = shrink
    cooldown: int = 0  # per-scope cooldown in seconds (0 = use sensor default)
    trigger_entities: List[str] = field(
        default_factory=list
    )  # specific entity_ids that trigger this scope (empty = any)
    alert_intensity: str = "low"  # low, med, high — multiplier for bounce percentage
    alert_count: int = 3  # number of bounces in alert mode


@dataclass
class MotionScope:
    """A scope defines which areas a motion sensor controls and how.

    All areas in a scope share the same settings (mode, duration, boost, etc.).
    A motion sensor can have multiple scopes with different settings.
    """

    areas: List[str] = field(default_factory=list)
    mode: str = "on_off"  # on_only, on_off, alert, disabled
    duration: int = 60  # seconds for on_off auto-off timer
    boost_enabled: bool = False
    boost_brightness: int = 50
    active_when: str = "always"  # always, sunset_to_sunrise, wake_to_bed
    active_offset: int = 0  # minutes: positive = widen window, negative = shrink
    cooldown: int = 0  # per-scope cooldown in seconds (0 = use sensor default)
    trigger_entities: List[str] = field(default_factory=list)
    alert_intensity: str = "low"  # low, med, high
    alert_count: int = 3  # number of bounces in alert mode

    def to_area_configs(self) -> List["MotionAreaConfig"]:
        """Expand this scope into per-area MotionAreaConfig objects."""
        return [
            MotionAreaConfig(
                area_id=area_id,
                mode=self.mode,
                duration=self.duration,
                boost_enabled=self.boost_enabled,
                boost_brightness=self.boost_brightness,
                active_when=self.active_when,
                active_offset=self.active_offset,
                cooldown=self.cooldown,
                trigger_entities=list(self.trigger_entities),
                alert_intensity=self.alert_intensity,
                alert_count=self.alert_count,
            )
            for area_id in self.areas
        ]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        d: Dict[str, Any] = {
            "areas": list(self.areas),
            "mode": self.mode,
            "duration": self.duration,
            "boost_enabled": self.boost_enabled,
            "boost_brightness": self.boost_brightness,
        }
        if self.active_when != "always":
            d["active_when"] = self.active_when
            d["active_offset"] = self.active_offset
        if self.cooldown > 0:
            d["cooldown"] = self.cooldown
        if self.trigger_entities:
            d["trigger_entities"] = self.trigger_entities
        if self.mode == "alert":
            d["alert_intensity"] = self.alert_intensity
            d["alert_count"] = self.alert_count
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MotionScope":
        """Create from dictionary."""
        return cls(
            areas=data.get("areas", []),
            mode=data.get("mode", "on_off"),
            duration=data.get("duration", 60),
            boost_enabled=data.get("boost_enabled", False),
            boost_brightness=data.get("boost_brightness", 50),
            active_when=data.get("active_when", "always"),
            active_offset=data.get("active_offset", 0),
            cooldown=data.get("cooldown", 0),
            trigger_entities=data.get("trigger_entities", []),
            alert_intensity=data.get("alert_intensity", "low"),
            alert_count=data.get("alert_count", 3),
        )

    @classmethod
    def from_legacy_area(cls, area_data: Dict[str, Any]) -> "MotionScope":
        """Migrate a single legacy MotionAreaConfig dict into a 1-area scope."""
        # Handle old 'function' format
        mode = area_data.get("mode", "on_off")
        boost_enabled = area_data.get("boost_enabled", False)
        if "function" in area_data and "mode" not in area_data:
            old_function = area_data.get("function", "on_off")
            if old_function == "boost":
                mode = "on_off"
                boost_enabled = True
            else:
                mode = old_function
                boost_enabled = False

        return cls(
            areas=[area_data.get("area_id", "")],
            mode=mode,
            duration=area_data.get("duration", 60),
            boost_enabled=boost_enabled,
            boost_brightness=area_data.get("boost_brightness", 50),
            active_when=area_data.get("active_when", "always"),
            active_offset=area_data.get("active_offset", 0),
            cooldown=area_data.get("cooldown", 0),
            trigger_entities=area_data.get("trigger_entities", []),
            alert_intensity=area_data.get("alert_intensity", "low"),
            alert_count=area_data.get("alert_count", 3),
        )


@dataclass
class MotionSensorConfig:
    """Configuration for a motion sensor."""

    id: str  # Device ID or unique identifier
    name: str  # User-friendly name
    scopes: List[MotionScope] = field(default_factory=list)
    device_id: Optional[str] = None  # HA device_id
    inactive: bool = False  # If True, sensor won't trigger actions
    inactive_until: Optional[str] = None  # ISO timestamp or "forever"; None = no timer
    trigger_entities: List[str] = field(
        default_factory=list
    )  # all binary_sensor entity_ids to listen for (union of scope-level lists)

    @property
    def areas(self) -> List[MotionAreaConfig]:
        """Expand scopes into per-area MotionAreaConfig objects.

        Provides backward compatibility for event handlers that iterate
        per-area with area_config.area_id, .mode, .duration, etc.
        """
        result = []
        for scope in self.scopes:
            result.extend(scope.to_area_configs())
        return result

    def get_area_config(self, area_id: str) -> Optional[MotionAreaConfig]:
        """Get config for a specific area."""
        for area in self.areas:
            if area.area_id == area_id:
                return area
        return None

    def get_all_area_ids(self) -> List[str]:
        """Get list of all area IDs this sensor controls."""
        return [area_id for scope in self.scopes for area_id in scope.areas]

    def remove_area(self, area_id: str) -> bool:
        """Remove an area from its scope. Returns True if found and removed."""
        for scope in self.scopes:
            if area_id in scope.areas:
                scope.areas.remove(area_id)
                return True
        return False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "id": self.id,
            "name": self.name,
            "scopes": [s.to_dict() for s in self.scopes],
            "inactive": self.inactive,
        }
        if self.device_id:
            result["device_id"] = self.device_id
        if self.inactive_until:
            result["inactive_until"] = self.inactive_until
        if self.trigger_entities:
            result["trigger_entities"] = self.trigger_entities
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MotionSensorConfig":
        """Create from dictionary, with migration from legacy flat areas."""
        if "scopes" in data:
            scopes = [MotionScope.from_dict(s) for s in data["scopes"]]
        elif "areas" in data:
            # Legacy migration: each area becomes its own 1-area scope
            scopes = [MotionScope.from_legacy_area(a) for a in data["areas"]]
        else:
            scopes = []
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            scopes=scopes,
            device_id=data.get("device_id"),
            inactive=data.get("inactive", False),
            inactive_until=data.get("inactive_until"),
            trigger_entities=data.get("trigger_entities", []),
        )


# =============================================================================
# Contact Sensor Data Classes
# =============================================================================


@dataclass
class ContactAreaConfig:
    """Runtime view of one area's contact config (expanded from a ContactScope).

    Used by event handlers to iterate per-area. Not stored directly —
    ContactSensorConfig stores ContactScope objects and expands them via
    the `areas` property.
    """

    area_id: str
    mode: str = "on_off"  # on_only, on_off, disabled
    duration: int = (
        60  # seconds, fallback timer for on_off (0 = forever, rely on close)
    )
    boost_enabled: bool = False
    boost_brightness: int = 50


@dataclass
class ContactScope:
    """A scope defines which areas a contact sensor controls and how.

    All areas in a scope share the same settings.
    """

    areas: List[str] = field(default_factory=list)
    mode: str = "on_off"  # on_only, on_off, disabled
    duration: int = 60
    boost_enabled: bool = False
    boost_brightness: int = 50

    def to_area_configs(self) -> List["ContactAreaConfig"]:
        """Expand this scope into per-area ContactAreaConfig objects."""
        return [
            ContactAreaConfig(
                area_id=area_id,
                mode=self.mode,
                duration=self.duration,
                boost_enabled=self.boost_enabled,
                boost_brightness=self.boost_brightness,
            )
            for area_id in self.areas
        ]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "areas": list(self.areas),
            "mode": self.mode,
            "duration": self.duration,
            "boost_enabled": self.boost_enabled,
            "boost_brightness": self.boost_brightness,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContactScope":
        """Create from dictionary."""
        return cls(
            areas=data.get("areas", []),
            mode=data.get("mode", "on_off"),
            duration=data.get("duration", 60),
            boost_enabled=data.get("boost_enabled", False),
            boost_brightness=data.get("boost_brightness", 50),
        )

    @classmethod
    def from_legacy_area(cls, area_data: Dict[str, Any]) -> "ContactScope":
        """Migrate a single legacy ContactAreaConfig dict into a 1-area scope."""
        mode = area_data.get("mode", "on_off")
        boost_enabled = area_data.get("boost_enabled", False)
        if "function" in area_data and "mode" not in area_data:
            old_function = area_data.get("function", "on_off")
            if old_function == "boost":
                mode = "on_off"
                boost_enabled = True
            else:
                mode = old_function
                boost_enabled = False

        return cls(
            areas=[area_data.get("area_id", "")],
            mode=mode,
            duration=area_data.get("duration", 60),
            boost_enabled=boost_enabled,
            boost_brightness=area_data.get("boost_brightness", 50),
        )


@dataclass
class ContactSensorConfig:
    """Configuration for a contact sensor (door/window sensor)."""

    id: str  # Device ID or unique identifier
    name: str  # User-friendly name
    scopes: List[ContactScope] = field(default_factory=list)
    device_id: Optional[str] = None  # HA device_id
    inactive: bool = False  # If True, sensor won't trigger actions
    inactive_until: Optional[str] = None  # ISO timestamp or "forever"; None = no timer

    @property
    def areas(self) -> List[ContactAreaConfig]:
        """Expand scopes into per-area ContactAreaConfig objects."""
        result = []
        for scope in self.scopes:
            result.extend(scope.to_area_configs())
        return result

    def get_area_config(self, area_id: str) -> Optional[ContactAreaConfig]:
        """Get config for a specific area."""
        for area in self.areas:
            if area.area_id == area_id:
                return area
        return None

    def get_all_area_ids(self) -> List[str]:
        """Get list of all area IDs this sensor controls."""
        return [area_id for scope in self.scopes for area_id in scope.areas]

    def remove_area(self, area_id: str) -> bool:
        """Remove an area from its scope. Returns True if found and removed."""
        for scope in self.scopes:
            if area_id in scope.areas:
                scope.areas.remove(area_id)
                return True
        return False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "id": self.id,
            "name": self.name,
            "scopes": [s.to_dict() for s in self.scopes],
            "inactive": self.inactive,
        }
        if self.device_id:
            result["device_id"] = self.device_id
        if self.inactive_until:
            result["inactive_until"] = self.inactive_until
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContactSensorConfig":
        """Create from dictionary, with migration from legacy flat areas."""
        if "scopes" in data:
            scopes = [ContactScope.from_dict(s) for s in data["scopes"]]
        elif "areas" in data:
            scopes = [ContactScope.from_legacy_area(a) for a in data["areas"]]
        else:
            scopes = []
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            scopes=scopes,
            device_id=data.get("device_id"),
            inactive=data.get("inactive", False),
            inactive_until=data.get("inactive_until"),
        )


def check_inactive_expired(config) -> bool:
    """Check if an inactive timer has expired. If so, auto-unpause and save.

    Returns True if the control is still inactive (should be skipped),
    False if it was unpaused (or was never paused).
    """
    if not config.inactive:
        return False
    if not config.inactive_until or config.inactive_until == "forever":
        return True  # still inactive, no expiry
    try:
        from datetime import datetime, timezone

        expiry = datetime.fromisoformat(config.inactive_until.replace("Z", "+00:00"))
        if datetime.now(timezone.utc) >= expiry:
            # Timer expired — unpause
            config.inactive = False
            config.inactive_until = None
            _save()
            return False
    except (ValueError, TypeError):
        pass
    return True  # still inactive, timer not yet expired


# =============================================================================
# Module State
# =============================================================================

# Configured switches (persisted)
_switches: Dict[str, SwitchConfig] = {}

# Configured motion sensors (persisted)
_motion_sensors: Dict[str, MotionSensorConfig] = {}

# Configured contact sensors (persisted)
_contact_sensors: Dict[str, ContactSensorConfig] = {}

# Runtime state per switch (not persisted)
_runtime_state: Dict[str, SwitchRuntimeState] = {}

# Path to config file
_config_file_path: Optional[str] = None

# Scope auto-reset timeout (seconds)
SCOPE_RESET_TIMEOUT = 45.0


# =============================================================================
# Initialization and Persistence
# =============================================================================


def _get_data_directory() -> str:
    """Get the appropriate data directory based on environment."""
    if os.path.exists("/config"):
        data_dir = "/config/circadian-light"
        os.makedirs(data_dir, exist_ok=True)
        return data_dir
    elif os.path.exists("/data"):
        return "/data"
    else:
        data_dir = os.path.join(os.path.dirname(__file__), ".data")
        os.makedirs(data_dir, exist_ok=True)
        return data_dir


def init(config_file: Optional[str] = None) -> None:
    """Initialize the switches module and load config from disk."""
    global _config_file_path, _switches, _motion_sensors, _contact_sensors, _runtime_state, _last_actions_cache

    data_dir = _get_data_directory()

    if config_file:
        _config_file_path = config_file
    else:
        _config_file_path = os.path.join(data_dir, "switches_config.json")

    _switches = {}
    _motion_sensors = {}
    _contact_sensors = {}
    _runtime_state = {}

    # Load configured switches and motion sensors
    if os.path.exists(_config_file_path):
        try:
            with open(_config_file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            for switch_data in data.get("switches", []):
                switch = SwitchConfig.from_dict(switch_data)
                _switches[switch.id] = switch
                _runtime_state[switch.id] = SwitchRuntimeState()

            for motion_data in data.get("motion_sensors", []):
                motion = MotionSensorConfig.from_dict(motion_data)
                _motion_sensors[motion.id] = motion

            for contact_data in data.get("contact_sensors", []):
                contact = ContactSensorConfig.from_dict(contact_data)
                _contact_sensors[contact.id] = contact

            logger.info(
                f"Loaded {len(_switches)} switch(es), {len(_motion_sensors)} motion sensor(s), {len(_contact_sensors)} contact sensor(s) from {_config_file_path}"
            )
        except Exception as e:
            logger.warning(
                f"Failed to load switches config from {_config_file_path}: {e}"
            )
    else:
        logger.info(f"No switches config found at {_config_file_path}, starting fresh")

    # Seed last_actions cache from disk (one-time read)
    _last_actions_cache = _load_last_actions()


def _save() -> None:
    """Save current switch, motion sensor, and contact sensor config to disk."""
    if not _config_file_path:
        logger.error("Switches module not initialized, cannot save")
        return

    try:
        data = {
            "switches": [s.to_dict() for s in _switches.values()],
            "motion_sensors": [m.to_dict() for m in _motion_sensors.values()],
            "contact_sensors": [c.to_dict() for c in _contact_sensors.values()],
        }
        tmp_path = _config_file_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, _config_file_path)
        logger.debug(f"Saved switches config to {_config_file_path}")
    except Exception as e:
        logger.error(f"Failed to save switches config to {_config_file_path}: {e}")


def purge_area(area_id: str) -> int:
    """Remove an area from all switch scopes, motion sensors, and contact sensors.

    Args:
        area_id: The area ID to remove

    Returns:
        Number of configs modified
    """
    cleaned = 0

    for switch in _switches.values():
        for scope in switch.scopes:
            if area_id in scope.areas:
                scope.areas.remove(area_id)
                cleaned += 1

    for motion in _motion_sensors.values():
        if motion.remove_area(area_id):
            cleaned += 1

    for contact in _contact_sensors.values():
        if contact.remove_area(area_id):
            cleaned += 1

    if cleaned:
        _save()
        logger.info(f"Purged area {area_id} from {cleaned} control config(s)")

    return cleaned


# =============================================================================
# Switch Management
# =============================================================================


def _reload_switches() -> None:
    """Reload configured switches from disk (for cross-process sync)."""
    global _switches

    if not _config_file_path or not os.path.exists(_config_file_path):
        return

    try:
        with open(_config_file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        new_switches = {}
        for switch_data in data.get("switches", []):
            switch = SwitchConfig.from_dict(switch_data)
            new_switches[switch.id] = switch
            # Preserve runtime state for existing switches
            if switch.id not in _runtime_state:
                _runtime_state[switch.id] = SwitchRuntimeState()

        _switches = new_switches
    except Exception as e:
        logger.warning(f"Failed to reload switches: {e}")


def get_switch(switch_id: str) -> Optional[SwitchConfig]:
    """Get a switch by ID.

    Reloads from disk to pick up changes from other processes.
    """
    _reload_switches()
    result = _switches.get(switch_id)
    if result is None and _switches:
        logger.debug(f"Switch {switch_id} not found ({len(_switches)} configured)")
    return result


def get_switch_by_device_id(device_id: str) -> Optional[SwitchConfig]:
    """Get a switch by its Home Assistant device_id.

    This is used for Hue hub devices which use device_id instead of IEEE address.
    Reloads from disk to pick up changes from other processes.
    """
    _reload_switches()
    for switch in _switches.values():
        if switch.device_id == device_id:
            return switch
    return None


def get_all_switches() -> Dict[str, SwitchConfig]:
    """Get all configured switches.

    Reloads from disk to pick up changes from other processes.
    """
    _reload_switches()
    return _switches.copy()


def add_switch(switch: SwitchConfig) -> None:
    """Add or update a switch configuration."""
    _switches[switch.id] = switch
    if switch.id not in _runtime_state:
        _runtime_state[switch.id] = SwitchRuntimeState()
    _save()
    logger.info(f"Added/updated switch: {switch.name} ({switch.id})")


def remove_switch(switch_id: str) -> bool:
    """Remove a switch configuration."""
    if switch_id in _switches:
        del _switches[switch_id]
        _runtime_state.pop(switch_id, None)
        _save()
        logger.info(f"Removed switch: {switch_id}")
        return True
    return False


def is_configured(switch_id: str) -> bool:
    """Check if a switch is configured."""
    return switch_id in _switches


# =============================================================================
# Motion Sensor Management
# =============================================================================


def _reload_motion_sensors() -> None:
    """Reload configured motion sensors from disk (for cross-process sync)."""
    global _motion_sensors

    if not _config_file_path or not os.path.exists(_config_file_path):
        return

    try:
        with open(_config_file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        new_sensors = {}
        for sensor_data in data.get("motion_sensors", []):
            sensor = MotionSensorConfig.from_dict(sensor_data)
            new_sensors[sensor.id] = sensor

        _motion_sensors = new_sensors
    except Exception as e:
        logger.warning(f"Failed to reload motion sensors: {e}")


def add_motion_sensor(config: MotionSensorConfig) -> None:
    """Add or update a motion sensor configuration."""
    _motion_sensors[config.id] = config
    _save()
    logger.info(f"Added/updated motion sensor: {config.id} ({config.name})")


def remove_motion_sensor(sensor_id: str) -> bool:
    """Remove a motion sensor configuration."""
    if sensor_id in _motion_sensors:
        del _motion_sensors[sensor_id]
        _save()
        logger.info(f"Removed motion sensor: {sensor_id}")
        return True
    return False


def get_motion_sensor(sensor_id: str) -> Optional[MotionSensorConfig]:
    """Get a motion sensor configuration by ID.

    Reloads from disk to pick up changes from other processes.
    """
    _reload_motion_sensors()
    return _motion_sensors.get(sensor_id)


def get_motion_sensor_by_device_id(device_id: str) -> Optional[MotionSensorConfig]:
    """Get a motion sensor configuration by HA device_id.

    Reloads from disk to pick up changes from other processes.
    """
    _reload_motion_sensors()
    for sensor in _motion_sensors.values():
        if sensor.device_id == device_id:
            return sensor
    return None


def is_motion_sensor_configured(sensor_id: str) -> bool:
    """Check if a motion sensor is configured."""
    return sensor_id in _motion_sensors


def get_all_motion_sensors() -> Dict[str, MotionSensorConfig]:
    """Get all configured motion sensors."""
    return _motion_sensors.copy()


def get_motion_sensors_for_area(area_id: str) -> List[MotionSensorConfig]:
    """Get all motion sensors that control a specific area."""
    result = []
    for sensor in _motion_sensors.values():
        if area_id in sensor.get_all_area_ids():
            result.append(sensor)
    return result


# =============================================================================
# Contact Sensor Management
# =============================================================================


def _reload_contact_sensors() -> None:
    """Reload configured contact sensors from disk (for cross-process sync)."""
    global _contact_sensors

    if not _config_file_path or not os.path.exists(_config_file_path):
        return

    try:
        with open(_config_file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        new_sensors = {}
        for sensor_data in data.get("contact_sensors", []):
            sensor = ContactSensorConfig.from_dict(sensor_data)
            new_sensors[sensor.id] = sensor

        _contact_sensors = new_sensors
    except Exception as e:
        logger.warning(f"Failed to reload contact sensors: {e}")


def add_contact_sensor(config: ContactSensorConfig) -> None:
    """Add or update a contact sensor configuration."""
    _contact_sensors[config.id] = config
    _save()
    logger.info(f"Added/updated contact sensor: {config.id} ({config.name})")


def remove_contact_sensor(sensor_id: str) -> bool:
    """Remove a contact sensor configuration."""
    if sensor_id in _contact_sensors:
        del _contact_sensors[sensor_id]
        _save()
        logger.info(f"Removed contact sensor: {sensor_id}")
        return True
    return False


def get_contact_sensor(sensor_id: str) -> Optional[ContactSensorConfig]:
    """Get a contact sensor configuration by ID.

    Reloads from disk to pick up changes from other processes.
    """
    _reload_contact_sensors()
    return _contact_sensors.get(sensor_id)


def get_contact_sensor_by_device_id(device_id: str) -> Optional[ContactSensorConfig]:
    """Get a contact sensor configuration by HA device_id.

    Reloads from disk to pick up changes from other processes.
    """
    _reload_contact_sensors()
    for sensor in _contact_sensors.values():
        if sensor.device_id == device_id:
            return sensor
    return None


def is_contact_sensor_configured(sensor_id: str) -> bool:
    """Check if a contact sensor is configured."""
    return sensor_id in _contact_sensors


def get_all_contact_sensors() -> Dict[str, ContactSensorConfig]:
    """Get all configured contact sensors."""
    return _contact_sensors.copy()


def get_contact_sensors_for_area(area_id: str) -> List[ContactSensorConfig]:
    """Get all contact sensors that control a specific area."""
    result = []
    for sensor in _contact_sensors.values():
        if area_id in sensor.get_all_area_ids():
            result.append(sensor)
    return result


# =============================================================================
# Switch Type Detection
# =============================================================================


def detect_switch_type(
    manufacturer: Optional[str], model: Optional[str]
) -> Optional[str]:
    """Attempt to detect switch type from manufacturer/model info.

    Requires BOTH manufacturer AND model to match to avoid false positives
    (e.g., a Philips motion sensor matching as a Philips dimmer).
    """
    if not manufacturer or not model:
        return None

    manufacturer_lower = (manufacturer or "").lower()
    model_lower = (model or "").lower()

    for type_id, type_info in SWITCH_TYPES.items():
        # Check manufacturers (support both single string and list)
        manufacturers = type_info.get("manufacturers", [])
        if isinstance(manufacturers, str):
            manufacturers = [manufacturers]
        if not manufacturers and type_info.get("manufacturer"):
            manufacturers = [type_info["manufacturer"]]

        # Check if manufacturer matches
        manufacturer_match = any(
            mfr.lower() in manufacturer_lower for mfr in manufacturers
        )
        if not manufacturer_match:
            continue

        # Check if model matches (require both manufacturer AND model)
        for known_model in type_info.get("models", []):
            if known_model.lower() in model_lower:
                return type_id

    return None


# =============================================================================
# Scope Management
# =============================================================================


def get_current_scope(switch_id: str) -> int:
    """Get the current scope index for a switch."""
    state = _runtime_state.get(switch_id)
    return state.current_scope if state else 0


def get_current_areas(switch_id: str) -> List[str]:
    """Get the areas for the current scope of a switch."""
    switch = _switches.get(switch_id)
    if not switch:
        return []

    scope_index = get_current_scope(switch_id)
    return switch.get_areas_for_scope(scope_index)


def cycle_scope(switch_id: str) -> int:
    """Cycle to the next scope for a switch. Returns new scope index."""
    switch = _switches.get(switch_id)
    if not switch or len(switch.scopes) <= 1:
        return 0

    state = _runtime_state.get(switch_id)
    if not state:
        state = SwitchRuntimeState()
        _runtime_state[switch_id] = state

    # Count non-empty scopes
    valid_scopes = [i for i, s in enumerate(switch.scopes) if s.areas]
    if len(valid_scopes) <= 1:
        return state.current_scope

    # Find next valid scope
    current_pos = (
        valid_scopes.index(state.current_scope)
        if state.current_scope in valid_scopes
        else -1
    )
    next_pos = (current_pos + 1) % len(valid_scopes)
    state.current_scope = valid_scopes[next_pos]

    state.last_activity = time.time()
    logger.info(f"Switch {switch_id} cycled to scope {state.current_scope + 1}")

    return state.current_scope


def reset_scope(switch_id: str) -> None:
    """Reset a switch to scope 0."""
    state = _runtime_state.get(switch_id)
    if state and state.current_scope != 0:
        state.current_scope = 0
        logger.debug(f"Switch {switch_id} reset to scope 1")


def record_activity(switch_id: str) -> None:
    """Record activity on a switch (updates last_activity timestamp)."""
    state = _runtime_state.get(switch_id)
    if state:
        state.last_activity = time.time()


def check_scope_timeouts() -> List[str]:
    """Check for switches that should be reset due to inactivity.

    Returns list of switch IDs that were reset.
    """
    now = time.time()
    reset_switches = []

    for switch_id, state in _runtime_state.items():
        if state.current_scope != 0:
            if now - state.last_activity > SCOPE_RESET_TIMEOUT:
                state.current_scope = 0
                reset_switches.append(switch_id)
                logger.debug(
                    f"Switch {switch_id} auto-reset to scope 1 due to inactivity"
                )

    return reset_switches


# =============================================================================
# Hold State Management
# =============================================================================


def start_hold(switch_id: str, action: str) -> None:
    """Mark that a hold action has started."""
    state = _runtime_state.get(switch_id)
    if state:
        state.hold_active = True
        state.hold_action = action
        state.last_activity = time.time()


def stop_hold(switch_id: str) -> Optional[str]:
    """Mark that a hold action has stopped. Returns the action that was active."""
    state = _runtime_state.get(switch_id)
    if state:
        action = state.hold_action
        state.hold_active = False
        state.hold_action = None
        return action
    return None


def is_holding(switch_id: str) -> bool:
    """Check if a switch is currently in a hold state."""
    state = _runtime_state.get(switch_id)
    return state.hold_active if state else False


def get_hold_action(switch_id: str) -> Optional[str]:
    """Get the current hold action for a switch."""
    state = _runtime_state.get(switch_id)
    return state.hold_action if state else None


def set_last_action(switch_id: str, action: str, cooldown_until: str = None) -> None:
    """Record the last button action for a switch with timestamp.

    Persists to file for cross-process sharing with webserver.

    Args:
        switch_id: Switch or sensor ID
        action: Action name (e.g., "motion_detected")
        cooldown_until: Optional ISO timestamp when cooldown expires
    """
    from datetime import datetime

    # Update in-memory state
    state = _runtime_state.get(switch_id)
    if state:
        state.last_action = action
    else:
        state = SwitchRuntimeState(last_action=action)
        _runtime_state[switch_id] = state

    # Update in-memory cache and persist to disk
    global _last_actions_cache
    if _last_actions_cache is None:
        _last_actions_cache = _load_last_actions()
    entry = {"action": action, "timestamp": datetime.now().isoformat()}
    if cooldown_until:
        entry["cooldown_until"] = cooldown_until
    _last_actions_cache[switch_id] = entry
    _save_last_actions(_last_actions_cache)
    logger.debug(f"[LastAction] SET '{switch_id}': {action}")


def get_last_action(switch_id: str) -> Optional[dict]:
    """Get the last button action for a switch with timestamp.

    Returns:
        dict with 'action' and 'timestamp' keys, or None if not found.
        For backwards compatibility, handles old format (plain string).
    """
    global _last_actions_cache
    if _last_actions_cache is None:
        _last_actions_cache = _load_last_actions()
    result = _last_actions_cache.get(switch_id)

    # Handle backwards compatibility (old format was just a string)
    if isinstance(result, str):
        result = {"action": result, "timestamp": None}

    logger.debug(f"[LastAction] GET '{switch_id}': {result}")
    return result


# =============================================================================
# Switch Type Helpers
# =============================================================================


def get_switch_type(type_id: str) -> Optional[Dict[str, Any]]:
    """Get a switch type definition."""
    return SWITCH_TYPES.get(type_id)


def get_all_switch_types() -> Dict[str, Dict[str, Any]]:
    """Get all switch type definitions."""
    return SWITCH_TYPES.copy()


def get_repeat_interval(switch_id: str) -> int:
    """Get the repeat interval for hold actions (in ms).

    Reads from global config setting (tenths of a second), falls back to
    switch type default (700ms).
    """
    try:
        raw_config = glozone.load_config_from_files()
        tenths = raw_config.get("long_press_repeat_interval")
        if tenths is not None:
            return int(float(tenths) * 100)
    except Exception:
        pass
    # Fall back to switch type default
    switch = _switches.get(switch_id)
    if switch:
        switch_type = SWITCH_TYPES.get(switch.type)
        if switch_type:
            return switch_type.get("repeat_interval_ms", 700)
    return 700


def should_repeat_on_hold(switch_id: str, button_event: str) -> bool:
    """Check if a button event should repeat while held."""
    switch = _switches.get(switch_id)
    if switch:
        switch_type = SWITCH_TYPES.get(switch.type)
        if switch_type:
            return button_event in switch_type.get("repeat_on_hold", [])
    return False


# =============================================================================
# Reach Group Utilities (for multi-area ZigBee group sync)
# =============================================================================


def get_reach_key(areas: List[str]) -> str:
    """Generate stable hash key for a reach (sorted, deduped areas).

    Args:
        areas: List of area IDs in the reach

    Returns:
        8-character hex hash uniquely identifying this reach combination
    """
    sorted_areas = sorted(set(areas))
    combined = "|".join(sorted_areas)
    return hashlib.md5(combined.encode()).hexdigest()[:8]


def get_all_unique_reaches() -> Dict[str, List[str]]:
    """Collect multi-area reaches from all configured switches.

    Scans all switches and their scopes to find unique reach combinations
    that span multiple areas. Single-area reaches are excluded since they
    can use existing area-level groups.

    Returns:
        Dict of reach_key -> list of sorted area IDs
    """
    _reload_switches()  # Ensure we have latest config
    reaches = {}

    for switch in _switches.values():
        for scope in switch.scopes:
            if len(scope.areas) >= 2:  # Only multi-area reaches
                key = get_reach_key(scope.areas)
                if key not in reaches:
                    reaches[key] = sorted(set(scope.areas))

    return reaches


# =============================================================================
# API Helpers (for webserver)
# =============================================================================


def get_switches_summary() -> List[Dict[str, Any]]:
    """Get a summary of all switches for the UI."""
    result = []
    for switch_id, switch in _switches.items():
        state = _runtime_state.get(switch_id, SwitchRuntimeState())
        valid_scopes = len([s for s in switch.scopes if s.areas])
        result.append(
            {
                "id": switch.id,
                "name": switch.name,
                "type": switch.type,
                "type_name": SWITCH_TYPES.get(switch.type, {}).get("name", switch.type),
                "current_scope": state.current_scope + 1,  # 1-indexed for display
                "total_scopes": valid_scopes,
                "scopes": [
                    {
                        "areas": s.areas,
                        **(
                            {"feedback_area": s.feedback_area}
                            if s.feedback_area
                            else {}
                        ),
                    }
                    for s in switch.scopes
                ],
                "device_id": switch.device_id,
                "inactive": switch.inactive,
                "inactive_until": switch.inactive_until,
                "magic_buttons": switch.magic_buttons,
            }
        )
    return result
