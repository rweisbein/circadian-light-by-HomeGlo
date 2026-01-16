#!/usr/bin/env python3
"""Brain module for Circadian Light by HomeGlo.

This module provides the CircadianLight calculator - a stateless engine that
computes brightness and color temperature values based on:
- Current time
- Per-area runtime state (midpoints, bounds)
- Global configuration (timing, solar rules)

Key concepts:
- Ascend phase: brightness and color rise (night → day)
- Descend phase: brightness and color fall (day → night)
- 48-hour unwrapping: handles cross-midnight schedules
- Separate midpoints: brightness and color can diverge independently
- Brightness-primary stepping: Step Up/Down uses brightness as primary dimension
"""

from __future__ import annotations

import math
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class ColorMode(Enum):
    """Color modes for light control."""
    KELVIN = "kelvin"
    RGB = "rgb"
    XY = "xy"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Absolute limits (hardcoded, never exceeded)
ABSOLUTE_MIN_BRI = 1
ABSOLUTE_MAX_BRI = 100
ABSOLUTE_MIN_CCT = 500
ABSOLUTE_MAX_CCT = 6500

# Default configuration values
DEFAULT_MIN_BRIGHTNESS = 1
DEFAULT_MAX_BRIGHTNESS = 100
DEFAULT_MIN_COLOR_TEMP = 500
DEFAULT_MAX_COLOR_TEMP = 6500
DEFAULT_MAX_DIM_STEPS = 10

# Timing defaults (hours 0-24)
DEFAULT_ASCEND_START = 3.0
DEFAULT_DESCEND_START = 12.0
DEFAULT_WAKE_TIME = 6.0
DEFAULT_BED_TIME = 22.0

# Speed defaults (1-10 scale)
DEFAULT_WAKE_SPEED = 8
DEFAULT_BED_SPEED = 6

# Speed-to-slope mapping (index 0-10, where 0 is unused)
SPEED_TO_SLOPE = [0.0, 0.4, 0.6, 0.8, 1.0, 1.3, 1.7, 2.3, 3.0, 4.0, 5.5]


# ---------------------------------------------------------------------------
# Data classes for inputs/outputs
# ---------------------------------------------------------------------------

@dataclass
class Config:
    """Global configuration (from designer/config file)."""
    # Timing
    ascend_start: float = DEFAULT_ASCEND_START
    descend_start: float = DEFAULT_DESCEND_START
    wake_time: float = DEFAULT_WAKE_TIME
    bed_time: float = DEFAULT_BED_TIME
    wake_speed: int = DEFAULT_WAKE_SPEED
    bed_speed: int = DEFAULT_BED_SPEED

    # Bounds
    min_brightness: int = DEFAULT_MIN_BRIGHTNESS
    max_brightness: int = DEFAULT_MAX_BRIGHTNESS
    min_color_temp: int = DEFAULT_MIN_COLOR_TEMP
    max_color_temp: int = DEFAULT_MAX_COLOR_TEMP

    # Steps
    max_dim_steps: int = DEFAULT_MAX_DIM_STEPS
    step_increments: int = None  # For Step Up/Down (defaults to max_dim_steps)
    brightness_increments: int = None  # For Brighten/Dim (defaults to max_dim_steps)
    color_increments: int = None  # For Cooler/Warmer (defaults to max_dim_steps)

    # Solar rules - warm at night
    warm_night_enabled: bool = False
    warm_night_mode: str = "all"  # "all", "sunrise", or "sunset"
    warm_night_target: int = 2700
    warm_night_start: int = -60   # minutes offset from sunset (negative = before)
    warm_night_end: int = 60      # minutes offset from sunrise (positive = after)
    warm_night_fade: int = 60     # fade duration in minutes

    # Solar rules - cool during day
    cool_day_enabled: bool = False
    cool_day_mode: str = "all"    # "all", "sunrise", or "sunset"
    cool_day_target: int = 6500
    cool_day_start: int = 0       # minutes offset from sunrise
    cool_day_end: int = 0         # minutes offset from sunset
    cool_day_fade: int = 60       # fade duration in minutes

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Config":
        """Create Config from a dictionary."""
        return cls(
            ascend_start=d.get("ascend_start", DEFAULT_ASCEND_START),
            descend_start=d.get("descend_start", DEFAULT_DESCEND_START),
            wake_time=d.get("wake_time", DEFAULT_WAKE_TIME),
            bed_time=d.get("bed_time", DEFAULT_BED_TIME),
            wake_speed=d.get("wake_speed", DEFAULT_WAKE_SPEED),
            bed_speed=d.get("bed_speed", DEFAULT_BED_SPEED),
            min_brightness=d.get("min_brightness", DEFAULT_MIN_BRIGHTNESS),
            max_brightness=d.get("max_brightness", DEFAULT_MAX_BRIGHTNESS),
            min_color_temp=d.get("min_color_temp", DEFAULT_MIN_COLOR_TEMP),
            max_color_temp=d.get("max_color_temp", DEFAULT_MAX_COLOR_TEMP),
            max_dim_steps=d.get("max_dim_steps", DEFAULT_MAX_DIM_STEPS),
            step_increments=d.get("step_increments"),
            brightness_increments=d.get("brightness_increments"),
            color_increments=d.get("color_increments"),
            # Warm at night
            warm_night_enabled=d.get("warm_night_enabled", False),
            warm_night_mode=d.get("warm_night_mode", "all"),
            warm_night_target=d.get("warm_night_target", 2700),
            warm_night_start=d.get("warm_night_start", -60),
            warm_night_end=d.get("warm_night_end", 60),
            warm_night_fade=d.get("warm_night_fade", 60),
            # Cool during day
            cool_day_enabled=d.get("cool_day_enabled", False),
            cool_day_mode=d.get("cool_day_mode", "all"),
            cool_day_target=d.get("cool_day_target", 6500),
            cool_day_start=d.get("cool_day_start", 0),
            cool_day_end=d.get("cool_day_end", 0),
            cool_day_fade=d.get("cool_day_fade", 60),
        )


