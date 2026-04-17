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
        self._auto_fired: dict = {}  # area_id -> {auto_on: {date, time}, auto_off: {date, time}}
        self._load_auto_fired()

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

    def _get_boost_return_transition(self) -> float:
        """Get the boost return transition time in seconds.

        Reads from global config, defaults to 6.0 seconds (60 tenths).
        The setting is stored as tenths of seconds in config.
        """
        try:
            raw_config = glozone.load_config_from_files()
            tenths = raw_config.get("boost_return_transition", 60)
            return tenths / 10.0
        except Exception:
            return 6.0

    def _get_two_step_delay(self) -> float:
        """Get the two-step turn-on delay in seconds.

        When turning on lights, a two-step process sets color at 1% brightness
        then transitions to target brightness. This delay between steps prevents
        some ZigBee lights from dropping the second command.

        Reads from global config, defaults to 0.2 seconds (2 tenths).
        The setting is stored as tenths of seconds in config.

        Returns:
            Delay time in seconds
        """
        try:
            raw_config = glozone.load_config_from_files()
            tenths = raw_config.get("two_step_delay", 5)
            return tenths / 10.0  # Convert tenths to seconds
        except Exception:
            return 0.2  # Default 0.2 seconds

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
        Reads from global config, defaults to 25 (%).

        Returns:
            Bounce percentage (0-100)
        """
        try:
            raw_config = glozone.load_config_from_files()
            return raw_config.get("limit_bounce_max_percent", 25)
        except Exception:
            return 25

    def _get_limit_bounce_min_percent(self) -> float:
        """Get the bounce percentage when hitting min limit (% of range).

        Controls how much lights flash when hitting the lower limit.
        Reads from global config, defaults to 13 (%).

        Returns:
            Bounce percentage (0-100)
        """
        try:
            raw_config = glozone.load_config_from_files()
            return raw_config.get("limit_bounce_min_percent", 13)
        except Exception:
            return 13

    def _get_alert_bounce_speed(self) -> float:
        """Get the alert bounce animation speed in seconds."""
        try:
            raw_config = glozone.load_config_from_files()
            tenths = raw_config.get("alert_bounce_speed", 10)
            return tenths / 10.0
        except Exception:
            return 1.0

    def _get_reach_daytime_threshold(self) -> float:
        """Get the reach daytime threshold (brightness % below which flash goes UP).

        When sun bright > 0 and brightness is below this threshold, reach feedback
        flashes UP to 100% instead of off to ensure visibility.

        Returns:
            Threshold percentage (0-100)
        """
        try:
            raw_config = glozone.load_config_from_files()
            return raw_config.get("reach_daytime_threshold", 50)
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

    async def _step_circadian(
        self,
        area_id: str,
        direction: str,
        source: str = "service_call",
        steps: int = 1,
        send_command: bool = True,
        skip_bounce: bool = False,
    ):
        """Step up or down along the circadian curve.

        Computes target curve position from current brightness + step_size,
        then delegates to set_position(mode="step") which shifts the midpoint.

        Args:
            area_id: The area ID to control
            direction: "up" or "down"
            source: Source of the action
            steps: Number of steps to take
            send_command: Whether to send light commands (False for reach group batching)
            skip_bounce: Whether to skip bounce at limit

        Returns:
            True if applied, or None if at limit / not circadian.
        """
        area_state = self._get_area_state(area_id)

        if not area_state.is_circadian:
            logger.debug(
                f"[{source}] step_{direction} ignored for area {area_id} "
                f"(not in circadian mode)"
            )
            return None

        config = self._get_config(area_id)
        hour = get_current_hour()

        # Current curve brightness (pre-pipeline, just the curve output)
        current_bri = CircadianLight.calculate_brightness_at_hour(
            hour, config, area_state
        )

        # Step size in brightness space
        step_size = (config.max_brightness - config.min_brightness) / (
            config.max_dim_steps or DEFAULT_MAX_DIM_STEPS
        )
        sign = 1 if direction == "up" else -1
        target_bri = current_bri + sign * step_size * steps
        target_bri = max(config.min_brightness, min(config.max_brightness, target_bri))

        # At limit — bounce
        if abs(target_bri - current_bri) < 0.5:
            # Check if sun dimming is why user can't go higher
            sun_dimming_hint = False
            if direction == "up":
                sun_bright_factor = self._compute_sun_bright_factor(area_id)
                if sun_bright_factor < 1.0:
                    sun_dimming_hint = True
                    logger.info(
                        f"step_up at limit for {area_id} (bri={current_bri:.0f}%, "
                        f"sun_bright_factor={sun_bright_factor:.2f}) — hint: use bright_up"
                    )
            if not sun_dimming_hint:
                logger.info(
                    f"step_{direction} at limit for {area_id} (bri={current_bri:.0f}%)"
                )
            if send_command and not skip_bounce and area_state.is_on:
                sun_times = (
                    self.client._get_sun_times()
                    if hasattr(self.client, "_get_sun_times")
                    else None
                )
                current_cct = CircadianLight.calculate_color_at_hour(
                    hour, config, area_state,
                    apply_solar_rules=True, sun_times=sun_times,
                )
                await self._bounce_at_limit(
                    area_id, current_bri, current_cct,
                    direction=direction, bounce_type="step",
                )
            return "sun_dimming_limit" if sun_dimming_hint else None

        # Convert target brightness to 0-100 position on curve
        b_range = config.max_brightness - config.min_brightness
        position = (target_bri - config.min_brightness) / b_range * 100 if b_range > 0 else 50
        position = max(0, min(100, round(position, 1)))

        logger.info(
            f"[{source}] step_{direction} for {area_id}: "
            f"bri {current_bri:.0f}→{target_bri:.0f}%, pos={position:.0f}"
        )
        await self.set_position(
            area_id, position, mode="step", source=source,
            _send_command=send_command,
        )
        return True

    async def step_up(
        self,
        area_id: str,
        source: str = "service_call",
        steps: int = 1,
        send_command: bool = True,
        skip_bounce: bool = False,
    ):
        """Step up along the circadian curve (brighter and cooler).

        Computes target and delegates to set_position(mode="step").

        Args:
            area_id: The area ID to control
            source: Source of the action
            steps: Number of steps to take (each computed from updated state)
            send_command: Whether to send light commands (False for reach group batching)
            skip_bounce: Whether to skip per-area bounce (True for multi-area, caller handles)

        Returns:
            The last result applied, or None if at limit / not circadian.
        """
        if source not in ("auto_on", "auto_off", "auto_off_fade_complete", "wake_alarm"):
            self.cancel_fade(area_id, source=source or "unknown")
            state.mark_user_action(area_id)
        return await self._step_circadian(
            area_id, "up", source=source, steps=steps, send_command=send_command,
            skip_bounce=skip_bounce,
        )

    async def step_down(
        self,
        area_id: str,
        source: str = "service_call",
        steps: int = 1,
        send_command: bool = True,
        skip_bounce: bool = False,
    ):
        """Step down along the circadian curve (dimmer and warmer).

        Computes target and delegates to set_position(mode="step").

        Args:
            area_id: The area ID to control
            source: Source of the action
            steps: Number of steps to take (each computed from updated state)
            send_command: Whether to send light commands (False for reach group batching)
            skip_bounce: Whether to skip per-area bounce (True for multi-area, caller handles)

        Returns:
            The last result applied, or None if at limit / not circadian.
        """
        if source not in ("auto_on", "auto_off", "auto_off_fade_complete", "wake_alarm"):
            self.cancel_fade(area_id, source=source or "unknown")
            state.mark_user_action(area_id)
        return await self._step_circadian(
            area_id, "down", source=source, steps=steps, send_command=send_command,
            skip_bounce=skip_bounce,
        )

    # -------------------------------------------------------------------------
    # Bright Up / Bright Down (brightness only)
    # -------------------------------------------------------------------------

    def _compute_sun_bright_factor(self, area_id: str) -> float:
        """Compute current sun bright factor for an area (matches main.py pipeline)."""
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

    def build_pipeline_context_for_area(
        self,
        area_id: str,
        *,
        fade_factor: float = 1.0,
        dim_factor: float = 1.0,
        transition: float = 0.5,
        weekday: Optional[int] = None,
        log_decay: bool = False,
    ):
        """Build a PipelineContext for an area from current state.

        Single source of truth — always reads from area_state and computes
        the curve from scratch. NEVER use precomputed_* for curve-driven
        delivery; that path silently bypasses sun_cooling_strength and other
        curve-stage factors.

        Side effects: clears expired brightness_override / color_override
        from state when their decay reaches 0.

        Args:
            area_id: The area ID
            fade_factor: Multiplicative fade (auto on/off transitions)
            dim_factor: Multiplicative warning dim (motion warning)
            transition: Light command transition time
            weekday: Optional weekday override (None = today)
            log_decay: Whether to log override decay calculations

        Returns:
            PipelineContext ready for pipeline.compute(). Never None
            (caller is responsible for skipping if area shouldn't be processed).
        """
        import lux_tracker
        from pipeline import PipelineContext

        # Config (effective = rhythm + globals like brightness_sensitivity)
        config_dict = glozone.get_effective_config_for_area(area_id)
        config = Config.from_dict(config_dict)

        # Area state (includes stepped midpoints, overrides, frozen_at)
        area_state = self._get_area_state(area_id)

        # Hour (frozen_at if set, else current)
        hour = (
            area_state.frozen_at
            if area_state.frozen_at is not None
            else get_current_hour()
        )

        # Sun times for solar rules
        sun_times = (
            self.client._get_sun_times()
            if hasattr(self.client, "_get_sun_times")
            else None
        ) or SunTimes()

        # Decayed brightness override
        effective_bri_override = None
        if area_state.brightness_override is not None:
            in_ascend, h48, t_ascend, t_descend, _ = CircadianLight.get_phase_info(
                hour, config
            )
            next_phase = t_descend if in_ascend else t_ascend + 24
            bri_decay = compute_override_decay(
                area_state.brightness_override_set_at,
                h48,
                next_phase,
                t_ascend=t_ascend,
            )
            effective_bri_override = area_state.brightness_override * bri_decay
            if bri_decay <= 0:
                state.update_area(
                    area_id,
                    {
                        "brightness_override": None,
                        "brightness_override_set_at": None,
                    },
                )
                effective_bri_override = None
            elif log_decay:
                logger.info(
                    f"[Pipeline] Area {area_id}: brightness_override="
                    f"{area_state.brightness_override:.1f} × decay={bri_decay:.2f} "
                    f"= {effective_bri_override:.1f}"
                )

        # Decayed color override (and adjust area_state if decayed)
        if (
            area_state.color_override is not None
            and area_state.color_override_set_at is not None
        ):
            in_ascend, h48, t_ascend, t_descend, _ = CircadianLight.get_phase_info(
                hour, config
            )
            next_phase = t_descend if in_ascend else t_ascend + 24
            color_decay = compute_override_decay(
                area_state.color_override_set_at,
                h48,
                next_phase,
                t_ascend=t_ascend,
            )
            if color_decay <= 0:
                state.update_area(
                    area_id,
                    {
                        "color_override": None,
                        "color_override_set_at": None,
                    },
                )
                area_state = self._get_area_state(area_id)
            elif color_decay < 1.0:
                area_state = AreaState(
                    is_circadian=area_state.is_circadian,
                    is_on=area_state.is_on,
                    frozen_at=area_state.frozen_at,
                    brightness_mid=area_state.brightness_mid,
                    color_mid=area_state.color_mid,
                    color_override=area_state.color_override * color_decay,
                    color_override_set_at=area_state.color_override_set_at,
                )
                if log_decay:
                    logger.info(
                        f"[Pipeline] Area {area_id}: color_override="
                        f"{area_state.color_override:.1f}K × decay={color_decay:.2f}"
                    )

        # Boost
        boost_amount = 0
        if state.is_boosted(area_id):
            boost_state = state.get_boost_state(area_id)
            boost_amount = boost_state.get("boost_brightness") or 0

        # Sun intensity
        outdoor_norm = lux_tracker.get_outdoor_normalized()

        # Raw config for CT comp
        raw_config = glozone.load_config_from_files()

        return PipelineContext(
            area_id=area_id,
            hour=hour,
            config=config,
            area_state=area_state,
            sun_times=sun_times,
            area_factor=glozone.get_area_brightness_factor(area_id),
            area_filters=glozone.get_area_light_filters(area_id),
            filter_presets=glozone.get_light_filter_presets(),
            off_threshold=glozone.get_off_threshold(),
            sun_exposure=glozone.get_area_natural_light_exposure(area_id),
            sun_intensity=outdoor_norm if outdoor_norm is not None else 0.0,
            brightness_override=effective_bri_override,
            boost_brightness=boost_amount if boost_amount > 0 else None,
            ct_comp_enabled=raw_config.get("ct_comp_enabled", False),
            ct_comp_begin=raw_config.get("ct_comp_begin", 1650),
            ct_comp_end=raw_config.get("ct_comp_end", 2250),
            ct_comp_factor=raw_config.get("ct_comp_factor", 1.7),
            transition=transition,
            weekday=weekday,
            fade_factor=fade_factor,
            dim_factor=dim_factor,
        )

    def compute_pipeline_for_area(self, area_id: str, **builder_kwargs):
        """Build context and compute pipeline result for an area.

        Convenience wrapper for callers that just need a PipelineResult.
        See build_pipeline_context_for_area for kwargs.
        """
        import pipeline as pipeline_mod

        ctx = self.build_pipeline_context_for_area(area_id, **builder_kwargs)
        return pipeline_mod.compute(ctx)

    def compute_fade_target(self, area_id: str, target_preset: str):
        """Compute what the pipeline would produce for a target preset.

        Builds a synthetic AreaState for the target preset without modifying
        actual area state. Used during fade to compute the lerp target each tick.

        Args:
            area_id: The area ID
            target_preset: "circadian", "nitelite", "britelite", or "off"

        Returns:
            PipelineResult for the target preset (includes per-purpose
            brightnesses with correct filter ratios). For "off": returns None.
        """
        import pipeline as pipeline_mod

        if target_preset == "off":
            return None

        config = self._get_config(area_id)

        # Build synthetic AreaState for the target preset
        if target_preset == "nitelite":
            synthetic_state = AreaState(
                is_circadian=True, is_on=True,
                frozen_at=config.ascend_start,
            )
        elif target_preset == "britelite":
            synthetic_state = AreaState(
                is_circadian=True, is_on=True,
                frozen_at=config.descend_start,
            )
        else:
            # circadian: default curve, no midpoints, no overrides
            synthetic_state = AreaState(is_circadian=True, is_on=True)

        # Build context with synthetic state.
        # IMPORTANT: override BOTH area_state AND hour. The builder reads
        # hour from actual area_state.frozen_at, which may be stale (e.g.,
        # area is frozen at nitelite's ascend_start). The target should use
        # either the synthetic frozen_at or the current time.
        ctx = self.build_pipeline_context_for_area(area_id)
        ctx.area_state = synthetic_state
        if synthetic_state.frozen_at is not None:
            ctx.hour = synthetic_state.frozen_at
        else:
            ctx.hour = get_current_hour()

        return pipeline_mod.compute(ctx)

    def _compute_current_actual(self, area_id: str) -> float:
        """Get current area brightness — from cache, falling back to pipeline.

        Returns the area-level brightness (post all area-level factors).
        """
        cached = state.get_last_sent_brightness(area_id)
        if cached is not None:
            return cached

        area_state = self._get_area_state(area_id)
        config = self._get_config(area_id)
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
        return self._compute_current_area_brightness(
            area_id, hour, config, area_state, sun_times
        )

    def _compute_current_area_brightness(
        self, area_id, hour, config, area_state, sun_times
    ) -> int:
        """Compute current area brightness via pipeline (cold start fallback)."""
        import lux_tracker
        from pipeline import PipelineContext
        import pipeline as pipeline_mod

        raw_config = glozone.load_config_from_files()
        outdoor_norm = lux_tracker.get_outdoor_normalized()
        effective_override = self._get_decayed_brightness_override(area_id)
        boost_brightness = None
        if state.is_boosted(area_id):
            boost_state = state.get_boost_state(area_id)
            boost_brightness = boost_state.get("boost_brightness")

        dim_factor = state.get_area(area_id).get("dim_factor", 1.0)

        ctx = PipelineContext(
            area_id=area_id,
            hour=hour,
            config=config,
            area_state=area_state,
            sun_times=sun_times or SunTimes(),
            area_factor=glozone.get_area_brightness_factor(area_id),
            area_filters=glozone.get_area_light_filters(area_id),
            filter_presets=glozone.get_light_filter_presets(),
            off_threshold=glozone.get_off_threshold(),
            sun_exposure=glozone.get_area_natural_light_exposure(area_id),
            sun_intensity=outdoor_norm if outdoor_norm is not None else 0.0,
            brightness_override=effective_override,
            boost_brightness=boost_brightness,
            dim_factor=dim_factor,
            ct_comp_enabled=raw_config.get("ct_comp_enabled", False),
            ct_comp_begin=raw_config.get("ct_comp_begin", 1650),
            ct_comp_end=raw_config.get("ct_comp_end", 2250),
            ct_comp_factor=raw_config.get("ct_comp_factor", 1.7),
        )
        result = pipeline_mod.compute(ctx)
        return result.area_brightness

    def _compute_override_decay_factor(self, area_id: str) -> float:
        """Get the current decay factor (0.0-1.0) for brightness override.

        Returns 1.0 if no set_at (no decay), 0.0 if fully decayed.
        """
        area_state = self._get_area_state(area_id)
        if area_state.brightness_override is None:
            return 1.0
        if area_state.brightness_override_set_at is None:
            return 1.0
        config = self._get_config(area_id)
        hour = get_current_hour()
        in_ascend, h48, t_ascend, t_descend, _ = CircadianLight.get_phase_info(
            hour, config
        )
        next_phase = t_descend if in_ascend else t_ascend + 24
        return compute_override_decay(
            area_state.brightness_override_set_at, h48, next_phase, t_ascend=t_ascend
        )

    async def set_position(
        self,
        area_id: str,
        value: float,
        mode: str = "step",
        source: str = "service_call",
        _send_command: bool = True,
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
            _send_command: Whether to send light commands (False for reach batching)
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
            # Override model: compute delta between target and current area brightness.
            # Target maps slider 0-100 to actual brightness 0-100%.
            target_actual = max(0, min(100, value))

            # Current area brightness from pipeline cache (includes all area-level factors)
            current_actual = state.get_last_sent_brightness(area_id)
            if current_actual is None:
                # Cold start fallback: compute via pipeline
                current_actual = self._compute_current_area_brightness(
                    area_id, hour, config, area_state, sun_times
                )

            delta = round(target_actual - current_actual, 1)
            existing_override = area_state.brightness_override or 0
            new_override = round(existing_override + delta, 1)
            self._update_area_state(
                area_id,
                {
                    "brightness_override": new_override,
                    "brightness_override_set_at": hour,
                },
            )
            logger.info(
                f"[{source}] set_position({value}, brightness) for area {area_id}: "
                f"target={target_actual}, current={current_actual}, delta={delta}, override={new_override}"
            )
            if _send_command and area_state.is_on:
                await self.client.update_lights_in_circadian_mode(area_id, log_periodic=True)
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

            if _send_command and area_state.is_on:
                await self.client.update_lights_in_circadian_mode(area_id, log_periodic=True)
                logger.info(
                    f"set_position color applied: {result.color_temp}K"
                )
            elif not area_state.is_on:
                logger.info(
                    f"set_position color state updated (lights off): {result.color_temp}K"
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

        if _send_command and area_state.is_on:
            await self.client.update_lights_in_circadian_mode(area_id, log_periodic=True)
            logger.info(
                f"set_position applied: {result.brightness}%, {result.color_temp}K"
            )
        elif not area_state.is_on:
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
        skip_bounce: bool = False,
    ):
        """Increase brightness by N steps. Delegates to set_position."""
        return await self._brightness_button(
            area_id, "up", source, steps, send_command, skip_bounce,
        )

    async def brightness_down(
        self,
        area_id: str,
        source: str = "service_call",
        steps: int = 1,
        send_command: bool = True,
        skip_bounce: bool = False,
    ):
        """Decrease brightness by N steps. Delegates to set_position."""
        return await self._brightness_button(
            area_id, "down", source, steps, send_command, skip_bounce,
        )

    async def _brightness_button(
        self,
        area_id: str,
        direction: str,
        source: str,
        steps: int = 1,
        send_command: bool = True,
        skip_bounce: bool = False,
    ):
        """Compute target brightness from current + N steps, delegate to set_position.

        Args:
            area_id: The area ID to control
            direction: "up" or "down"
            source: Source of the action
            steps: Number of steps (1 = normal, 2-5 = multiplied)
            send_command: Whether to send light commands (False for reach batching)
            skip_bounce: Whether to skip bounce at limit

        Returns:
            True if applied, None if at limit / not circadian.
        """
        area_state = self._get_area_state(area_id)
        if not area_state.is_circadian:
            logger.debug(
                f"[{source}] brightness_{direction} ignored for {area_id} (not circadian)"
            )
            return None

        config = self._get_config(area_id)
        current = self._compute_current_actual(area_id)
        num_steps = config.max_dim_steps or DEFAULT_MAX_DIM_STEPS
        step_size = (config.max_brightness - config.min_brightness) / num_steps
        sign = 1 if direction == "up" else -1

        target = round(current + sign * step_size * steps, 1)
        target = max(1, min(100, target))

        # At limit — bounce if first step, otherwise just stop
        if abs(target - current) < 0.5:
            logger.info(
                f"brightness_{direction} at limit for {area_id} (current={current})"
            )
            if send_command and not skip_bounce and area_state.is_on:
                hour = get_current_hour()
                sun_times = (
                    self.client._get_sun_times()
                    if hasattr(self.client, "_get_sun_times")
                    else None
                )
                current_cct = CircadianLight.calculate_color_at_hour(
                    hour, config, area_state,
                    apply_solar_rules=True, sun_times=sun_times,
                )
                await self._bounce_at_limit(
                    area_id, current, current_cct,
                    direction=direction, bounce_type="bright",
                )
            return None

        logger.info(
            f"[{source}] brightness_{direction} for {area_id}: "
            f"current={current}, target={target} ({steps} step{'s' if steps > 1 else ''})"
        )
        await self.set_position(
            area_id, target, mode="brightness", source=source,
            _send_command=send_command,
        )
        return True

    async def color_up(
        self, area_id: str, source: str = "service_call", steps: int = 1,
        send_command: bool = True, skip_bounce: bool = False,
    ):
        """Increase color temp (cooler) by N steps. Delegates to set_position."""
        state.mark_user_action(area_id)
        await self._color_button(
            area_id, "up", source, steps, send_command, skip_bounce,
        )

    async def color_down(
        self, area_id: str, source: str = "service_call", steps: int = 1,
        send_command: bool = True, skip_bounce: bool = False,
    ):
        """Decrease color temp (warmer) by N steps. Delegates to set_position."""
        state.mark_user_action(area_id)
        await self._color_button(
            area_id, "down", source, steps, send_command, skip_bounce,
        )

    async def _color_button(
        self, area_id: str, direction: str, source: str, steps: int = 1,
        send_command: bool = True, skip_bounce: bool = False,
    ):
        """Compute target color slider position from current + N steps, delegate to set_position.

        Maps current effective kelvin to a 0-100 slider position, adds steps,
        and calls set_position(mode="color") which handles the override math.
        """
        area_state = self._get_area_state(area_id)
        if not area_state.is_circadian:
            logger.debug(
                f"[{source}] color_{direction} ignored for {area_id} (not circadian)"
            )
            return

        config = self._get_config(area_id)
        hour = get_current_hour()
        sun_times = (
            self.client._get_sun_times()
            if hasattr(self.client, "_get_sun_times")
            else None
        )

        # Get current effective kelvin (base + decayed override)
        current_cct = CircadianLight.calculate_color_at_hour(
            hour, config, area_state,
            apply_solar_rules=True, sun_times=sun_times,
        )

        # Map to 0-100 slider position
        c_min = config.min_color_temp
        c_max = config.max_color_temp
        c_range = c_max - c_min
        if c_range <= 0:
            return
        current_pos = (current_cct - c_min) / c_range * 100

        # Step in slider space
        num_steps = config.max_dim_steps or DEFAULT_MAX_DIM_STEPS
        step_pct = 100.0 / num_steps
        sign = 1 if direction == "up" else -1
        target_pos = current_pos + sign * step_pct * steps
        target_pos = max(0, min(100, round(target_pos, 1)))

        # At limit — bounce
        if abs(target_pos - current_pos) < 0.5:
            logger.info(
                f"color_{direction} at limit for {area_id} (cct={current_cct:.0f}K)"
            )
            if area_state.is_on and not skip_bounce:
                current_bri = self._compute_current_actual(area_id)
                await self._bounce_at_limit(
                    area_id, current_bri, current_cct,
                    direction=direction, bounce_type="color",
                )
            return

        logger.info(
            f"[{source}] color_{direction} for {area_id}: "
            f"pos {current_pos:.0f}→{target_pos:.0f} ({steps} step{'s' if steps > 1 else ''})"
        )
        await self.set_position(
            area_id, target_pos, mode="color", source=source,
            _send_command=send_command,
        )

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
        if source not in ("auto_on", "auto_off", "auto_off_fade_complete", "wake_alarm"):
            self.cancel_fade(area_id, source=source or "unknown")
            state.mark_user_action(area_id)

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

        # brightness_override applied post-sun-bright in the filter pipeline (not pre-applied)
        effective_override = self._get_decayed_brightness_override(area_id)
        final_brightness = result.brightness

        # Set boost state BEFORE sending light to prevent race condition:
        # inner 2-step has an asyncio.sleep for delay, during which the
        # circadian tick can run. If boost state isn't saved yet,
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
        if has_boost:
            pipeline_kwargs["boost_brightness"] = boost_brightness

        await self._send_light(
            area_id,
            final_brightness,
            result.color_temp,
            include_color=True,
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
        if source not in ("auto_on", "auto_off", "auto_off_fade_complete", "wake_alarm"):
            self.cancel_fade(area_id, source=source or "unknown")
            state.mark_user_action(area_id)

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
            state.set_last_sent_kelvin(area_id, result.color_temp)
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

        # Cancel any active fade
        self.cancel_fade(area_id, source=source or "circadian_off")

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
            sun_times = (
                self.client._get_sun_times()
                if hasattr(self.client, "_get_sun_times")
                else None
            )
            result = CircadianLight.calculate_lighting(hour, config, area_state, sun_times=sun_times)
            transition = self._get_turn_on_transition()
            effective_override = self._get_decayed_brightness_override(area_id)
            await self._send_light(
                area_id,
                result.brightness,
                result.color_temp,
                transition=transition,
                rhythm_brightness=result.brightness,
                brightness_override=effective_override,
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
            # Cancel any active fades and mark user action before turning off
            for area_id in area_ids:
                self.cancel_fade(area_id, source=source or "toggle_off")
                state.mark_user_action(area_id)

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
                    state.set_last_sent_kelvin(area_id, result.color_temp)
                    logger.debug(
                        f"Stored last_sent_kelvin={result.color_temp} for area {area_id}"
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
                    self.client.turn_off_lights(area_id, transition=transition)
                )
                tasks.append(self.client.turn_off_switch_entities(area_id))
            await asyncio.gather(*tasks)

            reach_note = " (reach + per-area)" if reach_used else ""
            logger.info(
                f"[{source}] lights_toggle_multiple: turned off {len(area_ids)} area(s){reach_note}"
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

            # Cancel any active fades and mark user action before turning on
            for area_id in area_ids:
                self.cancel_fade(area_id, source=source or "toggle_on")
                state.mark_user_action(area_id)

            # Compute pipeline results for all areas via shared builder
            # (applies sun_cooling_strength, brightness_sensitivity, etc.)
            area_pipeline_results = {}
            for area_id in area_ids:
                if not glozone.is_area_in_any_zone(area_id):
                    glozone.add_area_to_default_zone(area_id)
                    logger.info(f"Added area {area_id} to default zone")

                state.enable_circadian_and_set_on(area_id, True)
                area_pipeline_results[area_id] = self.compute_pipeline_for_area(
                    area_id, transition=transition,
                )

            # Try reach groups (greedy largest-first)
            reach_handled = await self._send_via_reach(
                area_ids, area_pipeline_results, transition=transition
            )

            # Per-area fallback for unhandled
            fallback_tasks = []
            for area_id, pipe_result in area_pipeline_results.items():
                skip = reach_handled.get(area_id)
                if skip:
                    area_filters = glozone.get_area_light_filters(area_id)
                    all_filters = (
                        set(area_filters.values()) if area_filters else {"Standard"}
                    )
                    all_norms = {f.replace(" ", "_").lower() for f in all_filters}
                    if all_norms.issubset(skip):
                        continue  # Fully handled by reach
                # Per-area delivery (inner 2-step handles off→on)
                fallback_tasks.append(
                    self.client.send_light(
                        area_id,
                        transition=transition,
                        pipeline_result=pipe_result,
                    )
                )
            if fallback_tasks:
                await asyncio.gather(*fallback_tasks)

            # Also turn on any switch entities (relays, smart plugs)
            for area_id in area_ids:
                await self.client.turn_on_switch_entities(area_id)

            reach_note = ""
            if reach_handled:
                reach_note = f" (reach: {len(reach_handled)} areas)"
            logger.info(
                f"[{source}] lights_toggle_multiple: turned on {len(area_ids)} area(s){reach_note}"
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

        Note: mark_user_action only for non-motion sources.
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
        if not from_motion:
            state.mark_user_action(area_id)
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
        effective_override = self._get_decayed_brightness_override(area_id)
        transition = self._get_turn_on_transition()
        await self._send_light(
            area_id,
            result.brightness,
            result.color_temp,
            transition=transition,
            rhythm_brightness=result.brightness,
            brightness_override=effective_override,
            boost_brightness=boost_amount,
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
        effective_override = self._get_decayed_brightness_override(area_id)

        transition = self._get_turn_on_transition()
        await self._send_light(
            area_id,
            result.brightness,
            result.color_temp,
            transition=transition,
            rhythm_brightness=result.brightness,
            brightness_override=effective_override,
            boost_brightness=boost_amount,
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
                state.set_last_sent_kelvin(area_id, result.color_temp)
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
            effective_override = self._get_decayed_brightness_override(area_id)
            transition = self._get_boost_return_transition()
            await self._send_light(
                area_id,
                result.brightness,
                result.color_temp,
                transition=transition,
                rhythm_brightness=result.brightness,
                brightness_override=effective_override,
            )
            logger.info(
                f"[{source}] Boost ended for area {area_id}, returned to circadian: "
                f"{result.brightness}%, {result.color_temp}K"
                f"{f', override={effective_override:.1f}' if effective_override else ''}"
                f" (transition={transition}s)"
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
        # from_motion=False: on_only doesn't create a motion timer, so the "motion"
        # sentinel would never clear — use a real timestamp expiry instead.
        await self.lights_on(
            area_id,
            source=source,
            boost_brightness=boost_brightness,
            boost_duration=boost_duration,
            from_motion=False,
        )

        # on_only means lights stay on — override started_from_off so boost
        # expiry just removes the boost instead of turning lights off.
        if has_boost and state.is_boosted(area_id):
            boost_st = state.get_boost_state(area_id)
            if boost_st and boost_st.get("boost_started_from_off"):
                state.set_boost(
                    area_id,
                    started_from_off=False,
                    expires_at=boost_st["boost_expires_at"],
                    brightness=boost_st["boost_brightness"],
                )
                logger.info(
                    f"[{source}] on_only: overrode started_from_off=False for area {area_id}"
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
            state.set_last_sent_kelvin(area_id, result.color_temp)
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
    # Auto On/Off Schedules
    # -------------------------------------------------------------------------

    def _resolve_auto_time(self, settings: dict, prefix: str, current_weekday: int) -> Optional[float]:
        """Resolve trigger time for auto_on or auto_off.

        Args:
            settings: Area settings dict
            prefix: "auto_on" or "auto_off"
            current_weekday: Python weekday (0=Mon..6=Sun)

        Returns:
            Decimal hour (e.g. 7.5) or None if not firing today.
        """
        from datetime import date

        # Check override first
        override = settings.get(f"{prefix}_override")
        if override:
            mode = override.get("mode")
            if mode == "pause":
                return None
            until_date = override.get("until_date")
            today = date.today().isoformat()
            if until_date and until_date < today:
                pass  # Expired, fall through to normal
            elif mode in ("today", "tomorrow", "forever", "date"):
                return override.get("time")

        source = settings.get(f"{prefix}_source", "sunrise")

        if source in ("sunrise", "sunset"):
            active_days = settings.get(f"{prefix}_days", [0, 1, 2, 3, 4, 5, 6])
            if current_weekday not in active_days:
                return None
            sun_times = self.client._get_sun_times() if hasattr(self.client, '_get_sun_times') else None
            if sun_times is None:
                sun_times = SunTimes()
            base_time = sun_times.sunrise if source == "sunrise" else sun_times.sunset
            offset = settings.get(f"{prefix}_offset", 0)
            return base_time + offset / 60.0

        elif source == "custom":
            days_1 = settings.get(f"{prefix}_days_1", [])
            days_2 = settings.get(f"{prefix}_days_2", [])
            if current_weekday in days_1:
                return settings.get(f"{prefix}_time_1")
            elif current_weekday in days_2:
                return settings.get(f"{prefix}_time_2")
            return None

        return None

    async def check_auto_schedules(self):
        """Check and fire any due auto-on or auto-off schedules.

        Called every second from the fast tick loop.
        """
        from datetime import date

        try:
            config = glozone.get_config()
        except Exception:
            return

        area_settings = config.get("area_settings", {})
        now = datetime.now()
        current_hour = now.hour + now.minute / 60.0 + now.second / 3600.0
        current_weekday = now.weekday()
        today_str = date.today().isoformat()

        for area_id, settings in area_settings.items():
            # Check auto_on
            if settings.get("auto_on_enabled"):
                trigger_time = self._resolve_auto_time(settings, "auto_on", current_weekday)
                if trigger_time is not None and current_hour >= trigger_time:
                    # Check if already fired today at this time
                    fired = self._auto_fired.get(area_id, {}).get("auto_on", {})
                    if fired.get("date") == today_str and fired.get("time") == trigger_time:
                        pass  # Already fired
                    else:
                        # Trigger mode check
                        skip = False
                        trigger_mode = settings.get("auto_on_trigger_mode", "always")
                        # Backward compat: old boolean overrides if new field absent
                        if trigger_mode == "always" and settings.get("auto_on_skip_if_brighter", False):
                            trigger_mode = "skip_brighter"

                        if trigger_mode == "skip_on":
                            if state.is_circadian(area_id) and state.get_is_on(area_id):
                                skip = True
                                logger.info(f"[auto_on] Skipping {area_id}: already on (skip_on mode)")
                        elif trigger_mode == "skip_brighter":
                            if state.is_circadian(area_id) and state.get_is_on(area_id):
                                current_bri = state.get_area(area_id).get("last_sent_brightness")
                                if current_bri is not None:
                                    area_config = self._get_config(area_id)
                                    area_state = self._get_area_state(area_id)
                                    result = CircadianLight.calculate_lighting(
                                        current_hour, area_config, area_state
                                    )
                                    if current_bri > result.brightness:
                                        skip = True
                                        logger.info(
                                            f"[auto_on] Skipping {area_id}: current {current_bri}% > target {result.brightness}%"
                                        )

                        if not skip:
                            fade_minutes = settings.get("auto_on_fade", 0)
                            light_preset = settings.get("auto_on_light", "circadian")
                            if fade_minutes > 0:
                                # Capture current state BEFORE any changes.
                                # If lights are off, start from 0/warm (not stale last_sent).
                                is_currently_on = state.is_circadian(area_id) and state.get_is_on(area_id)
                                if is_currently_on:
                                    start_bri = state.get_last_sent_brightness(area_id) or 0
                                    start_kelvin = state.get_last_sent_kelvin(area_id) or 2000
                                else:
                                    start_bri = 0
                                    start_kelvin = 2000
                                # Enable circadian + is_on (but DON'T set target preset state
                                # — that happens at fade completion for clean cancel behavior)
                                state.enable_circadian_and_set_on(area_id, True)
                                state.set_fade(
                                    area_id, "in", fade_minutes * 60,
                                    target_preset=light_preset,
                                    start_brightness=start_bri,
                                    start_kelvin=start_kelvin,
                                )
                                # Send initial fade command immediately (don't wait for tick)
                                await self.client.update_lights_in_circadian_mode(
                                    area_id, log_periodic=True, periodic_transition=5.0,
                                )
                                logger.info(f"[auto_on] Starting {fade_minutes}min fade-in for {area_id} ({light_preset})")
                            else:
                                if light_preset in ("nitelite", "britelite"):
                                    await self.set(area_id, source="auto_on", preset=light_preset, is_on=True)
                                else:
                                    await self.glo_reset(area_id, source="auto_on")
                                    await self.lights_on(area_id, source="auto_on")
                                logger.info(f"[auto_on] Fired for {area_id} ({light_preset})")

                        # Mark as fired (even if skipped)
                        if area_id not in self._auto_fired:
                            self._auto_fired[area_id] = {}
                        self._auto_fired[area_id]["auto_on"] = {"date": today_str, "time": trigger_time}
                        self._save_auto_fired()

            # Check auto_off
            if settings.get("auto_off_enabled"):
                trigger_time = self._resolve_auto_time(settings, "auto_off", current_weekday)
                if trigger_time is not None and current_hour >= trigger_time:
                    fired = self._auto_fired.get(area_id, {}).get("auto_off", {})
                    if fired.get("date") == today_str and fired.get("time") == trigger_time:
                        pass  # Already fired
                    else:
                        # "Only if untouched" check — skip if user interacted since auto_on
                        if settings.get("auto_off_only_untouched", False):
                            last_action = state.get_last_user_action(area_id)
                            auto_on_fired = self._auto_fired.get(area_id, {}).get("auto_on", {})
                            auto_on_date = auto_on_fired.get("date")
                            if last_action and auto_on_date:
                                try:
                                    from datetime import datetime as dt_cls
                                    action_dt = dt_cls.fromisoformat(last_action)
                                    # auto_on stores date + time; reconstruct a datetime
                                    auto_on_time = auto_on_fired.get("time", 0)
                                    auto_on_h = int(auto_on_time)
                                    auto_on_m = int((auto_on_time - auto_on_h) * 60)
                                    auto_on_dt = dt_cls.fromisoformat(
                                        f"{auto_on_date}T{auto_on_h:02d}:{auto_on_m:02d}:00"
                                    )
                                    if action_dt > auto_on_dt:
                                        logger.info(
                                            f"[auto_off] Skipping {area_id}: user action at "
                                            f"{last_action} after auto_on at {auto_on_date} {auto_on_time}"
                                        )
                                        if area_id not in self._auto_fired:
                                            self._auto_fired[area_id] = {}
                                        self._auto_fired[area_id]["auto_off"] = {"date": today_str, "time": trigger_time}
                                        self._save_auto_fired()
                                        continue
                                except Exception:
                                    pass  # On parse error, don't skip

                        fade_minutes = settings.get("auto_off_fade", 0)
                        if fade_minutes > 0:
                            start_bri = state.get_last_sent_brightness(area_id) or 50
                            start_kelvin = state.get_last_sent_kelvin(area_id) or 2700
                            state.set_fade(
                                area_id, "out", fade_minutes * 60,
                                target_preset="off",
                                start_brightness=start_bri,
                                start_kelvin=start_kelvin,
                            )
                            # Send initial fade command immediately
                            await self.client.update_lights_in_circadian_mode(
                                area_id, log_periodic=True, periodic_transition=5.0,
                            )
                            logger.info(f"[auto_off] Starting {fade_minutes}min fade-out for {area_id}")
                        else:
                            await self.lights_off(area_id, source="auto_off")
                            logger.info(f"[auto_off] Fired for {area_id}")

                        if area_id not in self._auto_fired:
                            self._auto_fired[area_id] = {}
                        self._auto_fired[area_id]["auto_off"] = {"date": today_str, "time": trigger_time}
                        self._save_auto_fired()

    def clear_auto_fired(self):
        """Clear auto schedule fired tracking (called at phase change).

        After clearing, re-marks any schedules whose trigger time already
        passed today to prevent catch-up fires.
        """
        self._auto_fired = {}
        logger.info("[auto] Cleared fired state for all areas")

        # Re-mark already-passed triggers to prevent catch-up
        try:
            from datetime import date as date_cls
            config = glozone.get_config()
            area_settings = config.get("area_settings", {})
            now = datetime.now()
            current_hour = now.hour + now.minute / 60.0 + now.second / 3600.0
            current_weekday = now.weekday()
            today_str = date_cls.today().isoformat()

            for area_id, settings in area_settings.items():
                for prefix in ("auto_on", "auto_off"):
                    if not settings.get(f"{prefix}_enabled"):
                        continue
                    trigger_time = self._resolve_auto_time(
                        settings, prefix, current_weekday
                    )
                    if trigger_time is not None and current_hour >= trigger_time:
                        self._auto_fired.setdefault(area_id, {})[prefix] = {
                            "date": today_str, "time": trigger_time
                        }
                        logger.info(
                            f"[auto] Pre-marked {prefix} as fired for {area_id} "
                            f"(trigger {trigger_time:.2f} already passed)"
                        )
        except Exception as e:
            logger.warning(f"[auto] Error pre-marking fired state: {e}")

        self._save_auto_fired()

    def clear_auto_fired_for(self, area_id: str, prefix: str):
        """Clear fired state for a specific area/prefix, then re-mark if
        trigger time already passed today.

        Called when settings change (save handler, enable toggle). Uses the
        same _resolve_auto_time logic as check_auto_schedules to ensure
        consistent behavior.
        """
        from datetime import date as date_cls

        area_fired = self._auto_fired.get(area_id)
        if area_fired and prefix in area_fired:
            del area_fired[prefix]

        # Re-mark if trigger time already passed today — prevents catch-up fire
        # when user is configuring the schedule
        try:
            config = glozone.get_config()
            settings = config.get("area_settings", {}).get(area_id, {})
            if settings.get(f"{prefix}_enabled"):
                now = datetime.now()
                current_hour = now.hour + now.minute / 60.0 + now.second / 3600.0
                current_weekday = now.weekday()
                trigger_time = self._resolve_auto_time(
                    settings, prefix, current_weekday
                )
                if trigger_time is not None and current_hour >= trigger_time:
                    self._auto_fired.setdefault(area_id, {})[prefix] = {
                        "date": date_cls.today().isoformat(),
                        "time": trigger_time,
                    }
                    logger.info(
                        f"[auto] Re-marked {prefix} as fired for {area_id} "
                        f"(trigger {trigger_time:.2f} already passed)"
                    )
        except Exception as e:
            logger.warning(f"[auto] Error re-marking fired state: {e}")

        self._save_auto_fired()

    def _get_auto_fired_file(self) -> str:
        data_dir = os.environ.get("CIRCADIAN_DATA_DIR", "/config/circadian-light")
        return os.path.join(data_dir, "auto_fired.json")

    def _save_auto_fired(self):
        import tempfile

        path = self._get_auto_fired_file()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(self._auto_fired, f)
                os.replace(tmp, path)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        except Exception as e:
            logger.debug(f"[auto] Error saving fired state: {e}")

    def _load_auto_fired(self):
        path = self._get_auto_fired_file()
        try:
            with open(path) as f:
                self._auto_fired = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self._auto_fired = {}

    # -------------------------------------------------------------------------
    # Fade Management
    # -------------------------------------------------------------------------

    def cancel_fade(self, area_id: str, source: str = ""):
        """Cancel any active fade for an area (called on user actions).

        Bakes in the current fade position: applies target preset state,
        then sets a midpoint shift so the pipeline naturally produces the
        current lerped brightness. User's next action works from there.
        """
        if not state.is_fading(area_id):
            return

        fade = state.get_fade_state(area_id)
        progress = state.get_fade_progress(area_id) or 0.0
        target_preset = fade.get("fade_target_preset", "circadian")
        start_bri = fade.get("fade_start_brightness") or 0
        start_kelvin = fade.get("fade_start_kelvin") or 2000

        # Compute current lerped brightness
        if target_preset == "off":
            lerped_bri = max(1, round(start_bri * (1.0 - progress)))
        else:
            target_result = self.compute_fade_target(area_id, target_preset)
            target_bri = target_result.area_brightness if target_result else 0
            lerped_bri = max(1, round(start_bri + (target_bri - start_bri) * progress))

        # Clear fade FIRST (before applying preset, which may trigger state changes)
        state.clear_fade(area_id)

        # Apply target preset state (circadian/nitelite/britelite)
        if target_preset == "off":
            # Cancel during fade-out: stay in circadian mode at current brightness
            pass  # state is already circadian
        elif target_preset in ("nitelite", "britelite"):
            config = self._get_config(area_id)
            frozen_hour = config.ascend_start if target_preset == "nitelite" else config.descend_start
            state.update_area(area_id, {
                "brightness_mid": None, "color_mid": None,
                "brightness_override": None, "brightness_override_set_at": None,
                "color_override": None, "color_override_set_at": None,
            })
            state.set_frozen_at(area_id, frozen_hour)
        else:
            # circadian: reset midpoints (glo_reset equivalent)
            state.reset_area(area_id)

        # Bake in current brightness via set_position (sets midpoint so pipeline
        # produces ~lerped_bri). Skip for nitelite/britelite (frozen, no midpoint).
        if target_preset not in ("nitelite", "britelite"):
            config = self._get_config(area_id)
            b_range = config.max_brightness - config.min_brightness
            if b_range > 0:
                position = (lerped_bri - config.min_brightness) / b_range * 100
                position = max(0, min(100, round(position, 1)))
                area_state = self._get_area_state(area_id)
                sun_times = (
                    self.client._get_sun_times()
                    if hasattr(self.client, "_get_sun_times")
                    else None
                )
                result = CircadianLight.calculate_set_position(
                    hour=get_current_hour(),
                    position=position,
                    dimension="step",
                    config=config,
                    state=area_state,
                    sun_times=sun_times,
                )
                self._update_area_state(area_id, result.state_updates)

        logger.info(
            f"[{source}] Cancelled fade for {area_id}: baked in at {lerped_bri}% "
            f"(progress={progress:.0%}, target={target_preset})"
        )

    async def check_fade_completions(self):
        """Check for completed fades and finalize them.

        On completion, applies the target preset state for real (the fade
        was running with synthetic target computation, not modifying actual
        state). This is the atomic state transition.
        """
        for area_id in list(state.get_all_areas().keys()):
            if not state.is_fading(area_id):
                continue
            progress = state.get_fade_progress(area_id)
            if progress is None or progress < 1.0:
                continue
            fade = state.get_fade_state(area_id)
            target_preset = fade.get("fade_target_preset", "circadian")

            # Clear fade FIRST
            state.clear_fade(area_id)

            # Apply target preset state
            if target_preset == "off":
                await self.lights_off(area_id, source="auto_off_fade_complete")
                logger.info(f"[fade] Complete for {area_id}: off")
            elif target_preset in ("nitelite", "britelite"):
                await self.set(
                    area_id, source="fade_complete",
                    preset=target_preset, is_on=True,
                )
                logger.info(f"[fade] Complete for {area_id}: {target_preset}")
            else:
                # circadian: reset to default curve
                await self.glo_reset(area_id, source="fade_complete")
                logger.info(f"[fade] Complete for {area_id}: circadian")

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
            warning_time = raw_config.get("motion_warning_time", 20)
            blink_threshold = raw_config.get("motion_blink_threshold", 15)
            return (warning_time, blink_threshold)
        except Exception:
            return (20, 15)  # Defaults: 20s warning, 15%

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
        """Trigger motion warning for an area.

        Sets dim_factor in area state so the pipeline dims brightness.
        No direct light commands — the next periodic tick applies the dim.

        For low brightness (at or below blink_threshold), does a momentary
        blink-off as a visual cue before the pipeline-driven dim.

        Args:
            area_id: The area ID
            blink_threshold: Brightness % below which to add a blink cue
        """
        if state.is_motion_warned(area_id):
            logger.debug(f"[motion_warning] Area {area_id} already warned, skipping")
            return

        # Get current actual brightness from cache
        current_brightness = state.get_last_sent_brightness(area_id) or 0

        # Set warning state — pipeline will apply dim_factor on next tick
        state.set_motion_warning(area_id, current_brightness, dim_factor=0.5)

        logger.info(
            f"[motion_warning] Triggering warning for area {area_id}, "
            f"current brightness={current_brightness}%, dim_factor=0.5"
        )

        if current_brightness <= blink_threshold and current_brightness > 0:
            # Low brightness: blink off as visual cue (momentary side-channel)
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
            await self._send_light(
                area_id, 0, result.color_temp, include_color=False, transition=0.1
            )
            await asyncio.sleep(0.3)
            logger.info(
                f"[motion_warning] Blinked area {area_id} (was {current_brightness}%)"
            )

        # Trigger immediate pipeline update to apply the dim
        await self.client.update_lights_in_circadian_mode(
            area_id, log_periodic=True
        )

    async def cancel_motion_warning(
        self, area_id: str, source: str = "motion_detected"
    ):
        """Cancel motion warning and restore brightness.

        Clears dim_factor so the next pipeline computation produces
        full brightness. Triggers an immediate update to restore.

        Args:
            area_id: The area ID
            source: Source of the cancellation
        """
        if not state.is_motion_warned(area_id):
            return

        # Clear warning state — pipeline will compute full brightness
        state.clear_motion_warning(area_id)

        logger.info(
            f"[{source}] Cancelled motion warning for area {area_id}"
        )

        # Trigger immediate pipeline update to restore brightness
        await self.client.update_lights_in_circadian_mode(
            area_id, log_periodic=True
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
            state.set_last_sent_kelvin(area_id, result.color_temp)
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
        brightness: float = None,
        send_command: bool = True,
    ):
        """Configure area state with presets, frozen_at, or copy settings.

        Presets:
            - wake_or_bed: Set midpoints to match designed wake/bed brightness.
              Ascend phase → wake settings, descend phase → bed settings.
            - nitelite: Freeze at ascend_start (minimum values)
            - britelite: Freeze at descend_start (maximum values)
            - circadian: Circadian mode. If brightness is provided, adjusts to
              that actual brightness via circadian_adjust (P1/P2/P3).

        Priority: copy_from > frozen_at > preset

        Args:
            area_id: The area ID
            source: Source of the action
            preset: Optional preset name (wake, bed, nitelite, britelite, circadian)
            frozen_at: Optional specific hour (0-24) to freeze at
            copy_from: Optional area_id to copy settings from
            is_on: Controls whether to take control:
                - None (default): just configure settings, don't change control state
                - True: configure + take control + turn on
                - False: configure + take control + turn off
            brightness: Optional target actual brightness (0-100). Only used
                with preset="circadian". Ignored for other presets.
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
                    await self.client.update_lights_in_circadian_mode(area_id, log_periodic=True)
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
                await self.client.update_lights_in_circadian_mode(area_id, log_periodic=True)
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

            elif preset == "circadian":
                # Circadian mode with optional brightness target.
                # If brightness provided, shift midpoint to target via set_position.
                # Otherwise just enable circadian at current curve position.
                if brightness is not None:
                    config = self._get_config(area_id)
                    # brightness is actual (post-pipeline); convert to curve space
                    sun_bright_factor = self._compute_sun_bright_factor(area_id)
                    area_factor = glozone.get_area_brightness_factor(area_id)
                    denom = max(0.01, sun_bright_factor * area_factor)
                    curve_bri = brightness / denom
                    curve_bri = max(config.min_brightness, min(config.max_brightness, curve_bri))
                    b_range = config.max_brightness - config.min_brightness
                    position = (curve_bri - config.min_brightness) / b_range * 100 if b_range > 0 else 50
                    position = max(0, min(100, round(position, 1)))
                    logger.info(
                        f"[{source}] Set {area_id} to circadian preset "
                        f"(actual={brightness}, curve={curve_bri:.0f}, pos={position})"
                    )
                    await self.set_position(
                        area_id, position, mode="step", source=source,
                        _send_command=send_command,
                    )
                else:
                    logger.info(f"[{source}] Set {area_id} to circadian preset")
                    if (
                        state.is_circadian(area_id)
                        and state.get_is_on(area_id)
                        and send_command
                    ):
                        await self.client.update_lights_in_circadian_mode(area_id, log_periodic=True)
                return

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
                sun_times = (
                    self.client._get_sun_times()
                    if hasattr(self.client, "_get_sun_times")
                    else None
                )
                # Use turn_on_transition for presets (they're typically turn-on actions)
                transition = self._get_turn_on_transition()
                await self.client.update_lights_in_circadian_mode(
                    area_id, log_periodic=True, periodic_transition=transition
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
        state.mark_user_action(area_id)
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
        if source not in ("auto_on", "auto_off", "auto_off_fade_complete", "wake_alarm"):
            self.cancel_fade(area_id, source=source or "unknown")
            state.mark_user_action(area_id)

        logger.info(f"[{source}] glo_reset for area {area_id}")

        # Reset state (clears midpoints/bounds/frozen_at, preserves only enabled)
        state.reset_area(area_id)

        # Apply current time values only if circadian and is_on
        if state.is_circadian(area_id) and state.get_is_on(area_id):
            config = self._get_config(area_id)
            area_state = self._get_area_state(area_id)
            hour = get_current_hour()

            sun_times = (
                self.client._get_sun_times()
                if hasattr(self.client, "_get_sun_times")
                else None
            )
            if send_command:
                await self.client.update_lights_in_circadian_mode(area_id, log_periodic=True)

            logger.info(f"glo_reset complete for area {area_id}")
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
            await self.client.update_lights_in_circadian_mode(area_id, log_periodic=True)
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

    async def _send_light(
        self,
        area_id: str,
        brightness: int,
        color_temp: int,
        include_color: bool = True,
        transition: float = 0.4,
        *,
        rhythm_brightness: int = None,
        brightness_override: float = None,
        boost_brightness: int = None,
        skip_filters: Set[str] = None,
        skip_two_step: bool = False,
        skip_off_threshold: bool = False,
    ):
        """Apply lighting values to an area.

        Delegates to client.send_light() which is the single source
        of truth for light control. This ensures consistent behavior across all
        code paths (primitives, periodic updater, etc.).

        Args:
            area_id: The area ID
            brightness: Brightness percentage (0-100)
            color_temp: Color temperature in Kelvin
            include_color: Whether to include color in the command
            transition: Transition time in seconds
            rhythm_brightness: Pure curve brightness for filter curve position (pre-sun-bright/boost).
                If provided, brightness_override is applied post-sun-bright in the filter pipeline.
            brightness_override: Decay-adjusted additive delta applied post-sun-bright.
            skip_filters: Set of filter_norms to skip (already handled by reach groups).
            skip_two_step: Skip inner 2-step detection (caller already handles 2-step).
            skip_off_threshold: Skip OFF commands for filters below off_threshold (phase 1 only).
        """
        circadian_values = {
            "brightness": brightness,
            "kelvin": color_temp,
        }
        if rhythm_brightness is not None:
            circadian_values["rhythm_brightness"] = rhythm_brightness
        if brightness_override is not None:
            circadian_values["brightness_override"] = brightness_override
        if boost_brightness is not None:
            circadian_values["boost_brightness"] = boost_brightness
        if skip_filters:
            circadian_values["skip_filters"] = skip_filters
        if skip_two_step:
            circadian_values["skip_two_step"] = True
        if skip_off_threshold:
            circadian_values["skip_off_threshold"] = True

        await self.client.send_light(
            area_id,
            circadian_values,
            transition=transition,
            include_color=include_color,
        )

    async def _send_via_reach(
        self,
        area_ids: List[str],
        area_pipeline_results: Dict[str, "PipelineResult"],
        transition: float = 0.4,
    ) -> Dict[str, Set[str]]:
        """Attempt reach group dispatch for multi-area actions.

        Uses pre-computed pipeline results per area. Matches values across
        areas using greedy set cover (largest reach group first) to minimize
        ZigBee calls. Direction-aware 2-step with configured transition.

        Args:
            area_ids: List of area IDs
            area_pipeline_results: Dict of area_id -> PipelineResult
            transition: Transition time in seconds

        Returns:
            Dict of area_id -> set of filter_norms handled via reach groups.
            Empty dict if no reach groups were used.
        """
        handled_filters: Dict[str, Set[str]] = {}

        if len(area_ids) < 2:
            return handled_filters

        import switches as _switches

        # Build per-area per-purpose data from pipeline results
        # area_purpose_data[area_id] = [(filter_norm, factor_key, brightness, kelvin)]
        area_purpose_data: Dict[str, List[Tuple]] = {}
        for area_id, pipe_result in area_pipeline_results.items():
            area_factor = glozone.get_area_brightness_factor(area_id)
            factor_key = round(area_factor, 3)
            purposes = []
            for p in pipe_result.purposes:
                filter_norm = p.name.replace(" ", "_").lower()
                purposes.append((filter_norm, factor_key, p.brightness, p.kelvin))
            area_purpose_data[area_id] = purposes

        # Collect all candidate reach groups (exact + subset reaches)
        area_set = set(area_ids)
        candidate_reaches = []
        for rkey, rgroup in self.client.reach_groups.items():
            if not rgroup.filter_groups:
                continue
            rgroup_areas = set(rgroup.areas)
            if len(rgroup_areas) >= 2 and rgroup_areas.issubset(area_set):
                candidate_reaches.append((rkey, rgroup))

        if not candidate_reaches:
            return handled_filters

        # Sort by group size descending (greedy: largest reach first = most ZigBee calls saved)
        candidate_reaches.sort(
            key=lambda x: len(x[1].filter_groups), reverse=True
        )

        # 2-step config
        raw_cfg = glozone.load_config_from_files()
        ct_threshold = raw_cfg.get("two_step_ct_threshold", 500)
        bri_delta_threshold = raw_cfg.get("two_step_bri_threshold", 15)

        handled_set: Set[Tuple[str, str]] = set()  # (area_id, filter_norm)
        reach_commands = []  # list of command dicts

        for rkey, rgroup in candidate_reaches:
            for (filter_norm, factor_key, cap), entity_id in rgroup.filter_groups.items():
                # Find areas in this reach group that match filter+factor and aren't handled
                matching = {}
                for area_id in rgroup.areas:
                    if (area_id, filter_norm) in handled_set:
                        continue
                    for fn, fk, bri, ct in area_purpose_data.get(area_id, []):
                        if fn == filter_norm and fk == factor_key:
                            matching[area_id] = (bri, ct)

                if len(matching) < 2:
                    continue

                # All areas must have identical target values
                values = set(matching.values())
                if len(values) != 1:
                    continue

                bri, ct = values.pop()
                if bri <= 0:
                    continue  # All off — handled by per-area off logic

                # --- 2-step detection ---
                needs_2step = False
                brightening = True
                phase1_data = None  # (brightness, include_color)
                phase2_data = None  # (brightness, include_color)

                if ct_threshold > 0:
                    # Check CT delta for any area
                    any_ct_exceeded = False
                    for area_id in matching:
                        last_ct = state.get_last_sent_kelvin(area_id)
                        if last_ct is not None and abs(ct - last_ct) >= ct_threshold:
                            any_ct_exceeded = True
                            break

                    if any_ct_exceeded:
                        # Current state must match across all areas for batched 2-step
                        current_states = {}
                        for area_id in matching:
                            is_on = state.get_is_on(area_id)
                            curr_bri = state.get_last_sent_brightness(area_id) or 0
                            current_states[area_id] = (is_on, curr_bri)

                        state_values = set(current_states.values())
                        if len(state_values) != 1:
                            # States differ — can't batch, fall through to per-area
                            continue

                        shared_on, shared_bri = state_values.pop()

                        # Check brightness delta threshold
                        if not shared_on:
                            # Off→on
                            if bri >= bri_delta_threshold:
                                needs_2step = True
                                brightening = True
                                # Phase 1: color at 1%, Phase 2: target brightness + color
                                phase1_data = (1, True)
                                phase2_data = (bri, True)
                        else:
                            bri_delta = abs(bri - shared_bri)
                            if bri_delta >= bri_delta_threshold:
                                needs_2step = True
                                brightening = bri > shared_bri
                                if brightening:
                                    # Phase 1: color at low bri, Phase 2: target bri + color
                                    phase1_bri = max(1, min(shared_bri, bri))
                                    phase1_data = (phase1_bri, True)
                                    phase2_data = (bri, True)
                                else:
                                    # Phase 1: dim to target (no color), Phase 2: color (no bri)
                                    phase1_data = (bri, False)
                                    phase2_data = (None, True)

                        if needs_2step:
                            mode = "off→on" if not shared_on else (
                                f"brighten {shared_bri}→{bri}%" if brightening
                                else f"dim {shared_bri}→{bri}%"
                            )
                            logger.info(
                                f"Reach 2-step: {filter_norm} {cap}, {mode}, {ct}K"
                            )

                reach_commands.append({
                    "entity_id": entity_id,
                    "bri": bri,
                    "ct": ct,
                    "filter_norm": filter_norm,
                    "cap": cap,
                    "needs_2step": needs_2step,
                    "phase1_data": phase1_data,
                    "phase2_data": phase2_data,
                })
                for area_id in matching:
                    handled_filters.setdefault(area_id, set()).add(filter_norm)
                    handled_set.add((area_id, filter_norm))

        if not reach_commands:
            return handled_filters

        # --- Execute commands ---
        two_step_cmds = [c for c in reach_commands if c["needs_2step"]]
        direct_cmds = [c for c in reach_commands if not c["needs_2step"]]

        # Wave 1: phase 1 for 2-step + direct commands (parallel)
        wave1 = []
        for cmd in two_step_cmds:
            p1_bri, p1_color = cmd["phase1_data"]
            xy = CircadianLight.color_temperature_to_xy(cmd["ct"])
            sdata = {"transition": transition}
            if p1_bri is not None:
                sdata["brightness_pct"] = p1_bri
            if p1_color:
                if cmd["cap"] == "color":
                    sdata["xy_color"] = list(xy)
                elif cmd["cap"] == "ct":
                    sdata["color_temp_kelvin"] = max(2000, cmd["ct"])
            wave1.append(
                self.client.call_service("light", "turn_on", sdata, {"entity_id": cmd["entity_id"]})
            )

        for cmd in direct_cmds:
            xy = CircadianLight.color_temperature_to_xy(cmd["ct"])
            sdata = {"transition": transition, "brightness_pct": cmd["bri"]}
            if cmd["cap"] == "color":
                sdata["xy_color"] = list(xy)
            elif cmd["cap"] == "ct":
                sdata["color_temp_kelvin"] = max(2000, cmd["ct"])
            logger.info(
                f"Reach {cmd['filter_norm']} {cmd['cap']}: {cmd['entity_id']}, "
                f"{cmd['bri']}% {cmd['ct']}K, transition={transition}s"
            )
            wave1.append(
                self.client.call_service("light", "turn_on", sdata, {"entity_id": cmd["entity_id"]})
            )

        if wave1:
            await asyncio.gather(*wave1)

        # Wave 2: phase 2 for 2-step (after delay)
        if two_step_cmds:
            delay = self._get_two_step_delay()
            await asyncio.sleep(delay)

            wave2 = []
            for cmd in two_step_cmds:
                p2_bri, p2_color = cmd["phase2_data"]
                xy = CircadianLight.color_temperature_to_xy(cmd["ct"])
                sdata = {"transition": transition}
                if p2_bri is not None:
                    sdata["brightness_pct"] = p2_bri
                if p2_color:
                    if cmd["cap"] == "color":
                        sdata["xy_color"] = list(xy)
                    elif cmd["cap"] == "ct":
                        sdata["color_temp_kelvin"] = max(2000, cmd["ct"])
                logger.info(
                    f"Reach {cmd['filter_norm']} {cmd['cap']}: {cmd['entity_id']}, "
                    f"phase 2, transition={transition}s"
                )
                wave2.append(
                    self.client.call_service("light", "turn_on", sdata, {"entity_id": cmd["entity_id"]})
                )
            await asyncio.gather(*wave2)

        # Update state for handled areas
        for area_id, filter_norms in handled_filters.items():
            for fn, fk, bri, ct in area_purpose_data.get(area_id, []):
                if fn in filter_norms:
                    state.set_last_sent_kelvin(area_id, ct)
                    state.set_last_sent_purpose(area_id, fn, bri, ct or 4000)

        handled_count = sum(len(fns) for fns in handled_filters.values())
        if handled_count:
            logger.info(f"Reach handled {handled_count} area/purpose combos across {len(handled_filters)} areas")

        return handled_filters

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

        Phase 2 (restore) sends the original visible brightness back via
        call_service (same direct path as phase 1).

        Args:
            area_id: The area ID
            current_brightness: Raw circadian brightness (pre-sun-bright, pre-boost) for Phase 2 restore
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

        # Resolve feedback target first (needed to read correct brightness)
        feedback_target = getattr(self.client, "_active_feedback_target", None)
        if not feedback_target:
            # No switch context (web UI, etc.) — use most popular filter group
            feedback_target = self.client._get_feedback_group_for_area(area_id)
        if feedback_target:
            targets = [feedback_target]
        else:
            targets = [{"area_id": area_id}]

        # Read visible brightness from feedback target entity (not all area lights)
        target_entity = None
        if feedback_target and "entity_id" in feedback_target:
            target_entity = feedback_target["entity_id"]
        if target_entity:
            ls = self.client.cached_states.get(target_entity, {})
            visible_bri = ls.get("attributes", {}).get("brightness", 0) or 1
        else:
            # Fallback: max brightness across all area lights
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

        # Brightness bounce target in HA 0-255 space (% of full range, not % of current)
        if bounce_bri:
            delta = int(bounce_percent * 255)
            if direction == "up":
                target_visible = max(1, visible_bri - delta)
            else:
                target_visible = min(255, visible_bri + delta)
        else:
            target_visible = visible_bri

        # Color bounce target using xy (works across full Kelvin range)
        from brain import CircadianLight as CL
        include_color = bounce_type in ("step", "color")
        phase1_xy = None
        restore_xy = None
        if include_color and bounce_color:
            color_range = config.max_color_temp - config.min_color_temp
            color_delta = int(bounce_percent * color_range)
            if direction == "up":
                target_color = max(config.min_color_temp, int(current_color - color_delta))
            else:
                target_color = min(config.max_color_temp, int(current_color + color_delta))
            phase1_xy = list(CL.color_temperature_to_xy(target_color))
            restore_xy = list(CL.color_temperature_to_xy(current_color))

        # Build clean HA targets (strip metadata like filter_name)
        ha_targets = []
        for t in targets:
            if "entity_ids" in t:
                # Multiple lights for a purpose without a ZHA group
                for eid in t["entity_ids"]:
                    ha_targets.append({"entity_id": eid})
            elif "entity_id" in t:
                ha_targets.append({"entity_id": t["entity_id"]})
            elif "area_id" in t:
                ha_targets.append({"area_id": t["area_id"]})
            else:
                ha_targets.append(t)

        # Defer periodic tick during bounce to prevent overwriting
        self.client._defer_periodic_tick = True
        try:
            # Phase 1: Bounce away via call_service (visible space, bypass pipeline)
            phase1_tasks = []
            for target in ha_targets:
                sdata = {"brightness": target_visible, "transition": limit_speed}
                if phase1_xy:
                    sdata["xy_color"] = phase1_xy
                phase1_tasks.append(
                    self.client.call_service("light", "turn_on", sdata, target=target)
                )
            await asyncio.gather(*phase1_tasks)
            await asyncio.sleep(limit_speed + two_step_delay)

            # Phase 2: Restore to same targets (same visible brightness, no pipeline)
            phase2_tasks = []
            for target in ha_targets:
                rdata = {"brightness": visible_bri, "transition": limit_speed}
                if restore_xy:
                    rdata["xy_color"] = restore_xy
                phase2_tasks.append(
                    self.client.call_service("light", "turn_on", rdata, target=target)
                )
            await asyncio.gather(*phase2_tasks)
        finally:
            self.client._defer_periodic_tick = False

        target_entity = feedback_target.get("entity_id", feedback_target.get("area_id", "?")) if feedback_target else "none"
        logger.info(
            f"Limit bounce ({bounce_type} {direction}) for {area_id}: "
            f"target={target_entity}, "
            f"visible {visible_bri}/255 -> {target_visible}/255 -> restore, "
            f"speed={limit_speed}s, delay={two_step_delay}s"
        )

    async def alert_bounce(
        self,
        area_id: str,
        intensity: str = "low",
        count: int = 3,
        source: str = "motion_sensor",
    ):
        """Visual alert bounce — brightness pulse on the area's feedback target.

        Uses the shared "Small bounce" settings (max_percent / min_percent).
        Intensity multiplies the bounce percentage: low=1x, med=2x, high=3x.
        When lights are off, flashes on at bounce percentage then off.

        Args:
            area_id: The area to alert
            intensity: "low", "med", or "high"
            count: Number of bounces
            source: Source of the action
        """
        import asyncio

        # Resolve feedback target (same as limit bounce / reach feedback)
        feedback_target = self.client._get_feedback_group_for_area(area_id)
        if not feedback_target:
            logger.debug(f"Alert bounce: no feedback target for {area_id}")
            return

        # Build clean HA target (strip metadata like filter_name)
        if "entity_id" in feedback_target:
            targets = [{"entity_id": feedback_target["entity_id"]}]
        elif "area_id" in feedback_target:
            targets = [{"area_id": feedback_target["area_id"]}]
        else:
            targets = [feedback_target]

        # Read bounce settings
        max_pct = self._get_limit_bounce_max_percent() / 100.0
        min_pct = self._get_limit_bounce_min_percent() / 100.0
        multiplier = {"low": 1, "med": 2, "high": 3}.get(intensity, 1)
        speed = self._get_alert_bounce_speed()
        two_step_delay = self._get_two_step_delay()

        # Use our internal state, not HA cached_states
        was_on = state.get_is_on(area_id)
        if was_on:
            target_entity = feedback_target.get("entity_id") if feedback_target else None
            if target_entity:
                cached = self.client.cached_states.get(target_entity, {})
                cached_bri = cached.get("attributes", {}).get("brightness", 0) or 1
            else:
                cached_bri = 128  # fallback
        else:
            cached_bri = 0

        # Determine bounce direction and delta
        if was_on and cached_bri > 0:
            bri_pct = cached_bri / 2.55  # 0-100
            if bri_pct >= 50:
                bounce_pct = min(max_pct * multiplier, 0.95)
                target_bri = max(1, int(cached_bri * (1 - bounce_pct)))
            else:
                bounce_pct = min(min_pct * multiplier, 0.95)
                target_bri = min(255, int(cached_bri + 255 * bounce_pct))
        else:
            bounce_pct = min(min_pct * multiplier, 0.95)
            target_bri = max(1, int(255 * bounce_pct))

        # Compute circadian color only for was_off (lights on already have correct color)
        color_data = {}
        if not was_on:
            try:
                config = self._get_config(area_id)
                hour = get_current_hour()
                sun_times = self.client._get_sun_times() if hasattr(self.client, "_get_sun_times") else None
                area_state_obj = self._get_area_state(area_id)
                result = CircadianLight.calculate_lighting(hour, config, area_state_obj, sun_times=sun_times)
                xy = CircadianLight.color_temperature_to_xy(result.color_temp)
                color_data = {"xy_color": list(xy)}
            except Exception:
                pass

        target_desc = feedback_target.get("entity_id", feedback_target.get("area_id", "?"))
        logger.info(
            f"Alert bounce starting for {area_id}: {count}x, intensity={intensity} ({multiplier}x), "
            f"target={target_desc}, was_on={was_on}, cached_bri={cached_bri}, "
            f"target_bri={target_bri}, speed={speed}s"
        )

        self.client._defer_periodic_tick = True
        try:
            for i in range(count):
                # Phase 1: bounce to target (include color data)
                sdata = {"brightness": target_bri, "transition": speed, **color_data}
                for target in targets:
                    logger.info(f"Alert bounce [{i+1}/{count}] phase1: turn_on {target} bri={target_bri}")
                    await self.client.call_service(
                        "light", "turn_on", sdata, target=target,
                    )
                await asyncio.sleep(speed + two_step_delay)

                # Phase 2: restore
                if was_on:
                    rdata = {"brightness": cached_bri, "transition": speed, **color_data}
                    for target in targets:
                        logger.info(f"Alert bounce [{i+1}/{count}] phase2: restore bri={cached_bri}")
                        await self.client.call_service(
                            "light", "turn_on", rdata, target=target,
                        )
                else:
                    for target in targets:
                        logger.info(f"Alert bounce [{i+1}/{count}] phase2: turn_off")
                        await self.client.call_service(
                            "light", "turn_off",
                            {"transition": speed},
                            target=target,
                        )
                await asyncio.sleep(speed + two_step_delay)
        finally:
            self.client._defer_periodic_tick = False
            self.client.record_light_action()

        # For was_off areas: reset off-confirm counter so periodic tick
        # re-sends turn_off commands (catches lights stuck on from missed Zigbee)
        if not was_on:
            state.reset_off_confirm_count(area_id)
            state.set_off_enforced(area_id, False)

        logger.info(f"Alert bounce complete for {area_id}")

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
