#!/usr/bin/env python3
"""Switch management for Circadian Light.

This module manages:
- Switch type definitions (button layouts, default mappings)
- Per-switch configuration (scopes, optional button overrides)
- Runtime state (current scope, last activity, pending detection)

Switch config is persisted to JSON. Runtime state is in-memory only.
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

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
# Each type defines available buttons and default action mappings
SWITCH_TYPES: Dict[str, Dict[str, Any]] = {
    "hue_dimmer": {
        "name": "Philips Hue Dimmer",
        "manufacturer": "Philips",
        "models": ["RWL020", "RWL021", "RWL022"],
        "buttons": ["on", "up", "down", "off"],
        "action_types": ["press", "hold", "short_release", "long_release", "double_press"],
        "default_mapping": {
            # On button
            "on_short_release": "circadian_on",
            "on_hold": None,
            "on_long_release": "reset",
            "on_double_press": "glo_reset",
            # Up button
            "up_short_release": "step_up",
            "up_hold": "bright_up",        # Repeats while held
            "up_long_release": None,       # Stop repeat
            "up_double_press": "glo_up",
            # Down button
            "down_short_release": "cycle_scope",
            "down_hold": "bright_down",    # Repeats while held
            "down_long_release": None,     # Stop repeat
            "down_double_press": "glo_down",
            # Off button
            "off_short_release": "circadian_off",
            "off_hold": None,
            "off_long_release": "freeze_toggle",
            "off_double_press": None,
        },
        # Which actions should repeat while held
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
    type: str                                  # Switch type key (e.g., "hue_dimmer")
    scopes: List[SwitchScope] = field(default_factory=list)
    button_overrides: Dict[str, Optional[str]] = field(default_factory=dict)

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
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "scopes": [{"areas": s.areas} for s in self.scopes],
            "button_overrides": self.button_overrides,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SwitchConfig":
        """Create from dictionary."""
        scopes = [SwitchScope(areas=s.get("areas", [])) for s in data.get("scopes", [])]
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            type=data.get("type", "hue_dimmer"),
            scopes=scopes,
            button_overrides=data.get("button_overrides", {}),
        )


@dataclass
class SwitchRuntimeState:
    """Runtime state for a switch (not persisted)."""
    current_scope: int = 0
    last_activity: float = 0.0
    hold_active: bool = False
    hold_action: Optional[str] = None


# =============================================================================
# Module State
# =============================================================================

# Configured switches (persisted)
_switches: Dict[str, SwitchConfig] = {}

# Runtime state per switch (not persisted)
_runtime_state: Dict[str, SwitchRuntimeState] = {}

# Pending/detected switches not yet configured
_pending_switches: Dict[str, Dict[str, Any]] = {}

# Path to config files
_config_file_path: Optional[str] = None
_pending_file_path: Optional[str] = None

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
    global _config_file_path, _pending_file_path, _switches, _runtime_state, _pending_switches

    data_dir = _get_data_directory()

    if config_file:
        _config_file_path = config_file
    else:
        _config_file_path = os.path.join(data_dir, "switches_config.json")

    _pending_file_path = os.path.join(data_dir, "switches_pending.json")

    _switches = {}
    _runtime_state = {}
    _pending_switches = {}

    # Load configured switches
    if os.path.exists(_config_file_path):
        try:
            with open(_config_file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            for switch_data in data.get("switches", []):
                switch = SwitchConfig.from_dict(switch_data)
                _switches[switch.id] = switch
                _runtime_state[switch.id] = SwitchRuntimeState()

            logger.info(f"Loaded {len(_switches)} switch(es) from {_config_file_path}")
        except Exception as e:
            logger.warning(f"Failed to load switches config from {_config_file_path}: {e}")
    else:
        logger.info(f"No switches config found at {_config_file_path}, starting fresh")

    # Load pending switches
    if os.path.exists(_pending_file_path):
        try:
            with open(_pending_file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            _pending_switches = data.get("pending", {})
            # Remove any that have since been configured
            for switch_id in list(_pending_switches.keys()):
                if switch_id in _switches:
                    del _pending_switches[switch_id]
            logger.info(f"Loaded {len(_pending_switches)} pending switch(es) from {_pending_file_path}")
        except Exception as e:
            logger.warning(f"Failed to load pending switches from {_pending_file_path}: {e}")


def _save() -> None:
    """Save current switch config to disk."""
    if not _config_file_path:
        logger.error("Switches module not initialized, cannot save")
        return

    try:
        data = {
            "switches": [s.to_dict() for s in _switches.values()]
        }
        with open(_config_file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        logger.debug(f"Saved switches config to {_config_file_path}")
    except Exception as e:
        logger.error(f"Failed to save switches config to {_config_file_path}: {e}")


def _save_pending() -> None:
    """Save pending switches to disk."""
    if not _pending_file_path:
        logger.error("Switches module not initialized, cannot save pending")
        return

    try:
        data = {
            "pending": _pending_switches
        }
        with open(_pending_file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        logger.debug(f"Saved pending switches to {_pending_file_path}")
    except Exception as e:
        logger.error(f"Failed to save pending switches to {_pending_file_path}: {e}")


# =============================================================================
# Switch Management
# =============================================================================

def get_switch(switch_id: str) -> Optional[SwitchConfig]:
    """Get a switch by ID."""
    return _switches.get(switch_id)


def get_all_switches() -> Dict[str, SwitchConfig]:
    """Get all configured switches."""
    return _switches.copy()


def add_switch(switch: SwitchConfig) -> None:
    """Add or update a switch configuration."""
    _switches[switch.id] = switch
    if switch.id not in _runtime_state:
        _runtime_state[switch.id] = SwitchRuntimeState()
    # Remove from pending if it was there
    was_pending = switch.id in _pending_switches
    _pending_switches.pop(switch.id, None)
    _save()
    if was_pending:
        _save_pending()
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
# Pending Switch Detection
# =============================================================================

def add_pending_switch(switch_id: str, info: Dict[str, Any]) -> None:
    """Add a detected but unconfigured switch to pending list."""
    if switch_id not in _switches and switch_id not in _pending_switches:
        _pending_switches[switch_id] = {
            "id": switch_id,
            "name": info.get("name", f"Unknown ({switch_id[-8:]})"),
            "detected_type": info.get("type"),
            "manufacturer": info.get("manufacturer"),
            "model": info.get("model"),
            "detected_at": time.time(),
        }
        _save_pending()
        logger.info(f"New switch detected: {_pending_switches[switch_id]['name']} ({switch_id})")


def get_pending_switches() -> Dict[str, Dict[str, Any]]:
    """Get all pending/unconfigured switches."""
    return _pending_switches.copy()


def clear_pending_switch(switch_id: str) -> None:
    """Remove a switch from the pending list."""
    if switch_id in _pending_switches:
        _pending_switches.pop(switch_id, None)
        _save_pending()


def detect_switch_type(manufacturer: Optional[str], model: Optional[str]) -> Optional[str]:
    """Attempt to detect switch type from manufacturer/model info."""
    if not manufacturer and not model:
        return None

    manufacturer_lower = (manufacturer or "").lower()
    model_upper = (model or "").upper()

    for type_id, type_info in SWITCH_TYPES.items():
        # Check manufacturer
        if type_info.get("manufacturer", "").lower() in manufacturer_lower:
            return type_id
        # Check model
        for known_model in type_info.get("models", []):
            if known_model.upper() in model_upper:
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
        })
    return result


def get_pending_switches_summary() -> List[Dict[str, Any]]:
    """Get a summary of pending switches for the UI."""
    return list(_pending_switches.values())