@dataclass
class SunTimes:
    """Sun position times for a day."""
    sunrise: float = 6.0      # Hour (0-24)
    sunset: float = 18.0      # Hour (0-24)
    solar_noon: float = 12.0  # Hour (0-24)
    solar_mid: float = 0.0    # Hour (0-24), midnight opposite of noon

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SunTimes":
        """Create SunTimes from a dictionary."""
        return cls(
            sunrise=d.get("sunrise", 6.0),
            sunset=d.get("sunset", 18.0),
            solar_noon=d.get("solar_noon", 12.0),
            solar_mid=d.get("solar_mid", 0.0),
        )


@dataclass
class AreaState:
    """Per-area runtime state.

    Only one phase (Ascend/Descend) is active at a time, so we only need
    one midpoint per axis rather than separate wake/bed values.
    """
    enabled: bool = False              # Whether circadian lighting is active
    frozen_at: Optional[float] = None  # Hour (0-24) to freeze at, None = unfrozen

    # Midpoints (None = use config wake_time/bed_time based on phase)
    brightness_mid: Optional[float] = None
    color_mid: Optional[float] = None

    # Solar rule limit (None = use config target for active rule)
    solar_rule_color_limit: Optional[int] = None

    # Runtime bounds (None = use config bounds)
    min_brightness: Optional[int] = None
    max_brightness: Optional[int] = None
    min_color_temp: Optional[int] = None
    max_color_temp: Optional[int] = None

    @property
    def is_frozen(self) -> bool:
        """Check if this area is frozen."""
        return self.frozen_at is not None

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AreaState":
        """Create AreaState from a dictionary."""
        return cls(
            enabled=d.get("enabled", False),
            frozen_at=d.get("frozen_at"),
            brightness_mid=d.get("brightness_mid"),
            color_mid=d.get("color_mid"),
            solar_rule_color_limit=d.get("solar_rule_color_limit"),
            min_brightness=d.get("min_brightness"),
            max_brightness=d.get("max_brightness"),
            min_color_temp=d.get("min_color_temp"),
            max_color_temp=d.get("max_color_temp"),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "enabled": self.enabled,
            "frozen_at": self.frozen_at,
            "brightness_mid": self.brightness_mid,
            "color_mid": self.color_mid,
            "solar_rule_color_limit": self.solar_rule_color_limit,
            "min_brightness": self.min_brightness,
            "max_brightness": self.max_brightness,
            "min_color_temp": self.min_color_temp,
            "max_color_temp": self.max_color_temp,
        }


@dataclass
class LightingResult:
    """Result of a lighting calculation."""
    brightness: int  # 0-100
    color_temp: int  # Kelvin
    rgb: Tuple[int, int, int]
    xy: Tuple[float, float]
    phase: str  # "ascend" or "descend"


@dataclass
class StepResult:
    """Result of a step calculation, including state updates."""
    brightness: int
    color_temp: int
    rgb: Tuple[int, int, int]
    xy: Tuple[float, float]
    state_updates: Dict[str, Any]  # Updates to apply to area state


# ---------------------------------------------------------------------------
# Core math functions
# ---------------------------------------------------------------------------

def logistic(x: float, midpoint: float, slope: float, y0: float, y1: float) -> float:
    """Standard logistic function.

    Formula: y0 + (y1 - y0) / (1 + exp(-slope * (x - midpoint)))

    Args:
        x: Input value (typically hour)
        midpoint: Inflection point where output = (y0 + y1) / 2
        slope: Steepness (positive for ascending, negative for descending)
        y0: Minimum output value
        y1: Maximum output value
    """
    try:
        exp_val = math.exp(-slope * (x - midpoint))
        return y0 + (y1 - y0) / (1 + exp_val)
    except OverflowError:
        return y1 if slope * (x - midpoint) > 0 else y0


def inverse_midpoint(x: float, target_value: float, slope: float, y0: float, y1: float) -> float:
    """Solve for the midpoint that produces target_value at position x.

    Given the logistic equation, solve for midpoint:
    midpoint = x + ln((1 - ratio) / ratio) / slope

    Args:
        x: Current position (hour in 48h space)
        target_value: Desired output value (normalized)
        slope: Curve slope
        y0: Minimum output value
        y1: Maximum output value

    Returns:
        The midpoint value that produces target_value at x
    """
    epsilon = 0.001
    clamped = max(y0 + epsilon, min(y1 - epsilon, target_value))
    ratio = (clamped - y0) / (y1 - y0)

    try:
        return x + math.log((1 - ratio) / ratio) / slope
    except (ValueError, ZeroDivisionError):
        return x


# ---------------------------------------------------------------------------
# CircadianLight Calculator
# ---------------------------------------------------------------------------

