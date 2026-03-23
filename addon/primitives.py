#!/usr/bin/env python3
"""Circadian Light Primitives - Core actions triggered via service calls or switches."""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

import glozone
import glozone_state
import state
from brain import (
    CircadianLight,
    Config,
    AreaState,
    SunTimes,
    get_current_hour,
    compute_override_decay,
    calculate_natural_light_factor,
    apply_light_filter_pipeline,
    calculate_curve_position,
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
        self._wake_alarm_fired: dict = (
            {}
        )  # area_id -> {"date": "YYYY-MM-DD", "time": float}
        self._load_wake_alarm_fired()

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
                        with open(path, "r") as f:
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

    def _get_two_step_delay(self) -> float:
        """Get the two-step turn-on delay in seconds.

        When turning on lights, a two-step process sets color at 1% brightness
        then transitions to target brightness. This delay between steps prevents
        some ZigBee lights from dropping the second command.

        Reads from global config, defaults to 0.3 seconds (3 tenths).
        The setting is stored as tenths of seconds in config.

        Returns:
            Delay time in seconds
        """
        try:
            raw_config = glozone.load_config_from_files()
            tenths = raw_config.get("two_step_delay", 3)
            return tenths / 10.0  # Convert tenths to seconds
        except Exception:
            return 0.3  # Default 0.3 seconds

    def _get_freeze_off_rise(self) -> float:
        """Get the freeze-off rise transition time in seconds.

        When unfreezing, lights rise back to circadian values over this duration.
        Reads from global config, defaults to 1.0 seconds (10 tenths).

        Returns:
            Transition time in seconds
        """
        try:
            raw_config = glozone.load_config_from_files()
            tenths = raw_config.get("freeze_off_rise", 10)
            return tenths / 10.0
        except Exception:
            return 1.0

    def _is_limit_bounce_enabled(self) -> bool:
        """Check if limit bounce visual feedback is enabled."""
        try:
            raw_config = glozone.load_config_from_files()
            return raw_config.get("limit_bounce_enabled", True)
        except Exception:
            return True

    def _get_limit_warning_speed(self) -> float:
        """Get the limit warning animation speed in seconds.

        Controls how fast the bounce (dip/flash) animates when hitting a step limit.
        Reads from global config, defaults to 0.3 seconds (3 tenths).

        Returns:
            Transition time in seconds
        """
        try:
            raw_config = glozone.load_config_from_files()
            tenths = raw_config.get("limit_warning_speed", 3)
            return tenths / 10.0
        except Exception:
            return 0.3

    def _get_limit_bounce_max_percent(self) -> float:
        """Get the bounce percentage when hitting max limit (% of range).

        Controls how much lights dip when hitting the upper limit.
        Reads from global config, defaults to 30 (%).

        Returns:
            Bounce percentage (0-100)
        """
        try:
            raw_config = glozone.load_config_from_files()
            return raw_config.get("limit_bounce_max_percent", 30)
        except Exception:
            return 30

    def _get_limit_bounce_min_percent(self) -> float:
        """Get the bounce percentage when hitting min limit (% of range).

        Controls how much lights flash when hitting the lower limit.
        Reads from global config, defaults to 10 (%).

        Returns:
            Bounce percentage (0-100)
        """
        try:
            raw_config = glozone.load_config_from_files()
            return raw_config.get("limit_bounce_min_percent", 10)
        except Exception:
            return 10

    def _get_reach_dip_percent(self) -> float:
        """Get the reach feedback dip percentage (% of current brightness).

        Controls how much lights dip during reach change feedback.
        Reads from global config, defaults to 50 (%).

        Returns:
            Dip percentage (0-100)
        """
        try:
            raw_config = glozone.load_config_from_files()
            return raw_config.get("reach_dip_percent", 50)
        except Exception:
            return 50

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

    def _get_all_area_ids(self) -> list:
        """Get all area IDs from all GloZones.

        Returns:
            List of area IDs
        """
        area_ids = []
        glozones = glozone.get_glozones()
        for zone_name, zone_config in glozones.items():
            areas = zone_config.get("areas", [])
            for area in areas:
                if isinstance(area, dict):
                    area_ids.append(area.get("id"))
                else:
                    area_ids.append(area)
        return area_ids

    async def _apply_moment(self, moment_id: str, source: str = "moment"):
        """Apply a moment configuration to all areas.

        Args:
            moment_id: The moment ID to apply
            source: Source of the action
        """
        moments = self._get_moments()
        moment = moments.get(moment_id)
        if not moment:
            logger.warning(f"[{source}] Moment '{moment_id}' not found")
            return

        default_action = moment.get("default_action", "leave_alone")
        exceptions = moment.get("exceptions", {})

        logger.info(
            f"[{source}] Applying moment '{moment.get('name', moment_id)}' "
            f"(default: {default_action}, {len(exceptions)} exceptions)"
        )

        all_areas = self._get_all_area_ids()
        default_timer = moment.get("timer", 0)
        tasks = []
        # Track areas that get turned on and their per-area timer
        turn_on_timers: Dict[str, int] = {}

        for area_id in all_areas:
            exc_val = exceptions.get(area_id)
            if exc_val is not None:
                # Exception: may be old string format or new {action, timer} dict
                if isinstance(exc_val, dict):
                    action = exc_val.get("action", "leave_alone")
                    area_timer = exc_val.get("timer", 0)
                else:
                    action = exc_val
                    area_timer = 0
            else:
                action = default_action
                area_timer = default_timer

            if action == "leave_alone":
                continue
            elif action == "off":
                tasks.append(self.lights_off(area_id, source))
            elif action == "lights_on":
                tasks.append(self.lights_on(area_id, source))
                turn_on_timers[area_id] = area_timer
            elif action == "nitelite":
                tasks.append(self.set(area_id, source, preset="nitelite", is_on=True))
                turn_on_timers[area_id] = area_timer
            elif action == "britelite":
                tasks.append(self.set(area_id, source, preset="britelite", is_on=True))
                turn_on_timers[area_id] = area_timer
            elif action == "circadian_off":
                tasks.append(self.circadian_off(area_id, source))
            elif action == "wake_or_bed":
                tasks.append(self.set(area_id, source, preset="wake_or_bed"))
            elif action == "reset":
                tasks.append(self.glo_reset(area_id, source))

        if tasks:
            await asyncio.gather(*tasks)
            logger.info(
                f"[{source}] Moment '{moment_id}' applied to {len(tasks)} areas"
            )
        else:
            logger.info(
                f"[{source}] Moment '{moment_id}' - no areas to update (all leave_alone)"
            )

        # Set auto-off timers for areas that were turned on
        timer_areas = {area_id for area_id, t in turn_on_timers.items() if t > 0}
        if timer_areas:
            now = datetime.now()
            for area_id in timer_areas:
                t = turn_on_timers[area_id]
                expires_at = (now + timedelta(seconds=t)).isoformat()
                state.set_motion_expires(area_id, expires_at)
            logger.info(f"[{source}] Set auto-off timers for {len(timer_areas)} areas")

    async def _turn_off_area(self, area_id: str, transition: float = 0.3) -> None:
        """Turn off all lights in an area.

        Uses ZHA groups when available for efficient hardware-level control.

        Args:
            area_id: The area ID to turn off
            transition: Transition time in seconds
        """
        await self.client.turn_off_lights(area_id, transition=transition)

    def _get_area_state(self, area_id: str) -> AreaState:
        """Get area state from state module."""
        state_dict = state.get_area(area_id)
        return AreaState.from_dict(state_dict)

    def _update_area_state(self, area_id: str, updates: Dict[str, Any]) -> None:
        """Update area state in state module."""
        state.update_area(area_id, updates)

    def _get_decayed_brightness_override(self, area_id: str) -> Optional[float]:
        """Get the current decay-adjusted brightness override for an area.

        Returns None if no override is set or decay has completed.
        """
        area_state = self._get_area_state(area_id)
        if area_state.brightness_override is None:
            return None
        if area_state.brightness_override_set_at is None:
            return area_state.brightness_override
        config = self._get_config(area_id)
        hour = get_current_hour()
        in_ascend, h48, t_ascend, t_descend, _ = CircadianLight.get_phase_info(
            hour, config
        )
        next_phase = t_descend if in_ascend else t_ascend + 24
        decay = compute_override_decay(
            area_state.brightness_override_set_at, h48, next_phase, t_ascend=t_ascend
        )
        if decay <= 0:
            return None
        return area_state.brightness_override * decay

    async def _apply_step_result(
        self, area_id: str, result, skip_filters: Set[str] = None
    ) -> None:
        """Apply a StepResult to lights using the full pipeline.

        Uses the step's color/brightness values (not re-rendered) but runs
        through turn_on_lights_circadian so area_factor, filters, and
        brightness_override are applied correctly.

        Args:
            area_id: The area ID
            result: StepResult with brightness, color_temp, rgb, xy
            skip_filters: Set of filter_norms to skip (handled by reach groups)
        """
        effective_override = self._get_decayed_brightness_override(area_id)
        # Check for boost
        brightness = result.brightness
        if state.is_boosted(area_id):
            boost_state = state.get_boost_state(area_id)
            boost_amount = boost_state.get("boost_brightness") or 0
            brightness = result.brightness + boost_amount

        lighting_values = {
            "brightness": brightness,
            "kelvin": result.color_temp,
            "rgb": result.rgb,
            "xy": result.xy,
            "rhythm_brightness": result.brightness,
            "brightness_override": effective_override,
        }
        if skip_filters:
            lighting_values["skip_filters"] = skip_filters
        await self.client.turn_on_lights_circadian(area_id, lighting_values)
        self.client.schedule_nudge(area_id, lighting_values)

    def _reduce_overrides_toward_zero(
        self, area_id: str, area_state, config, direction: str
    ) -> bool:
        """Reduce brightness/color overrides that oppose the step direction.

        When step_up/step_down hits the curve limit but overrides are keeping
        the effective value away from the limit, reduce the overrides by one
        step instead of bouncing.

        Args:
            area_id: Area ID
            area_state: Current AreaState
            config: Area config
            direction: "up" or "down"

        Returns:
            True if any override was reduced (caller should skip bounce).
        """
        steps = config.max_dim_steps or DEFAULT_MAX_DIM_STEPS
        updates = {}

        # Brightness override
        bri_override = area_state.brightness_override or 0
        bri_opposes = (direction == "up" and bri_override < 0) or (
            direction == "down" and bri_override > 0
        )
        if bri_opposes:
            bri_step = (config.max_brightness - config.min_brightness) / steps
            if direction == "up":
                new_bri = round(min(0, bri_override + bri_step), 1)
            else:
                new_bri = round(max(0, bri_override - bri_step), 1)
            new_bri = new_bri if new_bri != 0 else None
            updates["brightness_override"] = new_bri
            updates["brightness_override_set_at"] = (
                area_state.brightness_override_set_at if new_bri is not None else None
            )

        # Color override (only user-originated, i.e. has set_at)
        color_override = area_state.color_override or 0
        color_opposes = (direction == "up" and color_override < 0) or (
            direction == "down" and color_override > 0
        )
        if color_opposes and area_state.color_override_set_at is not None:
            color_step = (config.max_color_temp - config.min_color_temp) / steps
            if direction == "up":
                new_color = round(min(0, color_override + color_step), 1)
            else:
                new_color = round(max(0, color_override - color_step), 1)
            new_color = new_color if new_color != 0 else None
            updates["color_override"] = new_color
            updates["color_override_set_at"] = (
                area_state.color_override_set_at if new_color is not None else None
            )

        if updates:
            self._update_area_state(area_id, updates)
            logger.info(
                f"Step {direction} at curve limit, reducing overrides for {area_id}: {updates}"
            )
            return True
        return False

    # -------------------------------------------------------------------------
    # Step Up / Step Down (brightness-primary, both curves)
    # -------------------------------------------------------------------------

    async def step_up(
        self,
        area_id: str,
        source: str = "service_call",
        steps: int = 1,
        send_command: bool = True,
    ):
        """Step up along the circadian curve (brighter and cooler).

        Uses brightness-primary algorithm: brightness determines the step,
        color follows the diverged curve.

        Only works when is_circadian=True. Updates midpoints always, but only
        applies to lights if is_on=True and send_command=True.

        Args:
            area_id: The area ID to control
            source: Source of the action
            steps: Number of steps to take (each computed from updated state)
            send_command: Whether to send light commands (False for reach group batching)

        Returns:
            The last StepResult applied, or None if at limit / not circadian.
        """
        area_state = self._get_area_state(area_id)

        if not area_state.is_circadian:
            logger.debug(
                f"[{source}] step_up ignored for area {area_id} (not in circadian mode)"
            )
            return None

        # If frozen, check if already at limit before unfreezing
        # (inverse_midpoint drift at asymptotes can mask the limit after unfreeze)
        # Both brightness AND color must be at limit to bounce
        if area_state.frozen_at is not None:
            config = self._get_config(area_id)
            frozen_bri = CircadianLight.calculate_brightness_at_hour(
                area_state.frozen_at, config, area_state
            )
            frozen_cct_natural = CircadianLight.calculate_color_at_hour(
                area_state.frozen_at, config, area_state, apply_solar_rules=False
            )
            bri_margin = max(
                1.0, (config.max_brightness - config.min_brightness) * 0.01
            )
            cct_margin = max(10, (config.max_color_temp - config.min_color_temp) * 0.01)
            bri_at_max = frozen_bri >= config.max_brightness - bri_margin
            cct_at_max = frozen_cct_natural >= config.max_color_temp - cct_margin
            if bri_at_max and cct_at_max:
                if self._reduce_overrides_toward_zero(
                    area_id, area_state, config, "up"
                ):
                    if send_command and area_state.is_on:
                        await self.client.update_lights_in_circadian_mode(area_id)
                    return None

                logger.info(f"Step up at limit for area {area_id} (frozen at max)")
                if send_command and area_state.is_on:
                    sun_times = (
                        self.client._get_sun_times()
                        if hasattr(self.client, "_get_sun_times")
                        else None
                    )
                    frozen_cct = CircadianLight.calculate_color_at_hour(
                        area_state.frozen_at,
                        config,
                        area_state,
                        apply_solar_rules=True,
                        sun_times=sun_times,
                    )
                    await self._bounce_at_limit(
                        area_id,
                        frozen_bri,
                        frozen_cct,
                        direction="up",
                        bounce_type="step",
                    )
                    await self.client.update_lights_in_circadian_mode(area_id)
                return None
            # At least one dimension has room → unfreeze and let calculate_step handle it
            self._unfreeze_internal(area_id, source)
            area_state = self._get_area_state(area_id)
        else:
            config = self._get_config(area_id)

        logger.info(f"[{source}] Step up for area {area_id}")

        hour = get_current_hour()
        sun_times = (
            self.client._get_sun_times()
            if hasattr(self.client, "_get_sun_times")
            else None
        )

        last_result = None
        for step_i in range(steps):
            if step_i > 0:
                area_state = self._get_area_state(area_id)

            result = CircadianLight.calculate_step(
                hour=hour,
                direction="up",
                config=config,
                state=area_state,
                sun_times=sun_times,
            )

            if result is None:
                if step_i == 0:
                    # First step at limit → existing override reduction + bounce
                    if self._reduce_overrides_toward_zero(
                        area_id, area_state, config, "up"
                    ):
                        if send_command and area_state.is_on:
                            await self.client.update_lights_in_circadian_mode(area_id)
                        return None

                    logger.info(f"Step up at limit for area {area_id}")
                    if send_command and area_state.is_on:
                        current_bri = CircadianLight.calculate_brightness_at_hour(
                            hour, config, area_state
                        )
                        current_cct = CircadianLight.calculate_color_at_hour(
                            hour,
                            config,
                            area_state,
                            apply_solar_rules=True,
                            sun_times=sun_times,
                        )
                        await self._bounce_at_limit(
                            area_id,
                            current_bri,
                            current_cct,
                            direction="up",
                            bounce_type="step",
                        )
                        await self.client.update_lights_in_circadian_mode(area_id)
                    return None
                break  # Mid-sequence limit → use last good result

            logger.info(f"Step up state_updates: {result.state_updates}")
            self._update_area_state(area_id, result.state_updates)
            last_result = result

        # Apply to lights only if send_command=True and we have a result
        if send_command and last_result:
            area_state = self._get_area_state(area_id)
            if area_state.is_on:
                await self._apply_step_result(area_id, last_result)
                logger.info(
                    f"Step up applied: {last_result.brightness}%, {last_result.color_temp}K"
                )
            else:
                logger.info(
                    f"Step up state updated (lights off): "
                    f"{last_result.brightness}%, {last_result.color_temp}K"
                )

        return last_result

    async def step_down(
        self,
        area_id: str,
        source: str = "service_call",
        steps: int = 1,
        send_command: bool = True,
    ):
        """Step down along the circadian curve (dimmer and warmer).

        Uses brightness-primary algorithm: brightness determines the step,
        color follows the diverged curve.

        Only works when is_circadian=True. Updates midpoints always, but only
        applies to lights if is_on=True and send_command=True.

        Args:
            area_id: The area ID to control
            source: Source of the action
            steps: Number of steps to take (each computed from updated state)
            send_command: Whether to send light commands (False for reach group batching)

        Returns:
            The last StepResult applied, or None if at limit / not circadian.
        """
        area_state = self._get_area_state(area_id)

        if not area_state.is_circadian:
            logger.debug(
                f"[{source}] step_down ignored for area {area_id} (not in circadian mode)"
            )
            return None

        # If frozen, check if already at limit before unfreezing
        # (inverse_midpoint drift at asymptotes can mask the limit after unfreeze)
        # Both brightness AND color must be at limit to bounce
        if area_state.frozen_at is not None:
            config = self._get_config(area_id)
            frozen_bri = CircadianLight.calculate_brightness_at_hour(
                area_state.frozen_at, config, area_state
            )
            frozen_cct_natural = CircadianLight.calculate_color_at_hour(
                area_state.frozen_at, config, area_state, apply_solar_rules=False
            )
            bri_margin = max(
                1.0, (config.max_brightness - config.min_brightness) * 0.01
            )
            cct_margin = max(10, (config.max_color_temp - config.min_color_temp) * 0.01)
            bri_at_min = frozen_bri <= config.min_brightness + bri_margin
            cct_at_min = frozen_cct_natural <= config.min_color_temp + cct_margin
            if bri_at_min and cct_at_min:
                if self._reduce_overrides_toward_zero(
                    area_id, area_state, config, "down"
                ):
                    if send_command and area_state.is_on:
                        await self.client.update_lights_in_circadian_mode(area_id)
                    return None

                logger.info(f"Step down at limit for area {area_id} (frozen at min)")
                if send_command and area_state.is_on:
                    sun_times = (
                        self.client._get_sun_times()
                        if hasattr(self.client, "_get_sun_times")
                        else None
                    )
                    frozen_cct = CircadianLight.calculate_color_at_hour(
                        area_state.frozen_at,
                        config,
                        area_state,
                        apply_solar_rules=True,
                        sun_times=sun_times,
                    )
                    await self._bounce_at_limit(
                        area_id,
                        frozen_bri,
                        frozen_cct,
                        direction="down",
                        bounce_type="step",
                    )
                    await self.client.update_lights_in_circadian_mode(area_id)
                return None
            # At least one dimension has room → unfreeze and let calculate_step handle it
            self._unfreeze_internal(area_id, source)
            area_state = self._get_area_state(area_id)
        else:
            config = self._get_config(area_id)

        logger.info(f"[{source}] Step down for area {area_id}")

        hour = get_current_hour()
        sun_times = (
            self.client._get_sun_times()
            if hasattr(self.client, "_get_sun_times")
            else None
        )

        last_result = None
        for step_i in range(steps):
            if step_i > 0:
                area_state = self._get_area_state(area_id)

            result = CircadianLight.calculate_step(
                hour=hour,
                direction="down",
                config=config,
                state=area_state,
                sun_times=sun_times,
            )

            if result is None:
                if step_i == 0:
                    # First step at limit → existing override reduction + bounce
                    if self._reduce_overrides_toward_zero(
                        area_id, area_state, config, "down"
                    ):
                        if send_command and area_state.is_on:
                            await self.client.update_lights_in_circadian_mode(area_id)
                        return None

                    logger.info(f"Step down at limit for area {area_id}")
                    if send_command and area_state.is_on:
                        current_bri = CircadianLight.calculate_brightness_at_hour(
                            hour, config, area_state
                        )
                        current_cct = CircadianLight.calculate_color_at_hour(
                            hour,
                            config,
                            area_state,
                            apply_solar_rules=True,
                            sun_times=sun_times,
                        )
                        await self._bounce_at_limit(
                            area_id,
                            current_bri,
                            current_cct,
                            direction="down",
                            bounce_type="step",
                        )
                        await self.client.update_lights_in_circadian_mode(area_id)
                    return None
                break  # Mid-sequence limit → use last good result

            self._update_area_state(area_id, result.state_updates)
            last_result = result

        # Apply to lights only if send_command=True and we have a result
        if send_command and last_result:
            area_state = self._get_area_state(area_id)
            if area_state.is_on:
                await self._apply_step_result(area_id, last_result)
                logger.info(
                    f"Step down applied: {last_result.brightness}%, {last_result.color_temp}K"
                )
            else:
                logger.info(
                    f"Step down state updated (lights off): "
                    f"{last_result.brightness}%, {last_result.color_temp}K"
                )

        return last_result

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
            logger.debug(
                f"[{source}] bright_up ignored for area {area_id} (not in circadian mode)"
            )
            return

        # If frozen, check if already at limit before unfreezing
        if area_state.frozen_at is not None:
            config = self._get_config(area_id)
            frozen_bri = CircadianLight.calculate_brightness_at_hour(
                area_state.frozen_at, config, area_state
            )
            safe_margin = max(
                1.0, (config.max_brightness - config.min_brightness) * 0.01
            )
            if frozen_bri >= config.max_brightness - safe_margin:
                logger.info(f"Bright up at limit for area {area_id} (frozen at max)")
                if area_state.is_on:
                    sun_times = (
                        self.client._get_sun_times()
                        if hasattr(self.client, "_get_sun_times")
                        else None
                    )
                    frozen_cct = CircadianLight.calculate_color_at_hour(
                        area_state.frozen_at,
                        config,
                        area_state,
                        apply_solar_rules=True,
                        sun_times=sun_times,
                    )
                    await self._bounce_at_limit(
                        area_id,
                        frozen_bri,
                        frozen_cct,
                        direction="up",
                        bounce_type="bright",
                    )
                return
            self._unfreeze_internal(area_id, source)
            area_state = self._get_area_state(area_id)
        else:
            config = self._get_config(area_id)

        logger.info(f"[{source}] Bright up for area {area_id}")

        hour = get_current_hour()
        sun_times = (
            self.client._get_sun_times()
            if hasattr(self.client, "_get_sun_times")
            else None
        )

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
                current_bri = CircadianLight.calculate_brightness_at_hour(
                    hour, config, area_state
                )
                current_cct = CircadianLight.calculate_color_at_hour(
                    hour,
                    config,
                    area_state,
                    apply_solar_rules=True,
                    sun_times=sun_times,
                )
                await self._bounce_at_limit(
                    area_id,
                    current_bri,
                    current_cct,
                    direction="up",
                    bounce_type="bright",
                )
            return

        # Update state (always, even if is_on=False)
        self._update_area_state(area_id, result.state_updates)

        # Apply to lights only if is_on=True
        if area_state.is_on:
            await self._apply_circadian_lighting(
                area_id, result.brightness, result.color_temp
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
            logger.debug(
                f"[{source}] bright_down ignored for area {area_id} (not in circadian mode)"
            )
            return

        # If frozen, check if already at limit before unfreezing
        if area_state.frozen_at is not None:
            config = self._get_config(area_id)
            frozen_bri = CircadianLight.calculate_brightness_at_hour(
                area_state.frozen_at, config, area_state
            )
            safe_margin = max(
                1.0, (config.max_brightness - config.min_brightness) * 0.01
            )
            if frozen_bri <= config.min_brightness + safe_margin:
                logger.info(f"Bright down at limit for area {area_id} (frozen at min)")
                if area_state.is_on:
                    sun_times = (
                        self.client._get_sun_times()
                        if hasattr(self.client, "_get_sun_times")
                        else None
                    )
                    frozen_cct = CircadianLight.calculate_color_at_hour(
                        area_state.frozen_at,
                        config,
                        area_state,
                        apply_solar_rules=True,
                        sun_times=sun_times,
                    )
                    await self._bounce_at_limit(
                        area_id,
                        frozen_bri,
                        frozen_cct,
                        direction="down",
                        bounce_type="bright",
                    )
                return
            self._unfreeze_internal(area_id, source)
            area_state = self._get_area_state(area_id)
        else:
            config = self._get_config(area_id)

        logger.info(f"[{source}] Bright down for area {area_id}")

        hour = get_current_hour()
        sun_times = (
            self.client._get_sun_times()
            if hasattr(self.client, "_get_sun_times")
            else None
        )

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
                current_bri = CircadianLight.calculate_brightness_at_hour(
                    hour, config, area_state
                )
                current_cct = CircadianLight.calculate_color_at_hour(
                    hour,
                    config,
                    area_state,
                    apply_solar_rules=True,
                    sun_times=sun_times,
                )
                await self._bounce_at_limit(
                    area_id,
                    current_bri,
                    current_cct,
                    direction="down",
                    bounce_type="bright",
                )
            return

        # Update state (always, even if is_on=False)
        self._update_area_state(area_id, result.state_updates)

        # Apply to lights only if is_on=True
        if area_state.is_on:
            await self._apply_circadian_lighting(
                area_id, result.brightness, result.color_temp
            )
            logger.info(f"Bright down applied: {result.brightness}%")
        else:
            logger.info(f"Bright down state updated (lights off): {result.brightness}%")

    # -------------------------------------------------------------------------
    # Color Up / Color Down (color only)
    # -------------------------------------------------------------------------

    async def color_up(
        self, area_id: str, source: str = "service_call", send_command: bool = True
    ):
        """Increase color temperature (cooler), brightness unchanged.

        Only works when is_circadian=True. Updates midpoints always, but only
        applies to lights if is_on=True and send_command=True.

        Args:
            area_id: The area ID to control
            source: Source of the action
            send_command: Whether to send light commands (False for reach group batching)
        """
        area_state = self._get_area_state(area_id)

        if not area_state.is_circadian:
            logger.debug(
                f"[{source}] color_up ignored for area {area_id} (not in circadian mode)"
            )
            return

        # If frozen, check if already at limit before unfreezing
        if area_state.frozen_at is not None:
            config = self._get_config(area_id)
            sun_times = (
                self.client._get_sun_times()
                if hasattr(self.client, "_get_sun_times")
                else None
            )
            frozen_cct = CircadianLight.calculate_color_at_hour(
                area_state.frozen_at,
                config,
                area_state,
                apply_solar_rules=True,
                sun_times=sun_times,
            )
            safe_margin = max(
                10, (config.max_color_temp - config.min_color_temp) * 0.01
            )
            if frozen_cct >= config.max_color_temp - safe_margin:
                logger.info(f"Color up at limit for area {area_id} (frozen at max)")
                if area_state.is_on:
                    frozen_bri = CircadianLight.calculate_brightness_at_hour(
                        area_state.frozen_at, config, area_state
                    )
                    await self._bounce_at_limit(
                        area_id,
                        frozen_bri,
                        frozen_cct,
                        direction="up",
                        bounce_type="color",
                    )
                return
            self._unfreeze_internal(area_id, source)
            area_state = self._get_area_state(area_id)
        else:
            config = self._get_config(area_id)

        logger.info(f"[{source}] Color up for area {area_id}")

        hour = get_current_hour()
        sun_times = (
            self.client._get_sun_times()
            if hasattr(self.client, "_get_sun_times")
            else None
        )

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
                current_bri = CircadianLight.calculate_brightness_at_hour(
                    hour, config, area_state
                )
                current_cct = CircadianLight.calculate_color_at_hour(
                    hour,
                    config,
                    area_state,
                    apply_solar_rules=True,
                    sun_times=sun_times,
                )
                await self._bounce_at_limit(
                    area_id,
                    current_bri,
                    current_cct,
                    direction="up",
                    bounce_type="color",
                )
            return

        # Update state (always, even if is_on=False)
        self._update_area_state(area_id, result.state_updates)

        # Apply to lights only if is_on=True and send_command=True
        if area_state.is_on and send_command:
            # Calculate current brightness to include in command (needed for CT compensation)
            current_bri = CircadianLight.calculate_brightness_at_hour(
                hour, config, area_state
            )
            await self._apply_circadian_lighting(
                area_id, current_bri, result.color_temp
            )
            logger.info(f"Color up applied: {result.color_temp}K, {current_bri}%")
        elif not area_state.is_on:
            logger.info(f"Color up state updated (lights off): {result.color_temp}K")

        return result

    async def color_down(
        self, area_id: str, source: str = "service_call", send_command: bool = True
    ):
        """Decrease color temperature (warmer), brightness unchanged.

        Only works when is_circadian=True. Updates midpoints always, but only
        applies to lights if is_on=True and send_command=True.

        Args:
            area_id: The area ID to control
            source: Source of the action
            send_command: Whether to send light commands (False for reach group batching)
        """
        area_state = self._get_area_state(area_id)

        if not area_state.is_circadian:
            logger.debug(
                f"[{source}] color_down ignored for area {area_id} (not in circadian mode)"
            )
            return

        # If frozen, check if already at limit before unfreezing
        if area_state.frozen_at is not None:
            config = self._get_config(area_id)
            sun_times = (
                self.client._get_sun_times()
                if hasattr(self.client, "_get_sun_times")
                else None
            )
            frozen_cct = CircadianLight.calculate_color_at_hour(
                area_state.frozen_at,
                config,
                area_state,
                apply_solar_rules=True,
                sun_times=sun_times,
            )
            safe_margin = max(
                10, (config.max_color_temp - config.min_color_temp) * 0.01
            )
            if frozen_cct <= config.min_color_temp + safe_margin:
                logger.info(f"Color down at limit for area {area_id} (frozen at min)")
                if area_state.is_on:
                    frozen_bri = CircadianLight.calculate_brightness_at_hour(
                        area_state.frozen_at, config, area_state
                    )
                    await self._bounce_at_limit(
                        area_id,
                        frozen_bri,
                        frozen_cct,
                        direction="down",
                        bounce_type="color",
                    )
                return
            self._unfreeze_internal(area_id, source)
            area_state = self._get_area_state(area_id)
        else:
            config = self._get_config(area_id)

        logger.info(f"[{source}] Color down for area {area_id}")

        hour = get_current_hour()
        sun_times = (
            self.client._get_sun_times()
            if hasattr(self.client, "_get_sun_times")
            else None
        )

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
                current_bri = CircadianLight.calculate_brightness_at_hour(
                    hour, config, area_state
                )
                current_cct = CircadianLight.calculate_color_at_hour(
                    hour,
                    config,
                    area_state,
                    apply_solar_rules=True,
                    sun_times=sun_times,
                )
                await self._bounce_at_limit(
                    area_id,
                    current_bri,
                    current_cct,
                    direction="down",
                    bounce_type="color",
                )
            return

        # Update state (always, even if is_on=False)
        self._update_area_state(area_id, result.state_updates)

        # Apply to lights only if is_on=True and send_command=True
        if area_state.is_on and send_command:
            # Calculate current brightness to include in command (needed for CT compensation)
            current_bri = CircadianLight.calculate_brightness_at_hour(
                hour, config, area_state
            )
            await self._apply_circadian_lighting(
                area_id, current_bri, result.color_temp
            )
            logger.info(f"Color down applied: {result.color_temp}K, {current_bri}%")
        elif not area_state.is_on:
            logger.info(f"Color down state updated (lights off): {result.color_temp}K")

        return result

    # -------------------------------------------------------------------------
    # Set Position - Slider-based absolute positioning
    # -------------------------------------------------------------------------

    def _compute_nl_factor(self, area_id: str) -> float:
        """Compute current natural light factor for an area (matches main.py pipeline)."""
        import lux_tracker

        natural_exposure = glozone.get_area_natural_light_exposure(area_id)
        if natural_exposure <= 0:
            return 1.0
        outdoor_norm = lux_tracker.get_outdoor_normalized()
        if outdoor_norm is None:
            outdoor_norm = 0.0
        sensitivity = glozone.get_config().get("brightness_sensitivity", 5.0)
        return calculate_natural_light_factor(
            natural_exposure, outdoor_norm, sensitivity
        )

    async def set_position(
        self,
        area_id: str,
        value: float,
        mode: str = "step",
        source: str = "service_call",
    ):
        """Set position along the circadian curve (0=min, 100=max).

        For step mode: walks the curve via midpoints (inverse_midpoint).
        For brightness mode: sets an additive override delta with time-based decay.
        For color mode: sets color_override directly via _converge_override (no color_mid change).

        Args:
            area_id: The area ID to control
            value: Position 0-100
            mode: "step" (both), "brightness", or "color"
            source: Source of the action
        """
        area_state = self._get_area_state(area_id)

        if not area_state.is_circadian:
            logger.debug(
                f"[{source}] set_position ignored for area {area_id} (not in circadian mode)"
            )
            return

        # Always unfreeze for position setting (no limit check needed)
        if area_state.frozen_at is not None:
            self._unfreeze_internal(area_id, source)
            area_state = self._get_area_state(area_id)

        config = self._get_config(area_id)
        hour = get_current_hour()
        sun_times = (
            self.client._get_sun_times()
            if hasattr(self.client, "_get_sun_times")
            else None
        )

        if mode == "brightness":
            # Override model: compute delta between target and current actual brightness.
            # Target maps slider 0-100 to actual brightness 0-100%.
            target_actual = max(0, min(100, value))

            # Current actual = rhythm_bri × NL × area_factor
            result = CircadianLight.calculate_lighting(
                hour,
                config,
                area_state,
                sun_times=sun_times,
            )
            rhythm_bri = result.brightness
            nl_factor = self._compute_nl_factor(area_id)
            area_factor = glozone.get_area_brightness_factor(area_id)
            current_actual = rhythm_bri * nl_factor * area_factor

            delta = round(target_actual - current_actual, 1)
            self._update_area_state(
                area_id,
                {
                    "brightness_override": delta,
                    "brightness_override_set_at": hour,
                },
            )
            logger.info(
                f"[{source}] set_position({value}, brightness) for area {area_id}: "
                f"target={target_actual}, current={current_actual:.1f}, delta={delta}"
            )
            if area_state.is_on:
                await self.client.update_lights_in_circadian_mode(area_id)
            return

        if mode == "color":
            # Override model: set color_override directly, no color_mid change.
            result = CircadianLight.calculate_set_position(
                hour=hour,
                position=value,
                dimension="color",
                config=config,
                state=area_state,
                sun_times=sun_times,
            )
            updates = result.state_updates
            updates["color_override_set_at"] = hour  # Enable decay
            logger.info(
                f"[{source}] set_position({value}, color) for area {area_id}: {updates}"
            )
            self._update_area_state(area_id, updates)

            if area_state.is_on:
                await self._apply_circadian_lighting(
                    area_id, result.brightness, result.color_temp
                )
                logger.info(
                    f"set_position color applied: {result.brightness}%, {result.color_temp}K"
                )
            else:
                logger.info(
                    f"set_position color state updated (lights off): {result.brightness}%, {result.color_temp}K"
                )
            return

        # mode == "step": walk the curve via midpoints (existing behavior)
        result = CircadianLight.calculate_set_position(
            hour=hour,
            position=value,
            dimension=mode,
            config=config,
            state=area_state,
            sun_times=sun_times,
        )

        logger.info(
            f"[{source}] set_position({value}, {mode}) for area {area_id}: {result.state_updates}"
        )
        self._update_area_state(area_id, result.state_updates)

        if area_state.is_on:
            await self._apply_circadian_lighting(
                area_id, result.brightness, result.color_temp
            )
            logger.info(
                f"set_position applied: {result.brightness}%, {result.color_temp}K"
            )
        else:
            logger.info(
                f"set_position state updated (lights off): {result.brightness}%, {result.color_temp}K"
            )

    # -------------------------------------------------------------------------
    # Per-axis override up/down (brightness and color buttons)
    # -------------------------------------------------------------------------

    async def brightness_up(
        self,
        area_id: str,
        source: str = "service_call",
        steps: int = 1,
        send_command: bool = True,
    ):
        """Bump brightness override up by one step. Uses override+decay model."""
        return await self._brightness_step(
            area_id,
            direction="up",
            source=source,
            steps=steps,
            send_command=send_command,
        )

    async def brightness_down(
        self,
        area_id: str,
        source: str = "service_call",
        steps: int = 1,
        send_command: bool = True,
    ):
        """Bump brightness override down by one step. Uses override+decay model."""
        return await self._brightness_step(
            area_id,
            direction="down",
            source=source,
            steps=steps,
            send_command=send_command,
        )

    async def _brightness_step(
        self,
        area_id: str,
        direction: str,
        source: str,
        steps: int = 1,
        send_command: bool = True,
    ):
        """Bump brightness override by one or more step increments.

        Collapses multiple steps into a single loop with one light command at the end.

        Args:
            area_id: The area ID to control
            direction: "up" or "down"
            source: Source of the action
            steps: Number of steps to take
            send_command: Whether to send light commands (False for reach group batching)

        Returns:
            True if override was applied, None if at limit / not circadian.
        """
        area_state = self._get_area_state(area_id)
        if not area_state.is_circadian:
            logger.debug(
                f"[{source}] brightness_{direction} ignored for {area_id} (not circadian)"
            )
            return None

        if area_state.frozen_at is not None:
            self._unfreeze_internal(area_id, source)
            area_state = self._get_area_state(area_id)

        config = self._get_config(area_id)
        hour = get_current_hour()
        sun_times = (
            self.client._get_sun_times()
            if hasattr(self.client, "_get_sun_times")
            else None
        )
        num_steps = config.max_dim_steps or DEFAULT_MAX_DIM_STEPS
        step_size = (config.max_brightness - config.min_brightness) / num_steps
        sign = 1 if direction == "up" else -1

        # Pre-compute constants that don't change between iterations
        base_bri = CircadianLight.calculate_brightness_at_hour(hour, config, area_state)
        nl_factor = self._compute_nl_factor(area_id)
        area_factor = glozone.get_area_brightness_factor(area_id)
        scaled_base = base_bri * nl_factor * area_factor

        applied = False
        for step_i in range(steps):
            if step_i > 0:
                area_state = self._get_area_state(area_id)

            # Get current decayed override
            current_override = area_state.brightness_override or 0
            set_at = area_state.brightness_override_set_at
            if set_at is not None:
                in_ascend, h48, t_ascend, t_descend, _ = CircadianLight.get_phase_info(
                    hour, config
                )
                next_phase = t_descend if in_ascend else t_ascend + 24
                decay = compute_override_decay(
                    set_at, h48, next_phase, t_ascend=t_ascend
                )
                current_override = current_override * decay

            effective_bri = scaled_base + current_override

            at_limit = (direction == "up" and effective_bri >= 99.0) or (
                direction == "down" and effective_bri <= 1.0
            )
            if at_limit:
                if step_i == 0:
                    logger.info(
                        f"brightness_{direction} at limit for {area_id} "
                        f"(effective={effective_bri:.1f}, nl={nl_factor:.2f})"
                    )
                    if send_command and area_state.is_on:
                        current_cct = CircadianLight.calculate_color_at_hour(
                            hour,
                            config,
                            area_state,
                            apply_solar_rules=True,
                            sun_times=sun_times,
                        )
                        # Pass raw circadian brightness (pre-NL, pre-boost)
                        await self._bounce_at_limit(
                            area_id,
                            base_bri,
                            current_cct,
                            direction=direction,
                            bounce_type="bright",
                        )
                    return None
                break  # Mid-sequence limit → use last good override

            new_override = round(current_override + sign * step_size, 1)

            # Clamp so effective brightness stays within physical limits (1–100)
            max_override = 100.0 - scaled_base
            min_override = 1.0 - scaled_base
            unclamped = new_override
            new_override = round(max(min_override, min(max_override, new_override)), 1)

            # If the clamp prevented movement, we're at the limit
            clamped_at_limit = (direction == "down" and unclamped < new_override) or (
                direction == "up" and unclamped > new_override
            )
            if clamped_at_limit:
                if step_i == 0:
                    logger.info(
                        f"brightness_{direction} clamped at limit for {area_id} "
                        f"(effective={scaled_base + new_override:.1f}, nl={nl_factor:.2f})"
                    )
                    if send_command and area_state.is_on:
                        current_cct = CircadianLight.calculate_color_at_hour(
                            hour,
                            config,
                            area_state,
                            apply_solar_rules=True,
                            sun_times=sun_times,
                        )
                        # Pass raw circadian brightness (pre-NL, pre-boost)
                        await self._bounce_at_limit(
                            area_id,
                            base_bri,
                            current_cct,
                            direction=direction,
                            bounce_type="bright",
                        )
                    return None
                break  # Mid-sequence clamp → use last good override

            self._update_area_state(
                area_id,
                {
                    "brightness_override": new_override,
                    "brightness_override_set_at": hour,
                },
            )
            logger.info(
                f"[{source}] brightness_{direction} for {area_id}: "
                f"override {current_override:.1f} -> {new_override} "
                f"(base={base_bri:.0f}, nl={nl_factor:.2f}, factor={area_factor:.2f})"
            )
            applied = True

        # Send ONE light command at end (not per-step)
        if send_command and applied:
            area_state = self._get_area_state(area_id)
            if area_state.is_on:
                await self.client.update_lights_in_circadian_mode(area_id)

        return True if applied else None

    async def color_up(
        self, area_id: str, source: str = "service_call", steps: int = 1
    ):
        """Bump color override up (cooler) by one step. Uses override+decay model."""
        await self._color_step(area_id, direction="up", source=source, steps=steps)

    async def color_down(
        self, area_id: str, source: str = "service_call", steps: int = 1
    ):
        """Bump color override down (warmer) by one step. Uses override+decay model."""
        await self._color_step(area_id, direction="down", source=source, steps=steps)

    async def _color_step(
        self, area_id: str, direction: str, source: str, steps: int = 1
    ):
        """Bump color override by one Kelvin step increment."""
        area_state = self._get_area_state(area_id)
        if not area_state.is_circadian:
            logger.debug(
                f"[{source}] color_{direction} ignored for {area_id} (not circadian)"
            )
            return

        if area_state.frozen_at is not None:
            self._unfreeze_internal(area_id, source)
            area_state = self._get_area_state(area_id)

        config = self._get_config(area_id)
        hour = get_current_hour()
        sun_times = (
            self.client._get_sun_times()
            if hasattr(self.client, "_get_sun_times")
            else None
        )
        num_steps = config.max_dim_steps or DEFAULT_MAX_DIM_STEPS
        cct_step = (config.max_color_temp - config.min_color_temp) / num_steps

        # Get current decayed override, then bump
        current_override = area_state.color_override or 0
        set_at = area_state.color_override_set_at
        if set_at is not None:
            in_ascend, h48, t_ascend, t_descend, _ = CircadianLight.get_phase_info(
                hour, config
            )
            next_phase = t_descend if in_ascend else t_ascend + 24
            decay = compute_override_decay(set_at, h48, next_phase, t_ascend=t_ascend)
            current_override = current_override * decay

        # Compute base CCT WITHOUT current override (matches _brightness_step pattern)
        # to avoid double-counting the override in the at_limit check and clamping.
        base_state = AreaState(
            is_circadian=area_state.is_circadian,
            is_on=area_state.is_on,
            frozen_at=area_state.frozen_at,
            brightness_mid=area_state.brightness_mid,
            color_mid=area_state.color_mid,
            color_override=None,
            color_override_set_at=None,
            brightness_override=area_state.brightness_override,
            brightness_override_set_at=area_state.brightness_override_set_at,
        )
        base_cct = CircadianLight.calculate_color_at_hour(
            hour, config, base_state, apply_solar_rules=True, sun_times=sun_times
        )
        effective_cct = base_cct + current_override

        # Limit bounds match the slider range (config min/max color temp)
        c_min = config.min_color_temp
        c_max = config.max_color_temp

        at_limit = (direction == "up" and effective_cct >= c_max - 50) or (
            direction == "down" and effective_cct <= c_min + 50
        )
        if at_limit:
            logger.info(
                f"color_{direction} at limit for {area_id} (effective={effective_cct:.0f}K)"
            )
            if area_state.is_on:
                current_bri = CircadianLight.calculate_brightness_at_hour(
                    hour, config, area_state
                )
                await self._bounce_at_limit(
                    area_id,
                    current_bri,
                    effective_cct,
                    direction=direction,
                    bounce_type="color",
                )
            return

        sign = 1 if direction == "up" else -1
        new_override = round(current_override + sign * cct_step, 1)

        # Clamp so effective color stays within config range
        max_override = c_max - base_cct
        min_override = c_min - base_cct
        new_override = round(max(min_override, min(max_override, new_override)), 1)

        self._update_area_state(
            area_id,
            {
                "color_override": new_override,
                "color_override_set_at": hour,
            },
        )
        logger.info(
            f"[{source}] color_{direction} for {area_id}: "
            f"override {current_override:.1f}K -> {new_override}K"
        )
        if area_state.is_on:
            await self.client.update_lights_in_circadian_mode(area_id)

        if steps > 1:
            await self._color_step(area_id, direction, source, steps - 1)

    # -------------------------------------------------------------------------
    # Lights On / Off / Toggle - Control light state under Circadian management
    # -------------------------------------------------------------------------

    async def lights_on(
        self,
        area_id: str,
        source: str = "service_call",
        boost_brightness: int = None,
        boost_duration: int = None,
        from_motion: bool = False,
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
            from_motion: If True, couple boost timer to motion timer (boost ends
                when motion timer ends, not independently).
        """
        has_boost = boost_brightness is not None and boost_duration is not None
        if has_boost:
            logger.info(
                f"[{source}] lights_on for area {area_id} with boost={boost_brightness}%, duration={'forever' if boost_duration == 0 else f'{boost_duration}s'}"
            )
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
        hour = (
            area_state.frozen_at
            if area_state.frozen_at is not None
            else get_current_hour()
        )
        sun_times = (
            self.client._get_sun_times()
            if hasattr(self.client, "_get_sun_times")
            else None
        )

        result = CircadianLight.calculate_lighting(
            hour, config, area_state, sun_times=sun_times
        )
        transition = self._get_turn_on_transition()

        # brightness_override applied post-NL in the filter pipeline (not pre-applied)
        effective_override = self._get_decayed_brightness_override(area_id)

        # Calculate final brightness (with boost if provided)
        # Boost goes into brightness (pre-NL, same as periodic path)
        if has_boost:
            final_brightness = min(100, result.brightness + boost_brightness)
        else:
            final_brightness = result.brightness

        # Set boost state BEFORE applying lighting to prevent race condition:
        # _apply_lighting_turn_on() has an asyncio.sleep for two-step delay,
        # during which the circadian tick can run. If boost state isn't saved yet,
        # the tick sees is_boosted=False and overwrites with base brightness.
        if has_boost:
            started_from_off = not lights_were_on
            if from_motion:
                # Motion-coupled boost: use "motion" sentinel so boost ends with motion timer
                expires_at = "motion"
            else:
                is_forever = boost_duration == 0
                expires_at = (
                    "forever"
                    if is_forever
                    else (
                        datetime.now() + timedelta(seconds=boost_duration)
                    ).isoformat()
                )
            state.set_boost(
                area_id,
                started_from_off=started_from_off,
                expires_at=expires_at,
                brightness=boost_brightness,
            )

        pipeline_kwargs = {
            "rhythm_brightness": result.brightness,
        }
        if effective_override is not None:
            pipeline_kwargs["brightness_override"] = effective_override

        if lights_were_on:
            # Lights already on - just adjust, no two-step needed
            await self._apply_lighting(
                area_id,
                final_brightness,
                result.color_temp,
                include_color=True,
                transition=transition,
                **pipeline_kwargs,
            )
        else:
            # Lights were off - use two-phase turn-on to avoid color jump
            await self._apply_lighting_turn_on(
                area_id,
                final_brightness,
                result.color_temp,
                transition=transition,
                **pipeline_kwargs,
            )

        # Also turn on any switch entities (relays, smart plugs) in the area
        await self.client.turn_on_switch_entities(area_id)

        if has_boost:
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
            hour = (
                area_state.frozen_at
                if area_state.frozen_at is not None
                else get_current_hour()
            )
            sun_times = (
                self.client._get_sun_times()
                if hasattr(self.client, "_get_sun_times")
                else None
            )
            result = CircadianLight.calculate_lighting(
                hour, config, area_state, sun_times=sun_times
            )
            state.set_last_off_ct(area_id, result.color_temp)
        except Exception as e:
            logger.warning(f"Could not calculate CT for area {area_id}: {e}")

        # Enable circadian control and set is_on=False (resets state if was not circadian)
        was_circadian = state.enable_circadian_and_set_on(area_id, False)

        # Clear off_enforced so the periodic loop verifies lights are actually off
        state.set_off_enforced(area_id, False)

        # Turn off lights (uses ZHA groups when available) and switch entities
        transition = self._get_turn_off_transition()
        await self.client.turn_off_lights(area_id, transition=transition)
        await self.client.turn_off_switch_entities(area_id)

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
            hour = (
                area_state.frozen_at
                if area_state.frozen_at is not None
                else get_current_hour()
            )
            result = CircadianLight.calculate_lighting(hour, config, area_state)
            transition = self._get_turn_on_transition()
            # Apply brightness_override (from step_up/down or zone sync)
            final_brightness = result.brightness
            effective_override = self._get_decayed_brightness_override(area_id)
            if effective_override is not None:
                final_brightness = max(
                    1, min(100, round(final_brightness + effective_override))
                )
            await self._apply_lighting_turn_on(
                area_id, final_brightness, result.color_temp, transition
            )
            logger.info(
                f"circadian_on applied: {final_brightness}%, {result.color_temp}K (is_on=True)"
            )
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

    async def lights_toggle_multiple(
        self, area_ids: list, source: str = "service_call"
    ):
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

        # Check if any lights are on using our own tracked state
        # This is more reliable than querying entity state which can be stale
        any_on = any(
            state.is_circadian(area_id) and state.get_is_on(area_id)
            for area_id in area_ids
        )
        logger.info(
            f"[{source}] lights_toggle_multiple: any_on={any_on} (from internal state)"
        )

        if any_on:
            # Turn off all areas - store CT first for smart 2-step on next turn-on
            transition = self._get_turn_off_transition()
            sun_times = (
                self.client._get_sun_times()
                if hasattr(self.client, "_get_sun_times")
                else None
            )
            # Phase 1: State updates (synchronous, no I/O)
            for area_id in area_ids:
                # Calculate current CT before turning off
                try:
                    config = self._get_config(area_id)
                    area_state = self._get_area_state(area_id)
                    hour = (
                        area_state.frozen_at
                        if area_state.frozen_at is not None
                        else get_current_hour()
                    )
                    result = CircadianLight.calculate_lighting(
                        hour, config, area_state, sun_times=sun_times
                    )
                    state.set_last_off_ct(area_id, result.color_temp)
                    logger.debug(
                        f"Stored last_off_ct={result.color_temp} for area {area_id}"
                    )
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

            # Phase 2: Turn off via reach groups (synchronized) + per-area fallback
            # Reach groups handle ZHA lights across areas simultaneously.
            # Per-area turn_off handles non-ZHA lights and areas not in reach groups.
            reach_used = await self.client.turn_off_reach_groups(
                area_ids, transition=transition
            )

            # Per-area turn_off for non-reach lights (Hue, WiFi, individual ZHA)
            # and switch entities. Idempotent — double-off for ZHA lights is harmless.
            tasks = []
            for area_id in area_ids:
                tasks.append(
                    self.client.turn_off_lights(
                        area_id, transition=transition, nudge=not reach_used
                    )
                )
                tasks.append(self.client.turn_off_switch_entities(area_id))
            await asyncio.gather(*tasks)

            reach_note = " (reach + per-area)" if reach_used else ""
            logger.info(
                f"lights_toggle_multiple: turned off {len(area_ids)} area(s){reach_note}"
            )

        else:
            # Turn on all areas with Circadian values
            transition = self._get_turn_on_transition()
            # Get sun times for solar rules (same as periodic update)
            sun_times = (
                self.client._get_sun_times()
                if hasattr(self.client, "_get_sun_times")
                else None
            )

            # Collect lighting values for all areas first
            area_lighting: List[Tuple[str, int, int]] = []
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
                hour = (
                    area_state.frozen_at
                    if area_state.frozen_at is not None
                    else get_current_hour()
                )

                result = CircadianLight.calculate_lighting(
                    hour, config, area_state, sun_times=sun_times
                )
                # Pass rhythm_brightness and brightness_override through to the
                # filter pipeline (applied post-NL, matching the periodic path).
                effective_override = self._get_decayed_brightness_override(area_id)
                area_lighting.append(
                    (
                        area_id,
                        result.brightness,
                        result.color_temp,
                        result.brightness,
                        effective_override,
                    )
                )

            # Try filter-aware reach groups for multi-area turn-on
            reach_handled = await self._try_reach_turn_on(
                area_ids, area_lighting, transition=transition
            )

            # Collect areas needing per-area turn-on (not fully handled by reach)
            needs_per_area_turn_on = []  # entries with no reach handling (get 2-step)
            needs_per_area_partial = (
                []
            )  # entries partially handled by reach (no 2-step, some lights already on)
            for entry in area_lighting:
                area_id = entry[0]
                skip = reach_handled.get(area_id)
                if skip:
                    area_filters = glozone.get_area_light_filters(area_id)
                    all_filters = (
                        set(area_filters.values()) if area_filters else {"Standard"}
                    )
                    all_norms = {f.replace(" ", "_").lower() for f in all_filters}
                    if all_norms.issubset(skip):
                        continue  # Fully handled by reach — skip per-area entirely
                    needs_per_area_partial.append((entry, skip))
                else:
                    needs_per_area_turn_on.append(entry)

            # 2-step turn-on for areas not handled by reach
            if needs_per_area_turn_on:
                await self._apply_lighting_turn_on_multiple(
                    needs_per_area_turn_on, transition=transition
                )

            # Direct apply for partially reach-handled areas (some lights already on)
            for entry, skip in needs_per_area_partial:
                await self._apply_lighting(
                    entry[0],
                    entry[1],
                    entry[2],
                    include_color=True,
                    transition=transition,
                    rhythm_brightness=entry[3] if len(entry) > 3 else None,
                    brightness_override=entry[4] if len(entry) > 4 else None,
                    skip_filters=skip,
                )

            # Also turn on any switch entities (relays, smart plugs)
            for area_id in area_ids:
                await self.client.turn_on_switch_entities(area_id)

            reach_note = ""
            if reach_handled:
                reach_note = f" (reach: {len(reach_handled)} areas)"
            logger.info(
                f"lights_toggle_multiple: turned on {len(area_ids)} area(s){reach_note}"
            )

    # -------------------------------------------------------------------------
    # Bright Boost - Temporary brightness increase
    # -------------------------------------------------------------------------

    async def bright_boost(
        self,
        area_id: str,
        duration_seconds: int,
        boost_amount: int,
        source: str = "motion_sensor",
        lights_were_off: bool = None,
        from_motion: bool = False,
    ):
        """Temporarily boost brightness for an area.

        Adds boost_amount percentage points to current circadian brightness.
        After duration expires, returns to previous state:
        - If lights were off when boost started: turn off
        - If lights were on: return to circadian brightness

        MAX logic when already boosted:
        - boost % = MAX(current %, new %)
        - If current timer is forever: stays forever
        - If current timer is motion-coupled: stays motion-coupled
        - If current timer is timed: timer = MAX(remaining, new duration)

        Args:
            area_id: The area ID to boost
            duration_seconds: How long the boost lasts (0 = forever)
            boost_amount: Brightness percentage points to add (0-100)
            source: Source of the action (e.g., "motion_sensor", "contact_sensor")
            lights_were_off: If provided, use this instead of checking current light state.
                This is useful when boost is called after motion_on_off, which already
                turned the lights on - we need to know the state BEFORE motion_on_off ran.
            from_motion: If True, couple boost timer to motion timer (boost ends
                when motion timer ends, not independently).
        """
        is_forever = duration_seconds == 0
        logger.info(
            f"[{source}] bright_boost for area {area_id}, duration={'forever' if is_forever else f'{duration_seconds}s'}, boost={boost_amount}%"
        )

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
                logger.info(
                    f"[{source}] Increased boost brightness to {new_brightness}% for area {area_id}"
                )

            # MAX logic for timer
            current_is_motion = boost_state.get("is_motion_coupled", False)
            if current_is_forever:
                # Forever boost stays forever, can't be shortened
                logger.debug(
                    f"[{source}] Area {area_id} has forever boost, timer unchanged"
                )
            elif current_is_motion:
                # Motion-coupled boost stays motion-coupled (can't shorten)
                # But if new boost is forever, upgrade to forever
                if is_forever:
                    state.update_boost_expires(area_id, "forever")
                    logger.info(
                        f"[{source}] Upgraded motion-coupled boost to forever for area {area_id}"
                    )
                else:
                    logger.debug(
                        f"[{source}] Area {area_id} has motion-coupled boost, timer unchanged"
                    )
            elif from_motion:
                # New boost is motion-coupled, upgrade existing timed boost
                state.update_boost_expires(area_id, "motion")
                logger.info(
                    f"[{source}] Upgraded boost to motion-coupled for area {area_id}"
                )
            elif is_forever:
                # New boost is forever, upgrade to forever
                state.update_boost_expires(area_id, "forever")
                logger.info(f"[{source}] Upgraded boost to forever for area {area_id}")
            else:
                # Both are timed - use MAX
                now = datetime.now()
                current_remaining = (
                    datetime.fromisoformat(current_expires) - now
                ).total_seconds()
                if duration_seconds > current_remaining:
                    new_expires = (
                        now + timedelta(seconds=duration_seconds)
                    ).isoformat()
                    state.update_boost_expires(area_id, new_expires)
                    logger.info(
                        f"[{source}] Extended boost timer to {new_expires} for area {area_id}"
                    )
                else:
                    logger.debug(
                        f"[{source}] Keeping existing timer ({current_remaining:.0f}s remaining > {duration_seconds}s new)"
                    )
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
        hour = (
            area_state.frozen_at
            if area_state.frozen_at is not None
            else get_current_hour()
        )
        sun_times = (
            self.client._get_sun_times()
            if hasattr(self.client, "_get_sun_times")
            else None
        )

        result = CircadianLight.calculate_lighting(
            hour, config, area_state, sun_times=sun_times
        )

        # Calculate boosted brightness
        boosted_brightness = min(100, result.brightness + boost_amount)

        # Set boost state
        if from_motion:
            expires_at = "motion"
        else:
            expires_at = (
                "forever"
                if is_forever
                else (datetime.now() + timedelta(seconds=duration_seconds)).isoformat()
            )
        state.set_boost(
            area_id,
            started_from_off=started_from_off,
            expires_at=expires_at,
            brightness=boost_amount,
        )

        # Enable Circadian Light and set is_on=True
        if not glozone.is_area_in_any_zone(area_id):
            glozone.add_area_to_default_zone(area_id)
        state.enable_circadian_and_set_on(area_id, True)

        # Apply boosted brightness with circadian color temp
        transition = self._get_turn_on_transition()
        if lights_currently_on:
            # Lights already on - just adjust brightness
            await self._apply_lighting(
                area_id, boosted_brightness, result.color_temp, transition=transition
            )
        else:
            # Lights were off - use two-phase turn-on
            await self._apply_lighting_turn_on(
                area_id, boosted_brightness, result.color_temp, transition=transition
            )

        logger.info(
            f"[{source}] Boosted area {area_id}: {result.brightness}% + {boost_amount}% = {boosted_brightness}%, "
            f"{result.color_temp}K, expires={expires_at}"
        )

    async def _apply_current_boost(self, area_id: str, boost_amount: int):
        """Re-apply lighting with current boost level (for when boost % increases)."""
        config = self._get_config(area_id)
        area_state = self._get_area_state(area_id)
        hour = (
            area_state.frozen_at
            if area_state.frozen_at is not None
            else get_current_hour()
        )
        sun_times = (
            self.client._get_sun_times()
            if hasattr(self.client, "_get_sun_times")
            else None
        )

        result = CircadianLight.calculate_lighting(
            hour, config, area_state, sun_times=sun_times
        )
        boosted_brightness = min(100, result.brightness + boost_amount)

        transition = self._get_turn_on_transition()
        await self._apply_lighting(
            area_id, boosted_brightness, result.color_temp, transition=transition
        )

    async def end_boost(self, area_id: str, source: str = "timer") -> bool:
        """End boost for an area and return to previous state.

        Called when boost timer expires or boost is explicitly cancelled.

        Args:
            area_id: The area ID
            source: Source of the action

        Returns:
            True if lights were turned off (started_from_off), False otherwise
        """
        boost_state = state.get_boost_state(area_id)

        if not boost_state["is_boosted"]:
            logger.debug(f"[{source}] Area {area_id} not boosted, nothing to end")
            return False

        started_from_off = boost_state["boost_started_from_off"]

        # Clear boost state
        state.clear_boost(area_id)

        if started_from_off:
            # Lights were off when boost started - turn off and set is_on=False
            # Clear any warning state first
            state.clear_motion_warning(area_id)

            # Store CT first for smart 2-step on next turn-on
            try:
                config = self._get_config(area_id)
                area_state = self._get_area_state(area_id)
                hour = (
                    area_state.frozen_at
                    if area_state.frozen_at is not None
                    else get_current_hour()
                )
                sun_times = (
                    self.client._get_sun_times()
                    if hasattr(self.client, "_get_sun_times")
                    else None
                )
                result = CircadianLight.calculate_lighting(
                    hour, config, area_state, sun_times=sun_times
                )
                state.set_last_off_ct(area_id, result.color_temp)
            except Exception as e:
                logger.warning(f"Could not store CT for area {area_id}: {e}")

            transition = self._get_turn_off_transition()
            await self._turn_off_area(area_id, transition=transition)
            state.set_is_on(area_id, False)
            state.set_off_enforced(area_id, False)
            logger.info(
                f"[{source}] Boost ended for area {area_id}, turned off (started from off)"
            )
            return True
        else:
            # Lights were on - return to current circadian settings (is_on stays True)
            config = self._get_config(area_id)
            area_state = self._get_area_state(area_id)
            hour = (
                area_state.frozen_at
                if area_state.frozen_at is not None
                else get_current_hour()
            )
            sun_times = (
                self.client._get_sun_times()
                if hasattr(self.client, "_get_sun_times")
                else None
            )

            result = CircadianLight.calculate_lighting(
                hour, config, area_state, sun_times=sun_times
            )
            await self._apply_lighting(area_id, result.brightness, result.color_temp)
            logger.info(
                f"[{source}] Boost ended for area {area_id}, returned to circadian: "
                f"{result.brightness}%, {result.color_temp}K"
            )
            return False

    async def check_expired_boosts(self, log_periodic: bool = False):
        """Check for and handle any expired boosts.

        Called every second from the fast tick loop.
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
            logger.debug(
                f"[{source}] motion_on_only: area {area_id} already on, skipping"
            )
            # If boost requested, apply it (lights already on, so no flash issue)
            # Don't use from_motion=True here because on_only doesn't start a motion
            # timer — the "motion" sentinel would never clear.
            if has_boost:
                await self.bright_boost(
                    area_id,
                    boost_duration,
                    boost_brightness,
                    source=source,
                    from_motion=False,
                )
            return

        logger.info(f"[{source}] motion_on_only: turning on area {area_id}")

        # Turn on with circadian values (enables circadian control if needed)
        # Pass boost params so we go directly to final brightness (no intermediate step)
        await self.lights_on(
            area_id,
            source=source,
            boost_brightness=boost_brightness,
            boost_duration=boost_duration,
            from_motion=True,
        )

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
                logger.debug(
                    f"[{source}] motion_on_off: area {area_id} has forever timer, unchanged"
                )
            elif is_forever:
                # New timer is forever, upgrade to forever
                state.extend_motion_expires(area_id, "forever")
                logger.info(
                    f"[{source}] motion_on_off: upgraded timer to forever for area {area_id}"
                )
            else:
                # Both are timed - use MAX(remaining, new duration)
                now = datetime.now()
                current_remaining = (
                    datetime.fromisoformat(current_expires) - now
                ).total_seconds()

                if duration_seconds > current_remaining:
                    new_expires = (
                        now + timedelta(seconds=duration_seconds)
                    ).isoformat()
                    state.extend_motion_expires(area_id, new_expires)
                    logger.debug(
                        f"[{source}] motion_on_off: extended timer for area {area_id} to {new_expires}"
                    )
                else:
                    logger.debug(
                        f"[{source}] motion_on_off: keeping existing timer ({current_remaining:.0f}s remaining > {duration_seconds}s new)"
                    )

            # If boost requested, apply/extend it (lights already on, so no flash issue)
            if has_boost:
                await self.bright_boost(
                    area_id,
                    boost_duration,
                    boost_brightness,
                    source=source,
                    from_motion=True,
                )
            return

        # Check if area is already on under circadian control (but not from on_off motion)
        if state.is_circadian(area_id) and state.get_is_on(area_id):
            logger.debug(
                f"[{source}] motion_on_off: area {area_id} already on (not from motion), skipping"
            )
            # If boost requested, apply it (lights already on, so no flash issue)
            # Don't use from_motion=True here because we didn't start a motion
            # timer — the "motion" sentinel would never clear.
            if has_boost:
                await self.bright_boost(
                    area_id,
                    boost_duration,
                    boost_brightness,
                    source=source,
                    from_motion=False,
                )
            return

        logger.info(
            f"[{source}] motion_on_off: turning on area {area_id}, timer={'forever' if is_forever else f'{duration_seconds}s'}"
        )

        # Set motion timer
        expires_at = (
            "forever"
            if is_forever
            else (datetime.now() + timedelta(seconds=duration_seconds)).isoformat()
        )
        state.set_motion_expires(area_id, expires_at)

        # Turn on with circadian values (enables circadian control if needed)
        # Pass boost params so we go directly to final brightness (no intermediate step)
        await self.lights_on(
            area_id,
            source=source,
            boost_brightness=boost_brightness,
            boost_duration=boost_duration,
            from_motion=True,
        )

    async def end_motion_on_off(self, area_id: str, source: str = "timer"):
        """End motion on_off timer and turn off lights.

        Called when motion on_off timer expires.
        Also clears any motion-coupled boost (boost_expires_at == "motion").

        Args:
            area_id: The area ID
            source: Source of the action
        """
        if not state.has_motion_timer(area_id):
            logger.debug(
                f"[{source}] Area {area_id} has no motion timer, nothing to end"
            )
            return

        # Clear motion timer
        state.clear_motion_expires(area_id)

        # Clear any motion-coupled boost (it ends with the motion timer)
        if state.is_boost_motion_coupled(area_id):
            state.clear_boost(area_id)
            logger.info(f"[{source}] Cleared motion-coupled boost for area {area_id}")

        # Store CT before turning off for smart 2-step on next turn-on
        try:
            config = self._get_config(area_id)
            area_state = self._get_area_state(area_id)
            hour = (
                area_state.frozen_at
                if area_state.frozen_at is not None
                else get_current_hour()
            )
            sun_times = (
                self.client._get_sun_times()
                if hasattr(self.client, "_get_sun_times")
                else None
            )
            result = CircadianLight.calculate_lighting(
                hour, config, area_state, sun_times=sun_times
            )
            state.set_last_off_ct(area_id, result.color_temp)
        except Exception as e:
            logger.warning(f"Could not store CT for area {area_id}: {e}")

        # Turn off (set is_on=False, Circadian enforces off state)
        transition = self._get_turn_off_transition()
        await self._turn_off_area(area_id, transition=transition)
        await self.client.turn_off_switch_entities(area_id)
        state.set_is_on(area_id, False)
        state.set_off_enforced(area_id, False)
        logger.info(
            f"[{source}] Motion on_off timer expired for area {area_id}, turned off"
        )

    async def check_expired_motion(self, log_periodic: bool = False):
        """Check for and handle any expired motion on_off timers.

        Called every second from the fast tick loop.
        """
        expired = state.get_expired_motion()
        for area_id in expired:
            # Clear any warning state before turning off
            state.clear_motion_warning(area_id)
            await self.end_motion_on_off(area_id, source="timer_expired")

    # -------------------------------------------------------------------------
    # Wake Alarm
    # -------------------------------------------------------------------------

    async def check_wake_alarms(self):
        """Check for and fire any due wake alarms.

        Called every second from the fast tick loop. For each area with
        wake_alarm enabled, fires glo_reset + lights_on once per day at
        the configured time.
        """
        try:
            raw_config = glozone.load_config_from_files()
        except Exception:
            return

        area_settings = raw_config.get("area_settings", {})
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        current_weekday = now.weekday()  # 0=Mon..6=Sun
        current_hour = now.hour + now.minute / 60.0

        for area_id, settings in area_settings.items():
            if not settings.get("wake_alarm"):
                continue

            # Skip if not an active day
            active_days = settings.get("wake_alarm_days", [0, 1, 2, 3, 4, 5, 6])
            if current_weekday not in active_days:
                continue

            # Resolve alarm time
            mode = settings.get("wake_alarm_mode", "rhythm")
            alarm_time = None

            if mode == "custom":
                alarm_time = settings.get("wake_alarm_time")
            else:
                # Rhythm mode: look up zone's rhythm wake time
                try:
                    zone_name = glozone.get_zone_for_area(area_id)

                    # Check if schedule override mode is "off" (alarm paused)
                    glozones = glozone.get_glozones()
                    zone_gz = glozones.get(zone_name, {})
                    override = zone_gz.get("schedule_override")
                    if override and override.get("mode") == "off":
                        until_date_str = override.get("until_date")
                        if until_date_str:
                            from datetime import date as date_cls

                            try:
                                until_date = date_cls.fromisoformat(until_date_str)
                                if now.date() <= until_date:
                                    continue  # Alarm suppressed by "off" override
                            except ValueError:
                                pass
                        else:
                            # No until_date = forever pause
                            continue

                    zone_cfg = glozone.get_effective_config_for_zone(zone_name)
                    # Check alt days for today
                    wake_time = zone_cfg.get("wake_time", 7.0)
                    wake_alt_time = zone_cfg.get("wake_alt_time")
                    wake_alt_days = zone_cfg.get("wake_alt_days", [])
                    if wake_alt_time is not None and current_weekday in wake_alt_days:
                        wake_time = wake_alt_time
                    offset = settings.get("wake_alarm_offset", 0)
                    alarm_time = wake_time + offset / 60.0
                except Exception as e:
                    logger.warning(
                        f"[wake_alarm] Failed to resolve rhythm wake time "
                        f"for {area_id}: {e}"
                    )
                    continue

            if alarm_time is None:
                continue

            # Skip if already fired today for this exact alarm time
            # (re-arms if user changes alarm time after it fired)
            fired = self._wake_alarm_fired.get(area_id)
            if fired and fired["date"] == today_str and fired["time"] == alarm_time:
                continue

            if current_hour >= alarm_time:
                self._wake_alarm_fired[area_id] = {
                    "date": today_str,
                    "time": alarm_time,
                }
                self._save_wake_alarm_fired()
                logger.info(
                    f"[wake_alarm] Firing wake alarm for area {area_id} "
                    f"(time={alarm_time:.2f}, now={current_hour:.2f})"
                )
                await self.glo_reset(area_id, source="wake_alarm")
                await self.lights_on(area_id, source="wake_alarm")

    def clear_wake_alarm_fired(self):
        """Clear wake alarm fired tracking, arming alarms for the next day."""
        if self._wake_alarm_fired:
            logger.info(
                f"[wake_alarm] Clearing fired state for "
                f"{len(self._wake_alarm_fired)} area(s)"
            )
            self._wake_alarm_fired.clear()
            self._save_wake_alarm_fired()

    def _get_wake_alarm_file(self) -> str:
        """Get the path to the wake alarm fired state file."""
        import os

        data_dir = os.environ.get("CIRCADIAN_DATA_DIR", "/config/circadian-light")
        return os.path.join(data_dir, "wake_alarm_fired.json")

    def _save_wake_alarm_fired(self):
        """Persist wake alarm fired state to disk."""
        import json
        import os

        path = self._get_wake_alarm_file()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                json.dump(self._wake_alarm_fired, f)
            logger.info(f"[wake_alarm] Saved fired state to {path}")
        except Exception as e:
            logger.warning(f"[wake_alarm] Failed to save fired state: {e}")

    def _load_wake_alarm_fired(self):
        """Load wake alarm fired state from disk."""
        import json
        import os

        path = self._get_wake_alarm_file()
        if not os.path.exists(path):
            logger.info(f"[wake_alarm] No fired state file at {path}")
            return
        try:
            with open(path) as f:
                self._wake_alarm_fired = json.load(f)
            logger.info(
                f"[wake_alarm] Loaded fired state: {len(self._wake_alarm_fired)} area(s)"
            )
        except Exception as e:
            logger.warning(f"[wake_alarm] Failed to load fired state: {e}")

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

    async def check_motion_warnings(self, log_periodic: bool = False):
        """Check for areas that need motion warnings and trigger them.

        Called every second from the fast tick loop.
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
        hour = (
            area_state.frozen_at
            if area_state.frozen_at is not None
            else get_current_hour()
        )
        sun_times = (
            self.client._get_sun_times()
            if hasattr(self.client, "_get_sun_times")
            else None
        )

        result = CircadianLight.calculate_lighting(
            hour, config, area_state, sun_times=sun_times
        )
        current_brightness = result.brightness

        # Add boost if boosted
        if state.is_boosted(area_id):
            boost_state = state.get_boost_state(area_id)
            boost_amount = boost_state.get("boost_brightness") or 0
            current_brightness = min(100, current_brightness + boost_amount)

        # Store pre-warning brightness for potential restoration
        state.set_motion_warning(area_id, current_brightness)

        logger.info(
            f"[motion_warning] Triggering warning for area {area_id}, current brightness={current_brightness}%"
        )

        if current_brightness > blink_threshold:
            # Above threshold: dim to 50% of current
            warning_brightness = int(current_brightness * 0.5)
            await self._apply_lighting(
                area_id,
                warning_brightness,
                result.color_temp,
                include_color=False,
                transition=0.5,
            )
            logger.info(
                f"[motion_warning] Dimmed area {area_id} from {current_brightness}% to {warning_brightness}%"
            )
        else:
            # At or below threshold: blink off, then hold at 3%
            await self._apply_lighting(
                area_id, 0, result.color_temp, include_color=False, transition=0.1
            )
            await asyncio.sleep(0.3)  # 300ms off
            warning_brightness = 3
            await self._apply_lighting(
                area_id,
                warning_brightness,
                result.color_temp,
                include_color=False,
                transition=0.1,
            )
            logger.info(
                f"[motion_warning] Blinked area {area_id} (was {current_brightness}%), holding at {warning_brightness}%"
            )

    async def cancel_motion_warning(
        self, area_id: str, source: str = "motion_detected"
    ):
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
            hour = (
                area_state.frozen_at
                if area_state.frozen_at is not None
                else get_current_hour()
            )
            sun_times = (
                self.client._get_sun_times()
                if hasattr(self.client, "_get_sun_times")
                else None
            )

            result = CircadianLight.calculate_lighting(
                hour, config, area_state, sun_times=sun_times
            )
            await self._apply_lighting(
                area_id, pre_warning_brightness, result.color_temp, transition=0.3
            )
            logger.info(
                f"[{source}] Cancelled motion warning for area {area_id}, restored to {pre_warning_brightness}%"
            )

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

        # Store CT before turning off for smart 2-step on next turn-on
        try:
            config = self._get_config(area_id)
            area_state = self._get_area_state(area_id)
            hour = (
                area_state.frozen_at
                if area_state.frozen_at is not None
                else get_current_hour()
            )
            sun_times = (
                self.client._get_sun_times()
                if hasattr(self.client, "_get_sun_times")
                else None
            )
            result = CircadianLight.calculate_lighting(
                hour, config, area_state, sun_times=sun_times
            )
            state.set_last_off_ct(area_id, result.color_temp)
        except Exception as e:
            logger.warning(f"Could not store CT for area {area_id}: {e}")

        # Turn off (set is_on=False, Circadian enforces off state)
        transition = self._get_turn_off_transition()
        await self._turn_off_area(area_id, transition=transition)
        state.set_is_on(area_id, False)
        logger.info(f"[{source}] Contact closed: turned off area {area_id}")

    # -------------------------------------------------------------------------
    # Set - Configure area state (presets, frozen_at, copy_from)
    # -------------------------------------------------------------------------

    async def set(
        self,
        area_id: str,
        source: str = "service_call",
        preset: str = None,
        frozen_at: float = None,
        copy_from: str = None,
        is_on: bool = None,
        send_command: bool = True,
    ):
        """Configure area state with presets, frozen_at, or copy settings.

        Presets:
            - wake_or_bed: Set midpoints to match designed wake/bed brightness.
              Ascend phase → wake settings, descend phase → bed settings.
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
            logger.info(
                f"[{source}] Taking control of area {area_id} with is_on={is_on}"
            )

        # Priority 1: copy_from another area
        if copy_from:
            source_state = state.get_area(copy_from)
            if source_state:
                # Copy relevant state from source area
                state.update_area(
                    area_id,
                    {
                        "frozen_at": source_state.get("frozen_at"),
                        "brightness_mid": source_state.get("brightness_mid"),
                        "color_mid": source_state.get("color_mid"),
                        "color_override": source_state.get("color_override"),
                        "brightness_override": source_state.get("brightness_override"),
                        "brightness_override_set_at": source_state.get(
                            "brightness_override_set_at"
                        ),
                        "color_override_set_at": source_state.get(
                            "color_override_set_at"
                        ),
                    },
                )
                logger.info(f"[{source}] Copied settings from {copy_from} to {area_id}")

                # Apply lighting or turn off based on state
                if (
                    state.is_circadian(area_id)
                    and state.get_is_on(area_id)
                    and send_command
                ):
                    area_state = self._get_area_state(area_id)
                    hour = (
                        area_state.frozen_at
                        if area_state.frozen_at is not None
                        else current_hour
                    )
                    result = CircadianLight.calculate_lighting(hour, config, area_state)
                    await self._apply_circadian_lighting(
                        area_id, result.brightness, result.color_temp
                    )
                elif take_control and is_on == False and send_command:
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
            if (
                state.is_circadian(area_id)
                and state.get_is_on(area_id)
                and send_command
            ):
                area_state = self._get_area_state(area_id)
                result = CircadianLight.calculate_lighting(
                    frozen_at, config, area_state
                )
                await self._apply_circadian_lighting(
                    area_id, result.brightness, result.color_temp
                )
            elif take_control and is_on == False and send_command:
                transition = self._get_turn_off_transition()
                await self._turn_off_area(area_id, transition=transition)
            return

        # Priority 3: preset
        if preset:
            # Check if preset is a moment (multi-area preset)
            moments = self._get_moments()
            if preset.lower() in moments:
                await self._apply_moment(preset.lower(), source)
                return

            # Single-area built-in presets
            # Reset state first (clears midpoints, bounds, frozen_at; preserves enabled)
            state.reset_area(area_id)

            if preset == "wake_or_bed":
                # Set midpoints so the curve output NOW matches what the rhythm
                # produces at wake_time/bed_time (including brightness shift).
                # Lights stay unfrozen so the curve continues from there.
                from brain import (
                    compute_shifted_midpoint,
                    resolve_effective_timing,
                    SPEED_TO_SLOPE,
                )

                in_ascend_now, h48_now, t_ascend, t_descend, slope = (
                    CircadianLight.get_phase_info(current_hour, config)
                )
                use_wake = in_ascend_now

                weekday = datetime.now().weekday()
                eff_wake, eff_bed = resolve_effective_timing(
                    config, current_hour, weekday
                )
                target_time = eff_wake if use_wake else eff_bed
                bri_pct = config.wake_brightness if use_wake else config.bed_brightness

                # Compute h48 at the target time
                _, h48_target, _, _, _ = CircadianLight.get_phase_info(
                    target_time, config
                )

                # Compute the shifted midpoint the brain would use at target_time
                # (this is the mid48 that produces the designed brightness there)
                default_mid = target_time
                if bri_pct != 50:
                    b_min_norm = config.min_brightness / 100.0
                    b_max_norm = config.max_brightness / 100.0
                    if use_wake:
                        target_slope = SPEED_TO_SLOPE[
                            max(1, min(10, config.wake_speed))
                        ]
                        mid48_raw = CircadianLight.lift_midpoint_to_phase(
                            default_mid, t_ascend, t_descend
                        )
                    else:
                        target_slope = -SPEED_TO_SLOPE[
                            max(1, min(10, config.bed_speed))
                        ]
                        descend_end = t_ascend + 24
                        mid48_raw = CircadianLight.lift_midpoint_to_phase(
                            default_mid, t_descend, descend_end
                        )
                    shifted_mid48 = compute_shifted_midpoint(
                        mid48_raw, bri_pct, target_slope, b_min_norm, b_max_norm
                    )
                else:
                    if use_wake:
                        shifted_mid48 = CircadianLight.lift_midpoint_to_phase(
                            default_mid, t_ascend, t_descend
                        )
                    else:
                        descend_end = t_ascend + 24
                        shifted_mid48 = CircadianLight.lift_midpoint_to_phase(
                            default_mid, t_descend, descend_end
                        )

                # Offset: shift so current time produces the target-time output
                new_mid48 = h48_now - h48_target + shifted_mid48
                new_mid = new_mid48 % 24

                state.update_area(
                    area_id,
                    {
                        "brightness_mid": new_mid,
                        "color_mid": new_mid,
                        "brightness_override": None,
                        "brightness_override_set_at": None,
                        "color_override": None,
                        "color_override_set_at": None,
                    },
                )
                phase_name = "wake" if use_wake else "bed"
                logger.info(
                    f"[{source}] Set {area_id} to {preset} preset "
                    f"({phase_name}, mid={new_mid:.2f}, target={target_time:.2f})"
                )

            elif preset == "nitelite":
                # Freeze at ascend_start (minimum values)
                # Reset midpoints to ensure true minimum brightness/color
                frozen_hour = config.ascend_start
                state.update_area(
                    area_id,
                    {
                        "brightness_mid": None,
                        "color_mid": None,
                        "brightness_override": None,
                        "brightness_override_set_at": None,
                        "color_override": None,
                        "color_override_set_at": None,
                    },
                )
                state.set_frozen_at(area_id, frozen_hour)
                logger.info(
                    f"[{source}] Set {area_id} to nitelite preset (frozen_at={frozen_hour})"
                )

            elif preset == "britelite":
                # Freeze at descend_start (maximum values)
                # Reset midpoints to ensure true maximum brightness/color
                frozen_hour = config.descend_start
                state.update_area(
                    area_id,
                    {
                        "brightness_mid": None,
                        "color_mid": None,
                        "brightness_override": None,
                        "brightness_override_set_at": None,
                        "color_override": None,
                        "color_override_set_at": None,
                    },
                )
                state.set_frozen_at(area_id, frozen_hour)
                logger.info(
                    f"[{source}] Set {area_id} to britelite preset (frozen_at={frozen_hour})"
                )

            else:
                logger.warning(f"[{source}] Unknown preset: {preset}")
                return

            # Apply lighting or turn off based on state
            if (
                state.is_circadian(area_id)
                and state.get_is_on(area_id)
                and send_command
            ):
                area_state = self._get_area_state(area_id)
                hour = (
                    area_state.frozen_at
                    if area_state.frozen_at is not None
                    else current_hour
                )
                logger.info(
                    f"[{source}] Preset apply: area_state.frozen_at={area_state.frozen_at}, using hour={hour}"
                )
                result = CircadianLight.calculate_lighting(hour, config, area_state)
                logger.info(
                    f"[{source}] Preset calculated: brightness={result.brightness}%, color_temp={result.color_temp}K at hour={hour}"
                )
                # Use turn_on_transition for presets (they're typically turn-on actions), boost-aware
                transition = self._get_turn_on_transition()
                await self._apply_circadian_lighting(
                    area_id, result.brightness, result.color_temp, transition=transition
                )
                # Also turn on any switch entities when preset turns lights on
                if take_control and is_on:
                    await self.client.turn_on_switch_entities(area_id)
            elif take_control and is_on == False and send_command:
                transition = self._get_turn_off_transition()
                await self._turn_off_area(area_id, transition=transition)
                await self.client.turn_off_switch_entities(area_id)

    # -------------------------------------------------------------------------
    # Freeze Toggle (kept for manual toggling)
    # -------------------------------------------------------------------------

    def _unfreeze_internal(self, area_id: str, source: str = "internal"):
        """Internal unfreeze: re-anchor midpoints so curve continues smoothly.

        Re-anchors midpoints so current time produces the same values as
        the frozen position, then clears frozen_at. No sudden jump.

        Also compensates for solar rule differences between frozen hour and
        current hour by setting a color_override. This prevents a visible
        jump when e.g. unfreezing from britelite (noon, no warm_night) at
        evening (warm_night active).

        Args:
            area_id: The area ID
            source: Source of the action
        """
        from brain import inverse_midpoint, _converge_override

        frozen_at = state.get_frozen_at(area_id)
        if frozen_at is None:
            return

        config = self._get_config(area_id)
        area_state = self._get_area_state(area_id)
        current_hour = get_current_hour()
        sun_times = (
            self.client._get_sun_times()
            if hasattr(self.client, "_get_sun_times")
            else None
        )

        # Calculate current frozen values
        # Use brightness as-is, but use NATURAL color (no solar rules) for midpoint re-anchoring
        # Solar rules are applied at render time, not baked into the curve midpoint
        frozen_bri = CircadianLight.calculate_brightness_at_hour(
            frozen_at, config, area_state
        )
        frozen_color = CircadianLight.calculate_color_at_hour(
            frozen_at, config, area_state, apply_solar_rules=False
        )

        # What the user was seeing while frozen (rendered with solar rules at frozen hour)
        frozen_rendered = CircadianLight.calculate_color_at_hour(
            frozen_at, config, area_state, apply_solar_rules=True, sun_times=sun_times
        )

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
        state.update_area(
            area_id,
            {
                "brightness_mid": new_bri_mid,
                "color_mid": new_color_mid,
                "frozen_at": None,
            },
        )

        # Compensate for solar rule differences between frozen hour and current hour.
        # Without this, unfreezing from britelite (noon, no warm_night) at evening
        # would cause a sudden drop as warm_night kicks in.
        new_state = self._get_area_state(area_id)
        current_rendered = CircadianLight.calculate_color_at_hour(
            current_hour, config, new_state, apply_solar_rules=True, sun_times=sun_times
        )
        safe_margin_cct = max(10, (c_max - c_min) * 0.01)
        tolerance = max(5, safe_margin_cct * 0.5)

        if abs(frozen_rendered - current_rendered) > tolerance:

            def _render_unfreeze(ovr):
                s = AreaState(
                    is_circadian=new_state.is_circadian,
                    is_on=new_state.is_on,
                    frozen_at=None,
                    brightness_mid=new_state.brightness_mid,
                    color_mid=new_state.color_mid,
                    color_override=ovr,
                )
                return CircadianLight.calculate_color_at_hour(
                    current_hour,
                    config,
                    s,
                    apply_solar_rules=True,
                    sun_times=sun_times,
                )

            override = _converge_override(
                frozen_rendered,
                current_rendered,
                tolerance,
                _render_unfreeze,
            )
            if override is not None:
                state.update_area(area_id, {"color_override": override})
                logger.info(
                    f"[{source}] Solar rule compensation for {area_id}: "
                    f"frozen_rendered={frozen_rendered}K, current_rendered={current_rendered}K, "
                    f"override={override:.1f}"
                )

        logger.info(
            f"[{source}] Unfrozen {area_id}: re-anchored midpoints to "
            f"bri_mid={new_bri_mid:.2f}, color_mid={new_color_mid:.2f}"
        )

    async def freeze_toggle(self, area_id: str, source: str = "service_call"):
        """Toggle freeze state for a single area.

        Visual feedback is handled separately by the caller via _feedback_cue.

        Args:
            area_id: The area ID
            source: Source of the action
        """
        await self.freeze_toggle_multiple([area_id], source)

    async def freeze_toggle_multiple(
        self, area_ids: list, source: str = "service_call"
    ):
        """Toggle freeze state for multiple areas.

        Toggles the freeze state for all circadian areas. Visual feedback
        is handled separately by the caller via _feedback_cue.

        Args:
            area_ids: List of area IDs
            source: Source of the action
        """
        if not area_ids:
            return

        # Filter to areas under circadian control
        circadian_areas = [a for a in area_ids if state.is_circadian(a)]
        if not circadian_areas:
            logger.info(f"[{source}] No circadian areas for freeze_toggle_multiple")
            return

        # Check freeze state of first area (all should be same, but use first as reference)
        is_frozen = state.is_frozen(circadian_areas[0])

        if is_frozen:
            # Was frozen → unfreeze all
            for area_id in circadian_areas:
                self._unfreeze_internal(area_id, source)
            logger.info(
                f"[{source}] Freeze toggle: {len(circadian_areas)} area(s) unfrozen"
            )
        else:
            # Was unfrozen → freeze all at current time
            frozen_at = get_current_hour()
            for area_id in circadian_areas:
                state.set_frozen_at(area_id, frozen_at)
            logger.info(
                f"[{source}] Freeze toggle: {len(circadian_areas)} area(s) frozen at hour {frozen_at:.2f}"
            )

    # -------------------------------------------------------------------------
    # Reset
    # -------------------------------------------------------------------------

    async def glo_reset(
        self, area_id: str, source: str = "service_call", send_command: bool = True
    ):
        """Reset area to Daily Rhythm settings.

        Resets midpoints, bounds, and frozen_at to defaults.
        Preserves enabled status. Only applies lighting if already enabled
        and send_command=True.

        Args:
            area_id: The area ID
            source: Source of the action
            send_command: Whether to send light commands (False for reach group batching)
        """
        logger.info(f"[{source}] glo_reset for area {area_id}")

        # Reset state (clears midpoints/bounds/frozen_at, preserves only enabled)
        state.reset_area(area_id)

        # Apply current time values only if circadian and is_on
        if state.is_circadian(area_id) and state.get_is_on(area_id):
            config = self._get_config(area_id)
            area_state = self._get_area_state(area_id)
            hour = get_current_hour()

            result = CircadianLight.calculate_lighting(hour, config, area_state)
            if send_command:
                await self._apply_circadian_lighting(
                    area_id, result.brightness, result.color_temp
                )

            logger.info(
                f"glo_reset complete for area {area_id}: "
                f"{result.brightness}%, {result.color_temp}K"
            )
        else:
            logger.info(
                f"glo_reset complete for area {area_id} (not circadian or lights off, no lighting change)"
            )

    # -------------------------------------------------------------------------
    # GloZone Primitives - Zone-based state synchronization
    # -------------------------------------------------------------------------

    async def glo_up(self, area_id: str, source: str = "service_call"):
        """Push area's runtime state to its GloZone.

        GloUp sends this area's brightness/color settings to the zone state.
        Does not propagate to other areas - use glozone_down for that.

        Args:
            area_id: The area ID to push from
            source: Source of the action
        """
        logger.info(f"[{source}] glo_up for area {area_id}")

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
            "color_override": area_state_dict.get("color_override"),
            "brightness_override": area_state_dict.get("brightness_override"),
            "brightness_override_set_at": area_state_dict.get(
                "brightness_override_set_at"
            ),
            "color_override_set_at": area_state_dict.get("color_override_set_at"),
        }

        # Push to zone state
        glozone_state.set_zone_state(zone_name, runtime_state)
        logger.info(
            f"glo_up complete: pushed state to zone '{zone_name}': {runtime_state}"
        )

    async def glo_down(
        self, area_id: str, source: str = "service_call", send_command: bool = True
    ):
        """Pull GloZone's runtime state to this area.

        glo_down syncs this area to match its zone's state. Use when you want
        a single area to rejoin the zone's current settings.

        Also cancels any active boost for the area.

        Args:
            area_id: The area ID to sync to zone state
            source: Source of the action
            send_command: Whether to send light commands (False for reach group batching)
        """
        logger.info(f"[{source}] glo_down for area {area_id}")

        # Clear boost state if boosted (glo_down overrides boost)
        if state.is_boosted(area_id):
            state.clear_boost(area_id)
            logger.info(f"Cleared boost for area {area_id} (glo_down)")

        # Reload glozone config from disk (webserver may have updated it)
        glozone.reload()

        # Get the zone this area belongs to
        zone_name = glozone.get_zone_for_area(area_id)
        logger.info(f"Area {area_id} is in zone '{zone_name}'")

        # Get zone's runtime state
        zone_state = glozone_state.get_zone_state(zone_name)
        logger.info(f"Zone '{zone_name}' state: {zone_state}")

        # Copy zone state to area
        state.update_area(
            area_id,
            {
                "brightness_mid": zone_state.get("brightness_mid"),
                "color_mid": zone_state.get("color_mid"),
                "frozen_at": zone_state.get("frozen_at"),
                "color_override": zone_state.get("color_override"),
                "brightness_override": zone_state.get("brightness_override"),
                "brightness_override_set_at": zone_state.get(
                    "brightness_override_set_at"
                ),
                "color_override_set_at": zone_state.get("color_override_set_at"),
            },
        )
        logger.info(f"Copied zone state to area {area_id}")

        # Apply lighting if area is circadian and is_on
        if state.is_circadian(area_id) and state.get_is_on(area_id) and send_command:
            await self.client.update_lights_in_circadian_mode(area_id)
            logger.info(f"glo_down complete for {area_id}")
        elif not state.is_circadian(area_id) or not state.get_is_on(area_id):
            logger.info(
                f"glo_down complete for {area_id} (not circadian or lights off, no lighting change)"
            )
        else:
            logger.info(
                f"glo_down complete for {area_id} (state updated, command deferred)"
            )

    # -------------------------------------------------------------------------
    # GloZone-level Primitives - Zone state operations
    # -------------------------------------------------------------------------

    async def glozone_reset(self, zone_name: str, source: str = "service_call"):
        """Reset GloZone to Daily Rhythm settings.

        Clears the zone's runtime state (brightness_mid, color_mid, frozen_at
        all become None). Does not propagate to areas - use glozone_down for that.

        Args:
            zone_name: The zone name to reset
            source: Source of the action
        """
        logger.info(f"[{source}] glozone_reset for zone '{zone_name}'")

        # Reload glozone config from disk (webserver may have updated it)
        glozone.reload()

        # Reset zone state to defaults (None)
        glozone_state.reset_zone_state(zone_name)
        logger.info(
            f"glozone_reset complete: zone '{zone_name}' reset to Daily Rhythm defaults"
        )

    async def glozone_down(self, zone_name: str, source: str = "service_call"):
        """Push GloZone settings to all areas in the zone.

        Copies the zone's runtime state to all member areas and applies lighting.

        Args:
            zone_name: The zone name
            source: Source of the action
        """
        logger.info(f"[{source}] glozone_down for zone '{zone_name}'")

        # Reload glozone config from disk (webserver may have updated it)
        glozone.reload()

        # Get zone's runtime state
        zone_state = glozone_state.get_zone_state(zone_name)
        runtime_state = {
            "brightness_mid": zone_state.get("brightness_mid"),
            "color_mid": zone_state.get("color_mid"),
            "frozen_at": zone_state.get("frozen_at"),
            "color_override": zone_state.get("color_override"),
            "brightness_override": zone_state.get("brightness_override"),
            "brightness_override_set_at": zone_state.get("brightness_override_set_at"),
            "color_override_set_at": zone_state.get("color_override_set_at"),
        }
        logger.info(f"Zone '{zone_name}' state: {runtime_state}")

        # Get all areas in the zone
        zone_areas = glozone.get_areas_in_zone(zone_name)
        logger.info(f"Zone '{zone_name}' has {len(zone_areas)} area(s): {zone_areas}")

        # Propagate to all areas in the zone
        for target_area_id in zone_areas:
            # Clear boost state if boosted (zone push overrides boost)
            if state.is_boosted(target_area_id):
                state.clear_boost(target_area_id)
                logger.debug(f"Cleared boost for area {target_area_id}")

            # Copy state to target area
            state.update_area(target_area_id, runtime_state)
            logger.debug(f"Copied state to area {target_area_id}")

            # Apply lighting if the target area is circadian and is_on
            if state.is_circadian(target_area_id) and state.get_is_on(target_area_id):
                await self.client.update_lights_in_circadian_mode(target_area_id)
                logger.debug(f"Triggered lighting update for {target_area_id}")

        logger.info(
            f"glozone_down complete: synced {len(zone_areas)} area(s) in zone '{zone_name}'"
        )

    async def full_send(self, area_id: str, source: str = "service_call"):
        """Push area settings to GloZone, then to all areas in zone.

        Compound action: glo_up + glozone_down.
        Use when you want all areas in a zone to match this area's settings.

        Args:
            area_id: The area ID to push from
            source: Source of the action
        """
        logger.info(f"[{source}] full_send for area {area_id}")

        # Get the zone this area belongs to
        glozone.reload()
        zone_name = glozone.get_zone_for_area(area_id)

        # Step 1: Push area state to zone
        await self.glo_up(area_id, source)

        # Step 2: Push zone state to all areas
        await self.glozone_down(zone_name, source)

        logger.info(f"full_send complete for area {area_id} in zone '{zone_name}'")

    # -------------------------------------------------------------------------
    # Zone-level actions (modify zone state only, no light control)
    # -------------------------------------------------------------------------

    def _get_zone_config(self, zone_name: str) -> Config:
        """Get config for a zone."""
        config_dict = glozone.get_effective_config_for_zone(zone_name)
        if config_dict:
            return Config.from_dict(config_dict)
        return self._get_config()

    def _get_zone_area_state(self, zone_name: str) -> AreaState:
        """Create an AreaState from zone runtime state for calculation purposes."""
        zs = glozone_state.get_zone_state(zone_name)
        return AreaState(
            is_circadian=True,
            is_on=True,
            frozen_at=zs.get("frozen_at"),
            brightness_mid=zs.get("brightness_mid"),
            color_mid=zs.get("color_mid"),
            color_override=zs.get("color_override"),
        )

    def _update_zone_state(self, zone_name: str, updates: dict):
        """Write state_updates back to zone runtime state."""
        glozone_state.set_zone_state(zone_name, updates)

    async def zone_step_up(self, zone_name: str, source: str = "webserver"):
        """Step up zone state along circadian curve."""
        config = self._get_zone_config(zone_name)
        zone_state = self._get_zone_area_state(zone_name)

        if zone_state.frozen_at is not None:
            frozen_bri = CircadianLight.calculate_brightness_at_hour(
                zone_state.frozen_at, config, zone_state
            )
            frozen_cct = CircadianLight.calculate_color_at_hour(
                zone_state.frozen_at, config, zone_state, apply_solar_rules=False
            )
            bri_margin = max(
                1.0, (config.max_brightness - config.min_brightness) * 0.01
            )
            cct_margin = max(10, (config.max_color_temp - config.min_color_temp) * 0.01)
            if (
                frozen_bri >= config.max_brightness - bri_margin
                and frozen_cct >= config.max_color_temp - cct_margin
            ):
                logger.info(f"Zone step up at limit for '{zone_name}'")
                return
            # Unfreeze
            self._update_zone_state(zone_name, {"frozen_at": None})
            zone_state = self._get_zone_area_state(zone_name)

        hour = get_current_hour()
        sun_times = (
            self.client._get_sun_times()
            if hasattr(self.client, "_get_sun_times")
            else None
        )
        result = CircadianLight.calculate_step(
            hour=hour,
            direction="up",
            config=config,
            state=zone_state,
            sun_times=sun_times,
        )
        if result is None:
            logger.info(f"Zone step up at limit for '{zone_name}'")
            return
        self._update_zone_state(zone_name, result.state_updates)
        logger.info(
            f"[{source}] Zone step up for '{zone_name}': {result.state_updates}"
        )

    async def zone_step_down(self, zone_name: str, source: str = "webserver"):
        """Step down zone state along circadian curve."""
        config = self._get_zone_config(zone_name)
        zone_state = self._get_zone_area_state(zone_name)

        if zone_state.frozen_at is not None:
            frozen_bri = CircadianLight.calculate_brightness_at_hour(
                zone_state.frozen_at, config, zone_state
            )
            frozen_cct = CircadianLight.calculate_color_at_hour(
                zone_state.frozen_at, config, zone_state, apply_solar_rules=False
            )
            bri_margin = max(
                1.0, (config.max_brightness - config.min_brightness) * 0.01
            )
            cct_margin = max(10, (config.max_color_temp - config.min_color_temp) * 0.01)
            if (
                frozen_bri <= config.min_brightness + bri_margin
                and frozen_cct <= config.min_color_temp + cct_margin
            ):
                logger.info(f"Zone step down at limit for '{zone_name}'")
                return
            self._update_zone_state(zone_name, {"frozen_at": None})
            zone_state = self._get_zone_area_state(zone_name)

        hour = get_current_hour()
        sun_times = (
            self.client._get_sun_times()
            if hasattr(self.client, "_get_sun_times")
            else None
        )
        result = CircadianLight.calculate_step(
            hour=hour,
            direction="down",
            config=config,
            state=zone_state,
            sun_times=sun_times,
        )
        if result is None:
            logger.info(f"Zone step down at limit for '{zone_name}'")
            return
        self._update_zone_state(zone_name, result.state_updates)
        logger.info(
            f"[{source}] Zone step down for '{zone_name}': {result.state_updates}"
        )

    async def zone_bright_up(self, zone_name: str, source: str = "webserver"):
        """Increase zone brightness only."""
        config = self._get_zone_config(zone_name)
        zone_state = self._get_zone_area_state(zone_name)

        if zone_state.frozen_at is not None:
            frozen_bri = CircadianLight.calculate_brightness_at_hour(
                zone_state.frozen_at, config, zone_state
            )
            safe_margin = max(
                1.0, (config.max_brightness - config.min_brightness) * 0.01
            )
            if frozen_bri >= config.max_brightness - safe_margin:
                logger.info(f"Zone bright up at limit for '{zone_name}'")
                return
            self._update_zone_state(zone_name, {"frozen_at": None})
            zone_state = self._get_zone_area_state(zone_name)

        hour = get_current_hour()
        sun_times = (
            self.client._get_sun_times()
            if hasattr(self.client, "_get_sun_times")
            else None
        )
        result = CircadianLight.calculate_bright_step(
            hour=hour,
            direction="up",
            config=config,
            state=zone_state,
            sun_times=sun_times,
        )
        if result is None:
            logger.info(f"Zone bright up at limit for '{zone_name}'")
            return
        self._update_zone_state(zone_name, result.state_updates)
        logger.info(
            f"[{source}] Zone bright up for '{zone_name}': {result.state_updates}"
        )

    async def zone_bright_down(self, zone_name: str, source: str = "webserver"):
        """Decrease zone brightness only."""
        config = self._get_zone_config(zone_name)
        zone_state = self._get_zone_area_state(zone_name)

        if zone_state.frozen_at is not None:
            frozen_bri = CircadianLight.calculate_brightness_at_hour(
                zone_state.frozen_at, config, zone_state
            )
            safe_margin = max(
                1.0, (config.max_brightness - config.min_brightness) * 0.01
            )
            if frozen_bri <= config.min_brightness + safe_margin:
                logger.info(f"Zone bright down at limit for '{zone_name}'")
                return
            self._update_zone_state(zone_name, {"frozen_at": None})
            zone_state = self._get_zone_area_state(zone_name)

        hour = get_current_hour()
        sun_times = (
            self.client._get_sun_times()
            if hasattr(self.client, "_get_sun_times")
            else None
        )
        result = CircadianLight.calculate_bright_step(
            hour=hour,
            direction="down",
            config=config,
            state=zone_state,
            sun_times=sun_times,
        )
        if result is None:
            logger.info(f"Zone bright down at limit for '{zone_name}'")
            return
        self._update_zone_state(zone_name, result.state_updates)
        logger.info(
            f"[{source}] Zone bright down for '{zone_name}': {result.state_updates}"
        )

    async def zone_color_up(self, zone_name: str, source: str = "webserver"):
        """Increase zone color temperature (cooler)."""
        config = self._get_zone_config(zone_name)
        zone_state = self._get_zone_area_state(zone_name)

        if zone_state.frozen_at is not None:
            sun_times = (
                self.client._get_sun_times()
                if hasattr(self.client, "_get_sun_times")
                else None
            )
            frozen_cct = CircadianLight.calculate_color_at_hour(
                zone_state.frozen_at,
                config,
                zone_state,
                apply_solar_rules=True,
                sun_times=sun_times,
            )
            safe_margin = max(
                10, (config.max_color_temp - config.min_color_temp) * 0.01
            )
            if frozen_cct >= config.max_color_temp - safe_margin:
                logger.info(f"Zone color up at limit for '{zone_name}'")
                return
            self._update_zone_state(zone_name, {"frozen_at": None})
            zone_state = self._get_zone_area_state(zone_name)

        hour = get_current_hour()
        sun_times = (
            self.client._get_sun_times()
            if hasattr(self.client, "_get_sun_times")
            else None
        )
        result = CircadianLight.calculate_color_step(
            hour=hour,
            direction="up",
            config=config,
            state=zone_state,
            sun_times=sun_times,
        )
        if result is None:
            logger.info(f"Zone color up at limit for '{zone_name}'")
            return
        self._update_zone_state(zone_name, result.state_updates)
        logger.info(
            f"[{source}] Zone color up for '{zone_name}': {result.state_updates}"
        )

    async def zone_color_down(self, zone_name: str, source: str = "webserver"):
        """Decrease zone color temperature (warmer)."""
        config = self._get_zone_config(zone_name)
        zone_state = self._get_zone_area_state(zone_name)

        if zone_state.frozen_at is not None:
            sun_times = (
                self.client._get_sun_times()
                if hasattr(self.client, "_get_sun_times")
                else None
            )
            frozen_cct = CircadianLight.calculate_color_at_hour(
                zone_state.frozen_at,
                config,
                zone_state,
                apply_solar_rules=True,
                sun_times=sun_times,
            )
            safe_margin = max(
                10, (config.max_color_temp - config.min_color_temp) * 0.01
            )
            if frozen_cct <= config.min_color_temp + safe_margin:
                logger.info(f"Zone color down at limit for '{zone_name}'")
                return
            self._update_zone_state(zone_name, {"frozen_at": None})
            zone_state = self._get_zone_area_state(zone_name)

        hour = get_current_hour()
        sun_times = (
            self.client._get_sun_times()
            if hasattr(self.client, "_get_sun_times")
            else None
        )
        result = CircadianLight.calculate_color_step(
            hour=hour,
            direction="down",
            config=config,
            state=zone_state,
            sun_times=sun_times,
        )
        if result is None:
            logger.info(f"Zone color down at limit for '{zone_name}'")
            return
        self._update_zone_state(zone_name, result.state_updates)
        logger.info(
            f"[{source}] Zone color down for '{zone_name}': {result.state_updates}"
        )

    async def zone_set_position(
        self,
        zone_name: str,
        value: float,
        mode: str = "step",
        source: str = "webserver",
    ):
        """Set zone position along circadian curve (0=min, 100=max)."""
        config = self._get_zone_config(zone_name)
        zone_state = self._get_zone_area_state(zone_name)

        # Always unfreeze for position setting
        if zone_state.frozen_at is not None:
            self._update_zone_state(zone_name, {"frozen_at": None})
            zone_state = self._get_zone_area_state(zone_name)

        hour = get_current_hour()
        sun_times = (
            self.client._get_sun_times()
            if hasattr(self.client, "_get_sun_times")
            else None
        )
        result = CircadianLight.calculate_set_position(
            hour=hour,
            position=value,
            dimension=mode,
            config=config,
            state=zone_state,
            sun_times=sun_times,
        )
        self._update_zone_state(zone_name, result.state_updates)
        logger.info(
            f"[{source}] Zone set_position({value}, {mode}) for '{zone_name}': {result.state_updates}"
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
        *,
        rhythm_brightness: int = None,
        brightness_override: float = None,
        skip_filters: Set[str] = None,
        nudge: bool = True,
    ):
        """Apply lighting values to an area.

        Delegates to client.turn_on_lights_circadian() which is the single source
        of truth for light control. This ensures consistent behavior across all
        code paths (primitives, periodic updater, etc.).

        Args:
            area_id: The area ID
            brightness: Brightness percentage (0-100)
            color_temp: Color temperature in Kelvin
            include_color: Whether to include color in the command
            transition: Transition time in seconds
            rhythm_brightness: Pure curve brightness for filter curve position (pre-NL/boost).
                If provided, brightness_override is applied post-NL in the filter pipeline.
            brightness_override: Decay-adjusted additive delta applied post-NL.
            skip_filters: Set of filter_norms to skip (already handled by reach groups).
            nudge: Whether to schedule a post-command nudge (False for temporary Phase 1 states).
        """
        circadian_values = {
            "brightness": brightness,
            "kelvin": color_temp,
        }
        if rhythm_brightness is not None:
            circadian_values["rhythm_brightness"] = rhythm_brightness
        if brightness_override is not None:
            circadian_values["brightness_override"] = brightness_override
        if skip_filters:
            circadian_values["skip_filters"] = skip_filters

        await self.client.turn_on_lights_circadian(
            area_id,
            circadian_values,
            transition=transition,
            include_color=include_color,
        )
        if nudge:
            self.client.schedule_nudge(area_id, circadian_values)

    async def _apply_circadian_lighting(
        self,
        area_id: str,
        brightness: int,
        color_temp: int,
        include_color: bool = True,
        transition: float = 0.4,
        nudge: bool = True,
    ):
        """Apply circadian lighting with boost awareness and full pipeline context.

        This is a wrapper around _apply_lighting that automatically adds boost
        brightness if the area is boosted, and passes rhythm_brightness and
        brightness_override so the filter pipeline computes correct curve position
        and applies the override post-NL (matching the periodic update path).

        Use _apply_lighting directly when you've already calculated the final
        brightness (e.g., motion sensor boost functions).

        Args:
            area_id: The area ID
            brightness: Base circadian brightness percentage (0-100)
            color_temp: Color temperature in Kelvin
            include_color: Whether to include color in the command
            transition: Transition time in seconds
            nudge: Whether to schedule a post-command nudge (False for temporary Phase 1 states).
        """
        # brightness parameter IS the rhythm brightness (pre-boost, pre-NL)
        rhythm_brightness = brightness

        # Fetch brightness_override from state (same as periodic path)
        brightness_override = self._get_decayed_brightness_override(area_id)

        # Apply boost if area is boosted
        final_brightness = brightness
        if state.is_boosted(area_id):
            boost_state = state.get_boost_state(area_id)
            boost_amount = boost_state.get("boost_brightness") or 0
            final_brightness = (
                brightness + boost_amount
            )  # No cap — nl_factor/area_factor scale it down
            logger.debug(
                f"Boost applied: {brightness}% + {boost_amount}% = {final_brightness}%"
            )

        await self._apply_lighting(
            area_id,
            final_brightness,
            color_temp,
            include_color,
            transition,
            rhythm_brightness=rhythm_brightness,
            brightness_override=brightness_override,
            nudge=nudge,
        )

    async def _apply_lighting_turn_on(
        self,
        area_id: str,
        brightness: int,
        color_temp: int,
        transition: float = 0.4,
        *,
        rhythm_brightness: int = None,
        brightness_override: float = None,
    ):
        """Turn on lights, using two-phase approach only if needed to avoid color jump.

        When lights are off, they briefly show their previous color before
        transitioning. If the new color is significantly different (>= 500K),
        we use a two-phase approach:
        1. Phase 1: Turn on at 1% brightness with target color (instant)
        2. Phase 2: Transition to target brightness

        If the color is similar to what it was when turned off, we skip the
        two-phase and just turn on directly.

        Hue hub-connected lights skip 2-step entirely - the Hue hub handles
        color transitions internally.

        Args:
            area_id: The area ID
            brightness: Target brightness percentage (0-100)
            color_temp: Color temperature in Kelvin
            transition: Transition time for phase 2 (brightness ramp)
            rhythm_brightness: Pure curve brightness for filter curve position (pre-NL/boost).
            brightness_override: Decay-adjusted additive delta applied post-NL.
        """
        pipeline_kwargs = {}
        if rhythm_brightness is not None:
            pipeline_kwargs["rhythm_brightness"] = rhythm_brightness
        if brightness_override is not None:
            pipeline_kwargs["brightness_override"] = brightness_override

        # Hue hub handles color transitions internally - skip 2-step for all-Hue areas
        if self.client.is_all_hue_area(area_id):
            logger.debug(
                f"Turn-on for all-Hue area {area_id} - skipping 2-step (Hue hub handles transitions)"
            )
            await self._apply_lighting(
                area_id,
                brightness,
                color_temp,
                include_color=True,
                transition=transition,
                **pipeline_kwargs,
            )
            return

        # Check if 2-step is needed based on CT difference
        last_ct = state.get_last_off_ct(area_id)
        raw_cfg = glozone.load_config_from_files()
        ct_threshold = raw_cfg.get("two_step_ct_threshold", 500)

        needs_two_step = True
        if last_ct is not None:
            ct_diff = abs(color_temp - last_ct)
            needs_two_step = ct_diff >= ct_threshold
            logger.debug(
                f"Turn-on CT check: last={last_ct}K, new={color_temp}K, diff={ct_diff}K, 2-step={needs_two_step}"
            )

        if needs_two_step:
            # Phase 1: Set color at minimal brightness (nearly invisible)
            await self._apply_lighting(
                area_id, 1, color_temp, include_color=True, transition=0
            )

            # Delay to ensure phase 1 completes before phase 2
            # Configurable via Settings > Two-step delay (some ZigBee lights need more time)
            delay = self._get_two_step_delay()
            await asyncio.sleep(delay)

            # Phase 2: Transition to target brightness
            await self._apply_lighting(
                area_id,
                brightness,
                color_temp,
                include_color=True,
                transition=transition,
                **pipeline_kwargs,
            )
        else:
            # CT is similar - just turn on directly
            await self._apply_lighting(
                area_id,
                brightness,
                color_temp,
                include_color=True,
                transition=transition,
                **pipeline_kwargs,
            )

    async def _try_reach_turn_on(
        self,
        area_ids: List[str],
        area_lighting: List[Tuple],
        transition: float = 0.4,
        nudge: bool = True,
    ) -> Dict[str, Set[str]]:
        """Try to use filter-aware reach groups for multi-area turn-on.

        Computes per-area per-filter brightness through the full pipeline,
        then uses reach groups where values match across areas. Returns a
        dict of area_id -> set of filter_norms that were handled via reach.
        The caller should skip those specific filters in per-area fallback.

        Args:
            area_ids: List of area IDs
            area_lighting: List of (area_id, brightness, color_temp, ...) tuples
            transition: Transition time in seconds
            nudge: Whether to schedule a post-command nudge for handled areas.

        Returns:
            Dict of area_id -> set of filter_norms handled via reach groups.
            Empty dict if no reach groups were used.
        """
        handled_filters: Dict[str, Set[str]] = {}

        if len(area_ids) < 2:
            return handled_filters

        import switches as _switches  # lazy import to avoid circular

        # Look up the reach group for this set of areas
        key = _switches.get_reach_key(area_ids)
        reach = self.client.reach_groups.get(key)
        if not reach or not reach.filter_groups:
            return handled_filters

        # Pre-compute per-area filter data
        area_filter_data = (
            {}
        )  # area_id -> [(filter_norm, factor_key, brightness, color_temp)]
        for entry in area_lighting:
            area_id = entry[0]
            rhythm_bri = entry[1]
            color_temp = entry[2]
            rhythm_brightness = entry[3] if len(entry) > 3 else rhythm_bri
            bri_override = entry[4] if len(entry) > 4 else None

            # NL reduction
            nl_factor = self._compute_nl_factor(area_id)
            base_bri = max(1, int(round(rhythm_bri * nl_factor)))

            # Get filter and factor info
            area_filters = glozone.get_area_light_filters(area_id)
            area_factor = glozone.get_area_brightness_factor(area_id)
            factor_key = round(area_factor, 3)
            presets = glozone.get_light_filter_presets()
            off_threshold = glozone.get_off_threshold()
            zone_cfg = glozone.get_zone_config_for_area(area_id)
            min_bri = zone_cfg.get("min_brightness", 1)
            max_bri = zone_cfg.get("max_brightness", 100)

            # Determine which filters this area uses
            # Include "Standard" for any lights not explicitly assigned a filter
            filter_names = set(area_filters.values()) if area_filters else set()
            # Check if any lights in this area lack an explicit filter assignment (→ Standard)
            area_lights = self.client.area_lights.get(area_id, [])
            if not area_filters or any(l not in area_filters for l in area_lights):
                filter_names.add("Standard")

            filter_results = []
            for filter_name in filter_names:
                filter_norm = filter_name.replace(" ", "_").lower()
                preset = presets.get(filter_name, {"at_bright": 100, "at_dim": 100})

                filtered_bri, should_off = apply_light_filter_pipeline(
                    base_bri,
                    min_bri,
                    max_bri,
                    area_factor,
                    preset,
                    off_threshold,
                    rhythm_brightness=rhythm_brightness,
                    brightness_override=bri_override,
                )
                if should_off:
                    filtered_bri = 0

                # CT compensation
                if filtered_bri > 0 and color_temp:
                    filtered_bri = self.client._apply_ct_brightness_compensation(
                        filtered_bri, color_temp
                    )

                filter_results.append(
                    (filter_norm, factor_key, filtered_bri, color_temp)
                )

            area_filter_data[area_id] = filter_results

        # For each reach filter group, check if all contributing areas match
        reach_commands = []  # (entity_id, brightness, color_temp)
        filters_handled = {}  # area_id -> set of filter_norms handled via reach
        handled_set = set()  # (area_id, filter_norm) pairs already handled

        # Try exact reach group first, then subset reach groups
        candidate_reaches = [(key, reach)]
        # Collect subset reach groups (other reaches whose areas ⊂ our areas)
        area_set = set(area_ids)
        for other_key, other_reach in self.client.reach_groups.items():
            if other_key == key:
                continue
            if not other_reach.filter_groups:
                continue
            other_areas = set(other_reach.areas)
            if len(other_areas) >= 2 and other_areas.issubset(area_set):
                candidate_reaches.append((other_key, other_reach))

        for rkey, rgroup in candidate_reaches:
            for (
                filter_norm,
                factor_key,
                cap,
            ), entity_id in rgroup.filter_groups.items():
                # Find areas that contribute to this group (matching filter+factor)
                # and haven't already been handled for this filter
                matching = {}
                for area_id in rgroup.areas:
                    if (area_id, filter_norm) in handled_set:
                        continue
                    for fn, fk, bri, ct in area_filter_data.get(area_id, []):
                        if fn == filter_norm and fk == factor_key:
                            matching[area_id] = (bri, ct)

                if len(matching) < 2:
                    continue  # Need 2+ areas for reach to be useful

                # Check if all matching areas have the same brightness
                values = set(matching.values())
                if len(values) != 1:
                    if rkey == key:
                        logger.debug(
                            f"Reach {rkey} {filter_norm} {cap}: values differ across areas, falling back"
                        )
                    continue

                bri, ct = values.pop()
                if bri <= 0:
                    continue  # All off — handled by per-area off logic

                reach_commands.append((entity_id, bri, ct, filter_norm, cap))
                for area_id in matching:
                    if area_id not in filters_handled:
                        filters_handled[area_id] = set()
                    filters_handled[area_id].add(filter_norm)
                    handled_set.add((area_id, filter_norm))

        if not reach_commands:
            return handled_filters

        # Send reach group commands
        tasks = []
        xy = None
        if reach_commands:
            # Compute xy from first color_temp
            ct = reach_commands[0][2]
            xy = CircadianLight.color_temperature_to_xy(ct)

        for entity_id, bri, ct, filter_norm, cap in reach_commands:
            service_data = {"transition": transition, "brightness_pct": bri}
            if cap == "color" and xy is not None:
                service_data["xy_color"] = list(xy)
            elif cap == "ct":
                service_data["color_temp_kelvin"] = max(2000, ct)

            logger.info(
                f"Reach group {filter_norm} {cap}: {entity_id}, "
                f"brightness={bri}%, {ct}K, transition={transition}s"
            )
            tasks.append(
                self.client.call_service(
                    "light", "turn_on", service_data, {"entity_id": entity_id}
                )
            )

        if tasks:
            await asyncio.gather(*tasks)

        # Schedule reach-group nudge: re-send the same reach commands
        # (synchronized, not per-area) after nudge_delay
        if nudge and reach_commands:
            import asyncio as _asyncio

            delay = self.client._get_nudge_delay()
            nudge_transition = self.client._get_nudge_transition()

            # Capture the commands to replay
            saved_commands = list(reach_commands)
            saved_xy = xy
            handled_areas = set(filters_handled.keys())

            async def _reach_nudge():
                try:
                    await _asyncio.sleep(delay)
                    ntasks = []
                    for entity_id, bri, ct, filter_norm, cap in saved_commands:
                        sdata = {
                            "transition": nudge_transition,
                            "brightness_pct": bri,
                        }
                        if cap == "color" and saved_xy is not None:
                            sdata["xy_color"] = list(saved_xy)
                        elif cap == "ct":
                            sdata["color_temp_kelvin"] = max(2000, ct)
                        ntasks.append(
                            self.client.call_service(
                                "light",
                                "turn_on",
                                sdata,
                                {"entity_id": entity_id},
                            )
                        )
                    if ntasks:
                        await _asyncio.gather(*ntasks)
                    logger.debug(f"Reach nudge fired: {len(saved_commands)} group(s)")
                except _asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.debug(f"Reach nudge failed: {e}")
                finally:
                    for aid in handled_areas:
                        self.client._pending_nudges.pop(aid, None)

            nudge_task = _asyncio.create_task(_reach_nudge())
            for area_id in handled_areas:
                self.client.cancel_nudge(area_id)
                self.client._pending_nudges[area_id] = nudge_task

        if filters_handled:
            fully = [
                a
                for a, fns in filters_handled.items()
                if fns == {fn for fn, fk, bri, ct in area_filter_data.get(a, [])}
            ]
            partial = [a for a in filters_handled if a not in fully]
            parts = []
            if fully:
                parts.append(f"{len(fully)} fully")
            if partial:
                parts.append(f"{len(partial)} partially ({', '.join(partial)})")
            logger.info(f"Reach groups handled: {', '.join(parts)}")

        return filters_handled

    async def _apply_lighting_turn_on_multiple(
        self,
        area_lighting: List[
            Tuple
        ],  # List of (area_id, brightness, color_temp, rhythm_brightness, brightness_override)
        transition: float = 0.4,
    ):
        """Turn on multiple areas, batching 2-step phases for unified appearance.

        Instead of doing Phase1-delay-Phase2 for each area sequentially, this batches:
        1. Phase 1 (1%) for all areas needing 2-step (parallel)
        2. Single delay
        3. Phase 2 (target) for all areas needing 2-step (parallel)
        4. Direct turn-on for areas not needing 2-step (parallel with phase 1)

        Args:
            area_lighting: List of (area_id, brightness, color_temp, rhythm_brightness, brightness_override) tuples.
                rhythm_brightness and brightness_override are forwarded to the filter pipeline.
            transition: Transition time for phase 2
        """
        if not area_lighting:
            return

        # Categorize areas by whether they need 2-step
        needs_two_step = []
        no_two_step = []
        raw_cfg = glozone.load_config_from_files()
        ct_threshold = raw_cfg.get("two_step_ct_threshold", 500)

        for entry in area_lighting:
            area_id, brightness, color_temp = entry[0], entry[1], entry[2]
            rhythm_bri = entry[3] if len(entry) > 3 else None
            bri_override = entry[4] if len(entry) > 4 else None

            item = (area_id, brightness, color_temp, rhythm_bri, bri_override)

            # All-Hue areas skip 2-step
            if self.client.is_all_hue_area(area_id):
                no_two_step.append(item)
                continue

            # Check CT difference
            last_ct = state.get_last_off_ct(area_id)
            if last_ct is not None:
                ct_diff = abs(color_temp - last_ct)
                if ct_diff < ct_threshold:
                    no_two_step.append(item)
                    continue

            needs_two_step.append(item)

        def _pipeline_kwargs(rhythm_bri, bri_override):
            kw = {}
            if rhythm_bri is not None:
                kw["rhythm_brightness"] = rhythm_bri
            if bri_override is not None:
                kw["brightness_override"] = bri_override
            return kw

        # Phase 1: Apply 1% to all 2-step areas + direct turn-on for no-2-step areas (parallel)
        phase1_tasks = []
        for area_id, brightness, color_temp, rhythm_bri, bri_override in needs_two_step:
            phase1_tasks.append(
                self._apply_lighting(
                    area_id, 1, color_temp, include_color=True, transition=0
                )
            )
        for area_id, brightness, color_temp, rhythm_bri, bri_override in no_two_step:
            phase1_tasks.append(
                self._apply_lighting(
                    area_id,
                    brightness,
                    color_temp,
                    include_color=True,
                    transition=transition,
                    **_pipeline_kwargs(rhythm_bri, bri_override),
                )
            )

        if phase1_tasks:
            await asyncio.gather(*phase1_tasks)

        # Delay (only if any areas need 2-step)
        if needs_two_step:
            delay = self._get_two_step_delay()
            await asyncio.sleep(delay)

            # Phase 2: Apply target brightness to all 2-step areas (parallel)
            phase2_tasks = []
            for (
                area_id,
                brightness,
                color_temp,
                rhythm_bri,
                bri_override,
            ) in needs_two_step:
                phase2_tasks.append(
                    self._apply_lighting(
                        area_id,
                        brightness,
                        color_temp,
                        include_color=True,
                        transition=transition,
                        **_pipeline_kwargs(rhythm_bri, bri_override),
                    )
                )
            if phase2_tasks:
                await asyncio.gather(*phase2_tasks)

    async def _apply_color_only(
        self, area_id: str, color_temp: int, transition: float = 0.4
    ):
        """Apply color temperature only to an area (brightness unchanged).

        Delegates to client.turn_on_lights_circadian() with brightness=None,
        which sets color without changing brightness.

        Args:
            area_id: The area ID
            color_temp: Color temperature in Kelvin
            transition: Transition time in seconds
        """
        await self.client.turn_on_lights_circadian(
            area_id,
            brightness=None,  # Don't change brightness
            color_temp=color_temp,
            transition=transition,
            include_color=True,
        )
        self.client.schedule_nudge(
            area_id,
            brightness=None,
            color_temp=color_temp,
            include_color=True,
        )

    async def _bounce_at_limit(
        self,
        area_id: str,
        current_brightness: int,
        current_color: int,
        direction: str = "up",
        bounce_type: str = "step",
    ):
        """Visual bounce effect when hitting a bound limit.

        Phase 1 (dip/flash) works in visible space: reads actual brightness
        from cached state, applies bounce delta, sends directly to lights
        via call_service (bypasses pipeline to avoid override interference).

        Phase 2 (restore) goes through the full pipeline via
        _apply_circadian_lighting (boost, NL, filters, nudge).

        Args:
            area_id: The area ID
            current_brightness: Raw circadian brightness (pre-NL, pre-boost) for Phase 2 restore
            current_color: Current color temperature in Kelvin
            direction: "up" (hit upper limit, dip down) or "down" (hit lower limit, flash up)
            bounce_type: "step", "bright", or "color"
        """
        if not self._is_limit_bounce_enabled():
            logger.debug(f"Limit bounce disabled, skipping for {area_id}")
            return

        import asyncio

        config = self._get_config(area_id)
        limit_speed = self._get_limit_warning_speed()
        two_step_delay = self._get_two_step_delay()

        # Read actual visible brightness from cached state (HA 0-255 scale)
        area_lights = self.client.area_lights.get(area_id, [])
        max_visible = 0
        for entity_id in area_lights:
            ls = self.client.cached_states.get(entity_id, {})
            if ls.get("state") == "on":
                bri = ls.get("attributes", {}).get("brightness", 0)
                if bri > max_visible:
                    max_visible = bri
        visible_bri = max_visible or 1

        # Bounce delta in visible space (0-255)
        if direction == "up":
            bounce_percent = self._get_limit_bounce_max_percent() / 100.0
        else:
            bounce_percent = self._get_limit_bounce_min_percent() / 100.0

        bounce_bri = bounce_type in ("step", "bright")
        bounce_color = bounce_type in ("step", "color")

        # Brightness bounce target in HA 0-255 space
        if bounce_bri:
            if direction == "up":
                target_visible = max(1, int(visible_bri * (1.0 - bounce_percent)))
            else:
                target_visible = min(255, int(visible_bri * (1.0 + bounce_percent)))
        else:
            target_visible = visible_bri

        # Color bounce target
        color_range = config.max_color_temp - config.min_color_temp
        color_delta = (bounce_percent * color_range) if bounce_color else 0
        if direction == "up":
            target_color = max(config.min_color_temp, int(current_color - color_delta))
        else:
            target_color = min(config.max_color_temp, int(current_color + color_delta))
        if not bounce_color:
            target_color = current_color

        include_color = bounce_type in ("step", "color")

        # Phase 1: Bounce away via call_service (visible space, bypass pipeline)
        # Use switch's feedback target if available (single purpose group)
        feedback_target = getattr(self.client, "_active_feedback_target", None)
        if feedback_target:
            targets = [feedback_target]
        else:
            zha_groups = self.client.get_area_zha_groups(area_id)
            has_parity = self.client.area_parity_cache.get(area_id, False)
            if zha_groups and has_parity:
                targets = [{"entity_id": g} for g in zha_groups]
            else:
                targets = [{"area_id": area_id}]

        phase1_tasks = []
        for target in targets:
            sdata = {"brightness": target_visible, "transition": limit_speed}
            if include_color:
                sdata["color_temp_kelvin"] = max(2000, target_color)
            phase1_tasks.append(
                self.client.call_service("light", "turn_on", sdata, target=target)
            )
        await asyncio.gather(*phase1_tasks)
        await asyncio.sleep(limit_speed + two_step_delay)

        # Phase 2: Restore via pipeline (with nudge)
        await self._apply_circadian_lighting(
            area_id,
            current_brightness,
            current_color,
            include_color=include_color,
            transition=limit_speed,
        )

        logger.info(
            f"Limit bounce ({bounce_type} {direction}) for {area_id}: "
            f"visible {visible_bri}/255 -> {target_visible}/255 -> restore"
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

        logger.info(
            f"Brightness {'increased' if direction > 0 else 'decreased'} by {step_pct}%"
        )
