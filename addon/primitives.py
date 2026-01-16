#!/usr/bin/env python3
"""Circadian Light Primitives - Core actions triggered via service calls or switches."""

import json
import logging
import os
import time
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
            # Use frozen hour if frozen, otherwise current time
            hour = area_state.frozen_at if area_state.frozen_at is not None else get_current_hour()

            result = CircadianLight.calculate_step(
                hour=hour,
                direction="up",
                config=config,
                state=area_state,
            )

            if result is None:
                logger.info(f"Step up at limit for area {area_id}")
                # Bounce effect at limit
                current_bri = CircadianLight.calculate_brightness_at_hour(hour, config, area_state)
                current_cct = CircadianLight.calculate_color_at_hour(hour, config, area_state, apply_solar_rules=True)
                await self._bounce_at_limit(area_id, current_bri, current_cct)
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
            # Use frozen hour if frozen, otherwise current time
            hour = area_state.frozen_at if area_state.frozen_at is not None else get_current_hour()

            result = CircadianLight.calculate_step(
                hour=hour,
                direction="down",
                config=config,
                state=area_state,
            )

            if result is None:
                logger.info(f"Step down at limit for area {area_id}")
                # Bounce effect at limit
                current_bri = CircadianLight.calculate_brightness_at_hour(hour, config, area_state)
                current_cct = CircadianLight.calculate_color_at_hour(hour, config, area_state, apply_solar_rules=True)
                await self._bounce_at_limit(area_id, current_bri, current_cct)
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
            # Use frozen hour if frozen, otherwise current time
            hour = area_state.frozen_at if area_state.frozen_at is not None else get_current_hour()

            result = CircadianLight.calculate_bright_step(
                hour=hour,
                direction="up",
                config=config,
                state=area_state,
            )

            if result is None:
                logger.info(f"Bright up at limit for area {area_id}")
                # Bounce effect at limit
                current_bri = CircadianLight.calculate_brightness_at_hour(hour, config, area_state)
                current_cct = CircadianLight.calculate_color_at_hour(hour, config, area_state, apply_solar_rules=True)
                await self._bounce_at_limit(area_id, current_bri, current_cct)
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
            # Use frozen hour if frozen, otherwise current time
            hour = area_state.frozen_at if area_state.frozen_at is not None else get_current_hour()

            result = CircadianLight.calculate_bright_step(
                hour=hour,
                direction="down",
                config=config,
                state=area_state,
            )

            if result is None:
                logger.info(f"Bright down at limit for area {area_id}")
                # Bounce effect at limit
                current_bri = CircadianLight.calculate_brightness_at_hour(hour, config, area_state)
                current_cct = CircadianLight.calculate_color_at_hour(hour, config, area_state, apply_solar_rules=True)
                await self._bounce_at_limit(area_id, current_bri, current_cct)
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
            # Use frozen hour if frozen, otherwise current time
            hour = area_state.frozen_at if area_state.frozen_at is not None else get_current_hour()

            result = CircadianLight.calculate_color_step(
                hour=hour,
                direction="up",
                config=config,
                state=area_state,
            )

            if result is None:
                logger.info(f"Color up at limit for area {area_id}")
                # Bounce effect at limit
                current_bri = CircadianLight.calculate_brightness_at_hour(hour, config, area_state)
                current_cct = CircadianLight.calculate_color_at_hour(hour, config, area_state, apply_solar_rules=True)
                await self._bounce_at_limit(area_id, current_bri, current_cct)
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
            # Use frozen hour if frozen, otherwise current time
            hour = area_state.frozen_at if area_state.frozen_at is not None else get_current_hour()

            result = CircadianLight.calculate_color_step(
                hour=hour,
                direction="down",
                config=config,
                state=area_state,
            )

            if result is None:
                logger.info(f"Color down at limit for area {area_id}")
                # Bounce effect at limit
                current_bri = CircadianLight.calculate_brightness_at_hour(hour, config, area_state)
                current_cct = CircadianLight.calculate_color_at_hour(hour, config, area_state, apply_solar_rules=True)
                await self._bounce_at_limit(area_id, current_bri, current_cct)
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

        # Calculate and apply lighting (use frozen_at if set, otherwise current time)
        config = self._get_config()
        area_state = self._get_area_state(area_id)
        hour = area_state.frozen_at if area_state.frozen_at is not None else get_current_hour()

        result = CircadianLight.calculate_lighting(hour, config, area_state)
        await self._apply_lighting(area_id, result.brightness, result.color_temp)

        logger.info(
            f"Circadian Light enabled for area {area_id}: "
            f"{result.brightness}%, {result.color_temp}K (hour={hour:.2f})"
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
                    "light", "turn_off", {"transition": 0.5}, {target_type: target_value}
                )
            logger.info(f"Turned off {len(area_ids)} area(s)")

        else:
            # Turn on all areas with Circadian values
            config = self._get_config()

            for area_id in area_ids:
                state.set_enabled(area_id, True)
                area_state = self._get_area_state(area_id)
                # Use frozen_at if set, otherwise current time
                hour = area_state.frozen_at if area_state.frozen_at is not None else get_current_hour()

                result = CircadianLight.calculate_lighting(hour, config, area_state)
                await self._apply_lighting(area_id, result.brightness, result.color_temp)

            logger.info(f"Turned on {len(area_ids)} area(s) with Circadian Light")

    # -------------------------------------------------------------------------
    # Set - Configure area state (presets, frozen_at, copy_from)
    # -------------------------------------------------------------------------

    async def set(
        self, area_id: str, source: str = "service_call",
        preset: str = None, frozen_at: float = None, copy_from: str = None,
        enable: bool = False
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
            enable: If True, also enable the area (default False = don't change enabled status)
        """
        config = self._get_config()
        current_hour = get_current_hour()

        # Enable the area first if requested
        if enable:
            state.set_enabled(area_id, True)
            logger.info(f"[{source}] Enabled area {area_id}")

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

                # Apply if enabled
                if state.is_enabled(area_id):
                    area_state = self._get_area_state(area_id)
                    hour = area_state.frozen_at if area_state.frozen_at is not None else current_hour
                    result = CircadianLight.calculate_lighting(hour, config, area_state)
                    await self._apply_lighting(area_id, result.brightness, result.color_temp)
                return
            else:
                logger.warning(f"[{source}] copy_from area {copy_from} not found")

        # Priority 2: explicit frozen_at
        if frozen_at is not None:
            state.set_frozen_at(area_id, float(frozen_at))
            logger.info(f"[{source}] Set {area_id} frozen_at={frozen_at:.2f}")

            # Apply if enabled
            if state.is_enabled(area_id):
                area_state = self._get_area_state(area_id)
                result = CircadianLight.calculate_lighting(frozen_at, config, area_state)
                await self._apply_lighting(area_id, result.brightness, result.color_temp)
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
                frozen_hour = config.ascend_start
                state.set_frozen_at(area_id, frozen_hour)
                logger.info(f"[{source}] Set {area_id} to nitelite preset (frozen_at={frozen_hour}, ascend_start={config.ascend_start}, descend_start={config.descend_start})")

            elif preset == "britelite":
                # Freeze at descend_start (maximum values)
                frozen_hour = config.descend_start
                state.set_frozen_at(area_id, frozen_hour)
                logger.info(f"[{source}] Set {area_id} to britelite preset (frozen_at={frozen_hour})")

            else:
                logger.warning(f"[{source}] Unknown preset: {preset}")
                return

            # Apply if enabled
            if state.is_enabled(area_id):
                area_state = self._get_area_state(area_id)
                hour = area_state.frozen_at if area_state.frozen_at is not None else current_hour
                logger.info(f"[{source}] Preset apply: area_state.frozen_at={area_state.frozen_at}, using hour={hour}")
                result = CircadianLight.calculate_lighting(hour, config, area_state)
                logger.info(f"[{source}] Preset calculated: brightness={result.brightness}%, color_temp={result.color_temp}K at hour={hour}")
                await self._apply_lighting(area_id, result.brightness, result.color_temp)

    async def broadcast(self, source_area_id: str, source: str = "service_call"):
        """Copy settings from source area to all other areas.

        Copies frozen_at, midpoints, bounds, and solar_rule_color_limit
        from the source area to every other known area.

        Args:
            source_area_id: The area to copy settings FROM
            source: Source of the action
        """
        all_areas = state.get_all_areas()

        if source_area_id not in all_areas:
            logger.warning(f"[{source}] broadcast: source area {source_area_id} not found")
            return

        target_areas = [a for a in all_areas.keys() if a != source_area_id]

        if not target_areas:
            logger.info(f"[{source}] broadcast: no other areas to copy to")
            return

        logger.info(f"[{source}] Broadcasting settings from {source_area_id} to {len(target_areas)} area(s)")

        for target_area in target_areas:
            await self.set(target_area, source, copy_from=source_area_id)

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

        config = self._get_config()
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

        Unfrozen → Frozen: dim over 0.8s, brighten instantly
        Frozen → Unfrozen: dim over 0.8s, brighten over 1s

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

        # Both directions dim over 0.5s
        # Freeze: flash on instantly (0s)
        # Unfreeze: rise over 2s (intentionally slow)
        dim_duration = 0.5

        await self._apply_lighting(area_id, 0, 2700, include_color=False, transition=dim_duration)
        await asyncio.sleep(dim_duration + 0.1)  # Wait for transition to complete

        if is_frozen:
            # Was frozen → unfreeze (re-anchor midpoints)
            self._unfreeze_internal(area_id, source)

            # Rise to unfrozen values over 2s
            area_state = self._get_area_state(area_id)
            hour = get_current_hour()
            result = CircadianLight.calculate_lighting(hour, config, area_state)
            await self._apply_lighting(area_id, result.brightness, result.color_temp, transition=2.0)

            logger.info(f"[{source}] Freeze toggle: {area_id} unfrozen")

        else:
            # Was unfrozen → freeze at current time
            frozen_at = get_current_hour()
            state.set_frozen_at(area_id, frozen_at)

            # Flash up to frozen values instantly
            area_state = self._get_area_state(area_id)
            result = CircadianLight.calculate_lighting(frozen_at, config, area_state)
            await self._apply_lighting(area_id, result.brightness, result.color_temp, transition=0)

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

        config = self._get_config()

        # Filter to enabled areas only
        enabled_areas = [a for a in area_ids if state.is_enabled(a)]
        if not enabled_areas:
            logger.info(f"[{source}] No enabled areas for freeze_toggle_multiple")
            return

        # Check freeze state of first area (all should be same, but use first as reference)
        is_frozen = state.is_frozen(enabled_areas[0])

        # Both directions dim over 0.5s
        # Freeze: flash on instantly (0s)
        # Unfreeze: rise over 2s (intentionally slow)
        dim_duration = 0.5

        # Dim ALL areas to 0%
        for area_id in enabled_areas:
            await self._apply_lighting(area_id, 0, 2700, include_color=False, transition=dim_duration)

        await asyncio.sleep(dim_duration + 0.1)  # Wait for transition to complete

        if is_frozen:
            # Was frozen → unfreeze all
            for area_id in enabled_areas:
                self._unfreeze_internal(area_id, source)

            # Rise ALL areas to unfrozen values over 2s
            hour = get_current_hour()
            for area_id in enabled_areas:
                area_state = self._get_area_state(area_id)
                result = CircadianLight.calculate_lighting(hour, config, area_state)
                await self._apply_lighting(area_id, result.brightness, result.color_temp, transition=2.0)

            logger.info(f"[{source}] Freeze toggle: {len(enabled_areas)} area(s) unfrozen")

        else:
            # Was unfrozen → freeze all at current time
            frozen_at = get_current_hour()
            for area_id in enabled_areas:
                state.set_frozen_at(area_id, frozen_at)

            # Flash ALL areas up to frozen values instantly
            for area_id in enabled_areas:
                area_state = self._get_area_state(area_id)
                result = CircadianLight.calculate_lighting(frozen_at, config, area_state)
                await self._apply_lighting(area_id, result.brightness, result.color_temp, transition=0)

            logger.info(f"[{source}] Freeze toggle: {len(enabled_areas)} area(s) frozen at hour {frozen_at:.2f}")

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

        # Apply current time values only if enabled
        if state.is_enabled(area_id):
            config = self._get_config()
            area_state = self._get_area_state(area_id)
            hour = get_current_hour()

            result = CircadianLight.calculate_lighting(hour, config, area_state)
            await self._apply_lighting(area_id, result.brightness, result.color_temp)

            logger.info(
                f"Reset complete for area {area_id}: "
                f"{result.brightness}%, {result.color_temp}K"
            )
        else:
            logger.info(f"Reset complete for area {area_id} (not enabled, no lighting change)")

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

        logger.info(f"_apply_lighting: {target_type}={target_value}, service_data={service_data}")

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

    async def _bounce_at_limit(self, area_id: str, current_brightness: int, current_color: int):
        """Visual bounce effect when hitting a bound limit.

        If brightness < 10%: flash off then on
        If brightness >= 10%: dim to 50% of current brightness over 0.3s, then restore

        Args:
            area_id: The area ID
            current_brightness: Current brightness percentage
            current_color: Current color temperature in Kelvin
        """
        import asyncio

        if current_brightness < 10:
            # Flash off then on
            await self._apply_lighting(area_id, 0, current_color, include_color=False, transition=0.1)
            await asyncio.sleep(0.15)
            await self._apply_lighting(area_id, current_brightness, current_color, transition=0.1)
        else:
            # Dim to 50% then restore
            dim_brightness = max(1, current_brightness // 2)
            await self._apply_lighting(area_id, dim_brightness, current_color, include_color=False, transition=0.3)
            await asyncio.sleep(0.35)
            await self._apply_lighting(area_id, current_brightness, current_color, transition=0.3)

        logger.info(f"Bounce effect for area {area_id} at {current_brightness}%")

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