class CircadianLight:
    """Stateless calculator for circadian lighting values.

    All methods take config and state as parameters and return results.
    No state is stored on the instance.
    """

    @staticmethod
    def get_phase_info(hour: float, config: Config) -> Tuple[bool, float, float, float, float]:
        """Get phase information for a given hour.

        Args:
            hour: Current hour (0-24)
            config: Global configuration

        Returns:
            Tuple of (in_ascend, h48, t_ascend, t_descend, slope)
        """
        t_ascend = config.ascend_start
        t_descend = config.descend_start

        # Handle cross-midnight patterns
        if t_descend <= t_ascend:
            t_descend += 24

        # Unwrap hour into 48h space
        h48 = hour + 24 if hour < t_ascend else hour

        in_ascend = t_ascend <= h48 < t_descend

        k_ascend = SPEED_TO_SLOPE[max(1, min(10, config.wake_speed))]
        k_descend = SPEED_TO_SLOPE[max(1, min(10, config.bed_speed))]
        slope = k_ascend if in_ascend else -k_descend

        return in_ascend, h48, t_ascend, t_descend, slope

    @staticmethod
    def lift_midpoint_to_phase(midpoint: float, phase_start: float, phase_end: float) -> float:
        """Lift a midpoint into the correct 48-hour phase window.

        Args:
            midpoint: The midpoint hour (0-24)
            phase_start: Start of phase in 48h space
            phase_end: End of phase in 48h space
        """
        mid = midpoint
        while mid < phase_start:
            mid += 24
        while mid > phase_end:
            mid -= 24
        return mid

    @staticmethod
    def calculate_brightness_at_hour(
        hour: float,
        config: Config,
        state: AreaState
    ) -> int:
        """Calculate brightness at a specific hour.

        Args:
            hour: Hour (0-24)
            config: Global configuration
            state: Area runtime state

        Returns:
            Brightness percentage (0-100)
        """
        in_ascend, h48, t_ascend, t_descend, slope = CircadianLight.get_phase_info(hour, config)

        # Effective bounds
        b_min = state.min_brightness if state.min_brightness is not None else config.min_brightness
        b_max = state.max_brightness if state.max_brightness is not None else config.max_brightness

        # Get midpoint for current phase (state.brightness_mid applies to current phase only)
        default_mid = config.wake_time if in_ascend else config.bed_time
        mid = state.brightness_mid if state.brightness_mid is not None else default_mid
        if in_ascend:
            mid48 = CircadianLight.lift_midpoint_to_phase(mid, t_ascend, t_descend)
        else:
            descend_end = t_ascend + 24
            mid48 = CircadianLight.lift_midpoint_to_phase(mid, t_descend, descend_end)

        # Calculate normalized value
        b_min_norm = b_min / 100.0
        b_max_norm = b_max / 100.0

        if in_ascend:
            value = logistic(h48, mid48, slope, b_min_norm, b_max_norm)
        else:
            calc_h = h48 + 24 if h48 < t_descend else h48
            value = logistic(calc_h, mid48, slope, b_min_norm, b_max_norm)

        return int(max(b_min, min(b_max, round(value * 100))))

    @staticmethod
    def calculate_color_at_hour(
        hour: float,
        config: Config,
        state: AreaState,
        apply_solar_rules: bool = True,
        sun_times: Optional[SunTimes] = None
    ) -> int:
        """Calculate color temperature at a specific hour.

        Args:
            hour: Hour (0-24)
            config: Global configuration
            state: Area runtime state
            apply_solar_rules: Whether to apply warm night/cool day rules
            sun_times: Sun position times for solar rules (if None, uses defaults)

        Returns:
            Color temperature in Kelvin
        """
        in_ascend, h48, t_ascend, t_descend, slope = CircadianLight.get_phase_info(hour, config)

        # Effective bounds
        c_min = state.min_color_temp if state.min_color_temp is not None else config.min_color_temp
        c_max = state.max_color_temp if state.max_color_temp is not None else config.max_color_temp

        # Get midpoint for current phase (state.color_mid applies to current phase only)
        default_mid = config.wake_time if in_ascend else config.bed_time
        mid = state.color_mid if state.color_mid is not None else default_mid
        if in_ascend:
            mid48 = CircadianLight.lift_midpoint_to_phase(mid, t_ascend, t_descend)
        else:
            descend_end = t_ascend + 24
            mid48 = CircadianLight.lift_midpoint_to_phase(mid, t_descend, descend_end)

        # Calculate normalized value (0 to 1)
        if in_ascend:
            norm = logistic(h48, mid48, slope, 0, 1)
        else:
            calc_h = h48 + 24 if h48 < t_descend else h48
            norm = logistic(calc_h, mid48, slope, 0, 1)

        kelvin = c_min + (c_max - c_min) * norm

        # Apply solar rules if enabled
        if apply_solar_rules:
            kelvin = CircadianLight._apply_solar_rules(kelvin, hour, config, state, sun_times)

        return int(max(c_min, min(c_max, round(kelvin))))

    @staticmethod
    def _wrap24(hour: float) -> float:
        """Wrap hour to 0-24 range."""
        return hour % 24

    @staticmethod
    def _get_window_weight(
        hour: float,
        window_start: float,
        window_end: float,
        fade_hrs: float
    ) -> Tuple[bool, float]:
        """Calculate if hour is in window and the fade weight.

        Args:
            hour: Hour to check (0-24)
            window_start: Window start hour
            window_end: Window end hour
            fade_hrs: Fade duration in hours

        Returns:
            Tuple of (in_window, weight)
        """
        h = CircadianLight._wrap24(hour)
        in_window = False
        dist_from_start = 0.0
        dist_to_end = 0.0

        if window_start > window_end:
            # Wraps around midnight
            in_window = h >= window_start or h <= window_end
            if in_window:
                dist_from_start = (h - window_start) if h >= window_start else (h + 24 - window_start)
                dist_to_end = (window_end - h) if h <= window_end else (window_end + 24 - h)
        else:
            # Normal range
            in_window = h >= window_start and h <= window_end
            if in_window:
                dist_from_start = h - window_start
                dist_to_end = window_end - h

        if not in_window:
            return (False, 0.0)

        # Calculate fade weight
        weight = 1.0
        if fade_hrs > 0.01:
            if dist_from_start < fade_hrs:
                weight = min(weight, dist_from_start / fade_hrs)
            if dist_to_end < fade_hrs:
                weight = min(weight, dist_to_end / fade_hrs)

        return (True, weight)

    @staticmethod
    def _apply_solar_rules(
        kelvin: float,
        hour: float,
        config: Config,
        state: AreaState,
        sun_times: Optional[SunTimes] = None
    ) -> float:
        """Apply warm night and cool day solar rules with window + fade.

        Args:
            kelvin: Base color temperature from curve
            hour: Current hour
            config: Global configuration
            state: Area runtime state
            sun_times: Sun position times (if None, uses defaults)

        Returns:
            Modified color temperature
        """
        if sun_times is None:
            sun_times = SunTimes()  # Use defaults

        sunrise = sun_times.sunrise
        sunset = sun_times.sunset
        solar_noon = sun_times.solar_noon
        solar_mid = sun_times.solar_mid
        wrap24 = CircadianLight._wrap24

        # Warm at night - ceiling
        if config.warm_night_enabled:
            warm_target = state.solar_rule_color_limit if state.solar_rule_color_limit is not None else config.warm_night_target

            if kelvin > warm_target:
                fade_hrs = config.warm_night_fade / 60.0
                start_offset_hrs = config.warm_night_start / 60.0
                end_offset_hrs = config.warm_night_end / 60.0
                mode = config.warm_night_mode

                # Determine window based on mode
                if mode == "sunrise":
                    window_start = wrap24(solar_mid)
                    window_end = wrap24(sunrise + end_offset_hrs)
                elif mode == "sunset":
                    window_start = wrap24(sunset + start_offset_hrs)
                    window_end = wrap24(solar_mid)
                else:  # "all"
                    window_start = wrap24(sunset + start_offset_hrs)
                    window_end = wrap24(sunrise + end_offset_hrs)

                in_window, weight = CircadianLight._get_window_weight(hour, window_start, window_end, fade_hrs)
                if in_window and weight > 0:
                    kelvin = kelvin + (warm_target - kelvin) * weight

        # Cool during day - floor
        if config.cool_day_enabled:
            cool_target = state.solar_rule_color_limit if state.solar_rule_color_limit is not None else config.cool_day_target

            if kelvin < cool_target:
                fade_hrs = config.cool_day_fade / 60.0
                start_offset_hrs = config.cool_day_start / 60.0
                end_offset_hrs = config.cool_day_end / 60.0
                mode = config.cool_day_mode

                # Determine window based on mode
                if mode == "sunrise":
                    window_start = wrap24(sunrise + start_offset_hrs)
                    window_end = wrap24(solar_noon)
                elif mode == "sunset":
                    window_start = wrap24(solar_noon)
                    window_end = wrap24(sunset + end_offset_hrs)
                else:  # "all"
                    window_start = wrap24(sunrise + start_offset_hrs)
                    window_end = wrap24(sunset + end_offset_hrs)

                in_window, weight = CircadianLight._get_window_weight(hour, window_start, window_end, fade_hrs)
                if in_window and weight > 0:
                    kelvin = kelvin + (cool_target - kelvin) * weight

        return kelvin

    @staticmethod
    def calculate_lighting(
        hour: float,
        config: Config,
        state: AreaState
    ) -> LightingResult:
        """Calculate full lighting values at a specific hour.

        Args:
            hour: Hour (0-24)
            config: Global configuration
            state: Area runtime state

        Returns:
            LightingResult with brightness, color_temp, rgb, xy, phase
        """
        in_ascend, _, _, _, _ = CircadianLight.get_phase_info(hour, config)

        brightness = CircadianLight.calculate_brightness_at_hour(hour, config, state)
        color_temp = CircadianLight.calculate_color_at_hour(hour, config, state)
        rgb = CircadianLight.color_temperature_to_rgb(color_temp)
        xy = CircadianLight.color_temperature_to_xy(color_temp)

        return LightingResult(
            brightness=brightness,
            color_temp=color_temp,
            rgb=rgb,
            xy=xy,
            phase="ascend" if in_ascend else "descend"
        )

    # ---------------------------------------------------------------------------
    # Step calculations (brightness-primary algorithm)
    # ---------------------------------------------------------------------------

    @staticmethod
    def calculate_step(
        hour: float,
        direction: str,  # "up" or "down"
        config: Config,
        state: AreaState,
        brightness_locked: bool = False,
        color_locked: bool = False
    ) -> Optional[StepResult]:
        """Calculate step up/down using brightness-primary algorithm.

        Step moves both brightness and color along the diverged curve.
        When at config bounds, pushes proportionally toward absolute limits.

        Args:
            hour: Current hour (0-24)
            direction: "up" (brighter/cooler) or "down" (dimmer/warmer)
            config: Global configuration
            state: Area runtime state
            brightness_locked: If True, can't push brightness bounds
            color_locked: If True, can't push color bounds

        Returns:
            StepResult with new values and state updates, or None if at limit
        """
        in_ascend, h48, t_ascend, t_descend, slope = CircadianLight.get_phase_info(hour, config)
        sign = 1 if direction == "up" else -1
        steps = config.step_increments or config.max_dim_steps or 10

        # Config bounds
        config_min_bri = config.min_brightness
        config_max_bri = config.max_brightness
        config_min_cct = config.min_color_temp
        config_max_cct = config.max_color_temp

        # Runtime bounds
        b_min = state.min_brightness if state.min_brightness is not None else config_min_bri
        b_max = state.max_brightness if state.max_brightness is not None else config_max_bri
        c_min = state.min_color_temp if state.min_color_temp is not None else config_min_cct
        c_max = state.max_color_temp if state.max_color_temp is not None else config_max_cct

        # Step size based on config range
        bri_step = (config_max_bri - config_min_bri) / steps

        # Current values
        current_bri = CircadianLight.calculate_brightness_at_hour(hour, config, state)
        current_cct = CircadianLight.calculate_color_at_hour(hour, config, state, apply_solar_rules=True)

        # Calculate target brightness
        target_bri_initial = current_bri + (1 if direction == "up" else -1) * bri_step

        # Check if CURRENTLY at config bounds (within 0.5%)
        # Note: we only push when AT the bound, not when step would overshoot
        at_config_max = direction == "up" and current_bri >= b_max - 0.5
        at_config_min = direction == "down" and current_bri <= b_min + 0.5

        # Check if at absolute limits
        at_absolute_max = current_bri >= ABSOLUTE_MAX_BRI - 0.5
        at_absolute_min = current_bri <= ABSOLUTE_MIN_BRI + 0.5

        if (direction == "up" and at_absolute_max) or (direction == "down" and at_absolute_min):
            return None  # At absolute limit

        if (at_config_max or at_config_min) and brightness_locked:
            return None  # At config bound and locked

        state_updates: Dict[str, Any] = {}
        target_bri: float
        target_cct: float

        # Check if we have headroom to push bounds
        bri_absolute_limit = ABSOLUTE_MAX_BRI if direction == "up" else ABSOLUTE_MIN_BRI
        bri_current_bound = b_max if direction == "up" else b_min
        bri_headroom = abs(bri_absolute_limit - bri_current_bound)

        # Only enter pushing mode if:
        # 1. We're at the config bound (at_config_max/min)
        # 2. There's room to push (headroom > 0.5)
        can_push = bri_headroom > 0.5
        use_pushing_mode = (at_config_max or at_config_min) and can_push

        if use_pushing_mode:
            # === PUSHING BEYOND CONFIG BOUNDS ===
            bri_push_amount = min(bri_step, bri_headroom)
            push_percent = bri_push_amount / bri_headroom if bri_headroom > 0 else 0

            # Push brightness
            if direction == "up":
                target_bri = b_max + bri_push_amount
                state_updates["max_brightness"] = min(ABSOLUTE_MAX_BRI, int(target_bri))
            else:
                target_bri = b_min - bri_push_amount
                state_updates["min_brightness"] = max(ABSOLUTE_MIN_BRI, int(target_bri))

            # Push color proportionally
            cct_absolute_limit = ABSOLUTE_MAX_CCT if direction == "up" else ABSOLUTE_MIN_CCT
            cct_headroom = abs(cct_absolute_limit - current_cct)
            cct_push_amount = push_percent * cct_headroom

            if direction == "up":
                target_cct = current_cct + cct_push_amount
                if target_cct > c_max and not color_locked:
                    state_updates["max_color_temp"] = min(ABSOLUTE_MAX_CCT, int(target_cct))
                # Push through warm night ceiling
                if config.warm_night_enabled:
                    warm_ceiling = state.solar_rule_color_limit if state.solar_rule_color_limit is not None else config.warm_night_target
                    if target_cct > warm_ceiling:
                        state_updates["solar_rule_color_limit"] = min(ABSOLUTE_MAX_CCT, int(target_cct))
            else:
                target_cct = current_cct - cct_push_amount
                if target_cct < c_min and not color_locked:
                    state_updates["min_color_temp"] = max(ABSOLUTE_MIN_CCT, int(target_cct))
                # Push through cool day floor
                if config.cool_day_enabled:
                    cool_floor = state.solar_rule_color_limit if state.solar_rule_color_limit is not None else config.cool_day_target
                    if target_cct < cool_floor:
                        state_updates["solar_rule_color_limit"] = max(ABSOLUTE_MIN_CCT, int(target_cct))

            # When pushing bounds, return immediately with new bounds - don't update midpoints
            rgb = CircadianLight.color_temperature_to_rgb(int(target_cct))
            xy = CircadianLight.color_temperature_to_xy(int(target_cct))
            return StepResult(
                brightness=int(target_bri),
                color_temp=int(target_cct),
                rgb=rgb,
                xy=xy,
                state_updates=state_updates
            )

        else:
            # === WITHIN BOUNDS - TRAVERSE DIVERGED CURVE ===
            target_bri = current_bri + sign * bri_step

            # Clamp target to absolute limits (instead of returning None)
            # This allows stepping to the limit even if the step size overshoots
            target_bri = max(ABSOLUTE_MIN_BRI, min(ABSOLUTE_MAX_BRI, target_bri))

            # If already at the limit and trying to go further, return None
            if direction == "down" and current_bri <= ABSOLUTE_MIN_BRI + 0.5 and target_bri <= ABSOLUTE_MIN_BRI:
                return None  # Already at absolute minimum
            if direction == "up" and current_bri >= ABSOLUTE_MAX_BRI - 0.5 and target_bri >= ABSOLUTE_MAX_BRI:
                return None  # Already at absolute maximum

            # Get midpoints (state midpoints apply to current phase only)
            default_mid = config.wake_time if in_ascend else config.bed_time
            bri_mid = state.brightness_mid if state.brightness_mid is not None else default_mid
            color_mid = state.color_mid if state.color_mid is not None else default_mid

            # Lift midpoints into 48h space
            if in_ascend:
                bri_mid48 = CircadianLight.lift_midpoint_to_phase(bri_mid, t_ascend, t_descend)
                color_mid48 = CircadianLight.lift_midpoint_to_phase(color_mid, t_ascend, t_descend)
            else:
                descend_end = t_ascend + 24
                bri_mid48 = CircadianLight.lift_midpoint_to_phase(bri_mid, t_descend, descend_end)
                color_mid48 = CircadianLight.lift_midpoint_to_phase(color_mid, t_descend, descend_end)

            # Find virtual time where brightness = target
            b_min_norm = b_min / 100.0
            b_max_norm = b_max / 100.0
            target_bri_norm = max(b_min_norm + 0.001, min(b_max_norm - 0.001, target_bri / 100.0))
            bri_ratio = (target_bri_norm - b_min_norm) / (b_max_norm - b_min_norm)

            try:
                virtual_time = bri_mid48 + math.log(bri_ratio / (1 - bri_ratio)) / slope
            except (ValueError, ZeroDivisionError):
                virtual_time = h48

            # Get color at virtual time from color curve
            if in_ascend:
                color_norm = logistic(virtual_time, color_mid48, slope, 0, 1)
            else:
                vt_descend = virtual_time + 24 if virtual_time < t_descend else virtual_time
                color_norm = logistic(vt_descend, color_mid48, slope, 0, 1)

            target_cct = c_min + (c_max - c_min) * color_norm

            # Apply solar rules to target color (warm_night ceiling, cool_day floor)
            target_cct = CircadianLight._apply_solar_rules(target_cct, hour, config, state)

        # Clamp to effective bounds
        effective_bri_min = state_updates.get("min_brightness", state.min_brightness if state.min_brightness is not None else config_min_bri)
        effective_bri_max = state_updates.get("max_brightness", state.max_brightness if state.max_brightness is not None else config_max_bri)
        effective_cct_min = state_updates.get("min_color_temp", state.min_color_temp if state.min_color_temp is not None else config_min_cct)
        effective_cct_max = state_updates.get("max_color_temp", state.max_color_temp if state.max_color_temp is not None else config_max_cct)

        target_bri = max(effective_bri_min, min(effective_bri_max, target_bri))
        target_cct = max(effective_cct_min, min(effective_cct_max, target_cct))

        # Adjust midpoints so current time gives target values
        b_min_norm = effective_bri_min / 100.0
        b_max_norm = effective_bri_max / 100.0
        target_bri_norm = target_bri / 100.0
        target_cct_norm = (target_cct - effective_cct_min) / (effective_cct_max - effective_cct_min)

        calc_time = h48
        if not in_ascend and h48 < t_descend:
            calc_time = h48 + 24

        new_bri_mid = inverse_midpoint(calc_time, target_bri_norm, slope, b_min_norm, b_max_norm)
        new_color_mid = inverse_midpoint(calc_time, target_cct_norm, slope, 0, 1)

        # Wrap back to 0-24
        new_bri_mid = new_bri_mid % 24
        new_color_mid = new_color_mid % 24

        state_updates["brightness_mid"] = new_bri_mid
        state_updates["color_mid"] = new_color_mid

        rgb = CircadianLight.color_temperature_to_rgb(int(target_cct))
        xy = CircadianLight.color_temperature_to_xy(int(target_cct))

        return StepResult(
            brightness=int(target_bri),
            color_temp=int(target_cct),
            rgb=rgb,
            xy=xy,
            state_updates=state_updates
        )

    @staticmethod
    def calculate_bright_step(
        hour: float,
        direction: str,  # "up" or "down"
        config: Config,
        state: AreaState,
        brightness_locked: bool = False
    ) -> Optional[StepResult]:
        """Calculate brightness-only step.

        Adjusts brightness midpoint only, color follows curve unchanged.

        Args:
            hour: Current hour (0-24)
            direction: "up" or "down"
            config: Global configuration
            state: Area runtime state
            brightness_locked: If True, can't push brightness bounds

        Returns:
            StepResult with new values and state updates, or None if at limit
        """
        in_ascend, h48, t_ascend, t_descend, slope = CircadianLight.get_phase_info(hour, config)
        sign = 1 if direction == "up" else -1
        steps = config.brightness_increments or config.max_dim_steps or 10

        # Bounds
        b_min = state.min_brightness if state.min_brightness is not None else config.min_brightness
        b_max = state.max_brightness if state.max_brightness is not None else config.max_brightness
        bri_step = (config.max_brightness - config.min_brightness) / steps

        current_bri = CircadianLight.calculate_brightness_at_hour(hour, config, state)
        target_bri = current_bri + sign * bri_step

        state_updates: Dict[str, Any] = {}

        # Check bounds
        if direction == "up" and current_bri >= b_max - 0.5:
            if b_max >= ABSOLUTE_MAX_BRI - 0.5 or brightness_locked:
                return None
            new_max = min(ABSOLUTE_MAX_BRI, b_max + bri_step)
            state_updates["max_brightness"] = int(new_max)
            target_bri = new_max
        elif direction == "down" and current_bri <= b_min + 0.5:
            if b_min <= ABSOLUTE_MIN_BRI + 0.5 or brightness_locked:
                return None
            new_min = max(ABSOLUTE_MIN_BRI, b_min - bri_step)
            state_updates["min_brightness"] = int(new_min)
            target_bri = new_min

        # Effective bounds
        effective_min = state_updates.get("min_brightness", b_min)
        effective_max = state_updates.get("max_brightness", b_max)
        target_bri = max(effective_min, min(effective_max, target_bri))

        # Calculate new midpoint
        b_min_norm = effective_min / 100.0
        b_max_norm = effective_max / 100.0
        target_norm = target_bri / 100.0

        calc_time = h48
        if not in_ascend and h48 < t_descend:
            calc_time = h48 + 24

        new_mid = inverse_midpoint(calc_time, target_norm, slope, b_min_norm, b_max_norm)
        new_mid = new_mid % 24

        state_updates["brightness_mid"] = new_mid

        # Color stays unchanged - recalculate at current hour
        color_temp = CircadianLight.calculate_color_at_hour(hour, config, state)
        rgb = CircadianLight.color_temperature_to_rgb(color_temp)
        xy = CircadianLight.color_temperature_to_xy(color_temp)

        return StepResult(
            brightness=int(target_bri),
            color_temp=color_temp,
            rgb=rgb,
            xy=xy,
            state_updates=state_updates
        )

    @staticmethod
    def calculate_color_step(
        hour: float,
        direction: str,  # "up" or "down"
        config: Config,
        state: AreaState,
        color_locked: bool = False,
        warm_night_locked: bool = False,
        cool_day_locked: bool = False
    ) -> Optional[StepResult]:
        """Calculate color-only step.

        Adjusts color midpoint only, brightness stays unchanged.

        Args:
            hour: Current hour (0-24)
            direction: "up" (cooler) or "down" (warmer)
            config: Global configuration
            state: Area runtime state
            color_locked: If True, can't push color bounds
            warm_night_locked: If True, can't push warm night ceiling
            cool_day_locked: If True, can't push cool day floor

        Returns:
            StepResult with new values and state updates, or None if at limit
        """
        in_ascend, h48, t_ascend, t_descend, slope = CircadianLight.get_phase_info(hour, config)
        sign = 1 if direction == "up" else -1
        steps = config.color_increments or config.max_dim_steps or 10

        # Bounds
        c_min = state.min_color_temp if state.min_color_temp is not None else config.min_color_temp
        c_max = state.max_color_temp if state.max_color_temp is not None else config.max_color_temp
        cct_step = (config.max_color_temp - config.min_color_temp) / steps

        current_cct = CircadianLight.calculate_color_at_hour(hour, config, state, apply_solar_rules=True)
        target_cct = current_cct + sign * cct_step

        state_updates: Dict[str, Any] = {}

        # Check bounds
        if direction == "up" and current_cct >= c_max - 10:
            if c_max >= ABSOLUTE_MAX_CCT - 10 or color_locked:
                return None
            new_max = min(ABSOLUTE_MAX_CCT, c_max + cct_step)
            state_updates["max_color_temp"] = int(new_max)
            target_cct = new_max
        elif direction == "down" and current_cct <= c_min + 10:
            if c_min <= ABSOLUTE_MIN_CCT + 10 or color_locked:
                return None
            new_min = max(ABSOLUTE_MIN_CCT, c_min - cct_step)
            state_updates["min_color_temp"] = int(new_min)
            target_cct = new_min

        # Effective bounds
        effective_min = state_updates.get("min_color_temp", c_min)
        effective_max = state_updates.get("max_color_temp", c_max)
        target_cct = max(effective_min, min(effective_max, target_cct))

        # Handle solar rule limit (applies to whichever rule is active)
        warm_ceiling = state.solar_rule_color_limit if state.solar_rule_color_limit is not None else config.warm_night_target
        cool_floor = state.solar_rule_color_limit if state.solar_rule_color_limit is not None else config.cool_day_target

        if direction == "up" and config.warm_night_enabled and target_cct > warm_ceiling and not warm_night_locked:
            state_updates["solar_rule_color_limit"] = int(target_cct)

        if direction == "down" and config.cool_day_enabled and target_cct < cool_floor and not cool_day_locked:
            state_updates["solar_rule_color_limit"] = int(target_cct)

        # Calculate new midpoint
        target_norm = (target_cct - effective_min) / (effective_max - effective_min)

        calc_time = h48
        if not in_ascend and h48 < t_descend:
            calc_time = h48 + 24

        new_mid = inverse_midpoint(calc_time, target_norm, slope, 0, 1)
        new_mid = new_mid % 24

        state_updates["color_mid"] = new_mid

        # Brightness stays unchanged
        brightness = CircadianLight.calculate_brightness_at_hour(hour, config, state)
        rgb = CircadianLight.color_temperature_to_rgb(int(target_cct))
        xy = CircadianLight.color_temperature_to_xy(int(target_cct))

        return StepResult(
            brightness=brightness,
            color_temp=int(target_cct),
            rgb=rgb,
            xy=xy,
            state_updates=state_updates
        )

    # ---------------------------------------------------------------------------
    # Color space conversions
    # ---------------------------------------------------------------------------

    @staticmethod
    def color_temperature_to_rgb(kelvin: int) -> Tuple[int, int, int]:
        """Convert color temperature to RGB."""
        x, y = CircadianLight.color_temperature_to_xy(kelvin)

        Y = 1.0
        X = (x * Y) / y if y != 0 else 0
        Z = ((1 - x - y) * Y) / y if y != 0 else 0

        r = 3.2404542 * X - 1.5371385 * Y - 0.4985314 * Z
        g = -0.9692660 * X + 1.8760108 * Y + 0.0415560 * Z
        b = 0.0556434 * X - 0.2040259 * Y + 1.0572252 * Z

        r = max(0, r)
        g = max(0, g)
        b = max(0, b)

        max_val = max(r, g, b)
        if max_val > 1:
            r /= max_val
            g /= max_val
            b /= max_val

        def linear_to_srgb(c):
            return 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1/2.4)) - 0.055

        r = linear_to_srgb(r)
        g = linear_to_srgb(g)
        b = linear_to_srgb(b)

        return (
            int(max(0, min(255, round(r * 255)))),
            int(max(0, min(255, round(g * 255)))),
            int(max(0, min(255, round(b * 255)))),
        )

    @staticmethod
    def color_temperature_to_xy(cct: float) -> Tuple[float, float]:
        """Convert color temperature to CIE 1931 x,y coordinates."""
        T = max(1000, min(cct, 25000))
        invT = 1000.0 / T

        if T <= 4000:
            x = (-0.2661239 * invT**3
                 - 0.2343589 * invT**2
                 + 0.8776956 * invT
                 + 0.179910)
        else:
            x = (-3.0258469 * invT**3
                 + 2.1070379 * invT**2
                 + 0.2226347 * invT
                 + 0.240390)

        if T <= 2222:
            y = (-1.1063814 * x**3
                 - 1.34811020 * x**2
                 + 2.18555832 * x
                 - 0.20219683)
        elif T <= 4000:
            y = (-0.9549476 * x**3
                 - 1.37418593 * x**2
                 + 2.09137015 * x
                 - 0.16748867)
        else:
            y = (3.0817580 * x**3
                 - 5.87338670 * x**2
                 + 3.75112997 * x
                 - 0.37001483)

        return (x, y)


