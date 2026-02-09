#!/usr/bin/env python3
"""Home Assistant WebSocket client - listens for events."""

import asyncio
import json
import logging
import os
import sys
import time
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
    SunTimes,
    get_current_hour,
    get_circadian_lighting,
    calculate_sun_times,
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


def _in_overnight_window(now: float, start: float, end: float) -> bool:
    """Check if now is in an overnight window (e.g. sunset 18:00 to sunrise 6:00)."""
    if start > end:  # wraps midnight (normal case)
        return now >= start or now <= end
    else:  # edge case: doesn't wrap
        return start <= now <= end


def _in_daytime_window(now: float, start: float, end: float) -> bool:
    """Check if now is in a daytime window (e.g. wake 6:00 to bed 22:00)."""
    if start <= end:  # normal case
        return start <= now <= end
    else:  # wraps midnight (edge case, e.g. night owl wake 14:00, bed 2:00)
        return now >= start or now <= end


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
        self._log_periodic = False  # Updated by circadian tick from config
        # State is managed by state.py module (per-area midpoints, bounds, etc.)
        self.cached_states = {}  # Cache of entity states
        self.last_states_update = None  # Timestamp of last states update
        self.area_parity_cache = {}  # Cache of area ZHA parity status
        self.device_registry: Dict[str, Dict[str, Any]] = {}  # device_id -> device info

        # Light capability cache for color mode detection
        self.light_color_modes: Dict[str, Set[str]] = {}  # entity_id -> set of supported color modes
        self.area_lights: Dict[str, List[str]] = {}  # area_id -> list of light entity_ids
        self.hue_lights: Set[str] = set()  # entity_ids of Hue-connected lights (skip 2-step for these)
        self.zha_lights: Set[str] = set()  # entity_ids of ZHA-connected lights (use ZHA groups for these)
        self.area_name_to_id: Dict[str, str] = {}  # area_name -> area_id (for group registration)

        # Pending response futures for async message routing (used when message loop is running)
        self._pending_responses: Dict[int, asyncio.Future] = {}
        self._message_loop_active = False  # Set True once main message loop starts

        # Motion sensor cache for event handling
        # Maps entity_id -> device_id (used to look up motion sensor config)
        self.motion_sensor_ids: Dict[str, str] = {}

        # Contact sensor cache for event handling
        # Maps entity_id -> device_id (used to look up contact sensor config)
        self.contact_sensor_ids: Dict[str, str] = {}

        # Live Design tracking - skip this area in periodic updates
        self.live_design_area: str = None

        # Initialize state module (loads from circadian_state.json)
        state.init()
        state.clear_all_off_enforced()

        # Initialize switches module (loads from switches_config.json)
        switches.init()

        # Hold repeat task for ramping
        self._hold_repeat_task: Optional[asyncio.Task] = None

        # Multi-click detection state for Hue Hub switches
        # Key: (switch_id, button) -> {"count": int, "timer": Optional[asyncio.Task]}
        self._multi_click_state: Dict[tuple, Dict[str, Any]] = {}

        # Last dial level per device (for wrap-around detection)
        # Key: device_ieee -> last level (0-255)
        self._dial_last_level: Dict[str, int] = {}

        # Dial debounce: buffer latest event and process after settling
        # Key: device_ieee -> {"level": int, "timer": asyncio.Task, "config": SwitchConfig}
        self._dial_pending: Dict[str, Dict[str, Any]] = {}

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

    def _get_turn_on_transition(self) -> float:
        """Get the turn-on transition time in seconds.

        Reads from global config, defaults to 0.3 seconds (3 tenths).
        The setting is stored as tenths of seconds in config.

        Returns:
            Transition time in seconds
        """
        try:
            raw_config = glozone.load_config_from_files()
            tenths = raw_config.get("turn_on_transition", 3)
            return tenths / 10.0  # Convert tenths to seconds
        except Exception:
            return 0.3  # Default 0.3 seconds

    def _is_multi_click_enabled(self) -> bool:
        """Check if multi-click detection is enabled for Hue Hub switches."""
        try:
            raw_config = glozone.load_config_from_files()
            return raw_config.get("multi_click_enabled", True)
        except Exception:
            return True

    def _get_multi_click_speed(self) -> float:
        """Get the multi-click detection window in seconds.

        The setting is stored as tenths of seconds in config.
        Default is 0.2 seconds (2 tenths).

        Returns:
            Multi-click window in seconds
        """
        try:
            raw_config = glozone.load_config_from_files()
            tenths = raw_config.get("multi_click_speed", 10)
            return tenths / 10.0  # Convert tenths to seconds
        except Exception:
            return 0.2  # Default 0.2 seconds

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

        # If we have area_name but no area_id, look it up from our mapping
        # This ensures groups registered by name also work when looked up by id
        if area_name and not area_id:
            normalized_name = area_name.lower().replace(' ', '_')
            area_id = self.area_name_to_id.get(normalized_name)
            if not area_id:
                # Try without underscores
                area_id = self.area_name_to_id.get(area_name.lower())

        # Track metadata about the entity
        display_name = area_name or area_id or entity_id
        self.group_entity_info[entity_id] = {
            "type": group_type,
            "area": display_name,
            "area_id": area_id,
            "area_name": area_name,
        }

        # Store normalized mapping for selection logic - area_id is the canonical key
        canonical_key = None
        if area_id:
            canonical_key = self._normalize_area_key(area_id)
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
            # Detect capability suffix for capability-based groups
            # New format: Circadian_<area>_color or Circadian_<area>_ct
            # Old format: Circadian_<area> (maps to zha_group for backwards compat)
            group_type = "zha_group"  # Default for old format
            area_name_lower = area_name.lower()

            if area_name_lower.endswith("_color"):
                group_type = "zha_group_color"
                area_name = area_name[:-6]  # Remove _color suffix
            elif area_name_lower.endswith("_ct"):
                group_type = "zha_group_ct"
                area_name = area_name[:-3]  # Remove _ct suffix

            self._register_area_group_entity(
                entity_id,
                area_name=area_name,
                area_id=None,
                group_type=group_type,
            )
            logger.debug(f"Registered Circadian ZHA group '{entity_id}' ({group_type}) for area '{area_name}'")

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

    def is_all_hue_area(self, area_id: str) -> bool:
        """Check if ALL lights in an area are Hue-connected.

        Hue hub handles color transitions internally, so areas with ONLY Hue lights
        don't need the 2-step turn-on workaround that ZHA lights require.

        If an area has mixed lights (Hue + ZHA), we still do 2-step for all
        since the ZHA lights need it (Hue lights won't be harmed by it).

        Args:
            area_id: The area ID to check

        Returns:
            True if ALL lights in the area are Hue-connected, False if any are non-Hue
        """
        lights = self.area_lights.get(area_id, [])
        if not lights:
            return False
        # All lights must be Hue-connected
        return all(light in self.hue_lights for light in lights)

    # =========================================================================
    # Motion Sensor Event Handling
    # =========================================================================

    def _is_motion_time_active(self, area_config) -> bool:
        """Check if current time falls within the motion sensor's active window."""
        if area_config.active_when == "always":
            return True

        now = get_current_hour()
        offset_hours = area_config.active_offset / 60.0

        if area_config.active_when == "sunset_to_sunrise":
            sun_times = self._get_sun_times()
            window_start = sun_times.sunset - offset_hours
            window_end = sun_times.sunrise + offset_hours
            return _in_overnight_window(now, window_start, window_end)

        elif area_config.active_when == "wake_to_bed":
            config_dict = glozone.get_effective_config_for_area(area_config.area_id)
            wake = config_dict.get("wake_time", 6.0) - offset_hours
            bed = config_dict.get("bed_time", 22.0) + offset_hours
            return _in_daytime_window(now, wake, bed)

        return True

    async def _handle_motion_event(self, entity_id: str, new_state: str, old_state: str) -> None:
        """Handle a motion sensor state change.

        Args:
            entity_id: The motion sensor entity_id
            new_state: New state ("on" = motion detected, "off" = motion cleared)
            old_state: Previous state
        """
        # Get device ID for this entity
        device_id = self.motion_sensor_ids.get(entity_id)
        if not device_id:
            logger.debug(f"[Motion] No device ID mapped for entity {entity_id}")
            return

        # Record last action for UI display (motion detected or cleared)
        if new_state == "on":
            switches.set_last_action(device_id, "motion_detected")
        else:
            switches.set_last_action(device_id, "motion_cleared")

        # Get motion sensor config by device_id
        sensor_config = switches.get_motion_sensor_by_device_id(device_id)
        if not sensor_config:
            logger.debug(f"[Motion] No config found for device {device_id}")
            return

        if sensor_config.inactive:
            logger.debug(f"[Motion] Sensor {sensor_config.name} is inactive, ignoring event")
            return

        if not sensor_config.areas:
            logger.debug(f"[Motion] Sensor {sensor_config.name} has no areas configured")
            return

        logger.info(f"[Motion] {entity_id} -> {new_state} (sensor={sensor_config.name})")

        # Process each area configured for this sensor
        for area_config in sensor_config.areas:
            area_id = area_config.area_id
            mode = area_config.mode
            duration = area_config.duration

            if mode == "disabled":
                logger.debug(f"[Motion] Mode disabled for area {area_id}")
                continue

            if not self._is_motion_time_active(area_config):
                logger.debug(f"[Motion] Outside active window for area {area_id} (when={area_config.active_when})")
                continue

            logger.debug(f"[Motion] Area {area_id}: mode={mode}, boost={area_config.boost_enabled}, duration={duration}")

            if new_state == "on":
                # Cancel any active warning first (restores brightness)
                await self.primitives.cancel_motion_warning(area_id, source="motion_sensor")

                # Get boost params if enabled (passed to motion_on_off for combined turn-on)
                boost_brightness = area_config.boost_brightness if area_config.boost_enabled else None
                boost_duration = duration if area_config.boost_enabled else None

                # Motion detected - handle mode (power behavior)
                # Boost is passed through to avoid intermediate brightness flash
                if mode == "on_off":
                    await self.primitives.motion_on_off(
                        area_id, duration, source="motion_sensor",
                        boost_brightness=boost_brightness, boost_duration=boost_duration
                    )
                elif mode == "on_only":
                    await self.primitives.motion_on_only(
                        area_id, source="motion_sensor",
                        boost_brightness=boost_brightness, boost_duration=boost_duration
                    )

            # Note: For on_off, the timer is managed via motion_expires_at state
            # When motion clears, we don't need to do anything - the timer continues
            # If motion is detected again, motion_on_off extends the timer

    async def _handle_zha_motion_event(self, sensor_config, command: str, args, device_id: str) -> None:
        """Handle a ZHA motion sensor event.

        Some ZHA motion sensors fire ZHA events instead of state_changed events.
        Common commands:
        - on_with_timed_off: Motion detected (args[1] is duration in tenths of seconds)
        - attribute_updated with on_off=1: Motion detected
        - attribute_updated with on_off=0: Motion cleared

        Args:
            sensor_config: The MotionSensorConfig for this sensor
            command: The ZHA command name
            args: Command arguments
            device_id: The HA device_id
        """
        # Check if sensor is inactive
        if sensor_config.inactive:
            logger.debug(f"[ZHA Motion] Sensor {sensor_config.name} is inactive, ignoring event")
            return

        # Determine if this is motion detected or cleared
        is_motion_detected = False

        if command == "on_with_timed_off":
            is_motion_detected = True
        elif command == "attribute_updated":
            # Check if this is on_off attribute changing
            if isinstance(args, dict):
                attr_name = args.get("attribute_name")
                attr_value = args.get("attribute_value") or args.get("value")
                if attr_name == "on_off":
                    is_motion_detected = (attr_value == 1 or attr_value == True)

        if not is_motion_detected:
            # Motion cleared - for motion sensors we just let the timer handle it
            logger.debug(f"[ZHA Motion] {sensor_config.name}: motion cleared (command={command})")
            switches.set_last_action(device_id, "motion_cleared")
            return

        # Motion detected
        logger.info(f"[ZHA Motion] {sensor_config.name}: motion detected (command={command})")
        switches.set_last_action(device_id, "motion_detected")

        if not sensor_config.areas:
            logger.debug(f"[ZHA Motion] Sensor {sensor_config.name} has no areas configured")
            return

        # Process each area configured for this sensor
        for area_config in sensor_config.areas:
            area_id = area_config.area_id
            mode = area_config.mode
            duration = area_config.duration

            if mode == "disabled":
                logger.debug(f"[ZHA Motion] Mode disabled for area {area_id}")
                continue

            if not self._is_motion_time_active(area_config):
                logger.debug(f"[ZHA Motion] Outside active window for area {area_id} (when={area_config.active_when})")
                continue

            logger.debug(f"[ZHA Motion] Area {area_id}: mode={mode}, boost={area_config.boost_enabled}, duration={duration}")

            # Cancel any active warning first (restores brightness)
            await self.primitives.cancel_motion_warning(area_id, source="motion_sensor")

            # Get boost params if enabled (passed to motion_on_off for combined turn-on)
            boost_brightness = area_config.boost_brightness if area_config.boost_enabled else None
            boost_duration = duration if area_config.boost_enabled else None

            # Handle mode (power behavior)
            # Boost is passed through to avoid intermediate brightness flash
            if mode == "on_off":
                await self.primitives.motion_on_off(
                    area_id, duration, source="motion_sensor",
                    boost_brightness=boost_brightness, boost_duration=boost_duration
                )
            elif mode == "on_only":
                await self.primitives.motion_on_only(
                    area_id, source="motion_sensor",
                    boost_brightness=boost_brightness, boost_duration=boost_duration
                )

    async def _handle_contact_event(self, entity_id: str, new_state: str, old_state: str) -> None:
        """Handle a contact sensor state change (door/window open/close).

        Contact sensors differ from motion sensors:
        - Open ("on") = turn on (like motion detected)
        - Close ("off") = for on_off/boost, trigger circadian_off; for on_only, ignore

        Args:
            entity_id: The contact sensor entity_id
            new_state: New state ("on" = open, "off" = closed)
            old_state: Previous state
        """
        # Get device ID for this entity
        device_id = self.contact_sensor_ids.get(entity_id)
        if not device_id:
            logger.info(f"[Contact] No device ID mapped for entity {entity_id}")
            return

        logger.info(f"[Contact] Event: {entity_id} -> {new_state} (device: {device_id})")

        # Record last action for UI display
        if new_state == "on":
            switches.set_last_action(device_id, "contact_opened")
        else:
            switches.set_last_action(device_id, "contact_closed")

        # Get contact sensor config by device_id
        sensor_config = switches.get_contact_sensor_by_device_id(device_id)
        if not sensor_config:
            logger.info(f"[Contact] No config found for device {device_id} - configure in Controls page")
            return

        if sensor_config.inactive:
            logger.info(f"[Contact] Sensor {sensor_config.name} is inactive, ignoring event")
            return

        if not sensor_config.areas:
            logger.info(f"[Contact] Sensor {sensor_config.name} has no areas configured")
            return

        logger.info(f"[Contact] {entity_id} -> {new_state} (sensor={sensor_config.name})")

        # Process each area configured for this sensor
        for area_config in sensor_config.areas:
            area_id = area_config.area_id
            mode = area_config.mode
            duration = area_config.duration

            if mode == "disabled":
                logger.debug(f"[Contact] Mode disabled for area {area_id}")
                continue

            logger.debug(f"[Contact] Area {area_id}: mode={mode}, boost={area_config.boost_enabled}, duration={duration}")

            if new_state == "on":
                # Cancel any active warning first (restores brightness)
                await self.primitives.cancel_motion_warning(area_id, source="contact_sensor")

                # Get boost params if enabled (passed to motion_on_off for combined turn-on)
                boost_brightness = area_config.boost_brightness if area_config.boost_enabled else None
                boost_duration = duration if area_config.boost_enabled else None

                # Contact opened - handle mode (power behavior)
                # Boost is passed through to avoid intermediate brightness flash
                if mode == "on_off":
                    await self.primitives.motion_on_off(
                        area_id, duration, source="contact_sensor",
                        boost_brightness=boost_brightness, boost_duration=boost_duration
                    )
                elif mode == "on_only":
                    await self.primitives.motion_on_only(
                        area_id, source="contact_sensor",
                        boost_brightness=boost_brightness, boost_duration=boost_duration
                    )

            else:
                # Contact closed - handle close behaviors
                # Clear any warning state first
                state.clear_motion_warning(area_id)

                # End boost first (if enabled)
                boost_turned_off = False
                if area_config.boost_enabled:
                    boost_turned_off = await self.primitives.end_boost(area_id, source="contact_sensor")
                    logger.info(f"[Contact] Closed: ended boost for area {area_id} (turned_off={boost_turned_off})")

                # Then handle mode-based off behavior
                if mode == "on_off":
                    if boost_turned_off:
                        # end_boost already turned off lights with transition - just
                        # clean up motion timer to avoid a duplicate turn_off command
                        # which can interrupt the transition on some ZigBee lights
                        state.clear_motion_expires(area_id)
                        logger.info(f"[contact_sensor] Contact closed: boost already turned off area {area_id}, cleared motion timer")
                    else:
                        # Turn off lights and disable circadian
                        await self.primitives.contact_off(area_id, source="contact_sensor")
                # on_only: ignore close event (lights stay on until manually turned off)

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

        # Check if this is a ZHA motion sensor (they fire ZHA events, not state_changed)
        if device_id:
            motion_config = switches.get_motion_sensor_by_device_id(device_id)
            if motion_config:
                await self._handle_zha_motion_event(motion_config, command, args, device_id)
                return

        # Check if this switch is configured
        switch_config = switches.get_switch(device_ieee)

        if not switch_config:
            # Unconfigured switch - add to pending list
            await self._handle_unconfigured_switch(device_ieee, event_data)
            return

        if switch_config.inactive:
            logger.info(f"Switch {switch_config.name} is inactive/paused, ignoring event")
            switches.set_last_action(device_ieee, f"{command}")
            return

        # Hue dimmers send duplicate events on multiple clusters:
        # - Cluster 5 (Scenes) for OFF button
        # - Cluster 6 (On/Off) for ON/OFF buttons
        # - Cluster 8 (Level Control) for UP/DOWN buttons
        # - Cluster 64512 (Hue proprietary) for ALL buttons with detailed info
        # We only want to handle cluster 64512 to avoid double-firing
        if switch_config.type in ("hue_dimmer", "hue_4button_v1", "hue_4button_v2", "hue_smart_button") and cluster_id in (5, 6, 8):
            logger.debug(f"Ignoring cluster {cluster_id} event for Hue dimmer (will use cluster 64512)")
            return

        # Handle dial/rotary devices (e.g., Lutron Aurora) — rotation sends
        # move_to_level_with_on_off with a 0-255 level value
        type_info = switches.get_switch_type(switch_config.type)
        if type_info and type_info.get("dial") and command in ("move_to_level_with_on_off", "move_to_level"):
            level = args[0] if isinstance(args, list) and len(args) > 0 else 0

            # Detect wrap-around: if level jumps by more than 128, the dial
            # overflowed past 0 or 255. Clamp to the nearest extreme.
            # Store raw level (not clamped) so wrap detection only fires once.
            raw_level = level
            prev_level = self._dial_last_level.get(device_ieee)
            if prev_level is not None:
                delta = level - prev_level
                if delta > 128:
                    level = 0
                elif delta < -128:
                    level = 255
            self._dial_last_level[device_ieee] = raw_level

            # Button press toggles between 0 and 255 — execute immediately
            if level == 0 or level == 255:
                # Cancel any pending dial rotation
                pending = self._dial_pending.pop(device_ieee, None)
                if pending and pending.get("timer"):
                    pending["timer"].cancel()
                button_event = "dial_press"
                switches.set_last_action(device_ieee, f"dial_press ({level})")
                action = switch_config.get_button_action(button_event)
                if action:
                    await self._execute_switch_action(device_ieee, action)
                return

            # Dial rotation — debounce: buffer latest level, process after 200ms
            # This filters out-of-order ZigBee events during fast spinning
            pending = self._dial_pending.get(device_ieee)
            if pending and pending.get("timer"):
                pending["timer"].cancel()
            self._dial_pending[device_ieee] = {
                "level": level,
                "config": switch_config,
                "timer": asyncio.ensure_future(self._dial_debounce(device_ieee)),
            }
            return

        # Map the ZHA command to our button event format (non-dial switches)
        button_event = self._map_zha_command_to_button_event(command, args, switch_config.type)

        # Record last action for UI display (even if unmapped, show raw command)
        display_event = button_event if button_event else f"{command}"
        switches.set_last_action(device_ieee, display_event)
        logger.info(f"[LastAction] Set for {device_ieee}: {display_event}")

        if not button_event:
            logger.debug(f"Unmapped ZHA command: {command}")
            return

        # Get the action for this button event
        action = switch_config.get_button_action(button_event)

        # Handle release events BEFORE the action-is-None check,
        # because release events (e.g. down_long_release) often map to None
        # but still need to stop active hold repeat loops.
        if "_long_release" in button_event or "_release" in button_event:
            was_holding = switches.is_holding(device_ieee)
            await self._stop_hold_repeat(device_ieee)

            if was_holding:
                if action:
                    await self._execute_switch_action(device_ieee, action)
            elif "_short_release" in button_event:
                if action:
                    await self._execute_switch_action(device_ieee, action)
            return

        if action is None:
            logger.debug(f"No action mapped for {button_event}")
            return

        logger.info(f"Switch {switch_config.name}: {button_event} -> {action}")

        # Handle hold start/stop
        if "_hold" in button_event:
            # Hold started (or Hue bridge repeat event)
            if switches.should_repeat_on_hold(device_ieee, button_event):
                if switches.is_holding(device_ieee):
                    # Already repeating — ignore Hue bridge repeat events
                    # so our own timer controls the pace
                    logger.debug(f"Ignoring duplicate hold event for {device_ieee} (already repeating)")
                    return
                await self._start_hold_repeat(device_ieee, action)
            else:
                # Single action on hold (non-repeating)
                await self._execute_switch_action(device_ieee, action)

        # Release events are handled above (before action-is-None check)

        else:
            # Other events (press, double_press, triple_press, quadruple_press, etc.)
            # Skip single _press events if we're waiting for release
            if "_press" in button_event and not any(x in button_event for x in ["_double", "_triple", "_quadruple", "_quintuple"]):
                # Single press - we'll handle on release to avoid double-firing
                pass
            else:
                await self._execute_switch_action(device_ieee, action)

    async def _handle_unconfigured_switch(self, device_ieee: str, event_data: Dict[str, Any]) -> None:
        """Handle an event from an unconfigured switch.

        Just logs the event - controls are now fetched directly from HA.
        Also records the last action for UI display.
        """
        command = event_data.get("command", "unknown")
        args = event_data.get("args", {})

        # Try to create a readable button event
        # Format raw command and args for display
        if isinstance(args, dict) and args:
            # e.g., "button_1_short_release" from press_type
            press_type = args.get("press_type", "")
            button = args.get("button", "")
            if press_type:
                button_event = press_type
            elif button:
                button_event = f"button_{button}_{command}"
            else:
                button_event = command
        elif isinstance(args, list) and args:
            button_event = f"{command}({', '.join(str(a) for a in args)})"
        else:
            button_event = command

        # Record for UI display
        switches.set_last_action(device_ieee, button_event)
        logger.debug(f"Event from unconfigured switch: {device_ieee} - {button_event}")

    # =========================================================================
    # Hue Event Handling (for Hue hub devices)
    # =========================================================================

    async def _handle_hue_event(self, event_data: Dict[str, Any]) -> None:
        """Handle a Hue event (button press from Hue hub devices).

        Hue events have a different format than ZHA:
        - device_id: HA device ID (not IEEE address)
        - type: Event type (initial_press, short_release, long_release, repeat)
        - subtype: Button number (1=ON, 2=UP, 3=DOWN, 4=OFF for Hue dimmer)

        Args:
            event_data: Event data from hue_event
        """
        device_id = event_data.get("device_id")
        event_type = event_data.get("type")  # e.g., "short_release", "initial_press"
        subtype = event_data.get("subtype")  # Button number

        if not device_id or not event_type or subtype is None:
            return

        logger.debug(f"Hue event: device={device_id}, type={event_type}, subtype={subtype}")

        # Look up switch by device_id
        switch_config = switches.get_switch_by_device_id(device_id)

        if not switch_config:
            # Unconfigured switch - log and record last action
            button_event = f"button_{subtype}_{event_type}"
            switches.set_last_action(device_id, button_event)
            logger.debug(f"Event from unconfigured Hue switch: {device_id} - {button_event}")
            return

        if switch_config.inactive:
            logger.info(f"Switch {switch_config.name} is inactive/paused, ignoring event")
            button_event = f"button_{subtype}_{event_type}"
            switches.set_last_action(device_id, button_event)
            return

        # Map Hue event to our button event format
        button_event = self._map_hue_event_to_button_event(event_type, subtype)

        # Record last action for UI display
        display_event = button_event if button_event else f"button_{subtype}_{event_type}"
        switches.set_last_action(switch_config.id, display_event)
        logger.info(f"[LastAction] Set for {switch_config.id}: {display_event}")

        if not button_event:
            logger.debug(f"Unmapped Hue event: type={event_type}, subtype={subtype}")
            return

        # Get the action for this button event
        action = switch_config.get_button_action(button_event)

        # Handle release events BEFORE the action-is-None check,
        # because release events often map to None but still need to stop hold loops.
        if "_long_release" in button_event:
            was_holding = switches.is_holding(switch_config.id)
            await self._stop_hold_repeat(switch_config.id)
            if action:
                await self._execute_switch_action(switch_config.id, action)
            return

        if action is None:
            logger.debug(f"No action mapped for {button_event}")
            return

        logger.info(f"Switch {switch_config.name}: {button_event} -> {action}")

        # Handle hold start/stop
        if "_hold" in button_event or event_type == "initial_press":
            # For initial_press, we treat it as hold start if there's a hold action
            if event_type == "initial_press":
                # Check if there's a hold action for this button
                hold_event = self._map_hue_event_to_button_event("repeat", subtype)
                if hold_event and switch_config.get_button_action(hold_event):
                    # There's a hold action - don't execute on initial press, wait for release or repeat
                    return

            # Hold started (or Hue bridge repeat event)
            if switches.should_repeat_on_hold(switch_config.id, button_event):
                if switches.is_holding(switch_config.id):
                    # Already repeating — ignore Hue bridge repeat events
                    logger.debug(f"Ignoring duplicate hold event for {switch_config.id} (already repeating)")
                    return
                await self._start_hold_repeat(switch_config.id, action)
            else:
                # Single action on hold (non-repeating)
                await self._execute_switch_action(switch_config.id, action)

        elif "_short_release" in button_event or "_release" in button_event:
            # Short release - check if ending a hold or a normal click
            if switches.is_holding(switch_config.id):
                await self._stop_hold_repeat(switch_config.id)
                # Execute the release action if any
                if action:
                    await self._execute_switch_action(switch_config.id, action)
            elif self._is_multi_click_enabled():
                # Multi-click detection enabled - track clicks and wait
                button_map = {1: "on", 2: "up", 3: "down", 4: "off"}
                button = button_map.get(subtype)
                if button:
                    state_key = (switch_config.id, button)

                    # Cancel existing timer if any
                    existing_state = self._multi_click_state.get(state_key)
                    if existing_state and existing_state.get("timer"):
                        existing_state["timer"].cancel()

                    # Get or create state
                    if state_key in self._multi_click_state:
                        self._multi_click_state[state_key]["count"] += 1
                    else:
                        self._multi_click_state[state_key] = {"count": 1, "timer": None}

                    click_count = self._multi_click_state[state_key]["count"]
                    logger.debug(f"[MultiClick] {switch_config.name} {button}: click {click_count}")

                    # Start new timer
                    delay = self._get_multi_click_speed()
                    timer = asyncio.create_task(
                        self._multi_click_timer_task(switch_config.id, switch_config, button, subtype, delay)
                    )
                    self._multi_click_state[state_key]["timer"] = timer
                else:
                    # Unknown button, execute immediately
                    await self._execute_switch_action(switch_config.id, action)
            else:
                # Multi-click disabled - execute immediately
                await self._execute_switch_action(switch_config.id, action)

        else:
            # Other events
            await self._execute_switch_action(switch_config.id, action)

    def _map_hue_event_to_button_event(
        self, event_type: str, subtype: int
    ) -> Optional[str]:
        """Map a Hue event to our button event format.

        Hue dimmer button subtypes:
        - 1: ON button
        - 2: UP button (brightness up)
        - 3: DOWN button (brightness down)
        - 4: OFF button (Hue button)

        Hue event types:
        - initial_press: Button first pressed
        - short_release: Quick release (short press)
        - long_release: Release after hold
        - repeat: Button held (fires repeatedly)

        Returns button event in format: {button}_{action_type}
        """
        # Map subtype to button name
        button_map = {
            1: "on",
            2: "up",
            3: "down",
            4: "off",
        }

        button = button_map.get(subtype)
        if not button:
            return None

        # Map event type to action type
        type_map = {
            "initial_press": "press",
            "short_release": "short_release",
            "long_release": "long_release",
            "repeat": "hold",
        }

        action_type = type_map.get(event_type)
        if not action_type:
            return None

        return f"{button}_{action_type}"

    def _get_button_event_for_click_count(self, button: str, click_count: int) -> str:
        """Map a click count to the appropriate button event.

        Args:
            button: Button name (on, up, down, off)
            click_count: Number of clicks (1, 2, 3, 4, 5)

        Returns:
            Button event string (e.g., "on_short_release", "on_double_press")
        """
        click_map = {
            1: "short_release",
            2: "double_press",
            3: "triple_press",
            4: "quadruple_press",
            5: "quintuple_press",
        }
        action_type = click_map.get(click_count, "short_release")
        return f"{button}_{action_type}"

    async def _handle_multi_click_timer(
        self, switch_id: str, switch_config: Any, button: str, subtype: int
    ) -> None:
        """Handle the multi-click timer expiration.

        Called when the multi-click window expires. Determines the final
        click count and executes the appropriate action.

        Args:
            switch_id: Switch identifier
            switch_config: Switch configuration object
            button: Button name (on, up, down, off)
            subtype: Button number (for display)
        """
        state_key = (switch_id, button)
        state = self._multi_click_state.get(state_key)

        if not state:
            return

        click_count = state.get("count", 1)

        # Clean up state
        del self._multi_click_state[state_key]

        # Map click count to button event
        button_event = self._get_button_event_for_click_count(button, click_count)

        # Update last action for UI display
        switches.set_last_action(switch_id, button_event)
        logger.info(f"[MultiClick] {click_count}x click detected: {button_event}")

        # Get the action for this button event
        action = switch_config.get_button_action(button_event)

        if action is None:
            # Fall back to single click if multi-click action not mapped
            if click_count > 1:
                fallback_event = f"{button}_short_release"
                action = switch_config.get_button_action(fallback_event)
                if action:
                    logger.debug(f"No action for {button_event}, falling back to {fallback_event}")
                    button_event = fallback_event

        if action is None:
            logger.debug(f"No action mapped for {button_event}")
            return

        logger.info(f"Switch {switch_config.name}: {button_event} -> {action}")
        await self._execute_switch_action(switch_id, action)

    async def _multi_click_timer_task(
        self, switch_id: str, switch_config: Any, button: str, subtype: int, delay: float
    ) -> None:
        """Timer task that waits for multi-click window then processes clicks.

        Args:
            switch_id: Switch identifier
            switch_config: Switch configuration object
            button: Button name (on, up, down, off)
            subtype: Button number (for display)
            delay: Time to wait in seconds
        """
        try:
            await asyncio.sleep(delay)
            await self._handle_multi_click_timer(switch_id, switch_config, button, subtype)
        except asyncio.CancelledError:
            # Timer was cancelled (another click came in)
            pass

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

    async def _execute_switch_action(self, switch_id: str, action) -> None:
        """Execute a switch action.

        Args:
            switch_id: The switch IEEE address
            action: The action to execute - string or {action, when_off} dict
        """
        # Record activity for scope timeout
        switches.record_activity(switch_id)

        # Get areas for current scope
        areas = switches.get_current_areas(switch_id)
        if not areas:
            logger.warning(f"No areas configured for switch {switch_id}")
            return

        # Parse action - can be string or {action, when_off} object
        main_action = action
        when_off_action = None
        if isinstance(action, dict):
            main_action = action.get("action")
            when_off_action = action.get("when_off")

        logger.info(f"Executing {main_action} on areas: {areas}" + (f" (when_off: {when_off_action})" if when_off_action else ""))

        # Helper to execute when_off action (or do nothing if not set)
        async def execute_when_off():
            if when_off_action:
                logger.info(f"[switch] Lights off, executing when_off action: {when_off_action}")
                await self._execute_switch_action(switch_id, when_off_action)
            else:
                logger.info(f"[switch] Lights off, no when_off action configured")

        # Execute the action
        if main_action == "cycle_scope":
            await self._execute_cycle_scope(switch_id)

        elif main_action == "circadian_on":
            for area in areas:
                await self.primitives.lights_on(area, "switch")

        elif main_action == "circadian_off":
            for area in areas:
                await self.primitives.circadian_off(area, "switch")

        elif main_action in ("toggle", "circadian_toggle"):
            await self.primitives.lights_toggle_multiple(areas, "switch")

        elif main_action == "step_up":
            # Step up only if lights are on AND in circadian mode
            any_on_circadian = any(state.is_circadian(area) and state.get_is_on(area) for area in areas)
            if any_on_circadian:
                await asyncio.gather(*[self.primitives.step_up(area, "switch") for area in areas])
            else:
                await execute_when_off()

        elif main_action == "step_down":
            # Step down only if lights are on AND in circadian mode
            any_on_circadian = any(state.is_circadian(area) and state.get_is_on(area) for area in areas)
            if any_on_circadian:
                await asyncio.gather(*[self.primitives.step_down(area, "switch") for area in areas])
            else:
                await execute_when_off()

        elif main_action == "bright_up":
            # Bright up only if lights are on AND in circadian mode
            any_on_circadian = any(state.is_circadian(area) and state.get_is_on(area) for area in areas)
            if any_on_circadian:
                await asyncio.gather(*[self.primitives.bright_up(area, "switch") for area in areas])
            else:
                await execute_when_off()

        elif main_action == "bright_down":
            # Bright down only if lights are on AND in circadian mode
            any_on_circadian = any(state.is_circadian(area) and state.get_is_on(area) for area in areas)
            if any_on_circadian:
                await asyncio.gather(*[self.primitives.bright_down(area, "switch") for area in areas])
            else:
                await execute_when_off()

        elif main_action == "color_up":
            # Color up only if lights are on AND in circadian mode
            any_on_circadian = any(state.is_circadian(area) and state.get_is_on(area) for area in areas)
            if any_on_circadian:
                await asyncio.gather(*[self.primitives.color_up(area, "switch") for area in areas])
            else:
                await execute_when_off()

        elif main_action == "color_down":
            # Color down only if lights are on AND in circadian mode
            any_on_circadian = any(state.is_circadian(area) and state.get_is_on(area) for area in areas)
            if any_on_circadian:
                await asyncio.gather(*[self.primitives.color_down(area, "switch") for area in areas])
            else:
                await execute_when_off()

        elif main_action == "glo_reset":
            # Reset area to Daily Rhythm
            await asyncio.gather(*[self.primitives.glo_reset(area, "switch") for area in areas])

        elif main_action == "freeze_toggle":
            await asyncio.gather(*[self.primitives.freeze_toggle(area, "switch") for area in areas])

        elif main_action == "glo_up":
            # Push area settings to GloZone (atomic - zone only, not to other areas)
            await asyncio.gather(*[self.primitives.glo_up(area, "switch") for area in areas])

        elif main_action == "glo_down":
            # Pull GloZone settings to this area
            await asyncio.gather(*[self.primitives.glo_down(area, "switch") for area in areas])

        elif main_action == "glozone_reset":
            # Reset GloZone to Daily Rhythm (zone state only, not propagated)
            # Get unique zones from areas
            glozone.reload()
            zones_done = set()
            for area in areas:
                zone_name = glozone.get_zone_for_area(area)
                if zone_name and zone_name not in zones_done:
                    await self.primitives.glozone_reset(zone_name, "switch")
                    zones_done.add(zone_name)

        elif main_action == "glozone_down":
            # Push GloZone settings to all areas in zone
            glozone.reload()
            zones_done = set()
            for area in areas:
                zone_name = glozone.get_zone_for_area(area)
                if zone_name and zone_name not in zones_done:
                    await self.primitives.glozone_down(zone_name, "switch")
                    zones_done.add(zone_name)

        elif main_action == "full_send":
            # Compound: glo_up + glozone_down (push area to zone, then zone to all)
            for area in areas:
                await self.primitives.full_send(area, "switch")

        elif main_action == "glozone_reset_full":
            # Compound: glozone_reset + glozone_down (reset zone, then push to all)
            glozone.reload()
            zones_done = set()
            for area in areas:
                zone_name = glozone.get_zone_for_area(area)
                if zone_name and zone_name not in zones_done:
                    await self.primitives.glozone_reset(zone_name, "switch")
                    await self.primitives.glozone_down(zone_name, "switch")
                    zones_done.add(zone_name)

        elif main_action == "set_britelite":
            # Freeze at descend_start (max brightness/coolest color on curve)
            # Uses primitives.set() which keeps circadian enabled and calculates from curve
            logger.info(f"[switch] set_britelite for areas: {areas}")
            for area in areas:
                await self.primitives.set(area, "switch", preset="britelite", is_on=True)

        elif main_action == "set_nitelite":
            # Freeze at ascend_start (min brightness/warmest color on curve)
            # Uses primitives.set() which keeps circadian enabled and calculates from curve
            logger.info(f"[switch] set_nitelite for areas: {areas}")
            for area in areas:
                await self.primitives.set(area, "switch", preset="nitelite", is_on=True)

        elif main_action == "toggle_wake_bed":
            # Set midpoint to current time (~50% values), stays unfrozen
            for area in areas:
                await self.primitives.set(area, "switch", preset="wake")

        elif main_action and main_action.startswith("set_"):
            # Check if it's a moment action (set_sleep, set_exit, etc.)
            moment_id = main_action[4:]  # Remove "set_" prefix
            moments = self._get_moments()
            if moment_id in moments:
                logger.info(f"[switch] Applying moment '{moment_id}'")
                # Moments apply to all areas per their config, not switch areas
                await self.primitives.set(None, "switch", preset=moment_id)
            else:
                logger.warning(f"Unknown set action: {main_action}")

        else:
            logger.warning(f"Unknown action: {main_action}")

    def _get_moments(self) -> dict:
        """Get all moments from config.

        Returns:
            Dict of moment_id -> moment config
        """
        try:
            raw_config = glozone.load_config_from_files()
            return raw_config.get("moments", {})
        except Exception:
            return {}

    def _is_reach_learn_mode(self) -> bool:
        """Check if reach learn mode is enabled (single indicator light feedback)."""
        try:
            raw_config = glozone.load_config_from_files()
            return raw_config.get("reach_learn_mode", True)
        except Exception:
            return True

    def _get_motion_warning_blink_threshold(self) -> int:
        """Get the motion warning blink threshold as brightness 0-255."""
        try:
            raw_config = glozone.load_config_from_files()
            pct = raw_config.get("motion_warning_blink_threshold", 15)
            return int(pct / 100.0 * 255)
        except Exception:
            return int(0.15 * 255)

    def _apply_ct_brightness_compensation(self, brightness: int, color_temp: int) -> int:
        """Apply brightness compensation for warm color temperatures.

        Hue bulbs transition from efficient warm-white LEDs to less efficient RGB LEDs
        at very warm color temperatures, causing a perceived brightness drop. This
        compensates by boosting brightness in the "handover zone".

        Args:
            brightness: Original brightness percentage (0-100)
            color_temp: Color temperature in Kelvin

        Returns:
            Compensated brightness percentage (0-100, clamped)
        """
        try:
            raw_config = glozone.load_config_from_files()
            enabled = raw_config.get("ct_comp_enabled", False)
            if not enabled:
                return brightness

            # Get compensation parameters
            handover_begin = raw_config.get("ct_comp_begin", 1650)  # Warmer end (lower K)
            handover_end = raw_config.get("ct_comp_end", 2250)      # Cooler end (higher K)
            max_factor = raw_config.get("ct_comp_factor", 1.4)

            # No compensation above handover zone
            if color_temp >= handover_end:
                return brightness

            # Full compensation below handover zone
            if color_temp <= handover_begin:
                compensated = brightness * max_factor
                return min(100, int(round(compensated)))

            # Linear interpolation within handover zone
            # At handover_end: factor = 1.0
            # At handover_begin: factor = max_factor
            position = (handover_end - color_temp) / (handover_end - handover_begin)
            factor = 1.0 + position * (max_factor - 1.0)
            compensated = brightness * factor
            return min(100, int(round(compensated)))

        except Exception as e:
            logger.warning(f"CT compensation error: {e}")
            return brightness

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
            scope_number = 1
            areas = switch_config.get_areas_for_scope(0)
        else:
            new_scope = switches.cycle_scope(switch_id)
            scope_number = new_scope + 1  # 1-indexed
            areas = switch_config.get_areas_for_scope(new_scope)

        # Choose feedback mode
        # Learn mode ON = all-lights (see which areas are in reach)
        # Learn mode OFF = single indicator light (subtle, once you know your reaches)
        learn_mode = self._is_reach_learn_mode()
        indicator = switch_config.indicator_light

        if not learn_mode and indicator:
            await self._show_reach_single_light_feedback(indicator, scope_number)
        else:
            await self._show_reach_all_lights_feedback(areas)

    async def _show_reach_all_lights_feedback(self, areas: List[str]) -> None:
        """Show visual feedback for reach change with subtle dip effect.

        Lights that are ON:
          - Above blink threshold: dip by reach_dip_percent of current brightness
          - At or below threshold: fade to off then restore (need full range for visibility)
        Lights that are OFF: briefly pulse on at blink threshold then off.

        Args:
            areas: Areas to fade
        """
        if not areas:
            return

        turn_off_transition = self.primitives._get_turn_off_transition()
        turn_on_transition = self.primitives._get_turn_on_transition()
        blink_threshold = self._get_motion_warning_blink_threshold()
        reach_dip_percent = self.primitives._get_reach_dip_percent() / 100.0

        # Pre-calculate restore values for each area BEFORE fading
        restore_data = {}
        for area in areas:
            was_on = state.is_circadian(area) and state.get_is_on(area)

            if was_on and state.is_circadian(area):
                area_state = AreaState.from_dict(state.get_area(area))
                config_dict = glozone.get_effective_config_for_area(area)
                config = Config.from_dict(config_dict)
                hour = area_state.frozen_at if area_state.frozen_at is not None else get_current_hour()
                result = CircadianLight.calculate_lighting(hour, config, area_state)
                brightness = int(result.brightness * 2.55)
                restore_data[area] = {
                    "was_on": True,
                    "brightness": brightness,
                    "xy": result.xy,
                    "dip_to_off": brightness <= blink_threshold,
                }
            else:
                restore_data[area] = {"was_on": was_on}

        # Phase 1: Dip ON lights, pulse OFF lights
        # - ON above threshold: dip by reach_dip_percent of current brightness
        # - ON at/below threshold: fade to off
        # - OFF: pulse on at blink threshold
        phase1_tasks = []
        for area in areas:
            data = restore_data[area]
            if data.get("was_on"):
                if data.get("dip_to_off"):
                    # Low brightness - fade to off for visibility
                    phase1_tasks.append(self.call_service(
                        "light", "turn_off",
                        {"transition": turn_off_transition},
                        target={"area_id": area}
                    ))
                else:
                    # Above threshold - dip by configured percentage of current
                    dip_brightness = int(data["brightness"] * (1.0 - reach_dip_percent))
                    phase1_tasks.append(self.call_service(
                        "light", "turn_on",
                        {"brightness": dip_brightness, "transition": turn_off_transition},
                        target={"area_id": area}
                    ))
            else:
                phase1_tasks.append(self.call_service(
                    "light", "turn_on",
                    {"brightness": blink_threshold, "transition": turn_on_transition},
                    target={"area_id": area}
                ))
        await asyncio.gather(*phase1_tasks)

        # Wait for transitions to complete
        await asyncio.sleep(max(turn_off_transition, turn_on_transition) + 0.1)

        # Phase 2: Restore all lights
        phase2_tasks = []
        for area, data in restore_data.items():
            if data.get("was_on"):
                service_data = {"transition": turn_on_transition}
                if data.get("xy"):
                    service_data["xy_color"] = data["xy"]
                    service_data["brightness"] = data["brightness"]
                phase2_tasks.append(self.call_service(
                    "light", "turn_on",
                    service_data,
                    target={"area_id": area}
                ))
            else:
                phase2_tasks.append(self.call_service(
                    "light", "turn_off",
                    {"transition": turn_off_transition},
                    target={"area_id": area}
                ))
        await asyncio.gather(*phase2_tasks)

    async def _show_reach_single_light_feedback(self, indicator_light: str, scope_number: int) -> None:
        """Flash a single indicator light to show which reach is active.

        Flashes 1x for reach 1, 2x for reach 2, 3x for reach 3.

        Args:
            indicator_light: Entity ID of the indicator light
            scope_number: Which scope (1, 2, or 3) — determines number of flashes
        """
        # Get current state of indicator light
        light_state = self.cached_states.get(indicator_light, {})
        was_on = light_state.get("state") == "on"
        attrs = light_state.get("attributes", {}) if was_on else {}
        original_brightness = attrs.get("brightness", 128)
        original_xy = attrs.get("xy_color")
        original_color_temp = attrs.get("color_temp")

        blink_brightness = original_brightness if was_on else self._get_motion_warning_blink_threshold()
        target = {"entity_id": indicator_light}

        # Flash sequence
        for i in range(scope_number):
            # Turn off
            await self.call_service("light", "turn_off", {"transition": 0}, target=target)
            await asyncio.sleep(0.3)
            # Turn on at flash brightness
            await self.call_service(
                "light", "turn_on",
                {"brightness": blink_brightness, "transition": 0},
                target=target
            )
            await asyncio.sleep(0.3)

        # Restore original state
        if not was_on:
            await self.call_service("light", "turn_off", {"transition": 0}, target=target)
        else:
            restore_data = {"brightness": original_brightness, "transition": 0}
            if original_xy:
                restore_data["xy_color"] = original_xy
            elif original_color_temp:
                restore_data["color_temp"] = original_color_temp
            await self.call_service("light", "turn_on", restore_data, target=target)

    async def _show_scope_error_feedback(self, switch_id: str) -> None:
        """Show error feedback when can't cycle scope (flash red or rapid blink).

        In non-learn mode with indicator light: rapid 5x blink on indicator.
        Otherwise: red flash on all area lights.

        Args:
            switch_id: The switch IEEE address
        """
        # Check for non-learn mode + indicator light
        switch_config = switches.get_switch(switch_id)
        if switch_config and not self._is_reach_learn_mode() and switch_config.indicator_light:
            # Rapid 5x blink on indicator light
            indicator = switch_config.indicator_light
            light_state = self.cached_states.get(indicator, {})
            was_on = light_state.get("state") == "on"
            attrs = light_state.get("attributes", {}) if was_on else {}
            original_brightness = attrs.get("brightness", 128)
            original_xy = attrs.get("xy_color")
            original_color_temp = attrs.get("color_temp")
            blink_brightness = original_brightness if was_on else self._get_motion_warning_blink_threshold()
            target = {"entity_id": indicator}

            for _ in range(5):
                await self.call_service("light", "turn_off", {"transition": 0}, target=target)
                await asyncio.sleep(0.1)
                await self.call_service(
                    "light", "turn_on",
                    {"brightness": blink_brightness, "transition": 0},
                    target=target
                )
                await asyncio.sleep(0.1)

            # Restore
            if not was_on:
                await self.call_service("light", "turn_off", {"transition": 0}, target=target)
            else:
                restore_data = {"brightness": original_brightness, "transition": 0}
                if original_xy:
                    restore_data["xy_color"] = original_xy
                elif original_color_temp:
                    restore_data["color_temp"] = original_color_temp
                await self.call_service("light", "turn_on", restore_data, target=target)
            return

        # Fallback: red flash on all area lights
        areas = switches.get_current_areas(switch_id)
        if not areas:
            return

        # Store current state (on/off and color)
        original_states = {}
        for area in areas:
            light_entity = self._get_fallback_group_entity(area)
            if light_entity and light_entity in self.cached_states:
                cached = self.cached_states[light_entity]
                was_on = cached.get("state") == "on"
                attrs = cached.get("attributes", {}) if was_on else {}
                original_states[area] = {
                    "was_on": was_on,
                    "color_temp": attrs.get("color_temp"),
                    "rgb_color": attrs.get("rgb_color"),
                    "xy_color": attrs.get("xy_color"),
                    "brightness": attrs.get("brightness", 128),
                }
            else:
                original_states[area] = {"was_on": False}

        # Determine flash brightness for lights that were off (based on sun position)
        sun_is_up = False
        if "sun.sun" in self.cached_states:
            sun_state = self.cached_states["sun.sun"]
            sun_is_up = sun_state.get("state") == "above_horizon"
        off_flash_brightness = int(0.20 * 255) if sun_is_up else int(0.01 * 255)

        # Flash red
        for area in areas:
            orig = original_states.get(area, {})
            if orig.get("was_on"):
                await self._set_area_color_quick(area, rgb_color=[255, 50, 50])
            else:
                await self._set_area_color_quick(area, rgb_color=[255, 50, 50], brightness=off_flash_brightness)

        await asyncio.sleep(0.3)

        # Restore original states
        for area, orig in original_states.items():
            if not orig.get("was_on"):
                await self.call_service("light", "turn_off", {}, target={"area_id": area})
            elif orig.get("color_temp"):
                await self._set_area_color_quick(area, color_temp=orig["color_temp"], brightness=orig.get("brightness"))
            elif orig.get("rgb_color"):
                await self._set_area_color_quick(area, rgb_color=orig["rgb_color"], brightness=orig.get("brightness"))
            elif orig.get("xy_color"):
                await self._set_area_color_quick(area, xy_color=orig["xy_color"], brightness=orig.get("brightness"))
            else:
                await self._set_area_brightness_quick(area, orig.get("brightness", 128))

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
        brightness: int = None,
    ) -> None:
        """Quickly set color for an area (no transition)."""
        service_data = {"transition": 0}
        if rgb_color:
            service_data["rgb_color"] = rgb_color
        elif color_temp:
            service_data["color_temp"] = color_temp
        elif xy_color:
            service_data["xy_color"] = xy_color
        if brightness is not None:
            service_data["brightness"] = brightness

        await self.call_service(
            "light",
            "turn_on",
            service_data,
            target={"area_id": area}
        )

    async def _dial_debounce(self, device_ieee: str) -> None:
        """Process a buffered dial rotation after a short settling delay.

        Waits 200ms for events to settle, then processes the latest level.
        This filters out-of-order ZigBee events during fast spinning.
        """
        try:
            await asyncio.sleep(0.2)
            pending = self._dial_pending.pop(device_ieee, None)
            if not pending:
                return
            level = pending["level"]
            switch_config = pending["config"]
            position = round(level / 255 * 100)

            dial_action = switch_config.get_button_action("dial_rotate") or "set_position_step"
            mode_map = {
                "set_position_step": "step",
                "set_position_brightness": "brightness",
                "set_position_color": "color",
            }
            mode = mode_map.get(dial_action, "step")
            switches.set_last_action(device_ieee, f"dial {position}%")
            logger.info(f"[Dial] {switch_config.name}: level={level} -> set_position({position}, {mode})")
            areas = switches.get_current_areas(device_ieee)
            for area in areas:
                await self.primitives.set_position(area, position, mode, "switch")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error in dial debounce: {e}", exc_info=True)

    async def _start_hold_repeat(self, switch_id: str, action: str) -> None:
        """Start repeating an action while button is held.

        Args:
            switch_id: The switch IEEE address
            action: The action to repeat
        """
        # Cancel any existing repeat task (without clearing hold state)
        if self._hold_repeat_task and not self._hold_repeat_task.done():
            self._hold_repeat_task.cancel()
            try:
                await self._hold_repeat_task
            except asyncio.CancelledError:
                pass
            self._hold_repeat_task = None

        # Mark hold as active (after cancel, before loop starts)
        switches.start_hold(switch_id, action)

        # Get repeat interval
        interval_ms = switches.get_repeat_interval(switch_id)

        max_hold_seconds = 30  # Safety timeout

        async def repeat_loop():
            try:
                start_time = time.time()
                # Execute immediately first
                await self._execute_switch_action(switch_id, action)

                # Then repeat at interval (with safety timeout)
                while switches.is_holding(switch_id):
                    if time.time() - start_time > max_hold_seconds:
                        logger.warning(f"Hold repeat safety timeout ({max_hold_seconds}s) for {switch_id}")
                        switches.stop_hold(switch_id)
                        break
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
        circadian_values: Dict[str, Any] = None,
        transition: float = 0.5,
        *,
        include_color: bool = True,
        brightness: int = None,
        color_temp: int = None,
        xy: tuple = None,
        log_periodic: bool = True,
    ) -> None:
        """Turn on lights with circadian values - the single source of truth for light control.

        This is the canonical function for turning on lights. All paths (primitives,
        periodic updater, etc.) should call this function to ensure consistent behavior.

        Splits lights by color capability:
        - Color-capable lights (xy/rgb/hs): Use xy_color for full color range
        - CT-only lights: Use color_temp_kelvin (clamped to 2000K minimum)

        Can be called two ways:
        1. With circadian_values dict: turn_on_lights_circadian(area_id, {"brightness": 50, "kelvin": 3000, "xy": (0.4, 0.4)})
        2. With keyword args: turn_on_lights_circadian(area_id, brightness=50, color_temp=3000)

        Args:
            area_id: The area ID to control lights in
            circadian_values: Dict with brightness, kelvin, xy keys (optional if using kwargs)
            transition: Transition time in seconds (default 0.5)
            include_color: Whether to include color data when turning on lights
            brightness: Brightness percentage 0-100 (alternative to dict)
            color_temp: Color temperature in Kelvin (alternative to dict)
            xy: Pre-computed CIE xy coordinates (optional, computed from color_temp if not provided)
        """
        # Support both dict and kwargs calling conventions
        if circadian_values:
            brightness = circadian_values.get('brightness') if brightness is None else brightness
            kelvin = circadian_values.get('kelvin')
            xy = circadian_values.get('xy') if xy is None else xy
        else:
            kelvin = color_temp

        # Compute xy from kelvin if not provided (for color-capable lights)
        if xy is None and kelvin is not None and include_color:
            xy = CircadianLight.color_temperature_to_xy(kelvin)

        # Apply CT brightness compensation (for warm color temps on Hue bulbs)
        if brightness is not None and kelvin is not None:
            original_brightness = brightness
            brightness = self._apply_ct_brightness_compensation(brightness, kelvin)
            if brightness != original_brightness:
                logger.debug(f"CT compensation: {original_brightness}% -> {brightness}% at {kelvin}K")

        color_lights, ct_lights, brightness_lights, onoff_lights = self.get_lights_by_capability(area_id)

        # If no lights found in cache, fall back to area-based control
        if not color_lights and not ct_lights and not brightness_lights and not onoff_lights:
            target_type, target_value = await self.determine_light_target(area_id)
            service_data = {"transition": transition}
            if brightness is not None:
                service_data["brightness_pct"] = brightness
            if include_color and kelvin is not None:
                service_data["color_temp_kelvin"] = max(2000, kelvin)

            if log_periodic:
                logger.info(f"Circadian update (fallback): {target_type}={target_value}, {service_data}")
            await self.call_service("light", "turn_on", service_data, {target_type: target_value})
            return

        tasks: List[asyncio.Task] = []

        # Look up ZHA capability groups for this area
        normalized_key = self._normalize_area_key(area_id)
        group_candidates = self.area_group_map.get(normalized_key, {}) if normalized_key else {}
        zha_color_group = group_candidates.get("zha_group_color")
        zha_ct_group = group_candidates.get("zha_group_ct")

        # Color-capable lights: use xy_color for full color range
        if color_lights:
            color_data = {"transition": transition}
            if brightness is not None:
                color_data["brightness_pct"] = brightness
            if include_color and xy is not None:
                color_data["xy_color"] = list(xy)

            # Use ZHA group if available (efficient hardware-level control)
            if zha_color_group:
                # Split into ZHA (use group) and non-ZHA (call individually)
                non_zha_color = [l for l in color_lights if l not in self.zha_lights]
                zha_count = len(color_lights) - len(non_zha_color)
                if log_periodic:
                    logger.info(f"Circadian update (color via ZHA group): {zha_color_group} ({zha_count} lights), xy={xy}, brightness={brightness}%")
                tasks.append(
                    asyncio.create_task(
                        self.call_service("light", "turn_on", color_data, {"entity_id": zha_color_group})
                    )
                )
                # Also call non-ZHA color lights individually
                if non_zha_color:
                    if log_periodic:
                        logger.info(f"Circadian update (color non-ZHA): {len(non_zha_color)} lights, xy={xy}, brightness={brightness}%")
                    tasks.append(
                        asyncio.create_task(
                            self.call_service("light", "turn_on", color_data, {"entity_id": non_zha_color})
                        )
                    )
            else:
                if log_periodic:
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

            # Use ZHA group if available (efficient hardware-level control)
            if zha_ct_group:
                # Split into ZHA (use group) and non-ZHA (call individually)
                non_zha_ct = [l for l in ct_lights if l not in self.zha_lights]
                zha_count = len(ct_lights) - len(non_zha_ct)
                if log_periodic:
                    logger.info(f"Circadian update (CT via ZHA group): {zha_ct_group} ({zha_count} lights), kelvin={kelvin}, brightness={brightness}%")
                tasks.append(
                    asyncio.create_task(
                        self.call_service("light", "turn_on", ct_data, {"entity_id": zha_ct_group})
                    )
                )
                # Also call non-ZHA CT lights individually
                if non_zha_ct:
                    if log_periodic:
                        logger.info(f"Circadian update (CT non-ZHA): {len(non_zha_ct)} lights, kelvin={kelvin}, brightness={brightness}%")
                    tasks.append(
                        asyncio.create_task(
                            self.call_service("light", "turn_on", ct_data, {"entity_id": non_zha_ct})
                        )
                    )
            else:
                if log_periodic:
                    logger.info(f"Circadian update (CT): {len(ct_lights)} lights, kelvin={kelvin}, brightness={brightness}%")
                tasks.append(
                    asyncio.create_task(
                        self.call_service("light", "turn_on", ct_data, {"entity_id": ct_lights})
                    )
                )

        # Brightness-only lights: only set brightness, no color
        if brightness_lights:
            bri_data = {"transition": transition}
            if brightness is not None:
                bri_data["brightness_pct"] = brightness

            if log_periodic:
                logger.info(f"Circadian update (brightness-only): {len(brightness_lights)} lights, brightness={brightness}%")
            tasks.append(
                asyncio.create_task(
                    self.call_service("light", "turn_on", bri_data, {"entity_id": brightness_lights})
                )
            )

        # On/off-only lights: just turn on, no brightness or color
        if onoff_lights:
            # Only include transition, no brightness or color data
            onoff_data = {"transition": transition}

            if log_periodic:
                logger.info(f"Circadian update (on/off-only): {len(onoff_lights)} lights")
            tasks.append(
                asyncio.create_task(
                    self.call_service("light", "turn_on", onoff_data, {"entity_id": onoff_lights})
                )
            )

        # Run all tasks concurrently
        if tasks:
            await asyncio.gather(*tasks)

    async def turn_off_lights(
        self,
        area_id: str,
        transition: float = 0.3,
        log_periodic: bool = True,
    ) -> None:
        """Turn off lights using ZHA groups when available.

        This mirrors turn_on_lights_circadian but for turning off. Uses ZHA groups
        for efficient hardware-level control when available, with fallback to
        individual light control for non-ZHA lights.

        Args:
            area_id: The area ID to control lights in
            transition: Transition time in seconds (default 0.3)
            log_periodic: Whether to log per-group off details
        """
        color_lights, ct_lights, brightness_lights, onoff_lights = self.get_lights_by_capability(area_id)

        # If no lights found in cache, fall back to area-based control
        if not color_lights and not ct_lights and not brightness_lights and not onoff_lights:
            target_type, target_value = await self.determine_light_target(area_id)
            service_data = {"transition": transition}
            if log_periodic:
                logger.info(f"Turn off (fallback): {target_type}={target_value}")
            await self.call_service("light", "turn_off", service_data, {target_type: target_value})
            return

        tasks: List[asyncio.Task] = []

        # Look up ZHA capability groups for this area
        normalized_key = self._normalize_area_key(area_id)
        group_candidates = self.area_group_map.get(normalized_key, {}) if normalized_key else {}
        zha_color_group = group_candidates.get("zha_group_color")
        zha_ct_group = group_candidates.get("zha_group_ct")

        service_data = {"transition": transition}

        # Color-capable lights
        if color_lights:
            if zha_color_group:
                # Split into ZHA (use group) and non-ZHA (call individually)
                non_zha_color = [l for l in color_lights if l not in self.zha_lights]
                zha_count = len(color_lights) - len(non_zha_color)
                if log_periodic:
                    logger.info(f"Turn off (color via ZHA group): {zha_color_group} ({zha_count} lights)")
                tasks.append(
                    asyncio.create_task(
                        self.call_service("light", "turn_off", service_data, {"entity_id": zha_color_group})
                    )
                )
                if non_zha_color:
                    if log_periodic:
                        logger.info(f"Turn off (color non-ZHA): {len(non_zha_color)} lights")
                    tasks.append(
                        asyncio.create_task(
                            self.call_service("light", "turn_off", service_data, {"entity_id": non_zha_color})
                        )
                    )
            else:
                if log_periodic:
                    logger.info(f"Turn off (color): {len(color_lights)} lights")
                tasks.append(
                    asyncio.create_task(
                        self.call_service("light", "turn_off", service_data, {"entity_id": color_lights})
                    )
                )

        # CT-only lights
        if ct_lights:
            if zha_ct_group:
                # Split into ZHA (use group) and non-ZHA (call individually)
                non_zha_ct = [l for l in ct_lights if l not in self.zha_lights]
                zha_count = len(ct_lights) - len(non_zha_ct)
                if log_periodic:
                    logger.info(f"Turn off (CT via ZHA group): {zha_ct_group} ({zha_count} lights)")
                tasks.append(
                    asyncio.create_task(
                        self.call_service("light", "turn_off", service_data, {"entity_id": zha_ct_group})
                    )
                )
                if non_zha_ct:
                    if log_periodic:
                        logger.info(f"Turn off (CT non-ZHA): {len(non_zha_ct)} lights")
                    tasks.append(
                        asyncio.create_task(
                            self.call_service("light", "turn_off", service_data, {"entity_id": non_zha_ct})
                        )
                    )
            else:
                if log_periodic:
                    logger.info(f"Turn off (CT): {len(ct_lights)} lights")
                tasks.append(
                    asyncio.create_task(
                        self.call_service("light", "turn_off", service_data, {"entity_id": ct_lights})
                    )
                )

        # Brightness-only lights (no ZHA groups for these)
        if brightness_lights:
            if log_periodic:
                logger.info(f"Turn off (brightness-only): {len(brightness_lights)} lights")
            tasks.append(
                asyncio.create_task(
                    self.call_service("light", "turn_off", service_data, {"entity_id": brightness_lights})
                )
            )

        # On/off-only lights (no ZHA groups for these)
        if onoff_lights:
            if log_periodic:
                logger.info(f"Turn off (on/off-only): {len(onoff_lights)} lights")
            tasks.append(
                asyncio.create_task(
                    self.call_service("light", "turn_off", service_data, {"entity_id": onoff_lights})
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
        self.hue_lights.clear()
        self.zha_lights.clear()
        hue_groups_skipped = 0

        # Build device_id -> integration mapping from device identifiers
        hue_device_ids: Set[str] = set()
        zha_device_ids: Set[str] = set()
        for device in devices:
            if isinstance(device, dict):
                device_id = device.get("id")
                identifiers = device.get("identifiers", [])
                device_name = device.get("name", "")
                manufacturer = device.get("manufacturer", "")
                found_zha = False
                for identifier in identifiers:
                    if isinstance(identifier, list) and len(identifier) >= 2:
                        if identifier[0] == "hue":
                            hue_device_ids.add(device_id)
                        elif identifier[0] == "zha":
                            zha_device_ids.add(device_id)
                            found_zha = True
                # Debug: log Signify devices that aren't detected as ZHA
                if manufacturer and "signify" in manufacturer.lower() and not found_zha:
                    logger.debug(f"Signify device NOT detected as ZHA: {device_name} | identifiers: {identifiers}")

        # Process light entities
        for entity in entities:
            if not isinstance(entity, dict):
                continue

            entity_id = entity.get("entity_id", "")
            if not entity_id.startswith("light."):
                continue

            # Get area - either direct or via device
            device_id = entity.get("device_id")
            area_id = entity.get("area_id")
            if not area_id and device_id:
                area_id = device_area_map.get(device_id)

            # Skip entities with no area
            if not area_id:
                continue

            # Skip Hue room/zone groups - they duplicate control of individual lights
            state = self.cached_states.get(entity_id, {})
            attributes = state.get("attributes", {})
            if attributes.get("is_hue_group"):
                hue_groups_skipped += 1
                logger.debug(f"Skipping Hue group entity: {entity_id}")
                continue

            # Track Hue-connected lights (skip 2-step for these)
            if device_id and device_id in hue_device_ids:
                self.hue_lights.add(entity_id)

            # Track ZHA-connected lights (can use ZHA groups)
            if device_id and device_id in zha_device_ids:
                self.zha_lights.add(entity_id)

            # Add to area_lights mapping
            if area_id not in self.area_lights:
                self.area_lights[area_id] = []
            self.area_lights[area_id].append(entity_id)

            # Get color modes from cached state (reuse attributes from above)
            supported_modes = attributes.get("supported_color_modes", [])

            if supported_modes:
                self.light_color_modes[entity_id] = set(supported_modes)
            else:
                # Default to color_temp if no modes specified (legacy lights)
                self.light_color_modes[entity_id] = {"color_temp"}

        logger.info(f"✓ Light capability cache built: {len(self.light_color_modes)} lights across {len(self.area_lights)} areas")

        # Log summary of light capabilities (4 types)
        color_count = 0
        ct_count = 0
        brightness_count = 0
        onoff_count = 0
        for modes in self.light_color_modes.values():
            if "xy" in modes or "rgb" in modes or "hs" in modes:
                color_count += 1
            elif "color_temp" in modes:
                ct_count += 1
            elif "brightness" in modes:
                brightness_count += 1
            else:
                onoff_count += 1
        logger.info(f"  Color: {color_count}, CT: {ct_count}, Brightness-only: {brightness_count}, On/off-only: {onoff_count}")
        logger.info(f"  ZHA-connected: {len(self.zha_lights)}, Hue-connected: {len(self.hue_lights)}, Hue groups skipped: {hue_groups_skipped}")

        # Build motion sensor entity_id -> device_id mapping
        # This lets us look up motion sensor config when events come in
        self.motion_sensor_ids.clear()
        for entity in entities:
            if not isinstance(entity, dict):
                continue

            entity_id = entity.get("entity_id", "")
            # Check for motion/occupancy binary sensors
            if not entity_id.startswith("binary_sensor."):
                continue
            if "_motion" not in entity_id and "_occupancy" not in entity_id:
                continue

            # Get device_id for this entity
            device_id = entity.get("device_id")
            if device_id:
                self.motion_sensor_ids[entity_id] = device_id

        if self.motion_sensor_ids:
            logger.info(f"✓ Motion sensor cache built: {len(self.motion_sensor_ids)} sensors")
            for entity_id, device_id in self.motion_sensor_ids.items():
                logger.debug(f"  {entity_id} -> device:{device_id}")

        # Build contact sensor entity_id -> device_id mapping
        # This lets us look up contact sensor config when events come in
        self.contact_sensor_ids.clear()
        for entity in entities:
            if not isinstance(entity, dict):
                continue

            entity_id = entity.get("entity_id", "")
            # Check for contact/door/window binary sensors
            if not entity_id.startswith("binary_sensor."):
                continue
            # Look for opening, door, window, contact in entity_id
            if not any(x in entity_id for x in ["_opening", "_door", "_window", "_contact"]):
                continue

            # Get device_id for this entity
            device_id = entity.get("device_id")
            if device_id:
                self.contact_sensor_ids[entity_id] = device_id
                logger.info(f"  Contact sensor cached: {entity_id} -> device:{device_id}")
            else:
                logger.warning(f"  Contact sensor skipped (no device_id): {entity_id}")

        if self.contact_sensor_ids:
            logger.info(f"✓ Contact sensor cache built: {len(self.contact_sensor_ids)} sensors")
        else:
            logger.warning("⚠ No contact sensors found in entity registry")

    def get_lights_by_color_capability(self, area_id: str) -> Tuple[List[str], List[str]]:
        """Get lights in an area split by color capability (legacy 2-bucket version).

        DEPRECATED: Use get_lights_by_capability() for the full 4-bucket split.

        Args:
            area_id: The area ID

        Returns:
            Tuple of (color_capable_lights, ct_only_lights)
            - color_capable_lights: lights that support xy, rgb, or hs color modes
            - ct_only_lights: lights that only support color_temp mode (includes brightness/onoff for compatibility)
        """
        color_lights, ct_lights, brightness_lights, onoff_lights = self.get_lights_by_capability(area_id)
        # For backward compatibility, lump brightness and onoff into ct_only
        ct_only = ct_lights + brightness_lights + onoff_lights
        return color_lights, ct_only

    def get_lights_by_capability(self, area_id: str) -> Tuple[List[str], List[str], List[str], List[str]]:
        """Get lights in an area split by capability level.

        Args:
            area_id: The area ID

        Returns:
            Tuple of (color_lights, ct_lights, brightness_lights, onoff_lights)
            - color_lights: support xy, rgb, or hs color modes (full color control)
            - ct_lights: support color_temp mode only (color temperature control)
            - brightness_lights: support brightness mode only (dimming, no color)
            - onoff_lights: support onoff mode only (no dimming, no color)
        """
        lights = self.area_lights.get(area_id, [])

        color_lights = []
        ct_lights = []
        brightness_lights = []
        onoff_lights = []

        for entity_id in lights:
            modes = self.light_color_modes.get(entity_id, {"color_temp"})

            # Check capabilities in order of most to least capable
            if "xy" in modes or "rgb" in modes or "hs" in modes:
                color_lights.append(entity_id)
            elif "color_temp" in modes:
                ct_lights.append(entity_id)
            elif "brightness" in modes:
                brightness_lights.append(entity_id)
            else:
                # onoff or unknown - treat as on/off only
                onoff_lights.append(entity_id)

        return color_lights, ct_lights, brightness_lights, onoff_lights


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
                # Prefer ZHA groups for state checking - they update in real-time vs Hue polling
                # ZHA group state is more reliable for detecting on/off changes
                light_entity_id = (
                    candidates.get("zha_group_color") or
                    candidates.get("zha_group_ct") or
                    candidates.get("zha_group") or
                    candidates.get("hue_group")
                )
            if not light_entity_id:
                light_entity_id = self._get_fallback_group_entity(area_id)
            if light_entity_id:
                light_state = self.cached_states.get(light_entity_id, {}).get("state")
                logger.info(f"[group_fastpath] {light_entity_id=} {area_id=} state={light_state}")
                if light_state in ("on", "off"):
                    if light_state == "on":
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

        Note: This is a low-level helper. Prefer using primitives.lights_on/off/toggle
        which handle the full state model (is_circadian + is_on).

        Args:
            area_id: The area ID to enable Circadian Light for
        """
        was_circadian = state.is_circadian(area_id)
        state.set_is_circadian(area_id, True)

        if not was_circadian:
            logger.info(f"Circadian Light enabled for area {area_id}")
        else:
            logger.debug(f"Circadian Light already enabled for area {area_id}")

    async def disable_circadian_mode(self, area_id: str):
        """Disable Circadian Light mode for an area.

        Note: This is a low-level helper. Prefer using primitives.circadian_off
        which handles state transitions properly.

        Args:
            area_id: The area ID to disable Circadian Light for
        """
        was_circadian = state.is_circadian(area_id)

        if not was_circadian:
            logger.info(f"Circadian Light already disabled for area {area_id}")
            return

        state.set_is_circadian(area_id, False)
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
        Uses zone-aware configuration - gets the rhythm config for the area's zone.

        Args:
            area_id: The area ID to get lighting values for
            current_time: Optional datetime to use for calculations (for time simulation)
            apply_time_offset: Whether to apply time offset (unused, kept for API compatibility)

        Returns:
            Dict containing circadian lighting values
        """
        # Get zone-aware config for this area (rhythm settings + global settings)
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
    
    def _get_sun_times(self) -> SunTimes:
        """Get current sun times from configured location.

        Returns:
            SunTimes object with sunrise, sunset, solar_noon, solar_mid (as hours 0-24)
        """
        try:
            from datetime import datetime
            from zoneinfo import ZoneInfo

            if self.latitude and self.longitude:
                date_str = datetime.now().strftime('%Y-%m-%d')
                sun_dict = calculate_sun_times(self.latitude, self.longitude, date_str)

                # Get local timezone for conversion
                local_tz = None
                if self.timezone:
                    try:
                        local_tz = ZoneInfo(self.timezone)
                    except:
                        pass

                # Convert ISO strings to local hours
                def iso_to_hour(iso_str, default):
                    if not iso_str:
                        return default
                    try:
                        dt = datetime.fromisoformat(iso_str)
                        # Convert to local timezone if available
                        if local_tz and dt.tzinfo:
                            dt = dt.astimezone(local_tz)
                        return dt.hour + dt.minute / 60.0 + dt.second / 3600.0
                    except:
                        return default

                sunrise = iso_to_hour(sun_dict.get("sunrise"), 6.0)
                sunset = iso_to_hour(sun_dict.get("sunset"), 18.0)
                solar_noon = iso_to_hour(sun_dict.get("noon"), 12.0)
                solar_mid = (solar_noon + 12.0) % 24.0  # Opposite of noon

                return SunTimes(
                    sunrise=sunrise,
                    sunset=sunset,
                    solar_noon=solar_noon,
                    solar_mid=solar_mid,
                )
        except Exception as e:
            logger.debug(f"Error calculating sun times: {e}")

        # Return defaults if calculation fails
        return SunTimes()

    async def update_lights_in_circadian_mode(self, area_id: str, log_periodic: bool = False):
        """Update lights in an area with circadian lighting if Circadian Light is enabled.

        This method respects per-area stepped state (brightness_mid, color_mid, pushed bounds)
        that was set via step_up/step_down buttons.

        If the area is frozen (frozen_at is set), uses frozen_at instead of current time.
        Uses zone-aware configuration - gets the rhythm config for the area's zone.

        Args:
            area_id: The area ID to update
            log_periodic: Whether to log periodic update details (controlled by settings toggle)
        """
        try:
            # Only update if area is under circadian control
            if not state.is_circadian(area_id):
                logger.debug(f"Area {area_id} not in Circadian mode, skipping update")
                return

            # Get area state (includes stepped midpoints, pushed bounds, and frozen_at)
            area_state_dict = state.get_area(area_id)
            area_state = AreaState.from_dict(area_state_dict)

            # Check target power state - enforce is_on with off_enforced optimization
            if not state.get_is_on(area_id):
                if not state.is_off_enforced(area_id):
                    # Check cached_states to see if lights are actually off
                    lights = self.area_lights.get(area_id, [])
                    if lights:
                        any_on = any(
                            self.cached_states.get(l, {}).get("state") == "on"
                            for l in lights
                        )
                        if any_on:
                            transition = self.primitives._get_turn_off_transition()
                            logger.debug(f"Area {area_id} is_on=false, straggler light detected, sending off")
                            await self.turn_off_lights(area_id, transition=transition, log_periodic=log_periodic)
                        else:
                            state.set_off_enforced(area_id, True)
                            logger.debug(f"Area {area_id} is_on=false, all lights confirmed off, setting off_enforced")
                    else:
                        # No lights in cache (capability cache not built yet) — fallback: send off
                        transition = self.primitives._get_turn_off_transition()
                        logger.debug(f"Area {area_id} is_on=false, no cached lights, sending off (fallback)")
                        await self.turn_off_lights(area_id, transition=transition, log_periodic=log_periodic)
                return

            # Skip areas in motion warning state (don't override the warning dim)
            if state.is_motion_warned(area_id):
                logger.debug(f"[Periodic] Area {area_id} in motion warning state, skipping update")
                return

            if area_state.brightness_mid is not None or area_state.color_mid is not None:
                if log_periodic:
                    logger.info(f"[Periodic] Area {area_id} has stepped state: brightness_mid={area_state.brightness_mid}, color_mid={area_state.color_mid}")

            # Get zone-aware config for this area
            config_dict = glozone.get_effective_config_for_area(area_id)
            config = Config.from_dict(config_dict)

            # Use frozen_at if set, otherwise current time
            if area_state.frozen_at is not None:
                hour = area_state.frozen_at
                logger.debug(f"Area {area_id} is frozen at hour {hour:.2f}")
            else:
                hour = get_current_hour()

            # Get actual sun times for solar rules
            sun_times = self._get_sun_times()

            # Calculate lighting using area state (respects stepped values)
            result = CircadianLight.calculate_lighting(hour, config, area_state, sun_times=sun_times)

            # Check if area is boosted - if so, apply boost to brightness
            brightness = result.brightness
            boost_note = ""
            is_boosted = state.is_boosted(area_id)
            if is_boosted:
                # Get boost brightness from area's boost state (set per-sensor)
                boost_state = state.get_boost_state(area_id)
                boost_amount = boost_state.get('boost_brightness') or 0
                brightness = min(100, result.brightness + boost_amount)
                boost_note = f" (boosted +{boost_amount}%)"
                if log_periodic:
                    logger.info(f"[Periodic] Area {area_id}: applying boost {boost_amount}% -> {brightness}% (state={boost_state})")

            # Build values dict for turn_on_lights_circadian
            lighting_values = {
                'brightness': brightness,
                'kelvin': result.color_temp,
                'rgb': result.rgb,
                'xy': result.xy,
            }

            # Log the calculation
            frozen_note = f" (frozen at {hour:.1f}h)" if area_state.frozen_at is not None else ""
            if log_periodic:
                logger.info(f"Periodic update for area {area_id}{frozen_note}{boost_note}: {result.color_temp}K, {brightness}%")

            # Use the centralized light control function
            await self.turn_on_lights_circadian(area_id, lighting_values, transition=0.5, log_periodic=log_periodic)

        except Exception as e:
            logger.error(f"Error updating lights in area {area_id}: {e}")

    async def reset_state_at_phase_change(self, last_check: Optional[datetime]) -> Optional[datetime]:
        """Reset all area and zone runtime state at phase transitions (ascend/descend).

        State resets when crossing ascend_start or descend_start times.
        Resets both area runtime state and GloZone runtime state.

        Note: Currently uses the first rhythm's phase times for the global check.
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

        # Load config (uses first rhythm for phase times)
        # Future: could check per-zone phase times
        raw_config = glozone.load_config_from_files()
        rhythms = raw_config.get("circadian_rhythms", {})

        if not rhythms:
            return now

        # Use first rhythm's phase times for global check
        first_rhythm = list(rhythms.values())[0]
        config = Config.from_dict(first_rhythm)

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

            # Update all circadian areas with new values
            for area_id in state.get_circadian_areas_for_update():
                await self.update_lights_in_circadian_mode(area_id)

        return now

    async def periodic_light_updater(self):
        """Run two independent loops: a fast tick (1s) for timers/state checks,
        and a circadian tick (configurable) for light updates.
        """
        # Create the Event lazily in the running event loop to avoid "different loop" errors
        if self.refresh_event is None:
            self.refresh_event = asyncio.Event()

        try:
            await asyncio.gather(
                self._fast_tick_loop(),
                self._circadian_tick_loop(),
            )
        except asyncio.CancelledError:
            logger.info("Periodic light updater cancelled")

    async def _fast_tick_loop(self):
        """Fast tick (1 second): in-memory state checks and timer expiry.

        All operations here are in-memory (microseconds, zero API calls)
        unless something actually expires and needs action.
        """
        last_phase_check = None

        while True:
            try:
                await asyncio.sleep(1)

                # Check if we should reset state at phase changes
                last_phase_check = await self.reset_state_at_phase_change(last_phase_check)

                # Check for switch scope timeouts (auto-reset to scope 1 after inactivity)
                reset_switches = switches.check_scope_timeouts()
                if reset_switches:
                    logger.debug(f"Reset {len(reset_switches)} switch(es) to scope 1 due to inactivity")

                # Use log_periodic from circadian tick (updated every circadian_refresh seconds)
                log_periodic = self._log_periodic

                # Check for motion warnings (before expiry check)
                await self.primitives.check_motion_warnings(log_periodic=log_periodic)

                # Check for expired boosts and motion timers
                await self.primitives.check_expired_boosts(log_periodic=log_periodic)
                await self.primitives.check_expired_motion(log_periodic=log_periodic)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Error in fast tick: {e}")

    async def _circadian_tick_loop(self):
        """Circadian tick (configurable 5-120s): update all circadian areas with current lighting."""
        while True:
            try:
                # Get refresh interval and log_periodic from config
                try:
                    raw_config = glozone.load_config_from_files()
                    refresh_interval = raw_config.get("circadian_refresh", 30)
                    refresh_interval = max(5, min(120, refresh_interval))
                    log_periodic = raw_config.get("log_periodic", False)
                except Exception:
                    refresh_interval = 30
                    log_periodic = False
                self._log_periodic = log_periodic

                # Wait for configured interval OR until refresh_event is signaled
                triggered_by_event = False
                try:
                    await asyncio.wait_for(self.refresh_event.wait(), timeout=refresh_interval)
                    self.refresh_event.clear()
                    triggered_by_event = True
                except asyncio.TimeoutError:
                    pass  # Normal periodic tick

                # Get all circadian areas from state module
                circadian_areas = state.get_circadian_areas_for_update()

                if not circadian_areas:
                    logger.debug("No areas enabled for Circadian Light update")
                else:
                    # Skip area being designed in Live Design mode
                    if self.live_design_area and self.live_design_area in circadian_areas:
                        circadian_areas = [a for a in circadian_areas if a != self.live_design_area]
                        logger.debug(f"Skipping Live Design area: {self.live_design_area}")

                    trigger_source = "refresh signal" if triggered_by_event else f"periodic ({refresh_interval}s)"
                    if circadian_areas:
                        if log_periodic:
                            logger.info(f"Running light update ({trigger_source}) for {len(circadian_areas)} Circadian areas")
                        for area_id in circadian_areas:
                            logger.debug(f"Updating lights in Circadian area: {area_id}")
                            await self.update_lights_in_circadian_mode(area_id, log_periodic=log_periodic)
                    else:
                        logger.debug(f"No areas to update ({trigger_source}) - all skipped or disabled")

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Error in circadian tick: {e}")
        
    async def run_manual_sync(self):
        """Run manual sync: refresh light caches, ZHA groups, and group entity mappings.

        Called from the "Sync devices" button in settings. Detects area membership changes,
        new/moved lights, and syncs ZHA groups.
        """
        try:
            logger.info("[sync] Starting area/group sync")

            # 1. Refresh group entity mappings from cached_states
            #    (picks up any new Circadian_ or Hue group entities from state_changed events)
            self._refresh_group_entity_mappings()

            # 2. Rebuild light capability cache (area_lights, light_color_modes, zha_lights, hue_lights)
            await self.build_light_capability_cache()

            # 3. Sync ZHA groups (creates/updates/deletes groups, refreshes parity cache + area_name_to_id)
            await self.sync_zha_groups(quiet=True)

            # 4. Re-scan group entity mappings again after sync
            #    (sync may have created new ZHA groups that are now in cached_states)
            self._refresh_group_entity_mappings()

            logger.info("[sync] Area/group sync complete")
        except Exception as e:
            logger.error(f"[sync] Error during sync: {e}")

    def _refresh_group_entity_mappings(self):
        """Re-scan cached_states for grouped light entities and update area_group_map.

        This refreshes area_group_map and area_to_light_entity from the current
        cached_states, picking up any new or removed Circadian_ ZHA groups and Hue rooms.
        """
        self.area_group_map.clear()
        self.area_to_light_entity.clear()
        self.group_entity_info.clear()

        for entity_id, entity_state in self.cached_states.items():
            if not entity_id.startswith("light."):
                continue
            attributes = entity_state.get("attributes", {}) if isinstance(entity_state, dict) else {}
            friendly_name = attributes.get("friendly_name", "")
            self._update_area_group_mapping(entity_id, friendly_name, attributes)

        grouped_count = len(self.group_entity_info)
        logger.debug(f"[sync] Refreshed group entity mappings: {grouped_count} grouped lights")

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
            
            # Clear and rebuild the caches
            self.area_parity_cache.clear()
            self.area_name_to_id.clear()

            for area_id, area_info in areas.items():
                area_name = area_info.get('name', '')

                # Build area_name -> area_id mapping (for group registration lookup)
                if area_name:
                    normalized_name = area_name.lower().replace(' ', '_')
                    self.area_name_to_id[normalized_name] = area_id
                    # Also store without underscores for flexible matching
                    self.area_name_to_id[area_name.lower()] = area_id

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
    
    async def sync_zha_groups(self, quiet: bool = False):
        """Helper method to sync ZHA groups with all areas.

        Args:
            quiet: If True, suppress banner logging (used for periodic slow-cycle syncs).
        """
        try:
            if not quiet:
                logger.info("=" * 60)
                logger.info("Starting ZHA group sync process")
                logger.info("=" * 60)

            zigbee_controller = self.light_controller.controllers.get(Protocol.ZIGBEE)
            if zigbee_controller:
                # Pre-fetch areas to populate area_name_to_id mapping BEFORE sync
                # This ensures group registration can look up area_id from area_name
                areas = await zigbee_controller.get_areas()
                self.area_name_to_id.clear()
                for area_id, area_info in areas.items():
                    area_name = area_info.get('name', '')
                    if area_name:
                        normalized_name = area_name.lower().replace(' ', '_')
                        self.area_name_to_id[normalized_name] = area_id
                        self.area_name_to_id[area_name.lower()] = area_id

                # Sync ZHA groups with all areas (no longer limited to areas with switches)
                success, areas = await zigbee_controller.sync_zha_groups_with_areas()
                if success:
                    logger.info("ZHA group sync completed")
                    # Refresh parity cache using the areas data we already have
                    await self.refresh_area_parity_cache(areas_data=areas)
            else:
                logger.warning("ZigBee controller not available for group sync")

            if not quiet:
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

                elif service in ("lights_on", "circadian_on", "on"):
                    areas = get_areas()
                    if areas:
                        for area in areas:
                            logger.info(f"[{domain}] lights_on for area: {area}")
                            await self.primitives.lights_on(area, "service_call")
                    else:
                        logger.warning("lights_on called without area_id")

                elif service in ("lights_off",):
                    areas = get_areas()
                    if areas:
                        for area in areas:
                            logger.info(f"[{domain}] lights_off for area: {area}")
                            await self.primitives.lights_off(area, "service_call")
                    else:
                        logger.warning("lights_off called without area_id")

                elif service in ("circadian_off", "off"):
                    areas = get_areas()
                    if areas:
                        for area in areas:
                            logger.info(f"[{domain}] circadian_off for area: {area}")
                            await self.primitives.circadian_off(area, "service_call")
                    else:
                        logger.warning("circadian_off called without area_id")

                elif service == "circadian_on":
                    areas = get_areas()
                    if areas:
                        for area in areas:
                            logger.info(f"[{domain}] circadian_on for area: {area}")
                            await self.primitives.circadian_on(area, "service_call")
                    else:
                        logger.warning("circadian_on called without area_id")

                elif service in ("lights_toggle", "circadian_toggle", "toggle"):
                    areas = get_areas()
                    if areas:
                        logger.info(f"[{domain}] lights_toggle for areas: {areas}")
                        await self.primitives.lights_toggle_multiple(areas, "service_call")
                    else:
                        logger.warning("lights_toggle called without area_id")

                elif service == "set":
                    areas = get_areas()
                    preset = service_data.get("preset")  # wake, bed, nitelite, britelite, or moment name
                    frozen_at = service_data.get("frozen_at")  # Optional specific hour (0-24)
                    copy_from = service_data.get("copy_from")  # Optional area_id to copy from
                    is_on = service_data.get("is_on")  # Optional: None=just configure, True=configure+turn on, False=configure+turn off
                    if areas:
                        for area in areas:
                            logger.info(f"[{domain}] set for area: {area} (preset={preset}, frozen_at={frozen_at}, copy_from={copy_from}, is_on={is_on})")
                            await self.primitives.set(area, "service_call", preset=preset, frozen_at=frozen_at, copy_from=copy_from, is_on=is_on)
                    elif preset:
                        # No area specified but preset given - could be a moment (applies to all areas)
                        logger.info(f"[{domain}] set with preset={preset} (no area - may be moment)")
                        await self.primitives.set(None, "service_call", preset=preset, frozen_at=frozen_at, copy_from=copy_from, is_on=is_on)
                    else:
                        logger.warning("set called without area_id or preset")

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
                logger.info("circadian_light_refresh event received - reloading config and signaling periodic updater")
                # Reload config from disk since webserver may have updated it
                glozone.reload()
                if self.refresh_event is not None:
                    self.refresh_event.set()
                else:
                    logger.warning("refresh_event not yet initialized, skipping signal")

            # Handle circadian_light_sync_devices event (fired by webserver Sync Devices button)
            elif event_type == "circadian_light_sync_devices":
                logger.info("circadian_light_sync_devices event received - running manual sync")
                await self.run_manual_sync()

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

            # Handle circadian_light_service_event (fired by webserver for area actions)
            elif event_type == "circadian_light_service_event":
                service = event_data.get('service')
                area_id = event_data.get('area_id')

                if not area_id:
                    logger.warning(f"circadian_light_service_event missing area_id: service={service}")
                elif service == "lights_on":
                    logger.info(f"[webserver] lights_on for area: {area_id}")
                    await self.primitives.lights_on(area_id, "webserver")
                elif service == "lights_off":
                    logger.info(f"[webserver] lights_off for area: {area_id}")
                    await self.primitives.lights_off(area_id, "webserver")
                elif service == "lights_toggle":
                    logger.info(f"[webserver] lights_toggle for area: {area_id}")
                    await self.primitives.lights_toggle(area_id, "webserver")
                elif service == "circadian_on":
                    logger.info(f"[webserver] circadian_on for area: {area_id}")
                    await self.primitives.circadian_on(area_id, "webserver")
                elif service == "circadian_off":
                    logger.info(f"[webserver] circadian_off for area: {area_id}")
                    await self.primitives.circadian_off(area_id, "webserver")
                elif service == "step_up":
                    logger.info(f"[webserver] step_up for area: {area_id}")
                    await self.primitives.step_up(area_id, "webserver")
                elif service == "step_down":
                    logger.info(f"[webserver] step_down for area: {area_id}")
                    await self.primitives.step_down(area_id, "webserver")
                elif service == "bright_up":
                    logger.info(f"[webserver] bright_up for area: {area_id}")
                    await self.primitives.bright_up(area_id, "webserver")
                elif service == "bright_down":
                    logger.info(f"[webserver] bright_down for area: {area_id}")
                    await self.primitives.bright_down(area_id, "webserver")
                elif service == "color_up":
                    logger.info(f"[webserver] color_up for area: {area_id}")
                    await self.primitives.color_up(area_id, "webserver")
                elif service == "color_down":
                    logger.info(f"[webserver] color_down for area: {area_id}")
                    await self.primitives.color_down(area_id, "webserver")
                elif service == "set_position":
                    value = event_data.get('value')
                    mode = event_data.get('mode', 'step')
                    logger.info(f"[webserver] set_position({value}, {mode}) for area: {area_id}")
                    await self.primitives.set_position(area_id, value, mode, "webserver")
                elif service == "freeze_toggle":
                    logger.info(f"[webserver] freeze_toggle for area: {area_id}")
                    await self.primitives.freeze_toggle(area_id, "webserver")
                elif service == "reset":
                    logger.info(f"[webserver] reset for area: {area_id}")
                    await self.primitives.reset(area_id, "webserver")
                elif service == "glo_up":
                    logger.info(f"[webserver] glo_up for area: {area_id}")
                    await self.primitives.glo_up(area_id, "webserver")
                elif service == "glo_down":
                    logger.info(f"[webserver] glo_down for area: {area_id}")
                    await self.primitives.glo_down(area_id, "webserver")
                elif service == "glo_reset":
                    logger.info(f"[webserver] glo_reset for area: {area_id}")
                    await self.primitives.glo_reset(area_id, "webserver")
                elif service == "boost":
                    # Legacy: toggle boost (state now set by webserver)
                    if state.is_boosted(area_id):
                        logger.info(f"[webserver] boost toggle OFF for area: {area_id}")
                        await self.primitives.end_boost(area_id, source="webserver")
                    else:
                        raw_config = glozone.load_config_from_files()
                        boost_amount = raw_config.get("boost_default", 30)
                        logger.info(f"[webserver] boost toggle ON for area: {area_id}, amount={boost_amount}%")
                        await self.primitives.bright_boost(area_id, duration_seconds=0, boost_amount=boost_amount, source="webserver")
                elif service == "boost_on":
                    # Boost state already set by webserver - apply boosted lighting
                    logger.info(f"[webserver] boost_on for area: {area_id}")
                    try:
                        # Reload state from disk (webserver set the boost state)
                        state.init()
                        state.clear_all_off_enforced()
                        boost_state = state.get_boost_state(area_id)
                        boost_amount = boost_state.get("boost_brightness") or 30
                        started_from_off = boost_state.get("boost_started_from_off", False)
                        config = self.primitives._get_config(area_id)
                        area_state = self.primitives._get_area_state(area_id)
                        hour = area_state.frozen_at if area_state.frozen_at is not None else get_current_hour()
                        sun_times = self._get_sun_times() if hasattr(self, '_get_sun_times') else None
                        result = CircadianLight.calculate_lighting(hour, config, area_state, sun_times=sun_times)
                        boosted_brightness = min(100, result.brightness + boost_amount)
                        transition = self.primitives._get_turn_on_transition()
                        if started_from_off:
                            await self.primitives._apply_lighting_turn_on(area_id, boosted_brightness, result.color_temp, transition=transition)
                        else:
                            await self.primitives._apply_lighting(area_id, boosted_brightness, result.color_temp, transition=transition)
                        logger.info(f"[webserver] boost_on applied: {area_id} {result.brightness}%+{boost_amount}%={boosted_brightness}%, {result.color_temp}K")
                    except Exception as e:
                        logger.error(f"[webserver] boost_on lighting failed for {area_id}: {e}", exc_info=True)
                elif service == "boost_off":
                    # Boost state already cleared by webserver - restore circadian lighting
                    logger.info(f"[webserver] boost_off for area: {area_id}")
                    try:
                        # Reload state from disk (webserver cleared the boost state)
                        state.init()
                        state.clear_all_off_enforced()
                        config = self.primitives._get_config(area_id)
                        area_state = self.primitives._get_area_state(area_id)
                        hour = area_state.frozen_at if area_state.frozen_at is not None else get_current_hour()
                        sun_times = self._get_sun_times() if hasattr(self, '_get_sun_times') else None
                        result = CircadianLight.calculate_lighting(hour, config, area_state, sun_times=sun_times)
                        transition = self.primitives._get_turn_on_transition()
                        await self.primitives._apply_lighting(area_id, result.brightness, result.color_temp, transition=transition)
                        logger.info(f"[webserver] boost_off restored: {area_id} {result.brightness}%, {result.color_temp}K")
                    except Exception as e:
                        logger.error(f"[webserver] boost_off restore failed for {area_id}: {e}", exc_info=True)
                elif service == "set_nitelite":
                    logger.info(f"[webserver] set_nitelite for area: {area_id}")
                    await self.primitives.set(area_id, "webserver", preset="nitelite", is_on=True)
                elif service == "set_britelite":
                    logger.info(f"[webserver] set_britelite for area: {area_id}")
                    await self.primitives.set(area_id, "webserver", preset="britelite", is_on=True)
                else:
                    logger.warning(f"Unknown circadian_light_service_event: service={service}, area_id={area_id}")

            # Handle zone-level actions (modify zone state only, no light control)
            elif event_type == "circadian_light_zone_action":
                service = event_data.get('service')
                zone_name = event_data.get('zone_name')
                if not zone_name:
                    logger.warning(f"circadian_light_zone_action missing zone_name: service={service}")
                elif service == "step_up":
                    logger.info(f"[webserver] zone step_up for zone: {zone_name}")
                    await self.primitives.zone_step_up(zone_name, "webserver")
                elif service == "step_down":
                    logger.info(f"[webserver] zone step_down for zone: {zone_name}")
                    await self.primitives.zone_step_down(zone_name, "webserver")
                elif service == "bright_up":
                    logger.info(f"[webserver] zone bright_up for zone: {zone_name}")
                    await self.primitives.zone_bright_up(zone_name, "webserver")
                elif service == "bright_down":
                    logger.info(f"[webserver] zone bright_down for zone: {zone_name}")
                    await self.primitives.zone_bright_down(zone_name, "webserver")
                elif service == "color_up":
                    logger.info(f"[webserver] zone color_up for zone: {zone_name}")
                    await self.primitives.zone_color_up(zone_name, "webserver")
                elif service == "color_down":
                    logger.info(f"[webserver] zone color_down for zone: {zone_name}")
                    await self.primitives.zone_color_down(zone_name, "webserver")
                elif service == "set_position":
                    value = event_data.get('value')
                    mode = event_data.get('mode', 'step')
                    logger.info(f"[webserver] zone set_position({value}, {mode}) for zone: {zone_name}")
                    await self.primitives.zone_set_position(zone_name, value, mode, "webserver")
                elif service == "glozone_reset":
                    logger.info(f"[webserver] glozone_reset for zone: {zone_name}")
                    await self.primitives.glozone_reset(zone_name, "webserver")
                elif service == "glozone_down":
                    logger.info(f"[webserver] glozone_down for zone: {zone_name}")
                    await self.primitives.glozone_down(zone_name, "webserver")
                else:
                    logger.warning(f"Unknown circadian_light_zone_action: service={service}, zone_name={zone_name}")

            # Handle device registry updates (log only, use Sync button to apply)
            elif event_type == "device_registry_updated":
                action = event_data.get("action")
                device_id = event_data.get("device_id")
                logger.debug(f"Device registry updated: action={action}, device_id={device_id}")

            # Handle area registry updates (log only, use Sync button to apply)
            elif event_type == "area_registry_updated":
                action = event_data.get("action")
                area_id = event_data.get("area_id")
                logger.debug(f"Area registry updated: action={action}, area_id={area_id}")

            # Handle entity registry updates (log only, use Sync button to apply)
            elif event_type == "entity_registry_updated":
                action = event_data.get("action")
                entity_id = event_data.get("entity_id")
                changes = event_data.get("changes", {})
                if "area_id" in changes:
                    old_area = changes["area_id"].get("old_value")
                    new_area = changes["area_id"].get("new_value")
                    logger.info(f"Entity {entity_id} moved from area {old_area} to {new_area} (press Sync to apply)")
            
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

                # Handle motion sensor state changes
                if entity_id and entity_id in self.motion_sensor_ids:
                    new_state_val = new_state.get("state") if isinstance(new_state, dict) else None
                    old_state_val = old_state.get("state") if isinstance(old_state, dict) else None
                    if new_state_val and new_state_val != old_state_val:
                        await self._handle_motion_event(entity_id, new_state_val, old_state_val)

                # Handle contact sensor state changes
                if entity_id and entity_id in self.contact_sensor_ids:
                    new_state_val = new_state.get("state") if isinstance(new_state, dict) else None
                    old_state_val = old_state.get("state") if isinstance(old_state, dict) else None
                    if new_state_val and new_state_val != old_state_val:
                        await self._handle_contact_event(entity_id, new_state_val, old_state_val)
                # Debug: Log contact-looking sensors that aren't cached
                elif entity_id and entity_id.startswith("binary_sensor.") and any(x in entity_id for x in ["_opening", "_door", "_window", "_contact"]):
                    new_state_val = new_state.get("state") if isinstance(new_state, dict) else None
                    old_state_val = old_state.get("state") if isinstance(old_state, dict) else None
                    if new_state_val and new_state_val != old_state_val:
                        logger.warning(f"[Contact] State changed for uncached sensor: {entity_id} ({old_state_val} -> {new_state_val})")

            # Handle ZHA events (switch button presses)
            elif event_type == "zha_event":
                logger.info(f"ZHA event received: {event_data}")
                await self._handle_zha_event(event_data)

            # Handle Hue events (switch button presses from Hue hub)
            elif event_type == "hue_event":
                logger.info(f"Hue event received: {event_data}")
                await self._handle_hue_event(event_data)

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
                    for entity_state in result:
                        entity_id = entity_state.get("entity_id", "")
                        self.cached_states[entity_id] = entity_state

                        attributes = entity_state.get("attributes", {})

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
                    for entity_id, entity_state in self.cached_states.items():
                        if entity_id.startswith("light."):
                            friendly_name = entity_state.get("attributes", {}).get("friendly_name", "")
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
        # When the main message loop is active, delegate to send_and_await
        # which uses futures resolved by the message loop instead of calling recv() directly
        if self._message_loop_active:
            return await self.send_and_await(message)

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
    
    async def send_and_await(
        self,
        message: Dict[str, Any],
        timeout: float = 10.0,
    ) -> Optional[Dict[str, Any]]:
        """Send a WebSocket message and await its response via the main message loop.

        Unlike send_message_wait_response (which calls recv() directly and conflicts
        with the main message loop), this method registers a Future that the main
        message loop resolves when the matching response arrives.

        Safe to call while the message loop is running.
        """
        if not self.websocket:
            logger.error("WebSocket not connected")
            return None

        message["id"] = self._get_next_message_id()
        msg_id = message["id"]

        loop = asyncio.get_event_loop()
        future = loop.create_future()
        self._pending_responses[msg_id] = future

        try:
            await self.websocket.send(json.dumps(message))
        except Exception as e:
            self._pending_responses.pop(msg_id, None)
            logger.error(f"WebSocket send failed for id={msg_id}: {e}")
            return None

        try:
            data = await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending_responses.pop(msg_id, None)
            logger.error(f"Timeout waiting for response to message id={msg_id}")
            return None

        # Return inner result on success
        if isinstance(data, dict) and data.get("type") == "result" and data.get("success", False):
            return data.get("result")

        err = data.get("error") if isinstance(data, dict) else None
        if err:
            logger.error(f"Error response to id={msg_id}: {err}")
        return None

    def _resolve_pending_response(self, message: Dict[str, Any]) -> bool:
        """Check if an incoming message matches a pending response future.

        Returns True if the message was consumed by a pending future.
        """
        msg_id = message.get("id")
        if msg_id is not None and msg_id in self._pending_responses:
            future = self._pending_responses.pop(msg_id)
            if not future.done():
                future.set_result(message)
            return True
        return False

    async def listen(self):
        """Main listener loop."""
        try:
            logger.info(f"Connecting to {self.websocket_url}")
            
            async with websockets.connect(self.websocket_url, ping_timeout=40) as websocket:
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

                # Pre-fetch areas to populate area_name_to_id mapping BEFORE loading states
                # This ensures group registration can look up area_id from area_name
                zigbee_controller = self.light_controller.controllers.get(Protocol.ZIGBEE)
                if zigbee_controller:
                    try:
                        areas = await zigbee_controller.get_areas()
                        self.area_name_to_id.clear()
                        for area_id, area_info in areas.items():
                            area_name = area_info.get('name', '')
                            if area_name:
                                normalized_name = area_name.lower().replace(' ', '_')
                                self.area_name_to_id[normalized_name] = area_id
                                self.area_name_to_id[area_name.lower()] = area_id
                        logger.info(f"Pre-loaded {len(self.area_name_to_id)} area name mappings")
                    except Exception as e:
                        logger.warning(f"Failed to pre-load area mappings: {e}")

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
                    for entity_state in states:
                        entity_id = entity_state.get("entity_id", "")
                        if entity_id.startswith("light."):
                            attributes = entity_state.get("attributes", {})
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
                logger.info("Started periodic light updater")
                
                # Listen for messages
                logger.info("Listening for events...")
                self._message_loop_active = True
                async for message in websocket:
                    try:
                        msg = json.loads(message)
                        # Route responses to pending futures before general handling
                        if not self._resolve_pending_response(msg):
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
            self._message_loop_active = False
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
