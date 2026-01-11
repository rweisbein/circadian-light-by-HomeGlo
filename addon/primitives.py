#!/usr/bin/env python3
"""Circadian Light Primitives - Core actions triggered via service calls or switches."""

import json
import logging
import os
from typing import Any, Dict, Optional

import state
from brain import (
    CircadianLight,
    Config,
    AreaState,
    get_current_hour,
    DEFAULT_MAX_DIM_STEPS,
)

logger = logging.getLogger(__name__)


def _get_data_directory() -> str:
    """Get the appropriate data directory based on environment."""
    if os.path.exists("/data"):
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

    def _get_config(self) -> Config:
        """Load the global config from config files."""
        config_dict = {}

        # Try config loader first
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

        Args:
            area_id: The area ID to control
            source: Source of the action
        """
        area_state = self._get_area_state(area_id)

        if area_state.enabled:
            logger.info(f"[{source}] Step up for area {area_id}")

            config = self._get_config()
            hour = get_current_hour()

            result = CircadianLight.calculate_step(
                hour=hour,
                direction="up",
                config=config,
                state=area_state,
                brightness_locked=False,
                color_locked=False,
            )

            if result is None:
                logger.info(f"Step up at limit for area {area_id}")
                return

            # Update state
            self._update_area_state(area_id, result.state_updates)

            # Apply to lights
            await self._apply_lighting(area_id, result.brightness, result.color_temp)

            logger.info(
                f"Step up applied: {result.brightness}%, {result.color_temp}K"
            )

        else:
            # Not in Circadian mode - standard brightness increase
            await self._standard_brightness_step(area_id, direction=1, source=source)

    async def step_down(self, area_id: str, source: str = "service_call"):
        """Step down along the circadian curve (dimmer and warmer).

        Uses brightness-primary algorithm: brightness determines the step,
        color follows the diverged curve.

        Args:
            area_id: The area ID to control
            source: Source of the action
        """
        area_state = self._get_area_state(area_id)

        if area_state.enabled:
            logger.info(f"[{source}] Step down for area {area_id}")

            config = self._get_config()
            hour = get_current_hour()

            result = CircadianLight.calculate_step(
                hour=hour,
                direction="down",
                config=config,
                state=area_state,
                brightness_locked=False,
                color_locked=False,
            )

            if result is None:
                logger.info(f"Step down at limit for area {area_id}")
                return

            # Update state
            self._update_area_state(area_id, result.state_updates)

            # Apply to lights
            await self._apply_lighting(area_id, result.brightness, result.color_temp)

            logger.info(
                f"Step down applied: {result.brightness}%, {result.color_temp}K"
            )

        else:
            # Not in Circadian mode - standard brightness decrease
            await self._standard_brightness_step(area_id, direction=-1, source=source)

    # -------------------------------------------------------------------------
    # Bright Up / Bright Down (brightness only)
    # -------------------------------------------------------------------------

    async def bright_up(self, area_id: str, source: str = "service_call"):
        """Increase brightness only, color unchanged.

        Args:
            area_id: The area ID to control
            source: Source of the action
        """
        area_state = self._get_area_state(area_id)

        if area_state.enabled:
            logger.info(f"[{source}] Bright up for area {area_id}")

            config = self._get_config()
            hour = get_current_hour()

            result = CircadianLight.calculate_bright_step(
                hour=hour,
                direction="up",
                config=config,
                state=area_state,
                brightness_locked=False,
            )

            if result is None:
                logger.info(f"Bright up at limit for area {area_id}")
                return

            # Update state
            self._update_area_state(area_id, result.state_updates)

            # Apply to lights (brightness only)
            await self._apply_lighting(
                area_id, result.brightness, result.color_temp, include_color=False
            )

            logger.info(f"Bright up applied: {result.brightness}%")

        else:
            await self._standard_brightness_step(area_id, direction=1, source=source)

    async def bright_down(self, area_id: str, source: str = "service_call"):
        """Decrease brightness only, color unchanged.

        Args:
            area_id: The area ID to control
            source: Source of the action
        """
        area_state = self._get_area_state(area_id)

        if area_state.enabled:
            logger.info(f"[{source}] Bright down for area {area_id}")

            config = self._get_config()
            hour = get_current_hour()

            result = CircadianLight.calculate_bright_step(
                hour=hour,
                direction="down",
                config=config,
                state=area_state,
                brightness_locked=False,
            )

            if result is None:
                logger.info(f"Bright down at limit for area {area_id}")
                return

            # Update state
            self._update_area_state(area_id, result.state_updates)

            # Apply to lights (brightness only)
            await self._apply_lighting(
                area_id, result.brightness, result.color_temp, include_color=False
            )

            logger.info(f"Bright down applied: {result.brightness}%")

        else:
            await self._standard_brightness_step(area_id, direction=-1, source=source)

    # -------------------------------------------------------------------------
    # Color Up / Color Down (color only)
    # -------------------------------------------------------------------------

    async def color_up(self, area_id: str, source: str = "service_call"):
        """Increase color temperature (cooler), brightness unchanged.

        Args:
            area_id: The area ID to control
            source: Source of the action
        """
        area_state = self._get_area_state(area_id)

        if area_state.enabled:
            logger.info(f"[{source}] Color up for area {area_id}")

            config = self._get_config()
            hour = get_current_hour()

            result = CircadianLight.calculate_color_step(
                hour=hour,
                direction="up",
                config=config,
                state=area_state,
                color_locked=False,
                warm_night_locked=False,
                cool_day_locked=False,
            )

            if result is None:
                logger.info(f"Color up at limit for area {area_id}")
                return

            # Update state
            self._update_area_state(area_id, result.state_updates)

            # Apply to lights (color only)
            await self._apply_color_only(area_id, result.color_temp)

            logger.info(f"Color up applied: {result.color_temp}K")

        else:
            logger.info(f"[{source}] Area {area_id} not in Circadian mode, color_up ignored")

    async def color_down(self, area_id: str, source: str = "service_call"):
        """Decrease color temperature (warmer), brightness unchanged.

        Args:
            area_id: The area ID to control
            source: Source of the action
        """
        area_state = self._get_area_state(area_id)

        if area_state.enabled:
            logger.info(f"[{source}] Color down for area {area_id}")

            config = self._get_config()
            hour = get_current_hour()

            result = CircadianLight.calculate_color_step(
                hour=hour,
                direction="down",
                config=config,
                state=area_state,
                color_locked=False,
                warm_night_locked=False,
                cool_day_locked=False,
            )

            if result is None:
                logger.info(f"Color down at limit for area {area_id}")
                return

            # Update state
            self._update_area_state(area_id, result.state_updates)

            # Apply to lights (color only)
            await self._apply_color_only(area_id, result.color_temp)

            logger.info(f"Color down applied: {result.color_temp}K")

        else:
            logger.info(f"[{source}] Area {area_id} not in Circadian mode, color_down ignored")

    # -------------------------------------------------------------------------
    # Circadian On / Off / Toggle
    # -------------------------------------------------------------------------

    async def circadian_on(self, area_id: str, source: str = "service_call"):
        """Enable Circadian Light mode and turn on lights.

        Args:
            area_id: The area ID to control
            source: Source of the action
        """
        logger.info(f"[{source}] Enabling Circadian Light for area {area_id}")

        was_enabled = state.is_enabled(area_id)

        if was_enabled:
            logger.info(f"Circadian Light already enabled for area {area_id}")
            return

        # Enable in state
        state.set_enabled(area_id, True)

        # Calculate and apply current lighting
        config = self._get_config()
        area_state = self._get_area_state(area_id)
        hour = get_current_hour()

        result = CircadianLight.calculate_lighting(hour, config, area_state)
        await self._apply_lighting(area_id, result.brightness, result.color_temp)

        logger.info(
            f"Circadian Light enabled for area {area_id}: "
            f"{result.brightness}%, {result.color_temp}K"
        )

    async def circadian_off(self, area_id: str, source: str = "service_call"):
        """Disable Circadian Light mode (lights unchanged).

        Args:
            area_id: The area ID to control
            source: Source of the action
        """
        logger.info(f"[{source}] Disabling Circadian Light for area {area_id}")

        if not state.is_enabled(area_id):
            logger.info(f"Circadian Light already disabled for area {area_id}")
            return

        state.set_enabled(area_id, False)
        logger.info(f"Circadian Light disabled for area {area_id}, lights unchanged")

    async def circadian_toggle(self, area_id: str, source: str = "service_call"):
        """Toggle Circadian Light based on light state.

        If lights on: turn off and disable Circadian
        If lights off: turn on with Circadian values and enable

        Args:
            area_id: The area ID to control
            source: Source of the action
        """
        await self.circadian_toggle_multiple([area_id], source)

    async def circadian_toggle_multiple(self, area_ids: list, source: str = "service_call"):
        """Toggle Circadian Light for multiple areas.

        If ANY lights are on in ANY area: turn all off, disable Circadian
        If ALL lights are off: turn all on with Circadian values, enable

        Args:
            area_ids: List of area IDs
            source: Source of the action
        """
        if isinstance(area_ids, str):
            area_ids = [area_ids]

        logger.info(f"[{source}] Toggle for areas: {area_ids}")

        # Check if any lights are on
        any_on = await self.client.any_lights_on_in_area(area_ids)

        if any_on:
            # Turn off all areas
            for area_id in area_ids:
                state.set_enabled(area_id, False)
                target_type, target_value = await self.client.determine_light_target(area_id)
                await self.client.call_service(
                    "light", "turn_off", {"transition": 1}, {target_type: target_value}
                )
            logger.info(f"Turned off {len(area_ids)} area(s)")

        else:
            # Turn on all areas with Circadian values
            config = self._get_config()
            hour = get_current_hour()

            for area_id in area_ids:
                state.set_enabled(area_id, True)
                area_state = self._get_area_state(area_id)

                result = CircadianLight.calculate_lighting(hour, config, area_state)
                await self._apply_lighting(area_id, result.brightness, result.color_temp)

            logger.info(f"Turned on {len(area_ids)} area(s) with Circadian Light")

    # -------------------------------------------------------------------------
    # Freeze / Unfreeze
    # -------------------------------------------------------------------------

    async def freeze(
        self, area_id: str, source: str = "service_call",
        preset: str = None, hour: float = None
    ):
        """Freeze an area at a specific time position.

        When frozen, calculations use frozen_at instead of current time.
        Stepping while frozen shifts midpoints but keeps frozen_at.

        Args:
            area_id: The area ID
            source: Source of the action
            preset: Optional preset - None/"current", "nitelite", or "britelite"
            hour: Optional specific hour (0-24) to freeze at. Takes priority over preset.
        """
        config = self._get_config()

        # Priority: hour > preset > current time
        if hour is not None:
            frozen_at = float(hour)
            logger.info(f"[{source}] Freezing area {area_id} at hour {frozen_at:.2f}")
        elif preset == "nitelite":
            # Freeze at beginning of ascend phase (minimum values)
            frozen_at = config.ascend_start
            logger.info(f"[{source}] Freezing area {area_id} at nitelite (hour {frozen_at})")
        elif preset == "britelite":
            # Freeze at beginning of descend phase (maximum values)
            frozen_at = config.descend_start
            logger.info(f"[{source}] Freezing area {area_id} at britelite (hour {frozen_at})")
        else:
            # Freeze at current time
            frozen_at = get_current_hour()
            logger.info(f"[{source}] Freezing area {area_id} at current time (hour {frozen_at:.2f})")

        state.set_frozen_at(area_id, frozen_at)

        # Apply the frozen values immediately if enabled
        if state.is_enabled(area_id):
            area_state = self._get_area_state(area_id)
            result = CircadianLight.calculate_lighting(frozen_at, config, area_state)
            await self._apply_lighting(area_id, result.brightness, result.color_temp)

    async def unfreeze(self, area_id: str, source: str = "service_call"):
        """Unfreeze an area with smooth transition (re-anchor midpoints).

        Re-anchors midpoints so current time produces the same values as
        the frozen position, then clears frozen_at. No sudden jump.

        Args:
            area_id: The area ID
            source: Source of the action
        """
        from brain import inverse_midpoint

        frozen_at = state.get_frozen_at(area_id)
        if frozen_at is None:
            logger.info(f"[{source}] Area {area_id} already unfrozen")
            return

        logger.info(f"[{source}] Unfreezing area {area_id} (re-anchoring from hour {frozen_at:.2f})")

        config = self._get_config()
        area_state = self._get_area_state(area_id)
        current_hour = get_current_hour()

        # Calculate current frozen values
        frozen_result = CircadianLight.calculate_lighting(frozen_at, config, area_state)
        frozen_bri = frozen_result.brightness
        frozen_color = frozen_result.color_temp

        # Get phase info for current time to determine slope
        in_ascend, slope, default_mid, phase_start, phase_end = CircadianLight.get_phase_info(
            current_hour, config
        )

        # Lift current hour to 48h space for proper midpoint calculation
        lifted_hour = CircadianLight.lift_midpoint_to_phase(current_hour, phase_start, phase_end)

        # Get bounds
        b_min = area_state.min_brightness if area_state.min_brightness is not None else config.min_brightness
        b_max = area_state.max_brightness if area_state.max_brightness is not None else config.max_brightness
        c_min = area_state.min_color_temp if area_state.min_color_temp is not None else config.min_color_temp
        c_max = area_state.max_color_temp if area_state.max_color_temp is not None else config.max_color_temp

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
            f"Unfrozen area {area_id}: re-anchored midpoints to "
            f"bri_mid={new_bri_mid:.2f}, color_mid={new_color_mid:.2f}"
        )

    async def freeze_toggle(self, area_id: str, source: str = "service_call"):
        """Toggle freeze state with visual effect.

        Unfrozen → Frozen: dim to 0% over 1s, flash up to frozen values
        Frozen → Unfrozen: dim to 0% over 1s, rise to unfrozen values

        Args:
            area_id: The area ID
            source: Source of the action
        """
        import asyncio

        is_frozen = state.is_frozen(area_id)
        config = self._get_config()

        if not state.is_enabled(area_id):
            logger.info(f"[{source}] Area {area_id} not enabled, skipping freeze_toggle")
            return

        # Dim to 0% over 1 second
        await self._apply_lighting(area_id, 0, 2700, include_color=False, transition=1.0)
        await asyncio.sleep(1.1)  # Wait for transition to complete

        if is_frozen:
            # Was frozen → unfreeze
            await self.unfreeze(area_id, source)

            # Rise to unfrozen values
            area_state = self._get_area_state(area_id)
            hour = get_current_hour()
            result = CircadianLight.calculate_lighting(hour, config, area_state)
            await self._apply_lighting(area_id, result.brightness, result.color_temp, transition=1.0)

            logger.info(f"[{source}] Freeze toggle: {area_id} unfrozen")

        else:
            # Was unfrozen → freeze at current time
            frozen_at = get_current_hour()
            state.set_frozen_at(area_id, frozen_at)

            # Flash up to frozen values
            area_state = self._get_area_state(area_id)
            result = CircadianLight.calculate_lighting(frozen_at, config, area_state)
            await self._apply_lighting(area_id, result.brightness, result.color_temp, transition=0.3)

            logger.info(f"[{source}] Freeze toggle: {area_id} frozen at hour {frozen_at:.2f}")

    # -------------------------------------------------------------------------
    # Reset
    # -------------------------------------------------------------------------

    async def reset(self, area_id: str, source: str = "service_call"):
        """Reset area to base config values.

        Resets midpoints, bounds, and frozen_at to defaults.
        Enables Circadian mode and applies current time values.

        Args:
            area_id: The area ID
            source: Source of the action
        """
        logger.info(f"[{source}] Resetting area {area_id}")

        # Reset state (clears midpoints/bounds/frozen_at, preserves only enabled)
        state.reset_area(area_id)

        # Enable (frozen_at is already cleared by reset_area)
        state.set_enabled(area_id, True)

        # Apply current time values
        config = self._get_config()
        area_state = self._get_area_state(area_id)
        hour = get_current_hour()

        result = CircadianLight.calculate_lighting(hour, config, area_state)
        await self._apply_lighting(area_id, result.brightness, result.color_temp)

        logger.info(
            f"Reset complete for area {area_id}: "
            f"{result.brightness}%, {result.color_temp}K"
        )

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

        Args:
            area_id: The area ID
            brightness: Brightness percentage (0-100)
            color_temp: Color temperature in Kelvin
            include_color: Whether to include color in the command
            transition: Transition time in seconds
        """
        target_type, target_value = await self.client.determine_light_target(area_id)

        service_data = {
            "brightness_pct": brightness,
            "transition": transition,
        }

        if include_color:
            service_data["kelvin"] = color_temp

        await self.client.call_service(
            "light", "turn_on", service_data, {target_type: target_value}
        )

    async def _apply_color_only(
        self, area_id: str, color_temp: int, transition: float = 0.4
    ):
        """Apply color temperature only to an area.

        Args:
            area_id: The area ID
            color_temp: Color temperature in Kelvin
            transition: Transition time in seconds
        """
        target_type, target_value = await self.client.determine_light_target(area_id)

        service_data = {
            "kelvin": color_temp,
            "transition": transition,
        }

        await self.client.call_service(
            "light", "turn_on", service_data, {target_type: target_value}
        )

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

        config = self._get_config()
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