# ---------------------------------------------------------------------------
# Convenience function for current time calculations
# ---------------------------------------------------------------------------

def get_current_hour() -> float:
    """Get current hour as decimal (0-24)."""
    from datetime import datetime
    now = datetime.now()
    return now.hour + now.minute / 60 + now.second / 3600


# ---------------------------------------------------------------------------
# Backwards compatibility aliases (deprecated - use CircadianLight directly)
# ---------------------------------------------------------------------------

# Deprecated alias - use CircadianLight
AdaptiveLighting = CircadianLight

# Activity presets (simplified for backwards compatibility)
ACTIVITY_PRESETS = {
    "young": {"bed_time": 18.0, "wake_time": 6.0},
    "adult": {"bed_time": 22.0, "wake_time": 6.0},
    "nightowl": {"bed_time": 2.0, "wake_time": 10.0},
    "duskbat": {"bed_time": 6.0, "wake_time": 14.0},
    "shiftearly": {"bed_time": 10.0, "wake_time": 18.0},
    "shiftlate": {"bed_time": 14.0, "wake_time": 22.0},
    "custom": {},
}


def get_preset_names():
    """Get list of preset names."""
    return list(ACTIVITY_PRESETS.keys())


def apply_activity_preset(preset_name: str, config: dict) -> dict:
    """Apply an activity preset to a config dict."""
    preset = ACTIVITY_PRESETS.get(preset_name, {})
    config.update(preset)
    return config


