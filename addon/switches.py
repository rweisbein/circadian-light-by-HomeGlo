#!/usr/bin/env python3
"""Switch management for Circadian Light.

This module manages:
- Switch type definitions (button layouts, default mappings)
- Per-switch configuration (scopes, optional button overrides)
- Runtime state (current scope, last activity, pending detection)

Switch config is persisted to JSON. Runtime state is in-memory only.
Last action is persisted to a separate file for cross-process sharing.
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# =============================================================================
# Last Action File Persistence (shared between main.py and webserver.py)
# =============================================================================

_LAST_ACTION_FILE: Optional[Path] = None


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
        with open(action_file, "w") as f:
            json.dump(actions, f, indent=2)
    except IOError as e:
        logger.error(f"Failed to save last actions file: {e}")

# =============================================================================
# Switch Type Definitions (hardcoded)
# =============================================================================

# Available actions that can be mapped to buttons
AVAILABLE_ACTIONS = [
    "circadian_on",      # Enable + apply circadian values
    "circadian_off",     # Disable circadian mode (lights unchanged)
    "toggle",            # Smart toggle based on state
    "step_up",           # Brighter + cooler along curve
    "step_down",         # Dimmer + warmer along curve
    "bright_up",         # Brightness only
    "bright_down",       # Brightness only
    "color_up",          # Color temp only
    "color_down",        # Color temp only
    "reset",             # Reset to current time position
    "freeze_toggle",     # Toggle freeze at current position
    "glo_up",            # Glo Up for zone
    "glo_down",          # Glo Down for zone
    "glo_reset",         # Glo Reset for zone
    "cycle_scope",       # Cycle through scopes
    "set_britelite",     # 100% brightness, cool white (6500K)
    "set_nitelite",      # 5% brightness, warm (2200K)
    "toggle_wake_bed",   # Set midpoint to current time
    None,                # Unmapped / do nothing
]

# Button action types (event suffixes from ZHA)
BUTTON_ACTION_TYPES = [
    "press",           # Immediately when pressed
    "hold",            # After ~0.5s if still held
    "short_release",   # Released quickly (short press)
    "long_release",    # Released after hold
    "double_press",    # Double click
    "triple_press",    # Triple click
    "quadruple_press", # 4x click
    "quintuple_press", # 5x click
]

# Switch type definitions
# Shared button mapping for Hue 4-button dimmers (v1 and v2 use same layout)
_HUE_4BUTTON_MAPPING = {
    # On button (top)
    "on_short_release": "circadian_toggle",     # 1x - on/off
    "on_double_press": "freeze_toggle",         # 2x - freeze
    "on_triple_press": "glo_up",                # 3x - send to zone
    "on_quadruple_press": None,                 # 4x - not used
    "on_quintuple_press": None,                 # 5x - coming soon: emergency toggle
    "on_hold": None,                            # long - RESERVED for magic button
    "on_long_release": None,
    # Up button
    "up_short_release": "step_up",              # 1x
    "up_double_press": "color_up",              # 2x
    "up_triple_press": "set_britelite",         # 3x
    "up_quadruple_press": None,                 # 4x - not used
    "up_quintuple_press": None,                 # 5x - not used
    "up_hold": "bright_up",                     # long - repeats while held
    "up_long_release": None,
    # Down button
    "down_short_release": "step_down",          # 1x
    "down_double_press": "color_down",          # 2x
    "down_triple_press": "set_nitelite",        # 3x
    "down_quadruple_press": None,               # 4x - not used
    "down_quintuple_press": None,               # 5x - not used
    "down_hold": "bright_down",                 # long - repeats while held
    "down_long_release": None,
    # Off button (bottom - "hue" button)
    "off_short_release": "cycle_scope",         # 1x - change controlled areas
    "off_double_press": "glo_down",             # 2x - reset area (pull zone state)
    "off_triple_press": "glo_reset",            # 3x - reset zone
    "off_quadruple_press": None,                # 4x - not used
    "off_quintuple_press": None,                # 5x - coming soon: Sleep
    "off_hold": None,                           # long - RESERVED for magic button
    "off_long_release": None,
}

# Each type defines available buttons and default action mappings
SWITCH_TYPES: Dict[str, Dict[str, Any]] = {
    "hue_4button_v1": {
        "name": "Hue 4-button v1",
        "manufacturers": ["Philips", "Signify", "Signify Netherlands B.V."],
        "models": ["RWL020"],
        "buttons": ["on", "up", "down", "off"],
        "action_types": ["press", "hold", "short_release", "long_release", "double_press", "triple_press", "quadruple_press", "quintuple_press"],
        "default_mapping": _HUE_4BUTTON_MAPPING,
        "repeat_on_hold": ["up_hold", "down_hold"],
        "repeat_interval_ms": 300,
    },
    "hue_4button_v2": {
        "name": "Hue 4-button v2",
        "manufacturers": ["Philips", "Signify", "Signify Netherlands B.V."],
        "models": ["RWL022"],
        "buttons": ["on", "up", "down", "off"],
        "action_types": ["press", "hold", "short_release", "long_release", "double_press", "triple_press", "quadruple_press", "quintuple_press"],
        "default_mapping": _HUE_4BUTTON_MAPPING,
        "repeat_on_hold": ["up_hold", "down_hold"],
        "repeat_interval_ms": 300,
    },
    "ikea_tradfri_remote": {
        "name": "IKEA Tradfri Remote",
        "manufacturer": "IKEA",
        "models": ["E1524", "E1810"],
        "buttons": ["toggle", "brightness_up", "brightness_down", "arrow_left", "arrow_right"],
        "action_types": ["press", "hold", "release"],
        "default_mapping": {
            "toggle_press": "toggle",
            "brightness_up_press": "step_up",
            "brightness_up_hold": "bright_up",
            "brightness_up_release": None,
            "brightness_down_press": "cycle_scope",
            "brightness_down_hold": "bright_down",
            "brightness_down_release": None,
            "arrow_left_press": "color_down",
            "arrow_left_hold": "color_down",
            "arrow_right_press": "color_up",
            "arrow_right_hold": "color_up",
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
def get_motion_sensor_name(manufacturer: Optional[str], model: Optional[str]) -> Optional[str]:
    """Deprecated: Use get_sensor_name instead."""
    return get_sensor_name(manufacturer, model)


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class SwitchScope:
    """A scope defines which areas a switch controls."""
    areas: List[str] = field(default_factory=list)


@dataclass
class SwitchConfig:
    """Configuration for a single switch."""
    id: str                                    # IEEE address or unique identifier
    name: str                                  # User-friendly name
    type: str                                  # Switch type key (e.g., "hue_4button_v2")
    scopes: List[SwitchScope] = field(default_factory=list)
    button_overrides: Dict[str, Optional[str]] = field(default_factory=dict)
    device_id: Optional[str] = None            # HA device_id for area lookup

    def get_button_action(self, button_event: str) -> Optional[str]:
        """Get the action for a button event, with override support."""
        # Check for switch-level override first
        if button_event in self.button_overrides:
            return self.button_overrides[button_event]
        # Fall back to type default
        switch_type = SWITCH_TYPES.get(self.type)
        if switch_type:
            return switch_type.get("default_mapping", {}).get(button_event)
        return None

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
            "scopes": [{"areas": s.areas} for s in self.scopes],
            "button_overrides": self.button_overrides,
        }
        if self.device_id:
            result["device_id"] = self.device_id
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SwitchConfig":
        """Create from dictionary."""
        scopes = [SwitchScope(areas=s.get("areas", [])) for s in data.get("scopes", [])]
        # Migrate old type names to new names
        switch_type = data.get("type", "hue_4button_v2")
        type_migrations = {
            "hue_dimmer": "hue_4button_v2",  # Old name -> default to v2
        }
        switch_type = type_migrations.get(switch_type, switch_type)
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            type=switch_type,
            scopes=scopes,
            button_overrides=data.get("button_overrides", {}),
            device_id=data.get("device_id"),
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
    """Config for one area controlled by a motion sensor."""
    area_id: str
    function: str = "on_off"  # on_only, on_off, boost, disabled
    duration: int = 60  # seconds, used for on_off and boost (0 = forever)
    boost_brightness: int = 50  # percentage points to add for boost function

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "area_id": self.area_id,
            "function": self.function,
            "duration": self.duration,
            "boost_brightness": self.boost_brightness,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MotionAreaConfig":
        """Create from dictionary."""
        return cls(
            area_id=data.get("area_id", ""),
            function=data.get("function", "on_off"),
            duration=data.get("duration", 60),
            boost_brightness=data.get("boost_brightness", 50),
        )


@dataclass
class MotionSensorConfig:
    """Configuration for a motion sensor."""
    id: str                              # Device ID or unique identifier
    name: str                            # User-friendly name
    areas: List[MotionAreaConfig] = field(default_factory=list)
    device_id: Optional[str] = None      # HA device_id

    def get_area_config(self, area_id: str) -> Optional[MotionAreaConfig]:
        """Get config for a specific area."""
        for area in self.areas:
            if area.area_id == area_id:
                return area
        return None

    def get_all_area_ids(self) -> List[str]:
        """Get list of all area IDs this sensor controls."""
        return [a.area_id for a in self.areas]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "id": self.id,
            "name": self.name,
            "areas": [a.to_dict() for a in self.areas],
        }
        if self.device_id:
            result["device_id"] = self.device_id
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MotionSensorConfig":
        """Create from dictionary."""
        areas = [MotionAreaConfig.from_dict(a) for a in data.get("areas", [])]
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            areas=areas,
            device_id=data.get("device_id"),
        )


# =============================================================================
# Contact Sensor Data Classes
# =============================================================================

@dataclass
class ContactAreaConfig:
    """Config for one area controlled by a contact sensor (e.g., door/window sensor).

    Contact sensors differ from motion sensors:
    - For on_off/boost: door CLOSE triggers circadian_off (primary), timer is fallback
    - For on_only: door CLOSE is ignored (same as motion)
    """
    area_id: str
    function: str = "on_off"  # on_only, on_off, boost, disabled
    duration: int = 60  # seconds, used for on_off and boost (0 = forever)
    boost_brightness: int = 50  # percentage points to add for boost function

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "area_id": self.area_id,
            "function": self.function,
            "duration": self.duration,
            "boost_brightness": self.boost_brightness,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContactAreaConfig":
        """Create from dictionary."""
        return cls(
            area_id=data.get("area_id", ""),
            function=data.get("function", "on_off"),
            duration=data.get("duration", 60),
            boost_brightness=data.get("boost_brightness", 50),
        )


@dataclass
class ContactSensorConfig:
    """Configuration for a contact sensor (door/window sensor)."""
    id: str                              # Device ID or unique identifier
    name: str                            # User-friendly name
    areas: List[ContactAreaConfig] = field(default_factory=list)
    device_id: Optional[str] = None      # HA device_id

    def get_area_config(self, area_id: str) -> Optional[ContactAreaConfig]:
        """Get config for a specific area."""
        for area in self.areas:
            if area.area_id == area_id:
                return area
        return None

    def get_all_area_ids(self) -> List[str]:
        """Get list of all area IDs this sensor controls."""
        return [a.area_id for a in self.areas]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "id": self.id,
            "name": self.name,
            "areas": [a.to_dict() for a in self.areas],
        }
        if self.device_id:
            result["device_id"] = self.device_id
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContactSensorConfig":
        """Create from dictionary."""
        areas = [ContactAreaConfig.from_dict(a) for a in data.get("areas", [])]
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            areas=areas,
            device_id=data.get("device_id"),
        )


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
    global _config_file_path, _switches, _motion_sensors, _contact_sensors, _runtime_state

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

            logger.info(f"Loaded {len(_switches)} switch(es), {len(_motion_sensors)} motion sensor(s), {len(_contact_sensors)} contact sensor(s) from {_config_file_path}")
        except Exception as e:
            logger.warning(f"Failed to load switches config from {_config_file_path}: {e}")
    else:
        logger.info(f"No switches config found at {_config_file_path}, starting fresh")


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
        with open(_config_file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        logger.debug(f"Saved switches config to {_config_file_path}")
    except Exception as e:
        logger.error(f"Failed to save switches config to {_config_file_path}: {e}")


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
        logger.info(f"Switch {switch_id} not found. Configured switches: {list(_switches.keys())}")
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
    """Get a motion sensor configuration by ID."""
    return _motion_sensors.get(sensor_id)


def get_motion_sensor_by_device_id(device_id: str) -> Optional[MotionSensorConfig]:
    """Get a motion sensor configuration by HA device_id."""
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
        for area in sensor.areas:
            if area.area_id == area_id:
                result.append(sensor)
                break
    return result


# =============================================================================
# Contact Sensor Management
# =============================================================================

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
    """Get a contact sensor configuration by ID."""
    return _contact_sensors.get(sensor_id)


def get_contact_sensor_by_device_id(device_id: str) -> Optional[ContactSensorConfig]:
    """Get a contact sensor configuration by HA device_id."""
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
        for area in sensor.areas:
            if area.area_id == area_id:
                result.append(sensor)
                break
    return result


# =============================================================================
# Switch Type Detection
# =============================================================================

def detect_switch_type(manufacturer: Optional[str], model: Optional[str]) -> Optional[str]:
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
        manufacturer_match = any(mfr.lower() in manufacturer_lower for mfr in manufacturers)
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
    current_pos = valid_scopes.index(state.current_scope) if state.current_scope in valid_scopes else -1
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
                logger.debug(f"Switch {switch_id} auto-reset to scope 1 due to inactivity")

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


def set_last_action(switch_id: str, action: str) -> None:
    """Record the last button action for a switch with timestamp.

    Persists to file for cross-process sharing with webserver.
    """
    from datetime import datetime

    # Update in-memory state
    state = _runtime_state.get(switch_id)
    if state:
        state.last_action = action
    else:
        state = SwitchRuntimeState(last_action=action)
        _runtime_state[switch_id] = state

    # Persist to file for webserver to read (with timestamp)
    all_actions = _load_last_actions()
    all_actions[switch_id] = {
        "action": action,
        "timestamp": datetime.now().isoformat()
    }
    _save_last_actions(all_actions)
    logger.debug(f"[LastAction] SET '{switch_id}': {action}")


def get_last_action(switch_id: str) -> Optional[dict]:
    """Get the last button action for a switch with timestamp.

    Reads from file to get cross-process state.

    Returns:
        dict with 'action' and 'timestamp' keys, or None if not found.
        For backwards compatibility, handles old format (plain string).
    """
    # Read from file (cross-process)
    all_actions = _load_last_actions()
    result = all_actions.get(switch_id)

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
    """Get the repeat interval for hold actions (in ms)."""
    switch = _switches.get(switch_id)
    if switch:
        switch_type = SWITCH_TYPES.get(switch.type)
        if switch_type:
            return switch_type.get("repeat_interval_ms", 300)
    return 300


def should_repeat_on_hold(switch_id: str, button_event: str) -> bool:
    """Check if a button event should repeat while held."""
    switch = _switches.get(switch_id)
    if switch:
        switch_type = SWITCH_TYPES.get(switch.type)
        if switch_type:
            return button_event in switch_type.get("repeat_on_hold", [])
    return False


# =============================================================================
# API Helpers (for webserver)
# =============================================================================

def get_switches_summary() -> List[Dict[str, Any]]:
    """Get a summary of all switches for the UI."""
    result = []
    for switch_id, switch in _switches.items():
        state = _runtime_state.get(switch_id, SwitchRuntimeState())
        valid_scopes = len([s for s in switch.scopes if s.areas])
        result.append({
            "id": switch.id,
            "name": switch.name,
            "type": switch.type,
            "type_name": SWITCH_TYPES.get(switch.type, {}).get("name", switch.type),
            "current_scope": state.current_scope + 1,  # 1-indexed for display
            "total_scopes": valid_scopes,
            "scopes": [{"areas": s.areas} for s in switch.scopes],
            "device_id": switch.device_id,
        })
    return result
