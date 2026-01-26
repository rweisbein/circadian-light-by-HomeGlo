#!/usr/bin/env python3
"""Circadian Light Primitives - Core actions triggered via service calls or switches."""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import glozone
import glozone_state
import state
from brain import (
    CircadianLight,
    Config,
    AreaState,
    SunTimes,
    get_current_hour,
    DEFAULT_MAX_DIM_STEPS,
)

logger = logging.getLogger(__name__)


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
        data_dir = os.path.join(os.path.dirname(__file__), ".data")
        os.makedirs(data_dir, exist_ok=True)
        return data_dir


class CircadianLightPrimitives:
    """Handles all Circadian Light primitive actions/service calls."""

    def __init__(self, websocket_client, config_loader=None):
        """Initialize the Circadian Light primitives handler.

        Args:
            websocket_client: Reference to the HomeAssistantWebSocketClient instance
            config_loader: Optional callable that returns config dict. If not provided,
                          will try to load from client.
        """
        self.client = websocket_client
        self._config_loader = config_loader

    def _get_config(self, area_id: Optional[str] = None) -> Config:
        """Load config, optionally zone-aware for a specific area.

        Args:
            area_id: Optional area ID. If provided, returns zone-specific config
                     (preset settings merged with global settings).
        """
        config_dict = {}

        # If area_id provided, use zone-aware config
        if area_id:
            try:
                config_dict = glozone.get_effective_config_for_area(area_id)
                if config_dict:
                    return Config.from_dict(config_dict)
            except Exception as e:
                logger.warning(f"Zone-aware config failed for {area_id}: {e}")

        # Try config loader
        if self._config_loader:
            try:
                config_dict = self._config_loader() or {}
            except Exception as e:
                logger.warning(f"Config loader failed: {e}")

        # Load from config files directly (same as update_lights_in_circadian_mode)
        if not config_dict:
            data_dir = _get_data_directory()
            for filename in ["options.json", "designer_config.json"]:
                path = os.path.join(data_dir, filename)
                if os.path.exists(path):
                    try:
                        with open(path, 'r') as f:
                            part = json.load(f)
                            if isinstance(part, dict):
                                config_dict.update(part)
                    except Exception as e:
                        logger.debug(f"Could not load config from {path}: {e}")

        # Fall back to client config if still empty
        if not config_dict and hasattr(self.client, "config"):
            config_dict = self.client.config or {}

        return Config.from_dict(config_dict)

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

    def _get_turn_off_transition(self) -> float:
        """Get the turn-off transition time in seconds.

        Reads from global config, defaults to 0.3 seconds (3 tenths).
        The setting is stored as tenths of seconds in config.

        Returns:
            Transition time in seconds
        """
        try:
            raw_config = glozone.load_config_from_files()
            tenths = raw_config.get("turn_off_transition", 3)
            return tenths / 10.0  # Convert tenths to seconds
        except Exception:
            return 0.3  # Default 0.3 seconds

    async def _turn_off_area(self, area_id: str, transition: float = 0.3) -> None:
        """Turn off all lights in an area.

        Args:
            area_id: The area ID to turn off
            transition: Transition time in seconds
        """
        target_type, target_value = await self.client.determine_light_target(area_id)
        await self.client.call_service(
            "light", "turn_off", {"transition": transition}, {target_type: target_value}
        )

    def _get_area_state(self, area_id: str) -> AreaState:
        """Get area state from state module."""
        state_dict = state.get_area(area_id)
        return AreaState.from_dict(state_dict)

    def _update_area_state(self, area_id: str, updates: Dict[str, Any]) -> None:
        """Update area state in state module."""
        state.update_area(area_id, updates)

    # -------------------------------------------------------------------------
    # Step Up / Step Down (brightness-primary, both curves)
    # -------------------------------------------------------------------------

    async def step_up(self, area_id: str, source: str = "service_call"):
        """Step up along the circadian curve (brighter and cooler).

        Uses brightness-primary algorithm: brightness determines the step,
        color follows the diverged curve.

        Only works when is_circadian=True. Updates midpoints always, but only
        applies to lights if is_on=True.

        Args:
            area_id: The area ID to control
            source: Source of the action
        """
        area_state = self._get_area_state(area_id)

        if not area_state.is_circadian:
            logger.debug(f"[{source}] step_up ignored for area {area_id} (not in circadian mode)")
            return

        # Auto-unfreeze if frozen (re-anchors midpoints for smooth transition)
        if area_state.frozen_at is not None:
            self._unfreeze_internal(area_id, source)
            area_state = self._get_area_state(area_id)  # Refresh after unfreeze

        logger.info(f"[{source}] Step up for area {area_id}")

        config = self._get_config(area_id)
        hour = get_current_hour()
        sun_times = self.client._get_sun_times() if hasattr(self.client, '_get_sun_times') else None

        result = CircadianLight.calculate_step(
            hour=hour,
            direction="up",
            config=config,
            state=area_state,
            sun_times=sun_times,
        )

        if result is None:
            logger.info(f"Step up at limit for area {area_id}")
            # Bounce effect at limit (only if is_on)
            if area_state.is_on:
                current_bri = CircadianLight.calculate_brightness_at_hour(hour, config, area_state)
                current_cct = CircadianLight.calculate_color_at_hour(hour, config, area_state, apply_solar_rules=True, sun_times=sun_times)
                await self._bounce_at_limit(area_id, current_bri, current_cct)
            return

        # Update state (always, even if is_on=False)
        logger.info(f"Step up state_updates: {result.state_updates}")
        self._update_area_state(area_id, result.state_updates)

        # Apply to lights only if is_on=True
        if area_state.is_on:
            await self._apply_circadian_lighting(area_id, result.brightness, result.color_temp)
            logger.info(f"Step up applied: {result.brightness}%, {result.color_temp}K")
        else:
            logger.info(f"Step up state updated (lights off): {result.brightness}%, {result.color_temp}K")

    async def step_down(self, area_id: str, source: str = "service_call"):
        """Step down along the circadian curve (dimmer and warmer).

        Uses brightness-primary algorithm: brightness determines the step,
        color follows the diverged curve.

        Only works when is_circadian=True. Updates midpoints always, but only
        applies to lights if is_on=True.

        Args:
            area_id: The area ID to control
            source: Source of the action
        """
        area_state = self._get_area_state(area_id)

        if not area_state.is_circadian:
            logger.debug(f"[{source}] step_down ignored for area {area_id} (not in circadian mode)")
            return

        # Auto-unfreeze if frozen (re-anchors midpoints for smooth transition)
        if area_state.frozen_at is not None:
            self._unfreeze_internal(area_id, source)
            area_state = self._get_area_state(area_id)  # Refresh after unfreeze

        logger.info(f"[{source}] Step down for area {area_id}")

        config = self._get_config(area_id)
        hour = get_current_hour()
        sun_times = self.client._get_sun_times() if hasattr(self.client, '_get_sun_times') else None

        result = CircadianLight.calculate_step(
            hour=hour,
            direction="down",
            config=config,
            state=area_state,
            sun_times=sun_times,
        )

        if result is None:
            logger.info(f"Step down at limit for area {area_id}")
            # Bounce effect at limit (only if is_on)
            if area_state.is_on:
                current_bri = CircadianLight.calculate_brightness_at_hour(hour, config, area_state)
                current_cct = CircadianLight.calculate_color_at_hour(hour, config, area_state, apply_solar_rules=True, sun_times=sun_times)
                await self._bounce_at_limit(area_id, current_bri, current_cct)
            return

        # Update state (always, even if is_on=False)
        self._update_area_state(area_id, result.state_updates)

        # Apply to lights only if is_on=True
        if area_state.is_on:
            await self._apply_circadian_lighting(area_id, result.brightness, result.color_temp)
            logger.info(f"Step down applied: {result.brightness}%, {result.color_temp}K")
        else:
            logger.info(f"Step down state updated (lights off): {result.brightness}%, {result.color_temp}K")

    # -------------------------------------------------------------------------
    # Bright Up / Bright Down (brightness only)
    # -------------------------------------------------------------------------

    async def bright_up(self, area_id: str, source: str = "service_call"):
        """Increase brightness only, color unchanged.

        Only works when is_circadian=True. Updates midpoints always, but only
        applies to lights if is_on=True.

        Args:
            area_id: The area ID to control
            source: Source of the action
        """
        area_state = self._get_area_state(area_id)

        if not area_state.is_circadian:
            logger.debug(f"[{source}] bright_up ignored for area {area_id} (not in circadian mode)")
            return

        # Auto-unfreeze if frozen (re-anchors midpoints for smooth transition)
        if area_state.frozen_at is not None:
            self._unfreeze_internal(area_id, source)
            area_state = self._get_area_state(area_id)  # Refresh after unfreeze

        logger.info(f"[{source}] Bright up for area {area_id}")

        config = self._get_config(area_id)
        hour = get_current_hour()
        sun_times = self.client._get_sun_times() if hasattr(self.client, '_get_sun_times') else None

        result = CircadianLight.calculate_bright_step(
            hour=hour,
            direction="up",
            config=config,
            state=area_state,
            sun_times=sun_times,
        )

        if result is None:
            logger.info(f"Bright up at limit for area {area_id}")
            if area_state.is_on:
                current_bri = CircadianLight.calculate_brightness_at_hour(hour, config, area_state)
                current_cct = CircadianLight.calculate_color_at_hour(hour, config, area_state, apply_solar_rules=True, sun_times=sun_times)
                await self._bounce_at_limit(area_id, current_bri, current_cct)
            return

        # Update state (always, even if is_on=False)
        self._update_area_state(area_id, result.state_updates)

        # Apply to lights only if is_on=True
        if area_state.is_on:
            await self._apply_circadian_lighting(
                area_id, result.brightness, result.color_temp, include_color=False
            )
            logger.info(f"Bright up applied: {result.brightness}%")
        else:
            logger.info(f"Bright up state updated (lights off): {result.brightness}%")

    async def bright_down(self, area_id: str, source: str = "service_call"):
        """Decrease brightness only, color unchanged.

        Only works when is_circadian=True. Updates midpoints always, but only
        applies to lights if is_on=True.

        Args:
            area_id: The area ID to control
            source: Source of the action
        """
        area_state = self._get_area_state(area_id)

        if not area_state.is_circadian:
            logger.debug(f"[{source}] bright_down ignored for area {area_id} (not in circadian mode)")
            return

        # Auto-unfreeze if frozen (re-anchors midpoints for smooth transition)
        if area_state.frozen_at is not None:
            self._unfreeze_internal(area_id, source)
            area_state = self._get_area_state(area_id)  # Refresh after unfreeze

        logger.info(f"[{source}] Bright down for area {area_id}")

        config = self._get_config(area_id)
        hour = get_current_hour()
        sun_times = self.client._get_sun_times() if hasattr(self.client, '_get_sun_times') else None

        result = CircadianLight.calculate_bright_step(
            hour=hour,
            direction="down",
            config=config,
            state=area_state,
            sun_times=sun_times,
        )

        if result is None:
            logger.info(f"Bright down at limit for area {area_id}")
            if area_state.is_on:
                current_bri = CircadianLight.calculate_brightness_at_hour(hour, config, area_state)
                current_cct = CircadianLight.calculate_color_at_hour(hour, config, area_state, apply_solar_rules=True, sun_times=sun_times)
                await self._bounce_at_limit(area_id, current_bri, current_cct)
            return

        # Update state (always, even if is_on=False)
        self._update_area_state(area_id, result.state_updates)

        # Apply to lights only if is_on=True
        if area_state.is_on:
            await self._apply_circadian_lighting(
                area_id, result.brightness, result.color_temp, include_color=False
            )
            logger.info(f"Bright down applied: {result.brightness}%")
        else:
            logger.info(f"Bright down state updated (lights off): {result.brightness}%")

    # -------------------------------------------------------------------------
    # Color Up / Color Down (color only)
    # -------------------------------------------------------------------------

    async def color_up(self, area_id: str, source: str = "service_call"):
        """Increase color temperature (cooler), brightness unchanged.

        Only works when is_circadian=True. Updates midpoints always, but only
        applies to lights if is_on=True.

        Args:
            area_id: The area ID to control
            source: Source of the action
        """
        area_state = self._get_area_state(area_id)

        if not area_state.is_circadian:
            logger.debug(f"[{source}] color_up ignored for area {area_id} (not in circadian mode)")
            return

        # Auto-unfreeze if frozen (re-anchors midpoints for smooth transition)
        if area_state.frozen_at is not None:
            self._unfreeze_internal(area_id, source)
            area_state = self._get_area_state(area_id)  # Refresh after unfreeze

        logger.info(f"[{source}] Color up for area {area_id}")

        config = self._get_config(area_id)
        hour = get_current_hour()
        sun_times = self.client._get_sun_times() if hasattr(self.client, '_get_sun_times') else None

        result = CircadianLight.calculate_color_step(
            hour=hour,
            direction="up",
            config=config,
            state=area_state,
            sun_times=sun_times,
        )

        if result is None:
            logger.info(f"Color up at limit for area {area_id}")
            if area_state.is_on:
                current_bri = CircadianLight.calculate_brightness_at_hour(hour, config, area_state)
                current_cct = CircadianLight.calculate_color_at_hour(hour, config, area_state, apply_solar_rules=True, sun_times=sun_times)
                await self._bounce_at_limit(area_id, current_bri, current_cct)
            return

        # Update state (always, even if is_on=False)
        self._update_area_state(area_id, result.state_updates)

        # Apply to lights only if is_on=True
        if area_state.is_on:
            await self._apply_color_only(area_id, result.color_temp)
            logger.info(f"Color up applied: {result.color_temp}K")
        else:
            logger.info(f"Color up state updated (lights off): {result.color_temp}K")

    async def color_down(self, area_id: str, source: str = "service_call"):
        """Decrease color temperature (warmer), brightness unchanged.

        Only works when is_circadian=True. Updates midpoints always, but only
        applies to lights if is_on=True.

        Args:
            area_id: The area ID to control
            source: Source of the action
        """
        area_state = self._get_area_state(area_id)

        if not area_state.is_circadian:
            logger.debug(f"[{source}] color_down ignored for area {area_id} (not in circadian mode)")
            return

        # Auto-unfreeze if frozen (re-anchors midpoints for smooth transition)
        if area_state.frozen_at is not None:
            self._unfreeze_internal(area_id, source)
            area_state = self._get_area_state(area_id)  # Refresh after unfreeze

        logger.info(f"[{source}] Color down for area {area_id}")

        config = self._get_config(area_id)
        hour = get_current_hour()
        sun_times = self.client._get_sun_times() if hasattr(self.client, '_get_sun_times') else None

        result = CircadianLight.calculate_color_step(
            hour=hour,
            direction="down",
            config=config,
            state=area_state,
            sun_times=sun_times,
        )

        if result is None:
            logger.info(f"Color down at limit for area {area_id}")
            if area_state.is_on:
                current_bri = CircadianLight.calculate_brightness_at_hour(hour, config, area_state)
                current_cct = CircadianLight.calculate_color_at_hour(hour, config, area_state, apply_solar_rules=True, sun_times=sun_times)
                await self._bounce_at_limit(area_id, current_bri, current_cct)
            return

        # Update state (always, even if is_on=False)
        self._update_area_state(area_id, result.state_updates)

        # Apply to lights only if is_on=True
        if area_state.is_on:
            await self._apply_color_only(area_id, result.color_temp)
            logger.info(f"Color down applied: {result.color_temp}K")
        else:
            logger.info(f"Color down state updated (lights off): {result.color_temp}K")

    # -------------------------------------------------------------------------
    # Lights On / Off / Toggle - Control light state under Circadian management
    # -------------------------------------------------------------------------

    async def lights_on(
        self,
        area_id: str,
        source: str = "service_call",
        boost_brightness: int = None,
        boost_duration: int = None,
    ):
        """Turn on lights with Circadian values and enable Circadian control.

        If is_circadian was False, resets all runtime state (midpoints, frozen_at, etc.)
        before enabling. Sets is_on=True and applies circadian lighting.

        Optionally applies boost in the same operation to avoid intermediate brightness
        steps (e.g., going directly to 51% instead of 11% then 51%).

        Args:
            area_id: The area ID to control
            source: Source of the action
            boost_brightness: Optional boost percentage to add (0-100). If provided,
                boost_duration must also be provided.
            boost_duration: Optional boost duration in seconds (0 = forever). Required
                if boost_brightness is provided.
        """
        has_boost = boost_brightness is not None and boost_duration is not None
        if has_boost:
            logger.info(f"[{source}] lights_on for area {area_id} with boost={boost_brightness}%, duration={'forever' if boost_duration == 0 else f'{boost_duration}s'}")
        else:
            logger.info(f"[{source}] lights_on for area {area_id}")

        # Ensure area is in a zone (add to default zone if not)
        if not glozone.is_area_in_any_zone(area_id):
            glozone.add_area_to_default_zone(area_id)
            logger.info(f"Added area {area_id} to default zone")

        # Check if lights were already on BEFORE enabling (for two-step decision)
        lights_were_on = state.is_circadian(area_id) and state.get_is_on(area_id)

        # Enable circadian control and set is_on=True (resets state if was not circadian)
        was_circadian = state.enable_circadian_and_set_on(area_id, True)

        # Calculate and apply lighting
        config = self._get_config(area_id)
        area_state = self._get_area_state(area_id)
        hour = area_state.frozen_at if area_state.frozen_at is not None else get_current_hour()
        sun_times = self.client._get_sun_times() if hasattr(self.client, '_get_sun_times') else None

        result = CircadianLight.calculate_lighting(hour, config, area_state, sun_times=sun_times)
        transition = self._get_turn_on_transition()

        # Calculate final brightness (with boost if provided)
        if has_boost:
            final_brightness = min(100, result.brightness + boost_brightness)
        else:
            final_brightness = result.brightness

        if lights_were_on:
            # Lights already on - just adjust, no two-step needed
            await self._apply_lighting(area_id, final_brightness, result.color_temp, include_color=True, transition=transition)
        else:
            # Lights were off - use two-phase turn-on to avoid color jump
            await self._apply_lighting_turn_on(area_id, final_brightness, result.color_temp, transition=transition)

        # Set boost state if boost was provided
        if has_boost:
            is_forever = boost_duration == 0
            expires_at = "forever" if is_forever else (datetime.now() + timedelta(seconds=boost_duration)).isoformat()
            # started_from_off is True since we just turned lights on (not already on case is handled by bright_boost directly)
            started_from_off = not lights_were_on
            state.set_boost(area_id, started_from_off=started_from_off, expires_at=expires_at, brightness=boost_brightness)
            logger.info(
                f"lights_on for area {area_id}: {result.brightness}% + {boost_brightness}% = {final_brightness}%, "
                f"{result.color_temp}K (hour={hour:.2f}, boost expires={expires_at})"
            )
        else:
            logger.info(
                f"lights_on for area {area_id}: {final_brightness}%, {result.color_temp}K "
                f"(hour={hour:.2f}, was_circadian={was_circadian}, lights_were_on={lights_were_on})"
            )

    async def lights_off(self, area_id: str, source: str = "service_call"):
        """Turn off lights and set is_on=False (Circadian enforces off state).

        If is_circadian was False, resets all runtime state before enabling.
        Sets is_on=False and turns off lights. Clears any active boost or motion timer.

        Args:
            area_id: The area ID to control
            source: Source of the action
        """
        logger.info(f"[{source}] lights_off for area {area_id}")

        # Clear boost state if boosted
        if state.is_boosted(area_id):
            state.clear_boost(area_id)
            logger.info(f"Cleared boost for area {area_id}")

        # Clear motion on_off timer if active
        if state.has_motion_timer(area_id):
            state.clear_motion_expires(area_id)

        # Store CT before turning off for smart 2-step on next turn-on
        try:
            config = self._get_config(area_id)
            area_state = self._get_area_state(area_id)
            hour = area_state.frozen_at if area_state.frozen_at is not None else get_current_hour()
            sun_times = self.client._get_sun_times() if hasattr(self.client, '_get_sun_times') else None
            result = CircadianLight.calculate_lighting(hour, config, area_state, sun_times=sun_times)
            state.set_last_off_ct(area_id, result.color_temp)
        except Exception as e:
            logger.warning(f"Could not calculate CT for area {area_id}: {e}")

        # Enable circadian control and set is_on=False (resets state if was not circadian)
        was_circadian = state.enable_circadian_and_set_on(area_id, False)

        # Turn off lights
        transition = self._get_turn_off_transition()
        target_type, target_value = await self.client.determine_light_target(area_id)
        await self.client.call_service(
            "light", "turn_off", {"transition": transition}, {target_type: target_value}
        )

        logger.info(f"lights_off for area {area_id} (was_circadian={was_circadian})")

    async def circadian_off(self, area_id: str, source: str = "service_call"):
        """Release Circadian control for an area (lights unchanged).

        Sets is_circadian=False. Also cancels any active boost and motion timer.
        The is_on state becomes stale but is ignored when is_circadian=False.

        Args:
            area_id: The area ID to control
            source: Source of the action
        """
        logger.info(f"[{source}] circadian_off for area {area_id}")

        # Clear boost state if boosted
        if state.is_boosted(area_id):
            state.clear_boost(area_id)
            logger.info(f"Cleared boost for area {area_id}")

        # Clear motion on_off timer if active
        if state.has_motion_timer(area_id):
            state.clear_motion_expires(area_id)

        if not state.is_circadian(area_id):
            logger.info(f"Circadian Light already disabled for area {area_id}")
            return

        state.set_is_circadian(area_id, False)
        logger.info(f"Circadian Light disabled for area {area_id}, lights unchanged")

    async def circadian_on(self, area_id: str, source: str = "service_call"):
        """Resume Circadian control for an area with preserved settings.

        Sets is_circadian=True, preserving all settings (midpoints, frozen_at, is_on).
        Applies lighting based on preserved is_on state:
        - If is_on=True: Apply circadian lighting
        - If is_on=False: Turn off lights

        Use this to return control to Circadian after circadian_off.
        Use lights_on/off/toggle instead if you want to explicitly set is_on.

        Args:
            area_id: The area ID to control
            source: Source of the action
        """
        logger.info(f"[{source}] circadian_on for area {area_id}")

        if state.is_circadian(area_id):
            logger.info(f"Circadian Light already enabled for area {area_id}")
            # Still apply lighting in case state changed
        else:
            state.set_is_circadian(area_id, True)
            logger.info(f"Circadian Light resumed for area {area_id}")

        # Apply lighting based on preserved is_on state
        is_on = state.get_is_on(area_id)
        if is_on:
            # Apply circadian lighting with preserved settings
            config = self._get_config(area_id)
            area_state = self._get_area_state(area_id)
            hour = area_state.frozen_at if area_state.frozen_at is not None else get_current_hour()
            result = CircadianLight.calculate_lighting(hour, config, area_state)
            transition = self._get_turn_on_transition()
            await self._apply_lighting_turn_on(area_id, result.brightness, result.color_temp, transition)
            logger.info(f"circadian_on applied: {result.brightness}%, {result.color_temp}K (is_on=True)")
        else:
            # Enforce off state
            transition = self._get_turn_off_transition()
            await self._turn_off_area(area_id, transition=transition)
            logger.info(f"circadian_on enforced off state (is_on=False)")

    async def lights_toggle(self, area_id: str, source: str = "service_call"):
        """Toggle lights under Circadian control.

        Uses collective logic via lights_toggle_multiple.
        If lights on: turn off (is_on=False)
        If lights off: turn on with Circadian values (is_on=True)

        Args:
            area_id: The area ID to control
            source: Source of the action
        """
        await self.lights_toggle_multiple([area_id], source)

    async def lights_toggle_multiple(self, area_ids: list, source: str = "service_call"):
        """Toggle lights for multiple areas with collective logic.

        If ANY lights are on in ANY area: turn all off, set is_on=False
        If ALL lights are off: turn all on with Circadian values, set is_on=True

        If is_circadian was False for any area, it gets reset (midpoints cleared)
        before being enabled.

        Args:
            area_ids: List of area IDs
            source: Source of the action
        """
        if isinstance(area_ids, str):
            area_ids = [area_ids]

        logger.info(f"[{source}] lights_toggle_multiple for areas: {area_ids}")

        # Check if any lights are on
        any_on = await self.client.any_lights_on_in_area(area_ids)

        if any_on:
            # Turn off all areas - store CT first for smart 2-step on next turn-on
            transition = self._get_turn_off_transition()
            sun_times = self.client._get_sun_times() if hasattr(self.client, '_get_sun_times') else None
            for area_id in area_ids:
                # Calculate current CT before turning off
                try:
                    config = self._get_config(area_id)
                    area_state = self._get_area_state(area_id)
                    hour = area_state.frozen_at if area_state.frozen_at is not None else get_current_hour()
                    result = CircadianLight.calculate_lighting(hour, config, area_state, sun_times=sun_times)
                    state.set_last_off_ct(area_id, result.color_temp)
                    logger.debug(f"Stored last_off_ct={result.color_temp} for area {area_id}")
                except Exception as e:
                    logger.warning(f"Could not calculate CT for area {area_id}: {e}")

                # Clear boost state if boosted
                if state.is_boosted(area_id):
                    state.clear_boost(area_id)
                    logger.info(f"Cleared boost for area {area_id}")

                # Clear motion on_off timer if active
                if state.has_motion_timer(area_id):
                    state.clear_motion_expires(area_id)

                # Enable circadian and set is_on=False
                state.enable_circadian_and_set_on(area_id, False)
                target_type, target_value = await self.client.determine_light_target(area_id)
                await self.client.call_service(
                    "light", "turn_off", {"transition": transition}, {target_type: target_value}
                )
            logger.info(f"lights_toggle_multiple: turned off {len(area_ids)} area(s)")

        else:
            # Turn on all areas with Circadian values
            transition = self._get_turn_on_transition()
            # Get sun times for solar rules (same as periodic update)
            sun_times = self.client._get_sun_times() if hasattr(self.client, '_get_sun_times') else None
            for area_id in area_ids:
                # Ensure area is in a zone (add to default zone if not)
                if not glozone.is_area_in_any_zone(area_id):
                    glozone.add_area_to_default_zone(area_id)
                    logger.info(f"Added area {area_id} to default zone")

                # Enable circadian and set is_on=True (resets state if was not circadian)
                state.enable_circadian_and_set_on(area_id, True)

                # Get zone-aware config and calculate lighting
                config = self._get_config(area_id)
                area_state = self._get_area_state(area_id)
                # Use area's frozen_at if set, otherwise current time
                hour = area_state.frozen_at if area_state.frozen_at is not None else get_current_hour()

                result = CircadianLight.calculate_lighting(hour, config, area_state, sun_times=sun_times)
                # Use two-phase turn-on to avoid color jump from previous light state
                await self._apply_lighting_turn_on(area_id, result.brightness, result.color_temp, transition=transition)

            logger.info(f"lights_toggle_multiple: turned on {len(area_ids)} area(s)")

    # -------------------------------------------------------------------------
    # Bright Boost - Temporary brightness increase
    # -------------------------------------------------------------------------

    async def bright_boost(
        self,
        area_id: str,
        duration_seconds: int,
        boost_amount: int,
        source: str = "motion_sensor",
        lights_were_off: bool = None
    ):
        """Temporarily boost brightness for an area.

        Adds boost_amount percentage points to current circadian brightness.
        After duration expires, returns to previous state:
        - If lights were off when boost started: turn off
        - If lights were on: return to circadian brightness

        MAX logic when already boosted:
        - boost % = MAX(current %, new %)
        - If current timer is forever: stays forever
        - If current timer is timed: timer = MAX(remaining, new duration)

        Args:
            area_id: The area ID to boost
            duration_seconds: How long the boost lasts (0 = forever)
            boost_amount: Brightness percentage points to add (0-100)
            source: Source of the action (e.g., "motion_sensor", "contact_sensor")
            lights_were_off: If provided, use this instead of checking current light state.
                This is useful when boost is called after motion_on_off, which already
                turned the lights on - we need to know the state BEFORE motion_on_off ran.
        """
        is_forever = duration_seconds == 0
        logger.info(f"[{source}] bright_boost for area {area_id}, duration={'forever' if is_forever else f'{duration_seconds}s'}, boost={boost_amount}%")

        # Check if already boosted - apply MAX logic
        if state.is_boosted(area_id):
            boost_state = state.get_boost_state(area_id)
            current_brightness = boost_state.get("boost_brightness") or 0
            current_is_forever = boost_state.get("is_forever", False)
            current_expires = boost_state.get("boost_expires_at")

            # MAX logic for brightness - always use higher
            new_brightness = max(current_brightness, boost_amount)
            if new_brightness > current_brightness:
                state.update_boost_brightness(area_id, new_brightness)
                # Re-apply lighting with new boost level
                await self._apply_current_boost(area_id, new_brightness)
                logger.info(f"[{source}] Increased boost brightness to {new_brightness}% for area {area_id}")

            # MAX logic for timer
            if current_is_forever:
                # Forever boost stays forever, can't be shortened
                logger.debug(f"[{source}] Area {area_id} has forever boost, timer unchanged")
            elif is_forever:
                # New boost is forever, upgrade to forever
                state.update_boost_expires(area_id, "forever")
                logger.info(f"[{source}] Upgraded boost to forever for area {area_id}")
            else:
                # Both are timed - use MAX
                now = datetime.now()
                current_remaining = (datetime.fromisoformat(current_expires) - now).total_seconds()
                if duration_seconds > current_remaining:
                    new_expires = (now + timedelta(seconds=duration_seconds)).isoformat()
                    state.update_boost_expires(area_id, new_expires)
                    logger.info(f"[{source}] Extended boost timer to {new_expires} for area {area_id}")
                else:
                    logger.debug(f"[{source}] Keeping existing timer ({current_remaining:.0f}s remaining > {duration_seconds}s new)")
            return

        # Not currently boosted - start new boost
        # Determine started_from_off for boost end behavior:
        # - Use provided lights_were_off if available (state BEFORE motion_on_off ran)
        # - Otherwise use our own state tracking (is_circadian + is_on)
        if lights_were_off is not None:
            started_from_off = lights_were_off
            # If lights_were_off is provided, we're being called right after lights_on.
            # Lights are NOW on (either lights_on just turned them on, or they were already on).
            lights_currently_on = True
        else:
            # Use our own state tracking - no need to query HA
            # If area is under circadian control and is_on=True, lights are on
            is_on = state.is_circadian(area_id) and state.get_is_on(area_id)
            started_from_off = not is_on
            lights_currently_on = is_on

        # Calculate circadian values
        config = self._get_config(area_id)
        area_state = self._get_area_state(area_id)
        hour = area_state.frozen_at if area_state.frozen_at is not None else get_current_hour()
        sun_times = self.client._get_sun_times() if hasattr(self.client, '_get_sun_times') else None

        result = CircadianLight.calculate_lighting(hour, config, area_state, sun_times=sun_times)

        # Calculate boosted brightness
        boosted_brightness = min(100, result.brightness + boost_amount)

        # Set boost state
        expires_at = "forever" if is_forever else (datetime.now() + timedelta(seconds=duration_seconds)).isoformat()
        state.set_boost(area_id, started_from_off=started_from_off, expires_at=expires_at, brightness=boost_amount)

        # Enable Circadian Light and set is_on=True
        if not glozone.is_area_in_any_zone(area_id):
            glozone.add_area_to_default_zone(area_id)
        state.enable_circadian_and_set_on(area_id, True)

        # Apply boosted brightness with circadian color temp
        transition = self._get_turn_on_transition()
        if lights_currently_on:
            # Lights already on - just adjust brightness
            await self._apply_lighting(area_id, boosted_brightness, result.color_temp, transition=transition)
        else:
            # Lights were off - use two-phase turn-on
            await self._apply_lighting_turn_on(area_id, boosted_brightness, result.color_temp, transition=transition)

        logger.info(
            f"[{source}] Boosted area {area_id}: {result.brightness}% + {boost_amount}% = {boosted_brightness}%, "
            f"{result.color_temp}K, expires={expires_at}"
        )

    async def _apply_current_boost(self, area_id: str, boost_amount: int):
        """Re-apply lighting with current boost level (for when boost % increases)."""
        config = self._get_config(area_id)
        area_state = self._get_area_state(area_id)
        hour = area_state.frozen_at if area_state.frozen_at is not None else get_current_hour()
        sun_times = self.client._get_sun_times() if hasattr(self.client, '_get_sun_times') else None

        result = CircadianLight.calculate_lighting(hour, config, area_state, sun_times=sun_times)
        boosted_brightness = min(100, result.brightness + boost_amount)

        transition = self._get_turn_on_transition()
        await self._apply_lighting(area_id, boosted_brightness, result.color_temp, transition=transition)

    async def end_boost(self, area_id: str, source: str = "timer"):
        """End boost for an area and return to previous state.

        Called when boost timer expires or boost is explicitly cancelled.

        Args:
            area_id: The area ID
            source: Source of the action
        """
        boost_state = state.get_boost_state(area_id)

        if not boost_state["is_boosted"]:
            logger.debug(f"[{source}] Area {area_id} not boosted, nothing to end")
            return

        started_from_off = boost_state["boost_started_from_off"]

        # Clear boost state
        state.clear_boost(area_id)

        if started_from_off:
            # Lights were off when boost started - turn off and set is_on=False
            transition = self._get_turn_off_transition()
            await self._turn_off_area(area_id, transition=transition)
            state.set_is_on(area_id, False)
            logger.info(f"[{source}] Boost ended for area {area_id}, turned off (started from off)")
        else:
            # Lights were on - return to current circadian settings (is_on stays True)
            config = self._get_config(area_id)
            area_state = self._get_area_state(area_id)
            hour = area_state.frozen_at if area_state.frozen_at is not None else get_current_hour()
            sun_times = self.client._get_sun_times() if hasattr(self.client, '_get_sun_times') else None

            result = CircadianLight.calculate_lighting(hour, config, area_state, sun_times=sun_times)
            await self._apply_lighting(area_id, result.brightness, result.color_temp)
            logger.info(
                f"[{source}] Boost ended for area {area_id}, returned to circadian: "
                f"{result.brightness}%, {result.color_temp}K"
            )

    async def check_expired_boosts(self):
        """Check for and handle any expired boosts.

        Called periodically (e.g., from the 30-second update loop).
        """
        expired = state.get_expired_boosts()
        for area_id in expired:
            await self.end_boost(area_id, source="timer_expired")

    # -------------------------------------------------------------------------
    # Motion Sensor Actions
    # -------------------------------------------------------------------------

    async def motion_on_only(
        self,
        area_id: str,
        source: str = "motion_sensor",
        boost_brightness: int = None,
        boost_duration: int = None,
    ):
        """Turn on lights if off, do nothing if already on.

        on_only: Lights turn on with motion, stay on until manually turned off.

        Optionally applies boost in the same operation to avoid intermediate brightness
        steps when turning on.

        Args:
            area_id: The area ID to control
            source: Source of the action
            boost_brightness: Optional boost percentage to add (0-100)
            boost_duration: Optional boost duration in seconds (0 = forever)
        """
        has_boost = boost_brightness is not None and boost_duration is not None

        # Check if area is already on under circadian control
        if state.is_circadian(area_id) and state.get_is_on(area_id):
            logger.debug(f"[{source}] motion_on_only: area {area_id} already on, skipping")
            # If boost requested, apply it (lights already on, so no flash issue)
            if has_boost:
                await self.bright_boost(area_id, boost_duration, boost_brightness, source=source)
            return

        logger.info(f"[{source}] motion_on_only: turning on area {area_id}")

        # Turn on with circadian values (enables circadian control if needed)
        # Pass boost params so we go directly to final brightness (no intermediate step)
        await self.lights_on(area_id, source=source, boost_brightness=boost_brightness, boost_duration=boost_duration)

    async def motion_on_off(
        self,
        area_id: str,
        duration_seconds: int,
        source: str = "motion_sensor",
        boost_brightness: int = None,
        boost_duration: int = None,
    ):
        """Turn on lights with timer, auto-off when timer expires.

        on_off behavior:
        - If room is off: turn on, start timer
        - If room is on FROM on_off motion: use MAX(remaining, new duration) for timer
        - If room is on from other source: do nothing
        - duration_seconds=0 means "forever" (never auto-off, like on_only but with timer state)

        Optionally applies boost in the same operation to avoid intermediate brightness
        steps when turning on (e.g., going directly to 51% instead of 11% then 51%).

        Args:
            area_id: The area ID to control
            duration_seconds: How long before auto-off (0 = forever/never)
            source: Source of the action
            boost_brightness: Optional boost percentage to add (0-100)
            boost_duration: Optional boost duration in seconds (0 = forever)
        """
        is_forever = duration_seconds == 0
        has_boost = boost_brightness is not None and boost_duration is not None

        # Check if area has an active motion timer (was turned on by on_off motion)
        if state.has_motion_timer(area_id):
            current_expires = state.get_motion_expires(area_id)
            current_is_forever = current_expires == "forever"

            # MAX logic for timer
            if current_is_forever:
                # Forever timer stays forever, can't be shortened
                logger.debug(f"[{source}] motion_on_off: area {area_id} has forever timer, unchanged")
            elif is_forever:
                # New timer is forever, upgrade to forever
                state.extend_motion_expires(area_id, "forever")
                logger.info(f"[{source}] motion_on_off: upgraded timer to forever for area {area_id}")
            else:
                # Both are timed - use MAX(remaining, new duration)
                now = datetime.now()
                current_remaining = (datetime.fromisoformat(current_expires) - now).total_seconds()

                if duration_seconds > current_remaining:
                    new_expires = (now + timedelta(seconds=duration_seconds)).isoformat()
                    state.extend_motion_expires(area_id, new_expires)
                    logger.debug(f"[{source}] motion_on_off: extended timer for area {area_id} to {new_expires}")
                else:
                    logger.debug(f"[{source}] motion_on_off: keeping existing timer ({current_remaining:.0f}s remaining > {duration_seconds}s new)")

            # If boost requested, apply/extend it (lights already on, so no flash issue)
            if has_boost:
                await self.bright_boost(area_id, boost_duration, boost_brightness, source=source)
            return

        # Check if area is already on under circadian control (but not from on_off motion)
        if state.is_circadian(area_id) and state.get_is_on(area_id):
            logger.debug(f"[{source}] motion_on_off: area {area_id} already on (not from motion), skipping")
            # If boost requested, apply it (lights already on, so no flash issue)
            if has_boost:
                await self.bright_boost(area_id, boost_duration, boost_brightness, source=source)
            return

        logger.info(f"[{source}] motion_on_off: turning on area {area_id}, timer={'forever' if is_forever else f'{duration_seconds}s'}")

        # Set motion timer
        expires_at = "forever" if is_forever else (datetime.now() + timedelta(seconds=duration_seconds)).isoformat()
        state.set_motion_expires(area_id, expires_at)

        # Turn on with circadian values (enables circadian control if needed)
        # Pass boost params so we go directly to final brightness (no intermediate step)
        await self.lights_on(area_id, source=source, boost_brightness=boost_brightness, boost_duration=boost_duration)

    async def end_motion_on_off(self, area_id: str, source: str = "timer"):
        """End motion on_off timer and turn off lights.

        Called when motion on_off timer expires.

        Args:
            area_id: The area ID
            source: Source of the action
        """
        if not state.has_motion_timer(area_id):
            logger.debug(f"[{source}] Area {area_id} has no motion timer, nothing to end")
            return

        # Clear motion timer
        state.clear_motion_expires(area_id)

        # Turn off (set is_on=False, Circadian enforces off state)
        transition = self._get_turn_off_transition()
        await self._turn_off_area(area_id, transition=transition)
        state.set_is_on(area_id, False)
        logger.info(f"[{source}] Motion on_off timer expired for area {area_id}, turned off")

    async def check_expired_motion(self):
        """Check for and handle any expired motion on_off timers.

        Called periodically (e.g., from the 30-second update loop).
        """
        expired = state.get_expired_motion()
        for area_id in expired:
            # Clear any warning state before turning off
            state.clear_motion_warning(area_id)
            await self.end_motion_on_off(area_id, source="timer_expired")

    # -------------------------------------------------------------------------
    # Motion Warning
    # -------------------------------------------------------------------------

    def _get_motion_warning_config(self) -> tuple:
        """Get motion warning configuration.

        Returns:
            Tuple of (warning_time_seconds, blink_threshold_percent)
        """
        try:
            raw_config = glozone.load_config_from_files()
            warning_time = raw_config.get("motion_warning_time", 0)
            blink_threshold = raw_config.get("motion_warning_blink_threshold", 15)
            return (warning_time, blink_threshold)
        except Exception:
            return (0, 15)  # Defaults: disabled, 15%

    async def check_motion_warnings(self):
        """Check for areas that need motion warnings and trigger them.

        Called periodically (e.g., from the 30-second update loop).
        """
        warning_time, blink_threshold = self._get_motion_warning_config()

        if warning_time <= 0:
            return  # Warnings disabled

        needs_warning = state.get_areas_needing_warning(warning_time)
        for area_id in needs_warning:
            await self.trigger_motion_warning(area_id, blink_threshold)

    async def trigger_motion_warning(self, area_id: str, blink_threshold: int = 15):
        """Trigger motion warning for an area (dim or blink+dim).

        Warning behavior:
        - Above blink_threshold: Dim to 50% of current brightness
        - At or below blink_threshold: Blink off (300ms), then dim to 3%

        Args:
            area_id: The area ID
            blink_threshold: Brightness % below which to use blink warning
        """
        if state.is_motion_warned(area_id):
            logger.debug(f"[motion_warning] Area {area_id} already warned, skipping")
            return

        # Get current brightness
        config = self._get_config(area_id)
        area_state = self._get_area_state(area_id)
        hour = area_state.frozen_at if area_state.frozen_at is not None else get_current_hour()
        sun_times = self.client._get_sun_times() if hasattr(self.client, '_get_sun_times') else None

        result = CircadianLight.calculate_lighting(hour, config, area_state, sun_times=sun_times)
        current_brightness = result.brightness

        # Add boost if boosted
        if state.is_boosted(area_id):
            boost_state = state.get_boost_state(area_id)
            boost_amount = boost_state.get("boost_brightness") or 0
            current_brightness = min(100, current_brightness + boost_amount)

        # Store pre-warning brightness for potential restoration
        state.set_motion_warning(area_id, current_brightness)

        logger.info(f"[motion_warning] Triggering warning for area {area_id}, current brightness={current_brightness}%")

        if current_brightness > blink_threshold:
            # Above threshold: dim to 50% of current
            warning_brightness = int(current_brightness * 0.5)
            await self._apply_lighting(area_id, warning_brightness, result.color_temp, include_color=False, transition=0.5)
            logger.info(f"[motion_warning] Dimmed area {area_id} from {current_brightness}% to {warning_brightness}%")
        else:
            # At or below threshold: blink off, then hold at 3%
            await self._apply_lighting(area_id, 0, result.color_temp, include_color=False, transition=0.1)
            await asyncio.sleep(0.3)  # 300ms off
            warning_brightness = 3
            await self._apply_lighting(area_id, warning_brightness, result.color_temp, include_color=False, transition=0.1)
            logger.info(f"[motion_warning] Blinked area {area_id} (was {current_brightness}%), holding at {warning_brightness}%")

    async def cancel_motion_warning(self, area_id: str, source: str = "motion_detected"):
        """Cancel motion warning and restore brightness.

        Called when motion is detected during warning period.

        Args:
            area_id: The area ID
            source: Source of the cancellation
        """
        warning_state = state.get_motion_warning_state(area_id)

        if not warning_state["is_warned"]:
            return

        pre_warning_brightness = warning_state["pre_warning_brightness"]

        # Clear warning state
        state.clear_motion_warning(area_id)

        # Restore brightness
        if pre_warning_brightness is not None:
            config = self._get_config(area_id)
            area_state = self._get_area_state(area_id)
            hour = area_state.frozen_at if area_state.frozen_at is not None else get_current_hour()
            sun_times = self.client._get_sun_times() if hasattr(self.client, '_get_sun_times') else None

            result = CircadianLight.calculate_lighting(hour, config, area_state, sun_times=sun_times)
            await self._apply_lighting(area_id, pre_warning_brightness, result.color_temp, transition=0.3)
            logger.info(f"[{source}] Cancelled motion warning for area {area_id}, restored to {pre_warning_brightness}%")

    async def contact_off(self, area_id: str, source: str = "contact_sensor"):
        """Turn off lights and disable Circadian for contact sensor close event.

        Used when a contact sensor closes (door/window) with on_off function.
        Clears any motion timer, turns off lights, and disables Circadian.

        Args:
            area_id: The area ID
            source: Source of the action
        """
        # Clear any motion timer
        state.clear_motion_expires(area_id)

        # Turn off (set is_on=False, Circadian enforces off state)
        transition = self._get_turn_off_transition()
        await self._turn_off_area(area_id, transition=transition)
        state.set_is_on(area_id, False)
        logger.info(f"[{source}] Contact closed: turned off area {area_id}")

    # -------------------------------------------------------------------------
    # Set - Configure area state (presets, frozen_at, copy_from)
    # -------------------------------------------------------------------------

    async def set(
        self, area_id: str, source: str = "service_call",
        preset: str = None, frozen_at: float = None, copy_from: str = None,
        is_on: bool = None
    ):
        """Configure area state with presets, frozen_at, or copy settings.

        Presets:
            - wake: Set midpoint to current time (50% values), NOT frozen
            - bed: Same as wake - set midpoint to current time, NOT frozen
            - nitelite: Freeze at ascend_start (minimum values)
            - britelite: Freeze at descend_start (maximum values)

        Priority: copy_from > frozen_at > preset

        Args:
            area_id: The area ID
            source: Source of the action
            preset: Optional preset name (wake, bed, nitelite, britelite)
            frozen_at: Optional specific hour (0-24) to freeze at
            copy_from: Optional area_id to copy settings from
            is_on: Controls whether to take control:
                - None (default): just configure settings, don't change control state
                - True: configure + take control + turn on
                - False: configure + take control + turn off
        """
        config = self._get_config(area_id)
        current_hour = get_current_hour()

        # Take control if is_on is explicitly set (not None)
        take_control = is_on is not None
        if take_control:
            state.enable_circadian_and_set_on(area_id, is_on)
            logger.info(f"[{source}] Taking control of area {area_id} with is_on={is_on}")

        # Priority 1: copy_from another area
        if copy_from:
            source_state = state.get_area(copy_from)
            if source_state:
                # Copy relevant state from source area (midpoints and frozen_at only)
                state.update_area(area_id, {
                    "frozen_at": source_state.get("frozen_at"),
                    "brightness_mid": source_state.get("brightness_mid"),
                    "color_mid": source_state.get("color_mid"),
                })
                logger.info(f"[{source}] Copied settings from {copy_from} to {area_id}")

                # Apply lighting or turn off based on state
                if state.is_circadian(area_id) and state.get_is_on(area_id):
                    area_state = self._get_area_state(area_id)
                    hour = area_state.frozen_at if area_state.frozen_at is not None else current_hour
                    result = CircadianLight.calculate_lighting(hour, config, area_state)
                    await self._apply_circadian_lighting(area_id, result.brightness, result.color_temp)
                elif take_control and is_on == False:
                    transition = self._get_turn_off_transition()
                    await self._turn_off_area(area_id, transition=transition)
                return
            else:
                logger.warning(f"[{source}] copy_from area {copy_from} not found")

        # Priority 2: explicit frozen_at
        if frozen_at is not None:
            state.set_frozen_at(area_id, float(frozen_at))
            logger.info(f"[{source}] Set {area_id} frozen_at={frozen_at:.2f}")

            # Apply lighting or turn off based on state
            if state.is_circadian(area_id) and state.get_is_on(area_id):
                area_state = self._get_area_state(area_id)
                result = CircadianLight.calculate_lighting(frozen_at, config, area_state)
                await self._apply_circadian_lighting(area_id, result.brightness, result.color_temp)
            elif take_control and is_on == False:
                transition = self._get_turn_off_transition()
                await self._turn_off_area(area_id, transition=transition)
            return

        # Priority 3: preset
        if preset:
            # Reset state first (clears midpoints, bounds, frozen_at; preserves enabled)
            state.reset_area(area_id)

            if preset in ("wake", "bed"):
                # Set midpoint to current time (produces ~50% values), stays unfrozen
                # get_phase_info returns: (in_ascend, h48, t_ascend, t_descend, slope)
                in_ascend, h48, t_ascend, t_descend, slope = CircadianLight.get_phase_info(
                    current_hour, config
                )
                state.update_area(area_id, {
                    "brightness_mid": h48,
                    "color_mid": h48,
                })
                logger.info(f"[{source}] Set {area_id} to {preset} preset (midpoint={h48:.2f})")

            elif preset == "nitelite":
                # Freeze at ascend_start (minimum values)
                # Reset midpoints to ensure true minimum brightness/color
                frozen_hour = config.ascend_start
                state.update_area(area_id, {
                    "brightness_mid": None,
                    "color_mid": None,
                })
                state.set_frozen_at(area_id, frozen_hour)
                logger.info(f"[{source}] Set {area_id} to nitelite preset (frozen_at={frozen_hour})")

            elif preset == "britelite":
                # Freeze at descend_start (maximum values)
                # Reset midpoints to ensure true maximum brightness/color
                frozen_hour = config.descend_start
                state.update_area(area_id, {
                    "brightness_mid": None,
                    "color_mid": None,
                })
                state.set_frozen_at(area_id, frozen_hour)
                logger.info(f"[{source}] Set {area_id} to britelite preset (frozen_at={frozen_hour})")

            else:
                logger.warning(f"[{source}] Unknown preset: {preset}")
                return

            # Apply lighting or turn off based on state
            if state.is_circadian(area_id) and state.get_is_on(area_id):
                area_state = self._get_area_state(area_id)
                hour = area_state.frozen_at if area_state.frozen_at is not None else current_hour
                logger.info(f"[{source}] Preset apply: area_state.frozen_at={area_state.frozen_at}, using hour={hour}")
                result = CircadianLight.calculate_lighting(hour, config, area_state)
                logger.info(f"[{source}] Preset calculated: brightness={result.brightness}%, color_temp={result.color_temp}K at hour={hour}")
                # Use turn_on_transition for presets (they're typically turn-on actions), boost-aware
                transition = self._get_turn_on_transition()
                await self._apply_circadian_lighting(area_id, result.brightness, result.color_temp, transition=transition)
            elif take_control and is_on == False:
                transition = self._get_turn_off_transition()
                await self._turn_off_area(area_id, transition=transition)

    # -------------------------------------------------------------------------
    # Freeze Toggle (kept for manual toggling)
    # -------------------------------------------------------------------------

    def _unfreeze_internal(self, area_id: str, source: str = "internal"):
        """Internal unfreeze: re-anchor midpoints so curve continues smoothly.

        Re-anchors midpoints so current time produces the same values as
        the frozen position, then clears frozen_at. No sudden jump.

        Args:
            area_id: The area ID
            source: Source of the action
        """
        from brain import inverse_midpoint

        frozen_at = state.get_frozen_at(area_id)
        if frozen_at is None:
            return

        config = self._get_config(area_id)
        area_state = self._get_area_state(area_id)
        current_hour = get_current_hour()

        # Calculate current frozen values
        frozen_result = CircadianLight.calculate_lighting(frozen_at, config, area_state)
        frozen_bri = frozen_result.brightness
        frozen_color = frozen_result.color_temp

        # Get phase info for current time to determine slope
        # get_phase_info returns: (in_ascend, h48, t_ascend, t_descend, slope)
        in_ascend, h48, t_ascend, t_descend, slope = CircadianLight.get_phase_info(
            current_hour, config
        )

        # h48 is already the current hour lifted to 48h space
        lifted_hour = h48

        # Use config bounds (no more runtime overrides)
        b_min = config.min_brightness
        b_max = config.max_brightness
        c_min = config.min_color_temp
        c_max = config.max_color_temp

        # Calculate new midpoints that produce frozen values at current time
        new_bri_mid = inverse_midpoint(lifted_hour, frozen_bri, slope, b_min, b_max)
        new_color_mid = inverse_midpoint(lifted_hour, frozen_color, slope, c_min, c_max)

        # Update state with new midpoints and clear frozen_at
        state.update_area(area_id, {
            "brightness_mid": new_bri_mid,
            "color_mid": new_color_mid,
            "frozen_at": None,
        })

        logger.info(
            f"[{source}] Unfrozen {area_id}: re-anchored midpoints to "
            f"bri_mid={new_bri_mid:.2f}, color_mid={new_color_mid:.2f}"
        )

    async def freeze_toggle(self, area_id: str, source: str = "service_call"):
        """Toggle freeze state with visual effect.

        Unfrozen → Frozen: dim over 0.3s, brighten instantly
        Frozen → Unfrozen: dim over 0.3s, brighten over 1s

        Args:
            area_id: The area ID
            source: Source of the action
        """
        import asyncio

        is_frozen = state.is_frozen(area_id)
        config = self._get_config(area_id)

        if not state.is_circadian(area_id):
            logger.info(f"[{source}] Area {area_id} not in circadian mode, skipping freeze_toggle")
            return

        # Both directions dim over 0.3s
        # Freeze: flash on instantly (0s)
        # Unfreeze: rise over 1s
        dim_duration = 0.3

        await self._apply_lighting(area_id, 0, 2700, include_color=False, transition=dim_duration)
        await asyncio.sleep(dim_duration + 0.1)  # Wait for transition to complete

        if is_frozen:
            # Was frozen → unfreeze (re-anchor midpoints)
            self._unfreeze_internal(area_id, source)

            # Rise to unfrozen values over 1s (boost-aware)
            area_state = self._get_area_state(area_id)
            hour = get_current_hour()
            result = CircadianLight.calculate_lighting(hour, config, area_state)
            await self._apply_circadian_lighting(area_id, result.brightness, result.color_temp, transition=1.0)

            logger.info(f"[{source}] Freeze toggle: {area_id} unfrozen")

        else:
            # Was unfrozen → freeze at current time
            frozen_at = get_current_hour()
            state.set_frozen_at(area_id, frozen_at)

            # Flash up to frozen values instantly (boost-aware)
            area_state = self._get_area_state(area_id)
            result = CircadianLight.calculate_lighting(frozen_at, config, area_state)
            await self._apply_circadian_lighting(area_id, result.brightness, result.color_temp, transition=0)

            logger.info(f"[{source}] Freeze toggle: {area_id} frozen at hour {frozen_at:.2f}")

    async def freeze_toggle_multiple(self, area_ids: list, source: str = "service_call"):
        """Toggle freeze state for multiple areas with single visual effect.

        All areas dim together, then brighten together (one bounce, not multiple).

        Args:
            area_ids: List of area IDs
            source: Source of the action
        """
        import asyncio

        if not area_ids:
            return

        # Filter to areas under circadian control
        circadian_areas = [a for a in area_ids if state.is_circadian(a)]
        if not circadian_areas:
            logger.info(f"[{source}] No circadian areas for freeze_toggle_multiple")
            return

        # Check freeze state of first area (all should be same, but use first as reference)
        is_frozen = state.is_frozen(circadian_areas[0])

        # Both directions dim over 0.3s
        # Freeze: flash on instantly (0s)
        # Unfreeze: rise over 1s
        dim_duration = 0.3

        # Dim ALL areas to 0%
        for area_id in circadian_areas:
            await self._apply_lighting(area_id, 0, 2700, include_color=False, transition=dim_duration)

        await asyncio.sleep(dim_duration + 0.1)  # Wait for transition to complete

        if is_frozen:
            # Was frozen → unfreeze all
            for area_id in circadian_areas:
                self._unfreeze_internal(area_id, source)

            # Rise ALL areas to unfrozen values over 1s (boost-aware)
            hour = get_current_hour()
            for area_id in circadian_areas:
                config = self._get_config(area_id)
                area_state = self._get_area_state(area_id)
                result = CircadianLight.calculate_lighting(hour, config, area_state)
                await self._apply_circadian_lighting(area_id, result.brightness, result.color_temp, transition=1.0)

            logger.info(f"[{source}] Freeze toggle: {len(circadian_areas)} area(s) unfrozen")

        else:
            # Was unfrozen → freeze all at current time
            frozen_at = get_current_hour()
            for area_id in circadian_areas:
                state.set_frozen_at(area_id, frozen_at)

            # Flash ALL areas up to frozen values instantly (boost-aware)
            for area_id in circadian_areas:
                config = self._get_config(area_id)
                area_state = self._get_area_state(area_id)
                result = CircadianLight.calculate_lighting(frozen_at, config, area_state)
                await self._apply_circadian_lighting(area_id, result.brightness, result.color_temp, transition=0)

            logger.info(f"[{source}] Freeze toggle: {len(circadian_areas)} area(s) frozen at hour {frozen_at:.2f}")

    # -------------------------------------------------------------------------
    # Reset
    # -------------------------------------------------------------------------

    async def reset(self, area_id: str, source: str = "service_call"):
        """Reset area to base config values.

        Resets midpoints, bounds, and frozen_at to defaults.
        Preserves enabled status. Only applies lighting if already enabled.

        Args:
            area_id: The area ID
            source: Source of the action
        """
        logger.info(f"[{source}] Resetting area {area_id}")

        # Reset state (clears midpoints/bounds/frozen_at, preserves only enabled)
        state.reset_area(area_id)

        # Apply current time values only if circadian and is_on
        if state.is_circadian(area_id) and state.get_is_on(area_id):
            config = self._get_config(area_id)
            area_state = self._get_area_state(area_id)
            hour = get_current_hour()

            result = CircadianLight.calculate_lighting(hour, config, area_state)
            await self._apply_circadian_lighting(area_id, result.brightness, result.color_temp)

            logger.info(
                f"Reset complete for area {area_id}: "
                f"{result.brightness}%, {result.color_temp}K"
            )
        else:
            logger.info(f"Reset complete for area {area_id} (not circadian or lights off, no lighting change)")

    # -------------------------------------------------------------------------
    # GloZone Primitives - Zone-based state synchronization
    # -------------------------------------------------------------------------

    async def glo_up(self, area_id: str, source: str = "service_call"):
        """Push area's runtime state to its zone, then propagate to all areas in zone.

        GloUp syncs the entire zone to match this area's state. Use when you want
        all areas in a zone to match the current area's brightness/color settings.

        Args:
            area_id: The area ID to push from
            source: Source of the action
        """
        logger.info(f"[{source}] GloUp for area {area_id}")

        # Reload glozone config from disk (webserver may have updated it)
        glozone.reload()

        # Get the zone this area belongs to
        zone_name = glozone.get_zone_for_area(area_id)
        logger.info(f"Area {area_id} is in zone '{zone_name}'")

        # Get the area's current runtime state
        area_state_dict = state.get_area(area_id)
        runtime_state = {
            "brightness_mid": area_state_dict.get("brightness_mid"),
            "color_mid": area_state_dict.get("color_mid"),
            "frozen_at": area_state_dict.get("frozen_at"),
        }

        # Push to zone state
        glozone_state.set_zone_state(zone_name, runtime_state)
        logger.info(f"Pushed state to zone '{zone_name}': {runtime_state}")

        # Get all areas in the zone
        zone_areas = glozone.get_areas_in_zone(zone_name)
        logger.info(f"Zone '{zone_name}' has {len(zone_areas)} area(s): {zone_areas}")

        # Propagate to all other areas in the zone
        for target_area_id in zone_areas:
            if target_area_id == area_id:
                continue  # Skip the source area

            # Copy state to target area
            state.update_area(target_area_id, runtime_state)
            logger.debug(f"Copied state to area {target_area_id}")

            # Apply lighting if the target area is circadian and is_on
            # Use centralized update function which handles boost, frozen state, etc.
            if state.is_circadian(target_area_id) and state.get_is_on(target_area_id):
                await self.client.update_lights_in_circadian_mode(target_area_id)
                logger.debug(f"Triggered lighting update for {target_area_id}")

        logger.info(f"GloUp complete: synced {len(zone_areas)} area(s) in zone '{zone_name}'")

    async def glo_down(self, area_id: str, source: str = "service_call"):
        """Pull zone's runtime state to this area.

        GloDown syncs this area to match its zone's state. Use when you want
        a single area to rejoin the zone's current settings.

        Also cancels any active boost for the area.

        Args:
            area_id: The area ID to sync to zone state
            source: Source of the action
        """
        logger.info(f"[{source}] GloDown for area {area_id}")

        # Clear boost state if boosted (GloDown overrides boost)
        if state.is_boosted(area_id):
            state.clear_boost(area_id)
            logger.info(f"Cleared boost for area {area_id} (GloDown)")

        # Reload glozone config from disk (webserver may have updated it)
        glozone.reload()

        # Get the zone this area belongs to
        zone_name = glozone.get_zone_for_area(area_id)
        logger.info(f"Area {area_id} is in zone '{zone_name}'")

        # Get zone's runtime state
        zone_state = glozone_state.get_zone_state(zone_name)
        logger.info(f"Zone '{zone_name}' state: {zone_state}")

        # Copy zone state to area
        state.update_area(area_id, {
            "brightness_mid": zone_state.get("brightness_mid"),
            "color_mid": zone_state.get("color_mid"),
            "frozen_at": zone_state.get("frozen_at"),
        })
        logger.info(f"Copied zone state to area {area_id}")

        # Apply lighting if area is circadian and is_on
        # Use centralized update function for consistency
        if state.is_circadian(area_id) and state.get_is_on(area_id):
            await self.client.update_lights_in_circadian_mode(area_id)
            logger.info(f"GloDown complete for {area_id}")
        else:
            logger.info(f"GloDown complete for {area_id} (not circadian or lights off, no lighting change)")

    async def glo_reset(self, area_id: str, source: str = "service_call"):
        """Reset zone runtime state to defaults, reset all member areas.

        GloReset clears the zone's state (brightness_mid, color_mid, frozen_at
        all become None), and resets all member areas. All areas return to
        following the preset's default circadian curve.

        Args:
            area_id: Any area ID in the zone to reset
            source: Source of the action
        """
        logger.info(f"[{source}] GloReset for area {area_id}")

        # Reload glozone config from disk (webserver may have updated it)
        glozone.reload()

        # Get the zone this area belongs to
        zone_name = glozone.get_zone_for_area(area_id)
        logger.info(f"Area {area_id} is in zone '{zone_name}'")

        # Reset zone state to defaults (None)
        glozone_state.reset_zone_state(zone_name)
        logger.info(f"Reset zone '{zone_name}' runtime state to defaults")

        # Get all areas in the zone
        zone_areas = glozone.get_areas_in_zone(zone_name)
        logger.info(f"Zone '{zone_name}' has {len(zone_areas)} area(s): {zone_areas}")

        # Reset all areas in the zone
        for target_area_id in zone_areas:
            # Reset area state (clears midpoints/bounds/frozen_at, preserves enabled)
            state.reset_area(target_area_id)
            logger.debug(f"Reset area {target_area_id}")

            # Apply lighting if area is circadian and is_on
            # Use centralized update function for consistency
            if state.is_circadian(target_area_id) and state.get_is_on(target_area_id):
                await self.client.update_lights_in_circadian_mode(target_area_id)
                logger.debug(f"Triggered lighting update for {target_area_id}")

        logger.info(f"GloReset complete: reset {len(zone_areas)} area(s) in zone '{zone_name}'")

    # -------------------------------------------------------------------------
    # Helper methods
    # -------------------------------------------------------------------------

    async def _apply_lighting(
        self,
        area_id: str,
        brightness: int,
        color_temp: int,
        include_color: bool = True,
        transition: float = 0.4,
    ):
        """Apply lighting values to an area.

        Splits lights by color capability:
        - Color-capable lights (xy/rgb/hs): Use xy_color for full color range including warm orange/red
        - CT-only lights: Use color_temp_kelvin (clamped to 2000K minimum)

        Args:
            area_id: The area ID
            brightness: Brightness percentage (0-100)
            color_temp: Color temperature in Kelvin
            include_color: Whether to include color in the command
            transition: Transition time in seconds
        """
        color_lights, ct_lights = self.client.get_lights_by_color_capability(area_id)

        # If no lights found in cache, fall back to area-based control
        if not color_lights and not ct_lights:
            target_type, target_value = await self.client.determine_light_target(area_id)
            service_data = {
                "brightness_pct": brightness,
                "transition": transition,
            }
            if include_color:
                service_data["color_temp_kelvin"] = max(2000, color_temp)

            logger.info(f"_apply_lighting (fallback): {target_type}={target_value}, service_data={service_data}")
            await self.client.call_service("light", "turn_on", service_data, {target_type: target_value})
            return

        tasks: List[asyncio.Task] = []

        # Color-capable lights: use xy_color for full color range
        if color_lights and include_color:
            xy = CircadianLight.color_temperature_to_xy(color_temp)
            color_data = {
                "brightness_pct": brightness,
                "xy_color": list(xy),
                "transition": transition,
            }
            logger.info(f"_apply_lighting (color): entity_id={color_lights}, xy={xy}, brightness={brightness}%")
            tasks.append(
                asyncio.create_task(
                    self.client.call_service("light", "turn_on", color_data, {"entity_id": color_lights})
                )
            )
        elif color_lights:
            # Brightness only for color lights
            bri_data = {
                "brightness_pct": brightness,
                "transition": transition,
            }
            logger.info(f"_apply_lighting (color, bri only): entity_id={color_lights}, brightness={brightness}%")
            tasks.append(
                asyncio.create_task(
                    self.client.call_service("light", "turn_on", bri_data, {"entity_id": color_lights})
                )
            )

        # CT-only lights: use color_temp_kelvin (clamped to 2000K min)
        if ct_lights and include_color:
            clamped_temp = max(2000, color_temp)
            ct_data = {
                "brightness_pct": brightness,
                "color_temp_kelvin": clamped_temp,
                "transition": transition,
            }
            logger.info(f"_apply_lighting (CT): entity_id={ct_lights}, color_temp_kelvin={clamped_temp}, brightness={brightness}%")
            tasks.append(
                asyncio.create_task(
                    self.client.call_service("light", "turn_on", ct_data, {"entity_id": ct_lights})
                )
            )
        elif ct_lights:
            # Brightness only for CT lights
            bri_data = {
                "brightness_pct": brightness,
                "transition": transition,
            }
            logger.info(f"_apply_lighting (CT, bri only): entity_id={ct_lights}, brightness={brightness}%")
            tasks.append(
                asyncio.create_task(
                    self.client.call_service("light", "turn_on", bri_data, {"entity_id": ct_lights})
                )
            )

        # Run all tasks concurrently
        if tasks:
            await asyncio.gather(*tasks)

    async def _apply_circadian_lighting(
        self,
        area_id: str,
        brightness: int,
        color_temp: int,
        include_color: bool = True,
        transition: float = 0.4,
    ):
        """Apply circadian lighting with boost awareness.

        This is a wrapper around _apply_lighting that automatically adds boost
        brightness if the area is boosted. Use this for circadian lighting updates
        where boost should be applied (step_up/down, freeze, etc.).

        Use _apply_lighting directly when you've already calculated the final
        brightness (e.g., motion sensor boost functions).

        Args:
            area_id: The area ID
            brightness: Base circadian brightness percentage (0-100)
            color_temp: Color temperature in Kelvin
            include_color: Whether to include color in the command
            transition: Transition time in seconds
        """
        # Apply boost if area is boosted
        final_brightness = brightness
        if state.is_boosted(area_id):
            boost_state = state.get_boost_state(area_id)
            boost_amount = boost_state.get("boost_brightness") or 0
            final_brightness = min(100, brightness + boost_amount)
            logger.debug(f"Boost applied: {brightness}% + {boost_amount}% = {final_brightness}%")

        await self._apply_lighting(area_id, final_brightness, color_temp, include_color, transition)

    async def _apply_lighting_turn_on(
        self,
        area_id: str,
        brightness: int,
        color_temp: int,
        transition: float = 0.4,
    ):
        """Turn on lights, using two-phase approach only if needed to avoid color jump.

        When lights are off, they briefly show their previous color before
        transitioning. If the new color is significantly different (>= 500K),
        we use a two-phase approach:
        1. Phase 1: Turn on at 1% brightness with target color (instant)
        2. Phase 2: Transition to target brightness

        If the color is similar to what it was when turned off, we skip the
        two-phase and just turn on directly.

        Args:
            area_id: The area ID
            brightness: Target brightness percentage (0-100)
            color_temp: Color temperature in Kelvin
            transition: Transition time for phase 2 (brightness ramp)
        """
        # Check if 2-step is needed based on CT difference
        last_ct = state.get_last_off_ct(area_id)
        ct_threshold = 500  # Kelvin difference threshold for 2-step

        needs_two_step = True
        if last_ct is not None:
            ct_diff = abs(color_temp - last_ct)
            needs_two_step = ct_diff >= ct_threshold
            logger.debug(f"Turn-on CT check: last={last_ct}K, new={color_temp}K, diff={ct_diff}K, 2-step={needs_two_step}")

        if needs_two_step:
            # Phase 1: Set color at minimal brightness (nearly invisible)
            await self._apply_lighting(area_id, 1, color_temp, include_color=True, transition=0)

            # Small delay to ensure phase 1 completes
            await asyncio.sleep(0.05)

            # Phase 2: Transition to target brightness
            await self._apply_lighting(area_id, brightness, color_temp, include_color=True, transition=transition)
        else:
            # CT is similar - just turn on directly
            await self._apply_lighting(area_id, brightness, color_temp, include_color=True, transition=transition)

    async def _apply_color_only(
        self, area_id: str, color_temp: int, transition: float = 0.4
    ):
        """Apply color temperature only to an area.

        Splits lights by color capability:
        - Color-capable lights: Use xy_color for full color range
        - CT-only lights: Use color_temp_kelvin (clamped to 2000K minimum)

        Args:
            area_id: The area ID
            color_temp: Color temperature in Kelvin
            transition: Transition time in seconds
        """
        color_lights, ct_lights = self.client.get_lights_by_color_capability(area_id)

        # If no lights found in cache, fall back to area-based control
        if not color_lights and not ct_lights:
            target_type, target_value = await self.client.determine_light_target(area_id)
            service_data = {
                "color_temp_kelvin": max(2000, color_temp),
                "transition": transition,
            }
            logger.info(f"_apply_color_only (fallback): {target_type}={target_value}, service_data={service_data}")
            await self.client.call_service("light", "turn_on", service_data, {target_type: target_value})
            return

        tasks: List[asyncio.Task] = []

        # Color-capable lights: use xy_color for full color range
        if color_lights:
            xy = CircadianLight.color_temperature_to_xy(color_temp)
            color_data = {
                "xy_color": list(xy),
                "transition": transition,
            }
            logger.info(f"_apply_color_only (color): entity_id={color_lights}, xy={xy}")
            tasks.append(
                asyncio.create_task(
                    self.client.call_service("light", "turn_on", color_data, {"entity_id": color_lights})
                )
            )

        # CT-only lights: use color_temp_kelvin (clamped to 2000K min)
        if ct_lights:
            clamped_temp = max(2000, color_temp)
            ct_data = {
                "color_temp_kelvin": clamped_temp,
                "transition": transition,
            }
            logger.info(f"_apply_color_only (CT): entity_id={ct_lights}, color_temp_kelvin={clamped_temp}")
            tasks.append(
                asyncio.create_task(
                    self.client.call_service("light", "turn_on", ct_data, {"entity_id": ct_lights})
                )
            )

        # Run all tasks concurrently
        if tasks:
            await asyncio.gather(*tasks)

    async def _bounce_at_limit(self, area_id: str, current_brightness: int, current_color: int):
        """Visual bounce effect when hitting a bound limit.

        Dip depth scales with brightness - lower brightness = deeper dip.
        At 100%: dip to 50% (50% depth)
        At 50%: dip to 12.5% (75% depth)
        At 20%: dip to 2% (90% depth)
        At 10%: dip to 0.5% (95% depth)

        Always 0.3s down, 0.3s up.

        Note: This function is boost-aware. If the area is boosted, the bounce
        uses the effective (boosted) brightness, not just the circadian base.

        Args:
            area_id: The area ID
            current_brightness: Current circadian base brightness percentage
            current_color: Current color temperature in Kelvin
        """
        import asyncio

        # Add boost if area is boosted
        effective_brightness = current_brightness
        if state.is_boosted(area_id):
            boost_state = state.get_boost_state(area_id)
            boost_amount = boost_state.get("boost_brightness") or 0
            effective_brightness = min(100, current_brightness + boost_amount)

        # Depth scales from 50% (at 100 brightness) to 100% (at 0 brightness)
        depth_ratio = 0.5 + (100 - effective_brightness) / 200
        dim_brightness = max(0, int(effective_brightness * (1 - depth_ratio)))

        await self._apply_lighting(area_id, dim_brightness, current_color, include_color=False, transition=0.3)
        await asyncio.sleep(0.35)
        await self._apply_lighting(area_id, effective_brightness, current_color, transition=0.3)

        logger.info(f"Bounce effect for area {area_id}: {effective_brightness}% -> {dim_brightness}% -> {effective_brightness}%")

    async def _standard_brightness_step(
        self, area_id: str, direction: int, source: str
    ):
        """Apply standard HA brightness step when not in Circadian mode.

        Args:
            area_id: The area ID
            direction: 1 for increase, -1 for decrease
            source: Source of the action
        """
        logger.info(
            f"[{source}] Area {area_id} not in Circadian mode, using standard brightness"
        )

        any_on = await self.client.any_lights_on_in_area(area_id)
        if not any_on:
            logger.info(f"No lights on in area {area_id}")
            return

        config = self._get_config(area_id)
        steps = config.max_dim_steps or DEFAULT_MAX_DIM_STEPS
        step_pct = int(100 / steps)

        if step_pct == 0:
            step_pct = 1

        target_type, target_value = await self.client.determine_light_target(area_id)

        service_data = {
            "brightness_step_pct": step_pct * direction,
            "transition": 0.4,
        }

        await self.client.call_service(
            "light", "turn_on", service_data, {target_type: target_value}
        )

        logger.info(f"Brightness {'increased' if direction > 0 else 'decreased'} by {step_pct}%")