def get_circadian_lighting(
    current_time=None,
    **kwargs
) -> Dict[str, Any]:
    """Get circadian lighting values for a given time.

    Returns dict with brightness, kelvin, rgb, xy keys.
    """
    from datetime import datetime

    if current_time is None:
        hour = get_current_hour()
    elif isinstance(current_time, datetime):
        hour = current_time.hour + current_time.minute / 60 + current_time.second / 3600
    else:
        hour = float(current_time)

    config = Config.from_dict(kwargs)
    area_state = AreaState()  # Default state

    result = CircadianLight.calculate_lighting(hour, config, area_state)

    return {
        "brightness": result.brightness,
        "kelvin": result.color_temp,
        "rgb": result.rgb,
        "xy": result.xy,
        "phase": result.phase,
    }


# Deprecated alias - use get_circadian_lighting
get_adaptive_lighting = get_circadian_lighting


def calculate_dimming_step(
    current_time=None,
    action: str = "brighten",
    max_steps: int = DEFAULT_MAX_DIM_STEPS,
    **kwargs
) -> Dict[str, Any]:
    """Backwards compatibility wrapper for step calculations."""
    from datetime import datetime

    if current_time is None:
        hour = get_current_hour()
    elif isinstance(current_time, datetime):
        hour = current_time.hour + current_time.minute / 60 + current_time.second / 3600
    else:
        hour = float(current_time)

    config = Config.from_dict(kwargs)
    config.max_dim_steps = max_steps
    area_state = AreaState()

    direction = "up" if action == "brighten" else "down"
    result = CircadianLight.calculate_step(hour, direction, config, area_state)

    if result is None:
        # At limit
        current = CircadianLight.calculate_lighting(hour, config, area_state)
        return {
            "brightness": current.brightness,
            "kelvin": current.color_temp,
            "time_offset_minutes": 0,
            "at_limit": True,
        }

    return {
        "brightness": result.brightness,
        "kelvin": result.color_temp,
        "time_offset_minutes": 0,  # New system doesn't use time offsets
        "at_limit": False,
    }


def calculate_sun_times(lat: float, lon: float, date_str: str = None) -> Dict[str, Any]:
    """Calculate sun times for a location."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from astral import LocationInfo
    from astral.sun import sun

    if date_str:
        date = datetime.strptime(date_str, "%Y-%m-%d").date()
    else:
        date = datetime.now().date()

    loc = LocationInfo(latitude=lat, longitude=lon)
    solar = sun(loc.observer, date=date)

    return {
        "sunrise": solar["sunrise"].isoformat() if solar.get("sunrise") else None,
        "sunset": solar["sunset"].isoformat() if solar.get("sunset") else None,
        "noon": solar["noon"].isoformat() if solar.get("noon") else None,
    }
