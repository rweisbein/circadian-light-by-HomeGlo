#!/usr/bin/env python3
"""Home Assistant WebSocket client - listens for events."""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from typing import Dict, Any, List, Optional, Sequence, Set, Tuple, Union

import websockets
from websockets.client import WebSocketClientProtocol

import state
import switches
import glozone
from primitives import CircadianLightPrimitives
from brain import (
    CircadianLight,
    Config,
    AreaState,
    ColorMode,
    get_current_hour,
    get_circadian_lighting,
    DEFAULT_MAX_DIM_STEPS,
    DEFAULT_MIN_BRIGHTNESS,
    DEFAULT_MAX_BRIGHTNESS,
)
from light_controller import (
    LightControllerFactory,
    MultiProtocolController,
    LightCommand,
    Protocol
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class HomeAssistantWebSocketClient:
    """WebSocket client for Home Assistant."""
    
    def __init__(self, host: str, port: int, access_token: str, use_ssl: bool = False):
        """Initialize the client.
        
        Args:
            host: Home Assistant host
            port: Home Assistant port
            access_token: Long-lived access token
            use_ssl: Whether to use SSL/TLS
        """
        self.host = host
        self.port = port
        self.access_token = access_token
        self.use_ssl = use_ssl
        self.websocket: WebSocketClientProtocol = None
        self.message_id = 1
        self.sun_data = {}  # Store latest sun data
        self.area_to_light_entity = {}  # Map area aliases to their grouped light entity
        self.area_group_map: Dict[str, Dict[str, str]] = {}  # Normalized area key -> {"zha_group": entity, "hue_group": entity, ...}
        self.group_entity_info: Dict[str, Dict[str, Any]] = {}  # Metadata for grouped light entities
        self.primitives = CircadianLightPrimitives(self)  # Initialize primitives handler
        self.light_controller = None  # Will be initialized after websocket connection
        self.latitude = None  # Home Assistant latitude
        self.longitude = None  # Home Assistant longitude
        self.timezone = None  # Home Assistant timezone
        self.periodic_update_task = None  # Task for periodic light updates
        self.refresh_event = None  # Will be created lazily in the running event loop
        # State is managed by state.py module (per-area midpoints, bounds, etc.)
        self.cached_states = {}  # Cache of entity states
        self.last_states_update = None  # Timestamp of last states update
        self.area_parity_cache = {}  # Cache of area ZHA parity status
        self.device_registry: Dict[str, Dict[str, Any]] = {}  # device_id -> device info

        # Light capability cache for color mode detection
        self.light_color_modes: Dict[str, Set[str]] = {}  # entity_id -> set of supported color modes
        self.area_lights: Dict[str, List[str]] = {}  # area_id -> list of light entity_ids

        # Live Design tracking - skip this area in periodic updates
        self.live_design_area: str = None

        # Initialize state module (loads from circadian_state.json)
        state.init()

        # Initialize switches module (loads from switches_config.json)
        switches.init()

        # Hold repeat task for ramping
        self._hold_repeat_task: Optional[asyncio.Task] = None

        # Brightness curve configuration (populated from supervisor/designer config)
        self.max_dim_steps = DEFAULT_MAX_DIM_STEPS
        self.min_brightness = DEFAULT_MIN_BRIGHTNESS
        self.max_brightness = DEFAULT_MAX_BRIGHTNESS
        
        # Color mode configuration - defaults to KELVIN (CT)
        color_mode_str = os.getenv("COLOR_MODE", "kelvin").lower()
        try:
            # Try to get by value (lowercase) first
            self.color_mode = ColorMode(color_mode_str)
        except ValueError:
            # Try uppercase enum name as fallback
            try:
                self.color_mode = ColorMode[color_mode_str.upper()]
            except KeyError:
                logger.warning(f"Invalid COLOR_MODE '{color_mode_str}', defaulting to KELVIN")
                self.color_mode = ColorMode.KELVIN
        logger.info(f"Using color mode: {self.color_mode.value}")
        
        # Note: Gamma parameters have been replaced with morning/evening curve parameters in brain.py
        # The new curve system provides separate control for morning and evening transitions
        
        
    @property
    def websocket_url(self) -> str:
        """Get the WebSocket URL."""
        # Check if a full URL is provided via environment variable
        url_from_env = os.getenv("HA_WEBSOCKET_URL")
        if url_from_env:
            return url_from_env
        
        # Otherwise construct from host/port
        protocol = "wss" if self.use_ssl else "ws"
        return f"{protocol}://{self.host}:{self.port}/api/websocket"
        
    def _get_next_message_id(self) -> int:
        """Get the next message ID."""
        current_id = self.message_id
        self.message_id += 1
        return current_id
    
    def _normalize_area_key(self, value: Optional[str]) -> Optional[str]:
        """Normalize area identifiers to a lowercase underscore-delimited key."""
        if not value or not isinstance(value, str):
            return None
        normalized = value.strip().lower().replace("-", "_")
        normalized = normalized.replace(" ", "_")
        while "__" in normalized:
            normalized = normalized.replace("__", "_")
        return normalized or None

    def _register_area_group_entity(
        self,
        entity_id: str,
        *,
        area_name: Optional[str],
        area_id: Optional[str],
        group_type: str,
    ) -> None:
        """Register a grouped light entity for fast lookup by area aliases."""
        if not entity_id or not entity_id.startswith("light."):
            return

        # Track metadata about the entity
        display_name = area_name or area_id or entity_id
        self.group_entity_info[entity_id] = {
            "type": group_type,
            "area": display_name,
            "area_id": area_id,
            "area_name": area_name,
        }

        # Store normalized mapping for selection logic
        canonical_key = self._normalize_area_key(area_id or area_name)
        if canonical_key:
            area_entry = self.area_group_map.setdefault(canonical_key, {})
            area_entry[group_type] = entity_id

        # Build alias variations to continue supporting legacy lookups
        alias_candidates = set()
        for raw in (area_id, area_name):
            if raw and isinstance(raw, str):
                trimmed = raw.strip()
                if not trimmed:
                    continue
                alias_candidates.add(trimmed)
                alias_candidates.add(trimmed.replace("-", " "))

        # Include canonical key so callers who already rely on lowercase ids still work
        if canonical_key:
            alias_candidates.add(canonical_key)

        for candidate in alias_candidates:
            if not candidate:
                continue
            variants = {
                candidate,
                candidate.lower(),
                candidate.replace("_", " "),
                candidate.replace("_", " ").lower(),
                candidate.replace(" ", "_"),
                candidate.replace(" ", "_").lower(),
            }
            for variant in variants:
                if variant:
                    self.area_to_light_entity[variant] = entity_id

    def _update_area_group_mapping(
        self,
        entity_id: str,
        friendly_name: str,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Update grouped light mappings for ZHA Circadian groups and Hue rooms."""
        if not entity_id or not entity_id.startswith("light."):
            return

        attributes = attributes or {}
        friendly_name = friendly_name or ""
        friendly_lower = friendly_name.lower()
        entity_lower = entity_id.lower()

        # Detect Hue grouped light entities exposed by the Hue integration
        is_hue_group = False
        hue_flags = [
            attributes.get("is_hue_group"),
            attributes.get("is_hue_grouped_light"),
            attributes.get("is_hue_grouped"),
            attributes.get("is_group"),
        ]
        for flag in hue_flags:
            if isinstance(flag, bool) and flag:
                is_hue_group = True
                break
            if isinstance(flag, str) and flag.strip().lower() in {"true", "1", "yes", "on"}:
                is_hue_group = True
                break

        if not is_hue_group:
            hue_resource = attributes.get("hue_resource_type") or attributes.get("type")
            if isinstance(hue_resource, str) and hue_resource.lower() in {"grouped_light", "room"}:
                is_hue_group = True

        if not is_hue_group:
            icon = attributes.get("icon")
            if isinstance(icon, str) and "bulb-group" in icon:
                is_hue_group = True

        if not is_hue_group:
            hue_group_id = attributes.get("hue_group") or attributes.get("hue_group_id")
            if hue_group_id:
                is_hue_group = True

        if is_hue_group:
            area_id = attributes.get("area_id")
            area_name = friendly_name or attributes.get("name")
            self._register_area_group_entity(
                entity_id,
                area_name=area_name,
                area_id=area_id,
                group_type="hue_group",
            )
            logger.debug(f"Registered Hue grouped light '{entity_id}' for area '{area_name or area_id}'")
            return

        # Detect Circadian_ ZHA group entities
        if "circadian_" not in entity_lower and "circadian_" not in friendly_lower:
            return

        area_name = None

        # Try to extract from friendly_name first (preserving case)
        if "Circadian_" in friendly_name:
            parts = friendly_name.split("Circadian_")
            if len(parts) >= 2:
                area_name = parts[-1].strip()
        elif "circadian_" in friendly_lower:
            idx = friendly_lower.index("circadian_")
            area_name = friendly_name[idx + 10:].strip()

        # If not found in friendly_name, try entity_id
        if not area_name and "circadian_" in entity_lower:
            idx = entity_lower.index("circadian_")
            area_name = entity_id[idx + 10:]
            area_name = area_name.replace("light.", "")

        if area_name:
            self._register_area_group_entity(
                entity_id,
                area_name=area_name,
                area_id=None,
                group_type="zha_group",
            )
            logger.debug(f"Registered Circadian ZHA group '{entity_id}' for area '{area_name}'")

    # Backwards compatibility for tests and legacy callers
    def _update_zha_group_mapping(self, entity_id: str, friendly_name: str) -> None:
        """Legacy wrapper maintained for compatibility with older tests."""
        self._update_area_group_mapping(entity_id, friendly_name, None)

    def _get_fallback_group_entity(self, area_id: str) -> Optional[str]:
        """Return the first grouped entity mapped to any alias of the given area."""
        if not area_id or not isinstance(area_id, str):
            return None

        candidates = [
            area_id,
            area_id.lower(),
            area_id.replace("_", " "),
            area_id.replace("_", " ").lower(),
            area_id.replace(" ", "_"),
            area_id.replace(" ", "_").lower(),
        ]

        seen = set()
        for candidate in candidates:
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            entity = self.area_to_light_entity.get(candidate)
            if entity:
                return entity
        return None

    # =========================================================================
    # ZHA Switch Event Handling
    # =========================================================================

    async def _handle_zha_event(self, event_data: Dict[str, Any]) -> None:
        """Handle a ZHA event (switch button press).

        Args:
            event_data: Event data from zha_event
        """
        device_ieee = event_data.get("device_ieee")
        device_id = event_data.get("device_id")
        command = event_data.get("command")
        args = event_data.get("args", {})
        cluster_id = event_data.get("cluster_id")

        if not device_ieee or not command:
            return

        logger.debug(f"ZHA event: device={device_ieee}, command={command}, args={args}, cluster={cluster_id}")

        # Check if this switch is configured
        switch_config = switches.get_switch(device_ieee)

        if not switch_config:
            # Unconfigured switch - add to pending list
            await self._handle_unconfigured_switch(device_ieee, event_data)
            return

        # Hue dimmers send duplicate events on multiple clusters:
        # - Cluster 6 (On/Off) for ON/OFF buttons
        # - Cluster 8 (Level Control) for UP/DOWN buttons
        # - Cluster 64512 (Hue proprietary) for ALL buttons with detailed info
        # We only want to handle cluster 64512 to avoid double-firing
        if switch_config.type == "hue_dimmer" and cluster_id in (6, 8):
            logger.debug(f"Ignoring cluster {cluster_id} event for Hue dimmer (will use cluster 64512)")
            return

        # Map the ZHA command to our button event format
        button_event = self._map_zha_command_to_button_event(command, args, switch_config.type)

        if not button_event:
            logger.debug(f"Unmapped ZHA command: {command}")
            return

        # Get the action for this button event
        action = switch_config.get_button_action(button_event)

        if action is None:
            logger.debug(f"No action mapped for {button_event}")
            return

        logger.info(f"Switch {switch_config.name}: {button_event} -> {action}")

        # Handle hold start/stop
        if "_hold" in button_event:
            # Hold started
            if switches.should_repeat_on_hold(device_ieee, button_event):
                switches.start_hold(device_ieee, action)
                await self._start_hold_repeat(device_ieee, action)
            else:
                # Single action on hold (non-repeating)
                await self._execute_switch_action(device_ieee, action)

        elif "_long_release" in button_event or "_release" in button_event:
            # Check if this is ending a hold
            if switches.is_holding(device_ieee):
                await self._stop_hold_repeat(device_ieee)
                # Execute the release action if any
                if action:
                    await self._execute_switch_action(device_ieee, action)
            elif "_short_release" in button_event:
                # Normal short press release - execute the action
                await self._execute_switch_action(device_ieee, action)

        else:
            # Other events (press, double_press, etc.)
            # Skip _press events if we're waiting for release
            if "_press" in button_event and not "_double" in button_event and not "_triple" in button_event:
                # Single press - we'll handle on release to avoid double-firing
                pass
            else:
                await self._execute_switch_action(device_ieee, action)

    async def _handle_unconfigured_switch(self, device_ieee: str, event_data: Dict[str, Any]) -> None:
        """Handle an event from an unconfigured switch.

        Adds the switch to the pending list for configuration.
        """
        logger.info(f"Unconfigured switch detected: {device_ieee}")

        # Try to get device info from cached states or device registry
        device_name = f"Unknown Switch ({device_ieee[-8:]})"
        manufacturer = None
        model = None

        # Look up device info
        device_id = event_data.get("device_id")
        if device_id and device_id in self.device_registry:
            device_info = self.device_registry[device_id]
            device_name = device_info.get("name_by_user") or device_info.get("name") or device_name
            manufacturer = device_info.get("manufacturer")
            model = device_info.get("model")

        # Detect switch type
        detected_type = switches.detect_switch_type(manufacturer, model)

        switches.add_pending_switch(device_ieee, {
            "name": device_name,
            "type": detected_type,
            "manufacturer": manufacturer,
            "model": model,
        })

    def _map_zha_command_to_button_event(
        self,
        command: str,
        args: Union[Dict[str, Any], List[Any]],
        switch_type: str
    ) -> Optional[str]:
        """Map a ZHA command to our button event format.

        ZHA sends commands like:
        - on, off, on_short_release, off_long_release
        - up_short_release, up_hold, up_long_release
        - step_with_on_off, move_with_on_off (older style)

        We normalize these to: {button}_{action_type}

        Note: ZHA args can be either a dict or a list depending on the command.
        For step commands: args is list [step_mode, step_size, transition_time]
        For move commands: args is list [move_mode, rate]
        """
        command_lower = command.lower()

        # Already in our format
        if "_" in command_lower and any(
            action in command_lower
            for action in ["press", "release", "hold", "double", "triple", "quadruple", "quintuple"]
        ):
            return command_lower

        # Handle old-style ZHA commands
        if command_lower == "on":
            return "on_short_release"
        elif command_lower == "off" or command_lower == "off_with_effect":
            return "off_short_release"
        elif command_lower == "step_with_on_off" or command_lower == "step":
            # Determine direction from args
            # Args can be list [step_mode, step_size, transition_time] or dict
            if isinstance(args, list) and len(args) > 0:
                step_mode = args[0]
            elif isinstance(args, dict):
                step_mode = args.get("step_mode", 0)
            else:
                step_mode = 0
            if step_mode == 0:  # Up
                return "up_short_release"
            else:  # Down
                return "down_short_release"
        elif command_lower == "move_with_on_off" or command_lower == "move":
            # This is a hold/move command
            # Args can be list [move_mode, rate] or dict
            if isinstance(args, list) and len(args) > 0:
                move_mode = args[0]
            elif isinstance(args, dict):
                move_mode = args.get("move_mode", 0)
            else:
                move_mode = 0
            if move_mode == 0:  # Up
                return "up_hold"
            else:  # Down
                return "down_hold"
        elif command_lower == "stop" or command_lower == "stop_with_on_off":
            # Stop command indicates release after hold
            # We need to determine which button based on current hold state
            # For now, return a generic release - the hold state tracker will handle it
            return "up_long_release"  # TODO: track which button was held

        return command_lower

    async def _execute_switch_action(self, switch_id: str, action: str) -> None:
        """Execute a switch action.

        Args:
            switch_id: The switch IEEE address
            action: The action to execute
        """
        # Record activity for scope timeout
        switches.record_activity(switch_id)

        # Get areas for current scope
        areas = switches.get_current_areas(switch_id)
        if not areas:
            logger.warning(f"No areas configured for switch {switch_id}")
            return

        logger.info(f"Executing {action} on areas: {areas}")

        # Execute the action
        if action == "cycle_scope":
            await self._execute_cycle_scope(switch_id)

        elif action == "circadian_on":
            for area in areas:
                await self.primitives.circadian_on(area, "switch")

        elif action == "circadian_off":
            for area in areas:
                await self.primitives.circadian_off(area, "switch")

        elif action == "toggle":
            await self.primitives.circadian_toggle_multiple(areas, "switch")

        elif action == "circadian_toggle":
            await self.primitives.circadian_toggle_multiple(areas, "switch")

        elif action == "step_up":
            for area in areas:
                await self.primitives.step_up(area, "switch")

        elif action == "step_down":
            for area in areas:
                await self.primitives.step_down(area, "switch")

        elif action == "bright_up":
            for area in areas:
                await self.primitives.bright_up(area, "switch")

        elif action == "bright_down":
            for area in areas:
                await self.primitives.bright_down(area, "switch")

        elif action == "color_up":
            for area in areas:
                await self.primitives.color_up(area, "switch")

        elif action == "color_down":
            for area in areas:
                await self.primitives.color_down(area, "switch")

        elif action == "reset":
            for area in areas:
                await self.primitives.reset(area, "switch")

        elif action == "freeze_toggle":
            for area in areas:
                await self.primitives.freeze_toggle(area, "switch")

        elif action == "glo_up":
            # Glo actions work on zones, get zone for first area
            zone_id = glozone.get_zone_for_area(areas[0]) if areas else None
            if zone_id:
                await self.primitives.glo_up(zone_id, "switch")
            else:
                logger.warning(f"No zone found for area {areas[0]}")

        elif action == "glo_down":
            zone_id = glozone.get_zone_for_area(areas[0]) if areas else None
            if zone_id:
                await self.primitives.glo_down(zone_id, "switch")
            else:
                logger.warning(f"No zone found for area {areas[0]}")

        elif action == "glo_reset":
            zone_id = glozone.get_zone_for_area(areas[0]) if areas else None
            if zone_id:
                await self.primitives.glo_reset(zone_id, "switch")
            else:
                logger.warning(f"No zone found for area {areas[0]}")

        elif action == "set_britelite":
            # TODO: Implement set_britelite - sets lights to bright white
            logger.info(f"set_britelite action on areas: {areas} (not yet implemented)")

        elif action == "set_nitelite":
            # TODO: Implement set_nitelite - sets lights to dim warm
            logger.info(f"set_nitelite action on areas: {areas} (not yet implemented)")

        elif action == "toggle_wake_bed":
            # TODO: Implement toggle_wake_bed - toggle wake/bed mode
            logger.info(f"toggle_wake_bed action on areas: {areas} (not yet implemented)")

        else:
            logger.warning(f"Unknown action: {action}")

    async def _execute_cycle_scope(self, switch_id: str) -> None:
        """Cycle to the next scope and provide visual feedback.

        Args:
            switch_id: The switch IEEE address
        """
        switch_config = switches.get_switch(switch_id)
        if not switch_config:
            return

        # Count valid scopes
        valid_scopes = [i for i, s in enumerate(switch_config.scopes) if s.areas]
        if len(valid_scopes) <= 1:
            # Only one scope - show error feedback
            await self._show_scope_error_feedback(switch_id)
            return

        # Cycle to next scope
        new_scope = switches.cycle_scope(switch_id)
        new_areas = switch_config.get_areas_for_scope(new_scope)

        # Show visual feedback (pulse count = scope number)
        await self._show_scope_feedback(new_areas, new_scope + 1)  # 1-indexed

    async def _show_scope_feedback(self, areas: List[str], scope_number: int) -> None:
        """Show visual feedback for scope change (pulse count).

        Args:
            areas: Areas to pulse
            scope_number: Which scope (1, 2, or 3) - determines pulse count
        """
        if not areas:
            return

        # Get current brightness of lights in these areas
        # For simplicity, we'll do adaptive pulse based on a representative light
        current_brightness = 50  # Default assumption

        for area in areas:
            # Try to get a light's current state
            light_entity = self._get_fallback_group_entity(area)
            if light_entity and light_entity in self.cached_states:
                state = self.cached_states[light_entity]
                if state.get("state") == "on":
                    attrs = state.get("attributes", {})
                    current_brightness = attrs.get("brightness", 128) / 2.55  # Convert to %
                    break

        # Calculate pulse delta
        if current_brightness > 35:
            pulse_delta = -20  # Dip down
        else:
            pulse_delta = 25  # Bump up

        pulse_brightness = max(1, min(100, current_brightness + pulse_delta))

        # Perform pulses
        for pulse in range(scope_number):
            # Pulse to delta
            for area in areas:
                await self._set_area_brightness_quick(area, int(pulse_brightness * 2.55))

            await asyncio.sleep(0.2)  # 200ms pulse

            # Restore
            for area in areas:
                await self._set_area_brightness_quick(area, int(current_brightness * 2.55))

            if pulse < scope_number - 1:
                await asyncio.sleep(0.15)  # 150ms gap between pulses

    async def _show_scope_error_feedback(self, switch_id: str) -> None:
        """Show error feedback when can't cycle scope (flash red).

        Args:
            switch_id: The switch IEEE address
        """
        areas = switches.get_current_areas(switch_id)
        if not areas:
            return

        # Store current color
        original_colors = {}
        for area in areas:
            light_entity = self._get_fallback_group_entity(area)
            if light_entity and light_entity in self.cached_states:
                state = self.cached_states[light_entity]
                if state.get("state") == "on":
                    attrs = state.get("attributes", {})
                    original_colors[area] = {
                        "color_temp": attrs.get("color_temp"),
                        "rgb_color": attrs.get("rgb_color"),
                        "xy_color": attrs.get("xy_color"),
                    }

        # Flash red
        for area in areas:
            await self._set_area_color_quick(area, rgb_color=[255, 50, 50])

        await asyncio.sleep(0.3)

        # Restore original colors
        for area, colors in original_colors.items():
            if colors.get("color_temp"):
                await self._set_area_color_quick(area, color_temp=colors["color_temp"])
            elif colors.get("rgb_color"):
                await self._set_area_color_quick(area, rgb_color=colors["rgb_color"])
            elif colors.get("xy_color"):
                await self._set_area_color_quick(area, xy_color=colors["xy_color"])

    async def _set_area_brightness_quick(self, area: str, brightness: int) -> None:
        """Quickly set brightness for an area (no transition)."""
        await self.call_service(
            "light",
            "turn_on",
            {"brightness": brightness, "transition": 0},
            target={"area_id": area}
        )

    async def _set_area_color_quick(
        self,
        area: str,
        rgb_color: List[int] = None,
        color_temp: int = None,
        xy_color: List[float] = None,
    ) -> None:
        """Quickly set color for an area (no transition)."""
        service_data = {"transition": 0}
        if rgb_color:
            service_data["rgb_color"] = rgb_color
        elif color_temp:
            service_data["color_temp"] = color_temp
        elif xy_color:
            service_data["xy_color"] = xy_color

        await self.call_service(
            "light",
            "turn_on",
            service_data,
            target={"area_id": area}
        )

    async def _start_hold_repeat(self, switch_id: str, action: str) -> None:
        """Start repeating an action while button is held.

        Args:
            switch_id: The switch IEEE address
            action: The action to repeat
        """
        # Cancel any existing repeat task
        await self._stop_hold_repeat(switch_id)

        # Get repeat interval
        interval_ms = switches.get_repeat_interval(switch_id)

        async def repeat_loop():
            try:
                # Execute immediately first
                await self._execute_switch_action(switch_id, action)

                # Then repeat at interval
                while switches.is_holding(switch_id):
                    await asyncio.sleep(interval_ms / 1000.0)
                    if switches.is_holding(switch_id):
                        await self._execute_switch_action(switch_id, action)
            except asyncio.CancelledError:
                pass

        self._hold_repeat_task = asyncio.create_task(repeat_loop())

    async def _stop_hold_repeat(self, switch_id: str) -> None:
        """Stop the hold repeat task.

        Args:
            switch_id: The switch IEEE address
        """
        switches.stop_hold(switch_id)

        if self._hold_repeat_task and not self._hold_repeat_task.done():
            self._hold_repeat_task.cancel()
            try:
                await self._hold_repeat_task
            except asyncio.CancelledError:
                pass
        self._hold_repeat_task = None

    async def authenticate(self) -> bool:
        """Authenticate with Home Assistant."""
        try:
            # Wait for auth_required message
            auth_required = await self.websocket.recv()
            auth_msg = json.loads(auth_required)
            
            if auth_msg["type"] != "auth_required":
                logger.error(f"Unexpected message type: {auth_msg['type']}")
                return False
                
            # Send authentication
            await self.websocket.send(json.dumps({
                "type": "auth",
                "access_token": self.access_token
            }))
            
            # Wait for auth result
            auth_result = await self.websocket.recv()
            result_msg = json.loads(auth_result)
            
            if result_msg["type"] == "auth_ok":
                logger.info("Successfully authenticated with Home Assistant")
                return True
            else:
                logger.error(f"Authentication failed: {result_msg}")
                return False
                
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            return False
            
    async def subscribe_events(self, event_type: str = None) -> int:
        """Subscribe to events.
        
        Args:
            event_type: Specific event type to subscribe to, or None for all events
            
        Returns:
            Message ID of the subscription request
        """
        message_id = self._get_next_message_id()
        
        subscribe_msg = {
            "id": message_id,
            "type": "subscribe_events"
        }
        
        if event_type:
            subscribe_msg["event_type"] = event_type
            
        await self.websocket.send(json.dumps(subscribe_msg))
        logger.info(f"Subscribed to events (id: {message_id}, type: {event_type or 'all'})")
        
        return message_id
        
    async def call_service(self, domain: str, service: str, service_data: Dict[str, Any], target: Optional[Dict[str, Any]] = None) -> int:
        """Call a Home Assistant service.
        
        Args:
            domain: Service domain (e.g., 'light')
            service: Service name (e.g., 'turn_on')
            service_data: Service parameters
            
        Returns:
            Message ID of the service call
        """
        message_id = self._get_next_message_id()
        
        # Handle target parameter separately from service_data
        final_target = target or {}
        final_service_data = service_data.copy() if service_data else {}
        
        # Extract area_id or entity_id from service_data if present (legacy support)
        if "area_id" in final_service_data:
            final_target["area_id"] = final_service_data.pop("area_id")
        if "entity_id" in final_service_data:
            final_target["entity_id"] = final_service_data.pop("entity_id")
        
        # Note: ZHA group vs area-based control is now handled in turn_on_lights_circadian
        # based on whether the area has ZHA parity (all lights are ZHA)
        # This call_service method remains generic and doesn't auto-substitute
        
        service_msg = {
            "id": message_id,
            "type": "call_service",
            "domain": domain,
            "service": service
        }
        
        if final_service_data:
            service_msg["service_data"] = final_service_data
        if final_target:
            service_msg["target"] = final_target

        logger.debug(f"Sending service call: {domain}.{service} (id: {message_id})")
        await self.websocket.send(json.dumps(service_msg))
        logger.debug(f"Called service: {domain}.{service} (id: {message_id})")
        
        return message_id
        
    async def determine_light_target(self, area_id: str) -> tuple[str, Any]:
        """Determine the best target for controlling lights in an area.
        
        This consolidates the logic for deciding whether to use:
        - ZHA group entity (if all lights are ZHA)
        - Area-based control (if any non-ZHA lights exist)
        
        Args:
            area_id: The area ID to control
            
        Returns:
            Tuple of (target_type, target_value) where:
            - target_type is "entity_id" or "area_id"
            - target_value is the entity/area ID to use
        """
        normalized_key = self._normalize_area_key(area_id)
        group_candidates = self.area_group_map.get(normalized_key, {}) if normalized_key else {}

        hue_entity = group_candidates.get("hue_group")
        zha_entity = group_candidates.get("zha_group")

        # Fall back to legacy lookup table if we did not find a candidate above
        fallback_entity = self._get_fallback_group_entity(area_id)
        if fallback_entity:
            meta = self.group_entity_info.get(fallback_entity, {})
            group_type = meta.get("type")

            if not hue_entity and group_type == "hue_group":
                hue_entity = fallback_entity
            elif not zha_entity and group_type == "zha_group":
                zha_entity = fallback_entity
            elif not group_type and not zha_entity:
                # Legacy compatibility for tests that set area_to_light_entity manually
                zha_entity = fallback_entity

        has_parity = self.area_parity_cache.get(area_id, False)

        if hue_entity:
            logger.debug(f"✓ Using Hue grouped light entity '{hue_entity}' for area '{area_id}'")
            return "entity_id", hue_entity

        if zha_entity:
            if has_parity:
                logger.debug(f"✓ Using ZHA group entity '{zha_entity}' for area '{area_id}' (all lights are ZHA)")
                return "entity_id", zha_entity
            logger.debug(f"⚠ Area '{area_id}' has non-ZHA lights, using area-based control for full coverage")
        
        logger.info(f"Using area-based control for area '{area_id}'")
        return "area_id", area_id
    
    async def turn_on_lights_circadian(
        self,
        area_id: str,
        circadian_values: Dict[str, Any],
        transition: float = 0.5,
        *,
        include_color: bool = True,
    ) -> None:
        """Turn on lights with circadian values using the light controller.

        Splits lights by color capability:
        - Color-capable lights (xy/rgb/hs): Use xy_color for full color range
        - CT-only lights: Use color_temp_kelvin (clamped to 2000K minimum)

        Args:
            area_id: The area ID to control lights in
            circadian_values: Circadian lighting values from get_circadian_lighting
            transition: Transition time in seconds (default 0.5)
            include_color: Whether to include color data when turning on lights
        """
        brightness = circadian_values.get('brightness')
        kelvin = circadian_values.get('kelvin')
        xy = circadian_values.get('xy')

        color_lights, ct_lights = self.get_lights_by_color_capability(area_id)

        # If no lights found in cache, fall back to area-based control
        if not color_lights and not ct_lights:
            target_type, target_value = await self.determine_light_target(area_id)
            service_data = {"transition": transition}
            if brightness is not None:
                service_data["brightness_pct"] = brightness
            if include_color and kelvin is not None:
                service_data["color_temp_kelvin"] = max(2000, kelvin)

            logger.info(f"Circadian update (fallback): {target_type}={target_value}, {service_data}")
            await self.call_service("light", "turn_on", service_data, {target_type: target_value})
            return

        tasks: List[asyncio.Task] = []

        # Color-capable lights: use xy_color for full color range
        if color_lights:
            color_data = {"transition": transition}
            if brightness is not None:
                color_data["brightness_pct"] = brightness
            if include_color and xy is not None:
                color_data["xy_color"] = list(xy)

            logger.info(f"Circadian update (color): {len(color_lights)} lights, xy={xy}, brightness={brightness}%")
            tasks.append(
                asyncio.create_task(
                    self.call_service("light", "turn_on", color_data, {"entity_id": color_lights})
                )
            )

        # CT-only lights: use color_temp_kelvin (clamped to 2000K min)
        if ct_lights:
            ct_data = {"transition": transition}
            if brightness is not None:
                ct_data["brightness_pct"] = brightness
            if include_color and kelvin is not None:
                ct_data["color_temp_kelvin"] = max(2000, kelvin)

            logger.info(f"Circadian update (CT): {len(ct_lights)} lights, kelvin={kelvin}, brightness={brightness}%")
            tasks.append(
                asyncio.create_task(
                    self.call_service("light", "turn_on", ct_data, {"entity_id": ct_lights})
                )
            )

        # Run all tasks concurrently
        if tasks:
            await asyncio.gather(*tasks)
        
    async def get_states(self) -> List[Dict[str, Any]]:
        """Get all entity states.
        
        Returns:
            List of entity states, or empty list if failed
        """
        logger.info("Requesting all entity states...")
        result = await self.send_message_wait_response({"type": "get_states"})
        
        if result and isinstance(result, list):
            # Update cache
            self.cached_states.clear()
            for state in result:
                entity_id = state.get("entity_id", "")
                if entity_id:
                    self.cached_states[entity_id] = state
                    
                    # Extract sun data while we're here
                    if entity_id == "sun.sun":
                        self.sun_data = state.get("attributes", {})
                        logger.debug(f"Found sun data: elevation={self.sun_data.get('elevation')}")
            
            logger.info(f"✓ Loaded {len(result)} entity states")
            return result
        
        logger.error(f"Failed to get states or invalid response: {type(result)}")
        return list(self.cached_states.values()) if self.cached_states else []
    
    async def request_states(self) -> int:
        """Request all entity states (legacy method for initialization).
        
        Returns:
            Message ID of the request
        """
        message_id = self._get_next_message_id()
        
        states_msg = {
            "id": message_id,
            "type": "get_states"
        }
        
        await self.websocket.send(json.dumps(states_msg))
        logger.info(f"Requested states (id: {message_id})")

        return message_id

    async def build_light_capability_cache(self) -> None:
        """Build the light capability cache from entity and device registries.

        Populates:
        - self.light_color_modes: entity_id -> set of supported color modes
        - self.area_lights: area_id -> list of light entity_ids
        """
        logger.info("Building light capability cache...")

        # Fetch entity registry
        entity_result = await self.send_message_wait_response({"type": "config/entity_registry/list"})
        entities = entity_result if isinstance(entity_result, list) else []

        # Fetch device registry for area mapping
        device_result = await self.send_message_wait_response({"type": "config/device_registry/list"})
        devices = device_result if isinstance(device_result, list) else []

        # Store device registry for switch detection and build device_id -> area_id mapping
        self.device_registry.clear()
        device_area_map: Dict[str, str] = {}
        for device in devices:
            if isinstance(device, dict):
                device_id = device.get("id")
                area_id = device.get("area_id")
                if device_id:
                    # Store full device info for switch detection
                    self.device_registry[device_id] = device
                    if area_id:
                        device_area_map[device_id] = area_id

        # Clear existing caches
        self.light_color_modes.clear()
        self.area_lights.clear()

        # Process light entities
        for entity in entities:
            if not isinstance(entity, dict):
                continue

            entity_id = entity.get("entity_id", "")
            if not entity_id.startswith("light."):
                continue

            # Get area - either direct or via device
            area_id = entity.get("area_id")
            if not area_id:
                device_id = entity.get("device_id")
                if device_id:
                    area_id = device_area_map.get(device_id)

            # Skip entities with no area
            if not area_id:
                continue

            # Add to area_lights mapping
            if area_id not in self.area_lights:
                self.area_lights[area_id] = []
            self.area_lights[area_id].append(entity_id)

            # Get color modes from cached state
            state = self.cached_states.get(entity_id, {})
            attributes = state.get("attributes", {})
            supported_modes = attributes.get("supported_color_modes", [])

            if supported_modes:
                self.light_color_modes[entity_id] = set(supported_modes)
            else:
                # Default to color_temp if no modes specified (legacy lights)
                self.light_color_modes[entity_id] = {"color_temp"}

        logger.info(f"✓ Light capability cache built: {len(self.light_color_modes)} lights across {len(self.area_lights)} areas")

        # Log summary of color capabilities
        color_capable = sum(1 for modes in self.light_color_modes.values() if "xy" in modes or "rgb" in modes or "hs" in modes)
        ct_only = len(self.light_color_modes) - color_capable
        logger.info(f"  Color-capable lights: {color_capable}, CT-only lights: {ct_only}")

    def get_lights_by_color_capability(self, area_id: str) -> Tuple[List[str], List[str]]:
        """Get lights in an area split by color capability.

        Args:
            area_id: The area ID

        Returns:
            Tuple of (color_capable_lights, ct_only_lights)
            - color_capable_lights: lights that support xy, rgb, or hs color modes
            - ct_only_lights: lights that only support color_temp mode
        """
        lights = self.area_lights.get(area_id, [])

        color_capable = []
        ct_only = []

        for entity_id in lights:
            modes = self.light_color_modes.get(entity_id, {"color_temp"})

            # Check if light supports any color mode (xy, rgb, hs)
            if "xy" in modes or "rgb" in modes or "hs" in modes:
                color_capable.append(entity_id)
            else:
                ct_only.append(entity_id)

        return color_capable, ct_only


    async def get_config(self) -> bool:
        """Get Home Assistant configuration and wait for response.
        
        Returns:
            True if config was successfully loaded, False otherwise
        """
        logger.info("Requesting Home Assistant configuration...")
        result = await self.send_message_wait_response({"type": "get_config"})
        
        if result and isinstance(result, dict):
            if "latitude" in result and "longitude" in result:
                self.latitude = result.get("latitude")
                self.longitude = result.get("longitude")
                self.timezone = result.get("time_zone")
                logger.info(f"✓ Loaded HA location: lat={self.latitude}, lon={self.longitude}, tz={self.timezone}")
                
                # Set environment variables for brain.py to use as defaults
                if self.latitude:
                    os.environ["HASS_LATITUDE"] = str(self.latitude)
                if self.longitude:
                    os.environ["HASS_LONGITUDE"] = str(self.longitude)
                if self.timezone:
                    os.environ["HASS_TIME_ZONE"] = self.timezone
                    
                return True
            else:
                logger.warning(f"⚠ Config response missing location data: {result.keys()}")
        else:
            logger.error(f"Failed to get config or invalid response type: {type(result)}")
            
        return False
        
    
    def _get_data_directory(self) -> str:
        """Get the appropriate data directory based on environment.

        Returns:
            Path to the data directory
        """
        # Prefer /config/circadian-light (visible in HA config folder, included in backups)
        if os.path.exists("/config"):
            data_dir = "/config/circadian-light"
            os.makedirs(data_dir, exist_ok=True)
            return data_dir
        elif os.path.exists("/data"):
            # Fallback to /data
            return "/data"
        else:
            # Running in development - use local .data directory
            data_dir = os.path.join(os.path.dirname(__file__), ".data")
            os.makedirs(data_dir, exist_ok=True)
            return data_dir

    def _get_state_file_path(self) -> str:
        """Return the path used for persisting state (deprecated, use state.py)."""
        return os.path.join(self._get_data_directory(), "circadian_state.json")


    def _update_color_mode_from_config(self, merged_config: Dict[str, Any]):
        """Update color mode from configuration if available.
        
        Args:
            merged_config: Dictionary containing configuration from options.json and designer_config.json
        """
        if 'color_mode' in merged_config:
            color_mode_str = str(merged_config['color_mode']).lower()
            try:
                # Try to get by value (lowercase) first
                new_color_mode = ColorMode(color_mode_str)
                if new_color_mode != self.color_mode:
                    logger.info(f"Updating color mode from config: {self.color_mode.value} -> {new_color_mode.value}")
                    self.color_mode = new_color_mode
            except ValueError:
                # Try uppercase enum name as fallback
                try:
                    new_color_mode = ColorMode[color_mode_str.upper()]
                    if new_color_mode != self.color_mode:
                        logger.info(f"Updating color mode from config: {self.color_mode.value} -> {new_color_mode.value}")
                        self.color_mode = new_color_mode
                except KeyError:
                    logger.warning(f"Invalid color_mode '{color_mode_str}' in config, keeping current: {self.color_mode.value}")
    

    async def any_lights_on_in_area(
        self,
        area_id_or_list: Union[str, Sequence[str]]
    ) -> bool:
        """Return True if any lights are on in the given area(s).

        Accepts a single area id/name/slug OR a list of them.
        Uses HA's template engine (no manual area registry lookup).
        """

        # Normalize to list[str]
        if isinstance(area_id_or_list, str):
            areas: list[str] = [area_id_or_list]
        else:
            areas = [a for a in area_id_or_list if isinstance(a, str)]

        if not areas:
            logger.warning("[template] no area_id provided")
            return False

        for area_id in areas:
            # Fast path: known group entity for this key
            normalized_key = self._normalize_area_key(area_id)
            light_entity_id = None
            if normalized_key and normalized_key in self.area_group_map:
                candidates = self.area_group_map[normalized_key]
                light_entity_id = candidates.get("hue_group") or candidates.get("zha_group")
            if not light_entity_id:
                light_entity_id = self._get_fallback_group_entity(area_id)
            if light_entity_id:
                state = self.cached_states.get(light_entity_id, {}).get("state")
                logger.info(f"[group_fastpath] {light_entity_id=} {area_id=} state={state}")
                if state in ("on", "off"):
                    if state == "on":
                        return True
                    continue  # go next area

            # Ask HA via template: does this area have ANY light.* that is 'on'?
            template = (
                f"{{{{ expand(area_entities('{area_id}')) "
                f"| selectattr('entity_id', 'match', '^light\\\\.') "
                f"| selectattr('state', 'eq', 'on') "
                f"| list | count > 0 }}}}"
            )
            logger.debug(f"[template] area={area_id} jinja={template}")

            resp = await self.send_message_wait_response(
                {
                    "type": "render_template",
                    "template": template,
                    "report_errors": True,
                    "timeout": 10,
                },
                full_envelope=True,
            )

            if isinstance(resp, dict) and resp.get("type") == "result" and resp.get("success", False):
                inner = resp.get("result") or {}
                rendered = inner.get("result")
                area_on = (
                    rendered if isinstance(rendered, bool)
                    else (str(rendered).strip().lower() in ("true", "1", "yes", "on"))
                )
                if area_on:
                    return True
            else:
                logger.warning(f"[template] failed for area={area_id}: {resp!r} (treating as off)")

        # None of the areas had lights on
        return False
    
    def enable_circadian_mode(self, area_id: str):
        """Enable Circadian Light mode for an area.

        Args:
            area_id: The area ID to enable Circadian Light for
        """
        was_enabled = state.is_enabled(area_id)
        state.set_enabled(area_id, True)

        if not was_enabled:
            logger.info(f"Circadian Light enabled for area {area_id}")
        else:
            logger.debug(f"Circadian Light already enabled for area {area_id}")

    async def disable_circadian_mode(self, area_id: str):
        """Disable Circadian Light mode for an area.

        Args:
            area_id: The area ID to disable Circadian Light for
        """
        was_enabled = state.is_enabled(area_id)

        if not was_enabled:
            logger.info(f"Circadian Light already disabled for area {area_id}")
            return

        state.set_enabled(area_id, False)
        logger.info(f"Circadian Light disabled for area {area_id}")
    
    def get_brightness_step_pct(self) -> float:
        """Return the configured brightness step size in percent."""
        steps = max(1, int(self.max_dim_steps) if self.max_dim_steps else DEFAULT_MAX_DIM_STEPS)
        return 100.0 / steps

    def get_brightness_bounds(self) -> tuple[int, int]:
        """Return the configured min/max brightness bounds."""
        return int(self.min_brightness), int(self.max_brightness)

    async def get_circadian_lighting_for_area(
        self,
        area_id: str,
        current_time: Optional[datetime] = None,
        apply_time_offset: bool = True,
        apply_brightness_adjustment: bool = True,
    ) -> Dict[str, Any]:
        """Get circadian lighting values for a specific area.

        This is the centralized method that should be used for all circadian lighting calculations.
        Uses zone-aware configuration - gets the preset config for the area's zone.

        Args:
            area_id: The area ID to get lighting values for
            current_time: Optional datetime to use for calculations (for time simulation)
            apply_time_offset: Whether to apply time offset (unused, kept for API compatibility)

        Returns:
            Dict containing circadian lighting values
        """
        # Get zone-aware config for this area (preset settings + global settings)
        merged_config = glozone.get_effective_config_for_area(area_id)

        # Load curve parameters from the merged config
        curve_params = {}

        # Keep merged config available to other components
        try:
            self.config = merged_config
        except Exception:
            pass

        # Update color mode from configuration if available
        self._update_color_mode_from_config(merged_config)

        try:
            # Extract simplified curve parameters if present
            # Using the new parameter names from designer.html
            config_params = {}
            
            # Morning parameters (up)
            for key in ["mid_bri_up", "steep_bri_up", "mid_cct_up", "steep_cct_up"]:
                if key in merged_config:
                    config_params[key] = merged_config[key]
            
            # Evening parameters (dn)
            for key in ["mid_bri_dn", "steep_bri_dn", "mid_cct_dn", "steep_cct_dn"]:
                if key in merged_config:
                    config_params[key] = merged_config[key]
            
            # Mirror and gamma parameters
            for key in ["mirror_up", "mirror_dn", "gamma_ui", "max_dim_steps"]:
                if key in merged_config:
                    config_params[key] = merged_config[key]
            
            # Add config parameters to curve_params
            if config_params:
                curve_params["config"] = config_params
                
        except Exception as e:
            logger.debug(f"Could not parse curve parameters from merged config: {e}")
        
        # Add min/max values to curve parameters
        # These can come from environment variables or the merged config
        if 'min_color_temp' in merged_config:
            curve_params['min_color_temp'] = int(merged_config['min_color_temp'])
        elif os.getenv('MIN_COLOR_TEMP'):
            curve_params['min_color_temp'] = int(os.getenv('MIN_COLOR_TEMP'))
            
        if 'max_color_temp' in merged_config:
            curve_params['max_color_temp'] = int(merged_config['max_color_temp'])
        elif os.getenv('MAX_COLOR_TEMP'):
            curve_params['max_color_temp'] = int(os.getenv('MAX_COLOR_TEMP'))
            
        if 'min_brightness' in merged_config:
            curve_params['min_brightness'] = int(merged_config['min_brightness'])
        elif os.getenv('MIN_BRIGHTNESS'):
            curve_params['min_brightness'] = int(os.getenv('MIN_BRIGHTNESS'))
            
        if 'max_brightness' in merged_config:
            curve_params['max_brightness'] = int(merged_config['max_brightness'])
        elif os.getenv('MAX_BRIGHTNESS'):
            curve_params['max_brightness'] = int(os.getenv('MAX_BRIGHTNESS'))

        # Update cached brightness configuration for quick access elsewhere
        if 'max_dim_steps' in merged_config:
            try:
                self.max_dim_steps = int(merged_config['max_dim_steps']) or DEFAULT_MAX_DIM_STEPS
            except (TypeError, ValueError):
                logger.debug(f"Invalid max_dim_steps '{merged_config.get('max_dim_steps')}', keeping {self.max_dim_steps}")

        if 'min_brightness' in curve_params:
            self.min_brightness = curve_params['min_brightness']
        if 'max_brightness' in curve_params:
            self.max_brightness = curve_params['max_brightness']

        # Store curve parameters for dimming calculations
        self.curve_params = curve_params

        # Get circadian lighting values with new morning/evening curves
        lighting_values = get_circadian_lighting(
            latitude=self.latitude,
            longitude=self.longitude,
            timezone=self.timezone,
            current_time=current_time,
            **curve_params
        )

        # Log the calculation
        logger.info(f"Circadian lighting for area {area_id}: {lighting_values['kelvin']}K, {lighting_values['brightness']}%")

        lighting_values = dict(lighting_values)

        if 'brightness' in lighting_values:
            lighting_values['brightness'] = int(round(lighting_values['brightness']))

        return lighting_values
    
    async def update_lights_in_circadian_mode(self, area_id: str):
        """Update lights in an area with circadian lighting if Circadian Light is enabled.

        This method respects per-area stepped state (brightness_mid, color_mid, pushed bounds)
        that was set via step_up/step_down buttons.

        If the area is frozen (frozen_at is set), uses frozen_at instead of current time.
        Uses zone-aware configuration - gets the preset config for the area's zone.

        Args:
            area_id: The area ID to update
        """
        try:
            # Only update if area is enabled
            if not state.is_enabled(area_id):
                logger.debug(f"Area {area_id} not in Circadian mode, skipping update")
                return

            # Get area state (includes stepped midpoints, pushed bounds, and frozen_at)
            area_state = AreaState.from_dict(state.get_area(area_id))

            # Get zone-aware config for this area
            config_dict = glozone.get_effective_config_for_area(area_id)
            config = Config.from_dict(config_dict)

            # Use frozen_at if set, otherwise current time
            if area_state.frozen_at is not None:
                hour = area_state.frozen_at
                logger.debug(f"Area {area_id} is frozen at hour {hour:.2f}")
            else:
                hour = get_current_hour()

            # Calculate lighting using area state (respects stepped values)
            result = CircadianLight.calculate_lighting(hour, config, area_state)

            # Build values dict for turn_on_lights_circadian
            lighting_values = {
                'brightness': result.brightness,
                'kelvin': result.color_temp,
                'rgb': result.rgb,
                'xy': result.xy,
            }

            # Log the calculation
            frozen_note = f" (frozen at {hour:.1f}h)" if area_state.frozen_at is not None else ""
            logger.info(f"Periodic update for area {area_id}{frozen_note}: {result.color_temp}K, {result.brightness}%")

            # Use the centralized light control function
            await self.turn_on_lights_circadian(area_id, lighting_values, transition=0.5)

        except Exception as e:
            logger.error(f"Error updating lights in area {area_id}: {e}")

    async def reset_state_at_phase_change(self, last_check: Optional[datetime]) -> Optional[datetime]:
        """Reset all area and zone runtime state at phase transitions (ascend/descend).

        State resets when crossing ascend_start or descend_start times.
        Resets both area runtime state and GloZone runtime state.

        Note: Currently uses the first preset's phase times for the global check.
        Future enhancement: per-zone phase checks for different schedules.

        Args:
            last_check: The last time we checked for phase change

        Returns:
            The updated last check time
        """
        from zoneinfo import ZoneInfo
        import glozone_state

        # Get current time
        tzinfo = ZoneInfo(self.timezone) if self.timezone else None
        now = datetime.now(tzinfo)

        # Initialize last check if needed
        if last_check is None:
            return now

        # Load config (uses first preset for phase times)
        # Future: could check per-zone phase times
        raw_config = glozone.load_config_from_files()
        presets = raw_config.get("circadian_presets", {})

        if not presets:
            return now

        # Use first preset's phase times for global check
        first_preset = list(presets.values())[0]
        config = Config.from_dict(first_preset)

        # Convert hours to today's datetime
        ascend_dt = now.replace(
            hour=int(config.ascend_start),
            minute=int((config.ascend_start % 1) * 60),
            second=0,
            microsecond=0
        )
        descend_dt = now.replace(
            hour=int(config.descend_start),
            minute=int((config.descend_start % 1) * 60),
            second=0,
            microsecond=0
        )

        # Check if we've crossed a phase boundary
        crossed_ascend = last_check < ascend_dt <= now
        crossed_descend = last_check < descend_dt <= now

        if crossed_ascend or crossed_descend:
            phase = "ascend" if crossed_ascend else "descend"
            logger.info(f"Phase change to {phase} - resetting all zone and area runtime state")

            # Reset all GloZone runtime state (preserves frozen zones)
            glozone_state.reset_all_zones()

            # Reset all area runtime state (preserves frozen areas)
            state.reset_all_areas()

            # Update all enabled areas with new values
            for area_id in state.get_unfrozen_enabled_areas():
                await self.update_lights_in_circadian_mode(area_id)

        return now

    async def periodic_light_updater(self):
        """Periodically update lights in areas that have Circadian Light enabled.

        Runs every 30 seconds, or immediately when refresh_event is signaled.
        """
        # Create the Event lazily in the running event loop to avoid "different loop" errors
        if self.refresh_event is None:
            self.refresh_event = asyncio.Event()

        last_phase_check = None

        while True:
            try:
                # Wait for 30 seconds OR until refresh_event is signaled
                triggered_by_event = False
                try:
                    await asyncio.wait_for(self.refresh_event.wait(), timeout=30)
                    self.refresh_event.clear()
                    triggered_by_event = True
                except asyncio.TimeoutError:
                    pass  # Normal 30s tick

                # Check if we should reset state at phase changes
                last_phase_check = await self.reset_state_at_phase_change(last_phase_check)

                # Check for switch scope timeouts (auto-reset to scope 1 after inactivity)
                reset_switches = switches.check_scope_timeouts()
                if reset_switches:
                    logger.debug(f"Reset {len(reset_switches)} switch(es) to scope 1 due to inactivity")

                # Get all enabled, unfrozen areas from state module
                circadian_areas = state.get_unfrozen_enabled_areas()

                if not circadian_areas:
                    logger.debug("No areas enabled for Circadian Light update")
                    continue

                # Skip area being designed in Live Design mode
                if self.live_design_area and self.live_design_area in circadian_areas:
                    circadian_areas = [a for a in circadian_areas if a != self.live_design_area]
                    logger.debug(f"Skipping Live Design area: {self.live_design_area}")

                trigger_source = "refresh signal" if triggered_by_event else "periodic (30s)"
                if circadian_areas:
                    logger.info(f"Running light update ({trigger_source}) for {len(circadian_areas)} Circadian areas")
                else:
                    logger.debug(f"No areas to update ({trigger_source}) - all skipped or disabled")
                    continue

                # Update lights in all enabled areas
                for area_id in circadian_areas:
                    logger.debug(f"Updating lights in Circadian area: {area_id}")
                    await self.update_lights_in_circadian_mode(area_id)

            except asyncio.CancelledError:
                logger.info("Periodic light updater cancelled")
                break
            except Exception as e:
                logger.error(f"Error in periodic light updater: {e}")
                # Continue running even if there's an error
        
    async def refresh_area_parity_cache(self, areas_data: dict = None):
        """Refresh the cache of area ZHA parity status.
        
        This should be called during initialization and when areas/devices change.
        
        Args:
            areas_data: Pre-loaded areas data to avoid duplicate queries (optional)
        """
        try:
            if not self.light_controller:
                return
                
            zigbee_controller = self.light_controller.controllers.get(Protocol.ZIGBEE)
            if not zigbee_controller:
                return
            
            # Use provided areas data or fetch new
            if areas_data:
                areas = areas_data
            else:
                # Get all areas with their light information
                areas = await zigbee_controller.get_areas()
            
            # Clear and rebuild the cache
            self.area_parity_cache.clear()
            
            for area_id, area_info in areas.items():
                area_name = area_info.get('name', '')
                
                # Skip the Circadian_Zigbee_Groups area - it's just for organizing group entities
                if area_name == 'Circadian_Zigbee_Groups':
                    continue
                    
                zha_lights = area_info.get('zha_lights', [])
                non_zha_lights = area_info.get('non_zha_lights', [])
                
                # Area has parity if it has ZHA lights and no non-ZHA lights
                has_parity = len(zha_lights) > 0 and len(non_zha_lights) == 0
                self.area_parity_cache[area_id] = has_parity
                
                if has_parity:
                    logger.info(f"Area '{area_info['name']}' has ZHA parity ({len(zha_lights)} ZHA lights)")
                elif non_zha_lights:
                    logger.info(f"Area '{area_info['name']}' lacks ZHA parity ({len(zha_lights)} ZHA, {len(non_zha_lights)} non-ZHA)")
                    
            logger.info(f"Refreshed area parity cache for {len(self.area_parity_cache)} areas")
            
        except Exception as e:
            logger.error(f"Failed to refresh area parity cache: {e}")
    
    async def sync_zha_groups(self):
        """Helper method to sync ZHA groups with all areas."""
        try:
            logger.info("=" * 60)
            logger.info("Starting ZHA group sync process")
            logger.info("=" * 60)

            zigbee_controller = self.light_controller.controllers.get(Protocol.ZIGBEE)
            if zigbee_controller:
                # Sync ZHA groups with all areas (no longer limited to areas with switches)
                success, areas = await zigbee_controller.sync_zha_groups_with_areas()
                if success:
                    logger.info("ZHA group sync completed")
                    # Refresh parity cache using the areas data we already have
                    await self.refresh_area_parity_cache(areas_data=areas)
            else:
                logger.warning("ZigBee controller not available for group sync")

            logger.info("=" * 60)
            logger.info("ZHA group sync process complete")
            logger.info("=" * 60)
        except Exception as e:
            logger.error(f"Failed to sync ZHA groups: {e}")
    
    
    async def handle_message(self, message: Dict[str, Any]):
        """Handle incoming messages."""
        msg_type = message.get("type")
        
        if msg_type == "event":
            event = message.get("event", {})
            event_type = event.get("event_type", "unknown")
            event_data = event.get("data", {})
            
            logger.debug(f"Event received: {event_type}")
            
            # Log more details for call_service events
            if event_type == "call_service":
                logger.debug(f"Service called: {event_data.get('domain')}.{event_data.get('service')} with data: {event_data.get('service_data')}")
            
            # logger.debug(f"Event data: {json.dumps(event_data, indent=2)}")
            
            # Handle custom service calls for "circadian" domain
            if event_type == "call_service" and event_data.get("domain") == "circadian":
                domain = event_data.get("domain")
                service = event_data.get("service")
                service_data = event_data.get("service_data", {})
                area_id = service_data.get("area_id")

                # Helper to get area list
                def get_areas():
                    if not area_id:
                        return None
                    return area_id if isinstance(area_id, list) else [area_id]

                # Map services to primitives
                if service == "step_up":
                    areas = get_areas()
                    if areas:
                        for area in areas:
                            logger.info(f"[{domain}] step_up for area: {area}")
                            await self.primitives.step_up(area, "service_call")
                    else:
                        logger.warning("step_up called without area_id")

                elif service == "step_down":
                    areas = get_areas()
                    if areas:
                        for area in areas:
                            logger.info(f"[{domain}] step_down for area: {area}")
                            await self.primitives.step_down(area, "service_call")
                    else:
                        logger.warning("step_down called without area_id")

                elif service in ("bright_up", "dim_up"):
                    areas = get_areas()
                    if areas:
                        for area in areas:
                            logger.info(f"[{domain}] bright_up for area: {area}")
                            await self.primitives.bright_up(area, "service_call")
                    else:
                        logger.warning("bright_up called without area_id")

                elif service in ("bright_down", "dim_down"):
                    areas = get_areas()
                    if areas:
                        for area in areas:
                            logger.info(f"[{domain}] bright_down for area: {area}")
                            await self.primitives.bright_down(area, "service_call")
                    else:
                        logger.warning("bright_down called without area_id")

                elif service == "color_up":
                    areas = get_areas()
                    if areas:
                        for area in areas:
                            logger.info(f"[{domain}] color_up for area: {area}")
                            await self.primitives.color_up(area, "service_call")
                    else:
                        logger.warning("color_up called without area_id")

                elif service == "color_down":
                    areas = get_areas()
                    if areas:
                        for area in areas:
                            logger.info(f"[{domain}] color_down for area: {area}")
                            await self.primitives.color_down(area, "service_call")
                    else:
                        logger.warning("color_down called without area_id")

                elif service in ("circadian_on", "on"):
                    areas = get_areas()
                    if areas:
                        for area in areas:
                            logger.info(f"[{domain}] circadian_on for area: {area}")
                            await self.primitives.circadian_on(area, "service_call")
                    else:
                        logger.warning("circadian_on called without area_id")

                elif service in ("circadian_off", "off"):
                    areas = get_areas()
                    if areas:
                        for area in areas:
                            logger.info(f"[{domain}] circadian_off for area: {area}")
                            await self.primitives.circadian_off(area, "service_call")
                    else:
                        logger.warning("circadian_off called without area_id")

                elif service in ("circadian_toggle", "toggle"):
                    areas = get_areas()
                    if areas:
                        logger.info(f"[{domain}] circadian_toggle for areas: {areas}")
                        await self.primitives.circadian_toggle_multiple(areas, "service_call")
                    else:
                        logger.warning("circadian_toggle called without area_id")

                elif service == "set":
                    areas = get_areas()
                    preset = service_data.get("preset")  # wake, bed, nitelite, britelite
                    frozen_at = service_data.get("frozen_at")  # Optional specific hour (0-24)
                    copy_from = service_data.get("copy_from")  # Optional area_id to copy from
                    enable = service_data.get("enable", False)  # Optional: also enable the area
                    if areas:
                        for area in areas:
                            logger.info(f"[{domain}] set for area: {area} (preset={preset}, frozen_at={frozen_at}, copy_from={copy_from}, enable={enable})")
                            await self.primitives.set(area, "service_call", preset=preset, frozen_at=frozen_at, copy_from=copy_from, enable=enable)
                    else:
                        logger.warning("set called without area_id")

                elif service == "freeze_toggle":
                    areas = get_areas()
                    if areas:
                        logger.info(f"[{domain}] freeze_toggle for areas: {areas}")
                        await self.primitives.freeze_toggle_multiple(areas, "service_call")
                    else:
                        logger.warning("freeze_toggle called without area_id")

                elif service == "reset":
                    areas = get_areas()
                    if areas:
                        for area in areas:
                            logger.info(f"[{domain}] reset for area: {area}")
                            await self.primitives.reset(area, "service_call")
                    else:
                        logger.warning("reset called without area_id")

                elif service == "broadcast":
                    areas = get_areas()
                    if areas:
                        # Use first area as source
                        source_area = areas[0]
                        logger.info(f"[{domain}] broadcast from source area: {source_area}")
                        await self.primitives.broadcast(source_area, "service_call")
                    else:
                        logger.warning("broadcast called without area_id")

                elif service == "refresh":
                    # Signal the periodic updater to run immediately
                    # This uses the exact same code path as the 30s refresh
                    logger.info(f"[{domain}] refresh requested - signaling periodic updater")
                    if self.refresh_event is not None:
                        self.refresh_event.set()
                    else:
                        logger.warning(f"[{domain}] refresh_event not yet initialized, skipping signal")

                elif service == "glo_up":
                    areas = get_areas()
                    if areas:
                        for area in areas:
                            logger.info(f"[{domain}] glo_up for area: {area}")
                            await self.primitives.glo_up(area, "service_call")
                    else:
                        logger.warning("glo_up called without area_id")

                elif service == "glo_down":
                    areas = get_areas()
                    if areas:
                        for area in areas:
                            logger.info(f"[{domain}] glo_down for area: {area}")
                            await self.primitives.glo_down(area, "service_call")
                    else:
                        logger.warning("glo_down called without area_id")

                elif service == "glo_reset":
                    areas = get_areas()
                    if areas:
                        for area in areas:
                            logger.info(f"[{domain}] glo_reset for area: {area}")
                            await self.primitives.glo_reset(area, "service_call")
                    else:
                        logger.warning("glo_reset called without area_id")

            # Handle circadian_light_refresh event (fired by webserver after config save)
            elif event_type == "circadian_light_refresh":
                logger.info("circadian_light_refresh event received - signaling periodic updater")
                if self.refresh_event is not None:
                    self.refresh_event.set()
                else:
                    logger.warning("refresh_event not yet initialized, skipping signal")

            # Handle circadian_light_live_design event (fired by webserver when Live Design starts/stops)
            elif event_type == "circadian_light_live_design":
                area_id = event_data.get('area_id')
                active = event_data.get('active', False)
                if active:
                    self.live_design_area = area_id
                    logger.info(f"Live Design started for area: {area_id} - skipping periodic updates")
                else:
                    if self.live_design_area == area_id:
                        self.live_design_area = None
                        logger.info(f"Live Design ended for area: {area_id} - resuming periodic updates")

            # Handle circadian_light_service_event (fired by webserver for GloZone actions)
            elif event_type == "circadian_light_service_event":
                service = event_data.get('service')
                area_id = event_data.get('area_id')

                if service == "glo_up" and area_id:
                    logger.info(f"[webserver] glo_up for area: {area_id}")
                    await self.primitives.glo_up(area_id, "webserver")
                elif service == "glo_down" and area_id:
                    logger.info(f"[webserver] glo_down for area: {area_id}")
                    await self.primitives.glo_down(area_id, "webserver")
                elif service == "glo_reset" and area_id:
                    logger.info(f"[webserver] glo_reset for area: {area_id}")
                    await self.primitives.glo_reset(area_id, "webserver")
                else:
                    logger.warning(f"Unknown circadian_light_service_event: service={service}, area_id={area_id}")

            # Handle device registry updates (when devices are added/removed/modified)
            elif event_type == "device_registry_updated":
                action = event_data.get("action")
                device_id = event_data.get("device_id")

                logger.info(f"Device registry updated: action={action}, device_id={device_id}")

                # Trigger resync if a device was added, removed, or updated
                if action in ["create", "update", "remove"]:
                    await self.sync_zha_groups()  # This includes parity cache refresh
            
            # Handle area registry updates (when areas are added/removed/modified)
            elif event_type == "area_registry_updated":
                action = event_data.get("action")
                area_id = event_data.get("area_id")
                
                logger.info(f"Area registry updated: action={action}, area_id={area_id}")
                
                # Always resync on area changes
                await self.sync_zha_groups()  # This includes parity cache refresh
            
            # Handle entity registry updates (when entities change areas)
            elif event_type == "entity_registry_updated":
                action = event_data.get("action")
                entity_id = event_data.get("entity_id")
                changes = event_data.get("changes", {})
                
                # Check if area_id changed
                if "area_id" in changes:
                    old_area = changes["area_id"].get("old_value")
                    new_area = changes["area_id"].get("new_value")
                    logger.info(f"Entity {entity_id} moved from area {old_area} to {new_area}")
                    await self.sync_zha_groups()  # This includes parity cache refresh
            
            # Handle state changes
            elif event_type == "state_changed":
                entity_id = event_data.get("entity_id")
                new_state = event_data.get("new_state", {})
                old_state = event_data.get("old_state", {})
                
                # Update cached state
                if entity_id and isinstance(new_state, dict):
                    self.cached_states[entity_id] = new_state
                    
                    # Check if this is a ZHA group light entity TODO: THIS IS VERY EXHAUSTIVE
                    if entity_id.startswith("light."):
                        attributes = new_state.get("attributes", {})
                        friendly_name = attributes.get("friendly_name", "")
                        self._update_area_group_mapping(entity_id, friendly_name, attributes)
                
                # Update sun data if it's the sun entity
                if entity_id == "sun.sun" and isinstance(new_state, dict):
                    self.sun_data = new_state.get("attributes", {})
                    logger.info(f"Updated sun data: elevation={self.sun_data.get('elevation')}")
                
                
                #if isinstance(new_state, dict):
                #    logger.info(f"State changed: {entity_id} -> {new_state.get('state')}")
                #else:
                #    logger.info(f"State changed: {entity_id} -> {new_state}")

            # Handle ZHA events (switch button presses)
            elif event_type == "zha_event":
                logger.info(f"ZHA event received: {event_data}")
                await self._handle_zha_event(event_data)

        elif msg_type == "result":
            success = message.get("success", False)
            msg_id = message.get("id")
            result = message.get("result")
            
            # Handle states result
            if result and isinstance(result, list) and len(result) > 0:
                first_item = result[0]
                # Check if this is states data
                if isinstance(first_item, dict) and "entity_id" in first_item:
                    # This is states data - update our cache
                    self.cached_states.clear()
                    for state in result:
                        entity_id = state.get("entity_id", "")
                        self.cached_states[entity_id] = state
                        
                        attributes = state.get("attributes", {})
                        
                        # Store initial sun data
                        if entity_id == "sun.sun":
                            self.sun_data = attributes
                            logger.info(f"Initial sun data: elevation={self.sun_data.get('elevation')}")
                        
                        # Detect ZHA group light entities (Circadian_AREA pattern)
                        if entity_id.startswith("light."):
                            # Check both entity_id and friendly_name for Circadian_ pattern
                            friendly_name = attributes.get("friendly_name", "")
                            
                            # Debug log all light entities
                            logger.debug(f"Light entity: {entity_id}, friendly_name: {friendly_name}")
                            
                            # Use the centralized method to update ZHA group mapping
                            self._update_area_group_mapping(entity_id, friendly_name, attributes)
                    
                    self.last_states_update = asyncio.get_event_loop().time()
                    logger.info(f"Cached {len(self.cached_states)} entity states")
                    
                    # Log ALL light entities for debugging
                    all_lights = []
                    for entity_id, state in self.cached_states.items():
                        if entity_id.startswith("light."):
                            friendly_name = state.get("attributes", {}).get("friendly_name", "")
                            all_lights.append((entity_id, friendly_name))
                    
                    if all_lights:
                        logger.info("=== All Light Entities Found ===")
                        for entity_id, name in all_lights:
                            logger.info(f"  - {entity_id}: {name}")
                        logger.info("="*40)
                    
                    # Log discovered grouped light entities
                    if self.group_entity_info:
                        logger.info("=== Discovered Grouped Light Entities ===")
                        for entity_id, info in self.group_entity_info.items():
                            group_type = info.get("type", "unknown")
                            area_label = info.get("area") or info.get("area_id") or info.get("area_name") or "unknown"
                            logger.info(f"  - {entity_id} [{group_type}] -> Area: '{area_label}'")
                        logger.info(f"Total: {len(self.group_entity_info)} grouped entities mapped to areas")
                        logger.info("=" * 50)
                    else:
                        logger.warning("No grouped light entities discovered (Circadian_ ZHA or Hue rooms)")
            
            # Handle config result
            elif result and isinstance(result, dict):
                # Check if this is config data
                if "latitude" in result and "longitude" in result:
                    self.latitude = result.get("latitude")
                    self.longitude = result.get("longitude")
                    self.timezone = result.get("time_zone")
                    logger.info(f"Home Assistant location: lat={self.latitude}, lon={self.longitude}, tz={self.timezone}")
                    
                    # Set environment variables for brain.py to use as defaults
                    if self.latitude:
                        os.environ["HASS_LATITUDE"] = str(self.latitude)
                    if self.longitude:
                        os.environ["HASS_LONGITUDE"] = str(self.longitude)
                    if self.timezone:
                        os.environ["HASS_TIME_ZONE"] = self.timezone
            
            logger.debug(f"Result for message {msg_id}: {'success' if success else 'failed'}")
            
        else:
            logger.debug(f"Received message type: {msg_type}")
            
    async def send_message_wait_response(
    self,
    message: Dict[str, Any],
    *,
    full_envelope: bool = False,
) -> Optional[Dict[str, Any]]:
        if not self.websocket:
            logger.error("WebSocket not connected")
            return None

        message["id"] = self._get_next_message_id()
        msg_id = message["id"]

        try:
            await self.websocket.send(json.dumps(message))
        except Exception as e:
            logger.error(f"WebSocket send failed for id={msg_id}: {e}")
            return None

        overall_timeout = 10.0
        deadline = asyncio.get_event_loop().time() + overall_timeout
        need_event_followup = False
        is_render_template = (message.get("type") == "render_template")

        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                logger.error(f"Timeout waiting for response to message id={msg_id}")
                return None

            try:
                frame = await asyncio.wait_for(self.websocket.recv(), timeout=remaining)
            except asyncio.TimeoutError:
                logger.error(f"Timeout waiting for response to message id={msg_id}")
                return None
            except Exception as e:
                logger.error(f"Error waiting for response to id={msg_id}: {e}")
                return None

            try:
                data = json.loads(frame)
            except Exception:
                logger.debug(f"Ignoring non-JSON frame while waiting for id={msg_id}: {frame!r}")
                continue

            # Ignore unrelated frames (e.g., other subscriptions)
            if data.get("id") != msg_id:
                continue

            # Case A: render_template sends a 'result' (often null) then an 'event' with the real value
            if is_render_template:
                if data.get("type") == "result":
                    # If success but result is null, expect an event next
                    if data.get("success", False) and data.get("result") is None:
                        need_event_followup = True
                        # don't return yet; keep looping for the event
                        continue
                    # Some HA versions may put the value here; handle normally below
                elif data.get("type") == "event":
                    # Synthesize a normal envelope from the event for caller convenience
                    event = data.get("event") or {}
                    if full_envelope:
                        return {
                            "id": msg_id,
                            "type": "result",
                            "success": True,
                            "result": {"result": event.get("result")},
                            "event": event,  # keep original if caller wants extra info
                        }
                    # legacy mode
                    return {"result": event.get("result")}

            # Case B: normal command or render_template that already included the result
            if full_envelope:
                return data

            # Legacy behavior: return only inner result on success; None otherwise
            if data.get("type") == "result" and data.get("success", False):
                return data.get("result")

            err = data.get("error")
            if err:
                logger.error(f"Error response to id={msg_id}: {err}")
                return None
    
    async def listen(self):
        """Main listener loop."""
        try:
            logger.info(f"Connecting to {self.websocket_url}")
            
            async with websockets.connect(self.websocket_url) as websocket:
                self.websocket = websocket
                
                # Authenticate
                if not await self.authenticate():
                    logger.error("Failed to authenticate")
                    return
                    
                # Initialize light controller with websocket client
                self.light_controller = MultiProtocolController(self)
                self.light_controller.add_controller(Protocol.ZIGBEE)
                self.light_controller.add_controller(Protocol.HOMEASSISTANT)
                logger.info("Initialized multi-protocol light controller")
                    
                # Get initial states to populate mappings and sun data
                logger.info("Loading initial entity states...")
                states = await self.get_states()
                
                if not states:
                    logger.error("Failed to load initial states! No states returned.")
                else:
                    logger.info(f"Successfully loaded {len(states)} entity states")
                    
                    # Count light entities
                    light_count = sum(1 for s in states if s.get("entity_id", "").startswith("light."))
                    logger.info(f"Found {light_count} light entities")
                    
                    # Process states to extract grouped light mappings
                    for state in states:
                        entity_id = state.get("entity_id", "")
                        if entity_id.startswith("light."):
                            attributes = state.get("attributes", {})
                            friendly_name = attributes.get("friendly_name", "")
                            self._update_area_group_mapping(entity_id, friendly_name, attributes)
                    
                    grouped_count = len(self.group_entity_info)
                    if grouped_count > 0:
                        logger.info(f"✓ Found {grouped_count} grouped light entities (Hue rooms or Circadian ZHA groups)")
                    else:
                        logger.warning("⚠ No grouped light entities detected (no Hue rooms or Circadian_ ZHA groups found)")

                # Build light capability cache for color mode detection
                await self.build_light_capability_cache()

                # Get Home Assistant configuration (lat/lng/tz)
                config_loaded = await self.get_config()
                if not config_loaded:
                    logger.warning("⚠ Failed to load Home Assistant configuration - circadian lighting may not work correctly")
                
                # Sync ZHA groups with all areas (includes parity cache refresh)
                await self.sync_zha_groups()

                # Subscribe to all events
                await self.subscribe_events()
                
                # Start periodic light updater
                self.periodic_update_task = asyncio.create_task(self.periodic_light_updater())
                logger.info("Started periodic light updater (runs every 60 seconds)")
                
                # Listen for messages
                logger.info("Listening for events...")
                async for message in websocket:
                    try:
                        msg = json.loads(message)
                        await self.handle_message(msg)
                    except json.JSONDecodeError:
                        logger.error(f"Failed to decode message: {message}")
                    except Exception as e:
                        logger.error(f"Error handling message: {e}")
                        
        except websockets.exceptions.ConnectionClosed:
            logger.warning("WebSocket connection closed")
        except Exception as e:
            logger.error(f"Connection error: {e}")
        finally:
            # Cancel periodic updater if running
            if self.periodic_update_task and not self.periodic_update_task.done():
                self.periodic_update_task.cancel()
                try:
                    await self.periodic_update_task
                except asyncio.CancelledError:
                    pass
            self.websocket = None
            
    async def run(self):
        """Run the client with automatic reconnection."""
        reconnect_interval = 5
        
        while True:
            try:
                await self.listen()
            except KeyboardInterrupt:
                logger.info("Interrupted by user")
                break
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                
            logger.info(f"Reconnecting in {reconnect_interval} seconds...")
            await asyncio.sleep(reconnect_interval)


def main():
    """Main entry point."""
    # Get configuration from environment variables
    host = os.getenv("HA_HOST", "localhost")
    port = int(os.getenv("HA_PORT", "8123"))
    token = os.getenv("HA_TOKEN")
    use_ssl = os.getenv("HA_USE_SSL", "false").lower() == "true"
    
    
    if not token:
        logger.error("HA_TOKEN environment variable is required")
        logger.info("Please set HA_TOKEN with your Home Assistant long-lived access token")
        sys.exit(1)
        
    # Create and run client
    client = HomeAssistantWebSocketClient(host, port, token, use_ssl)
    
    try:
        asyncio.run(client.run())
    except KeyboardInterrupt:
        logger.info("Shutting down...")


if __name__ == "__main__":
    main()
