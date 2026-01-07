#!/usr/bin/env python3
"""Brain module for adaptive lighting – Circadian Light by HomeGlo.

Key updates (ascend/descend model)
----------------------------------
* Renamed terminology: rise/fall → ascend/descend
* New timing model: ascend_start, descend_start, wake_time, bed_time
* 48-hour unwrapping for cross-midnight schedule handling
* Separate brightness and color midpoints (no mirroring)
* Speed-to-slope mapping (1-10 scale)
* Activity presets support
"""

from __future__ import annotations

import math
import os
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple, Any
from enum import Enum

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError  # stdlib ≥3.9
from astral import LocationInfo
from astral.sun import sun, elevation as solar_elevation

logger = logging.getLogger(__name__)

class ColorMode(Enum):
    """Color mode for light control."""
    KELVIN = "kelvin"           # Use Kelvin color temperature
    RGB = "rgb"                 # Use RGB values
    XY = "xy"                   # Use CIE xy coordinates

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Default color temperature range (Kelvin)
DEFAULT_MIN_COLOR_TEMP = int(os.getenv("MIN_COLOR_TEMP", "500"))  # Warm white (candle-like)
DEFAULT_MAX_COLOR_TEMP = int(os.getenv("MAX_COLOR_TEMP", "6500"))  # Cool daylight

# Default brightness range (percentage)
DEFAULT_MIN_BRIGHTNESS = int(os.getenv("MIN_BRIGHTNESS", "1"))
DEFAULT_MAX_BRIGHTNESS = int(os.getenv("MAX_BRIGHTNESS", "100"))

# Default dimming steps (for arc-based dimming)
DEFAULT_MAX_DIM_STEPS = int(os.getenv("MAX_DIM_STEPS", "10"))

# Ascend/Descend timing parameters (hours, 0-24)
DEFAULT_ASCEND_START = 3.0      # When ascend phase begins (3am default)
DEFAULT_DESCEND_START = 12.0    # When descend phase begins (solar noon default)
DEFAULT_WAKE_TIME = 6.0         # Brightness midpoint during ascend (6am default)
DEFAULT_BED_TIME = 22.0         # Brightness midpoint during descend (10pm default)

# Speed parameters (1-10 scale)
DEFAULT_WAKE_SPEED = 8          # Ascend curve steepness (fast)
DEFAULT_BED_SPEED = 6           # Descend curve steepness (crisp)

# Speed-to-slope mapping (index 0-10, where 0 is unused)
# From llm_access.html line 2356
SPEED_TO_SLOPE = [0.0, 0.4, 0.6, 0.8, 1.0, 1.3, 1.7, 2.3, 3.0, 4.0, 5.5]

# Activity presets
ACTIVITY_PRESETS = {
    "young": {
        "wake_time": 6.0,
        "bed_time": 18.0,
        "ascend_start": 0.0,    # solar midnight
        "descend_start": 12.0,  # solar noon
    },
    "adult": {
        "wake_time": 6.0,
        "bed_time": 22.0,
        "ascend_start": 4.0,
        "descend_start": 12.0,
    },
    "nightowl": {
        "wake_time": 10.0,
        "bed_time": 2.0,
        "ascend_start": 8.0,
        "descend_start": 16.0,
    },
    "duskbat": {
        "wake_time": 14.0,
        "bed_time": 6.0,
        "ascend_start": 12.0,
        "descend_start": 20.0,
    },
    "shiftearly": {
        "wake_time": 18.0,
        "bed_time": 10.0,
        "ascend_start": 16.0,
        "descend_start": 0.0,
    },
    "shiftlate": {
        "wake_time": 22.0,
        "bed_time": 14.0,
        "ascend_start": 20.0,
        "descend_start": 4.0,
    },
}

# ---------------------------------------------------------------------------
# Adaptive-lighting math (ascend/descend model)
# ---------------------------------------------------------------------------

class AdaptiveLighting:
    """Calculate adaptive lighting values based on ascend/descend model."""

    def __init__(
        self,
        *,
        min_color_temp: int = DEFAULT_MIN_COLOR_TEMP,
        max_color_temp: int = DEFAULT_MAX_COLOR_TEMP,
        min_brightness: int = DEFAULT_MIN_BRIGHTNESS,
        max_brightness: int = DEFAULT_MAX_BRIGHTNESS,
        sunrise_time: Optional[datetime] = None,
        sunset_time: Optional[datetime] = None,
        solar_noon: Optional[datetime] = None,
        solar_midnight: Optional[datetime] = None,
        color_mode: ColorMode = ColorMode.KELVIN,
        # Ascend/Descend timing parameters
        ascend_start: float = DEFAULT_ASCEND_START,
        descend_start: float = DEFAULT_DESCEND_START,
        wake_time: float = DEFAULT_WAKE_TIME,
        bed_time: float = DEFAULT_BED_TIME,
        wake_speed: int = DEFAULT_WAKE_SPEED,
        bed_speed: int = DEFAULT_BED_SPEED,
        # Runtime midpoints (can diverge from wake_time/bed_time via cursor controls)
        brightness_wake_mid: Optional[float] = None,
        brightness_bed_mid: Optional[float] = None,
        color_wake_mid: Optional[float] = None,
        color_bed_mid: Optional[float] = None,
    ) -> None:
        self.min_color_temp = min_color_temp
        self.max_color_temp = max_color_temp
        self.min_brightness = min_brightness
        self.max_brightness = max_brightness
        self.sunrise_time = sunrise_time
        self.sunset_time = sunset_time
        self.solar_noon = solar_noon
        self.solar_midnight = solar_midnight
        self.color_mode = color_mode

        # Ascend/Descend timing
        self.ascend_start = ascend_start
        self.descend_start = descend_start
        self.wake_time = wake_time
        self.bed_time = bed_time

        # Convert speed (1-10) to slope
        self.wake_speed = max(1, min(10, wake_speed))
        self.bed_speed = max(1, min(10, bed_speed))
        self.k_ascend = SPEED_TO_SLOPE[self.wake_speed]
        self.k_descend = SPEED_TO_SLOPE[self.bed_speed]

        # Runtime midpoints (default to base wake/bed times)
        self.brightness_wake_mid = brightness_wake_mid if brightness_wake_mid is not None else wake_time
        self.brightness_bed_mid = brightness_bed_mid if brightness_bed_mid is not None else bed_time
        self.color_wake_mid = color_wake_mid if color_wake_mid is not None else wake_time
        self.color_bed_mid = color_bed_mid if color_bed_mid is not None else bed_time

    def calculate_sun_position(self, now: datetime, elev_deg: float) -> float:
        """Calculate sun position using time-based cosine wave.

        Returns -1 (midnight) to +1 (solar noon).
        """
        if self.solar_noon:
            hours_from_noon = (now - self.solar_noon).total_seconds() / 3600
            solar_hour = (hours_from_noon + 12) % 24
            return -math.cos(2 * math.pi * solar_hour / 24)

        hour = now.hour + now.minute / 60
        return -math.cos(2 * math.pi * hour / 24)

    def get_clock_hour(self, now: datetime) -> float:
        """Get the current clock hour (0-24)."""
        return now.hour + now.minute / 60 + now.second / 3600

    @staticmethod
    def logistic_value(x: float, midpoint: float, slope: float, y0: float, y1: float) -> float:
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
            # Handle extreme values
            if slope * (x - midpoint) > 0:
                return y1
            else:
                return y0

    def _get_normalized_phases(self) -> Tuple[float, float]:
        """Get ascend_start and descend_start normalized for cross-midnight.

        Returns (ascend_start, descend_start) where descend_start > ascend_start.
        """
        ascend_start = self.ascend_start
        descend_start = self.descend_start

        # Handle cross-midnight patterns
        if descend_start <= ascend_start:
            descend_start += 24

        return ascend_start, descend_start

    def _unwrap_hour_48(self, hour: float, ascend_start: float) -> float:
        """Unwrap hour into 48-hour continuous space.

        This handles cross-midnight schedules by lifting hours before ascend_start
        into the 24-48 range.
        """
        if hour < ascend_start:
            return hour + 24
        return hour

    def _lift_midpoint_to_phase(self, midpoint: float, phase_start: float, phase_end: float) -> float:
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

    def is_in_ascend_phase(self, hour: float) -> bool:
        """Check if the given hour is in the ascend phase."""
        ascend_start, descend_start = self._get_normalized_phases()
        h48 = self._unwrap_hour_48(hour, ascend_start)
        return ascend_start <= h48 < descend_start

    def calculate_brightness(self, now: datetime) -> int:
        """Calculate brightness using ascend/descend curves with 48-hour unwrapping."""
        hour = self.get_clock_hour(now)
        return self.calculate_brightness_at_hour(hour)

    def calculate_brightness_at_hour(self, hour: float) -> int:
        """Calculate brightness at a specific hour.

        Uses 48-hour unwrapping for cross-midnight handling.
        Based on llm_access.html lines 3106-3139.
        """
        ascend_start, descend_start = self._get_normalized_phases()
        h48 = self._unwrap_hour_48(hour, ascend_start)

        b_min = self.min_brightness / 100.0
        b_max = self.max_brightness / 100.0

        in_ascend = ascend_start <= h48 < descend_start

        if in_ascend:
            # Ascend phase: brightness rises
            wake_mid_48 = self._lift_midpoint_to_phase(
                self.brightness_wake_mid, ascend_start, descend_start
            )
            value = self.logistic_value(h48, wake_mid_48, self.k_ascend, b_min, b_max)
        else:
            # Descend phase: brightness falls
            # Descend runs from descend_start to ascend_start + 24
            descend_end = ascend_start + 24
            bed_mid_48 = self._lift_midpoint_to_phase(
                self.brightness_bed_mid, descend_start, descend_end
            )
            # Use negative slope for descending
            value = self.logistic_value(h48, bed_mid_48, -self.k_descend, b_min, b_max)

        brightness = int(max(self.min_brightness, min(self.max_brightness, value * 100)))
        return brightness

    def calculate_color_temperature(self, now: datetime) -> int:
        """Calculate color temperature using ascend/descend curves."""
        hour = self.get_clock_hour(now)
        return self.calculate_color_at_hour(hour)

    def calculate_color_at_hour(self, hour: float) -> int:
        """Calculate color temperature at a specific hour.

        Uses separate color midpoints (can differ from brightness midpoints).
        """
        ascend_start, descend_start = self._get_normalized_phases()
        h48 = self._unwrap_hour_48(hour, ascend_start)

        c_min = self.min_color_temp
        c_max = self.max_color_temp

        in_ascend = ascend_start <= h48 < descend_start

        if in_ascend:
            # Ascend phase: color temp rises (warm to cool)
            color_wake_mid_48 = self._lift_midpoint_to_phase(
                self.color_wake_mid, ascend_start, descend_start
            )
            value = self.logistic_value(h48, color_wake_mid_48, self.k_ascend, c_min, c_max)
        else:
            # Descend phase: color temp falls (cool to warm)
            descend_end = ascend_start + 24
            color_bed_mid_48 = self._lift_midpoint_to_phase(
                self.color_bed_mid, descend_start, descend_end
            )
            value = self.logistic_value(h48, color_bed_mid_48, -self.k_descend, c_min, c_max)

        kelvin = int(max(self.min_color_temp, min(self.max_color_temp, value)))
        return kelvin

    def calculate_step_target(self, now: datetime, action: str = 'brighten',
                            max_steps: int = DEFAULT_MAX_DIM_STEPS,
                            adjust_brightness: bool = True,
                            adjust_color: bool = True) -> Tuple[datetime, Dict[str, Any]]:
        """Calculate target lighting values for step action.

        Args:
            now: Current time
            action: 'brighten'/'step_up' or 'dim'/'step_down'
            max_steps: Maximum number of steps from min to max
            adjust_brightness: Whether to adjust brightness midpoint
            adjust_color: Whether to adjust color midpoint

        Returns:
            Tuple of (target_datetime, lighting_values_dict)
        """
        hour = self.get_clock_hour(now)
        in_ascend = self.is_in_ascend_phase(hour)

        current_brightness = self.calculate_brightness_at_hour(hour)
        current_kelvin = self.calculate_color_at_hour(hour)

        # Calculate step size
        brightness_step = (self.max_brightness - self.min_brightness) / max(1, max_steps)
        color_step = (self.max_color_temp - self.min_color_temp) / max(1, max_steps)

        # Determine direction
        direction = 1 if action in ('brighten', 'step_up') else -1

        # Calculate target values
        target_brightness = current_brightness + (direction * brightness_step) if adjust_brightness else current_brightness
        target_kelvin = current_kelvin + (direction * color_step) if adjust_color else current_kelvin

        # Clamp to valid ranges
        target_brightness = max(self.min_brightness, min(self.max_brightness, target_brightness))
        target_kelvin = max(self.min_color_temp, min(self.max_color_temp, target_kelvin))

        # Update midpoints based on the adjustment
        if adjust_brightness:
            new_brightness_mid = self._solve_midpoint_for_target(
                hour, target_brightness / 100.0,
                self.min_brightness / 100.0, self.max_brightness / 100.0,
                in_ascend, is_brightness=True
            )
            if new_brightness_mid is not None:
                if in_ascend:
                    self.brightness_wake_mid = new_brightness_mid
                else:
                    self.brightness_bed_mid = new_brightness_mid

        if adjust_color:
            new_color_mid = self._solve_midpoint_for_target(
                hour, target_kelvin,
                self.min_color_temp, self.max_color_temp,
                in_ascend, is_brightness=False
            )
            if new_color_mid is not None:
                if in_ascend:
                    self.color_wake_mid = new_color_mid
                else:
                    self.color_bed_mid = new_color_mid

        target_brightness = int(target_brightness)
        target_kelvin = int(target_kelvin)

        rgb = self.color_temperature_to_rgb(target_kelvin)
        xy = self.color_temperature_to_xy(target_kelvin)

        return now, {
            'kelvin': target_kelvin,
            'brightness': target_brightness,
            'rgb': rgb,
            'xy': xy,
            'phase': 'ascend' if in_ascend else 'descend',
            'brightness_wake_mid': self.brightness_wake_mid,
            'brightness_bed_mid': self.brightness_bed_mid,
            'color_wake_mid': self.color_wake_mid,
            'color_bed_mid': self.color_bed_mid,
        }

    def _solve_midpoint_for_target(self, hour: float, target_value: float,
                                   val_min: float, val_max: float,
                                   in_ascend: bool, is_brightness: bool) -> Optional[float]:
        """Solve for the midpoint that produces target_value at the given hour.

        Based on llm_access.html solveMidpointForTarget (lines 2389-2410).
        Uses inverse logistic: midpoint = x + (1/slope) * ln((y1 - target) / (target - y0))
        """
        eps = 1e-6

        # Clamp target to valid range
        target = max(val_min + eps, min(val_max - eps, target_value))

        ascend_start, descend_start = self._get_normalized_phases()
        h48 = self._unwrap_hour_48(hour, ascend_start)

        if in_ascend:
            slope = self.k_ascend
            ratio = (val_max - target) / (target - val_min) if (target - val_min) > eps else 1e10
            if ratio <= eps:
                return None
            try:
                mid = h48 + (1 / slope) * math.log(ratio)
            except (ValueError, ZeroDivisionError):
                return None

            # Normalize to phase window
            while mid < ascend_start:
                mid += 24
            while mid > descend_start:
                mid -= 24
            mid = max(ascend_start + 0.1, min(descend_start - 0.1, mid))
        else:
            slope = -self.k_descend
            ratio = (val_max - target) / (target - val_min) if (target - val_min) > eps else 1e10
            if ratio <= eps:
                return None
            try:
                mid = h48 + (1 / slope) * math.log(ratio)
            except (ValueError, ZeroDivisionError):
                return None

            # Normalize to descend phase window
            descend_end = ascend_start + 24
            while mid < descend_start:
                mid += 24
            while mid > descend_end:
                mid -= 24
            mid = max(descend_start + 0.1, min(descend_end - 0.1, mid))

        # Wrap back to 0-24 range
        return mid % 24

    def reset_midpoints(self) -> None:
        """Reset all runtime midpoints to base wake_time/bed_time values."""
        self.brightness_wake_mid = self.wake_time
        self.brightness_bed_mid = self.bed_time
        self.color_wake_mid = self.wake_time
        self.color_bed_mid = self.bed_time

    # ---------------------------------------------------------------------------
    # Solar Color Rules
    # ---------------------------------------------------------------------------

    def apply_solar_color_rules(
        self,
        kelvin: int,
        now: datetime,
        config: Dict[str, Any]
    ) -> int:
        """Apply solar color rules to a base color temperature.

        Based on llm_access.html lines 2716-2770.

        Args:
            kelvin: Base color temperature from curve calculation
            now: Current datetime
            config: Configuration dict with solar rule settings

        Returns:
            Modified color temperature after applying rules
        """
        result_kelvin = kelvin

        # Apply warm-at-night rule
        if config.get("warm_night_enabled", False):
            result_kelvin = self._apply_warm_night_rule(result_kelvin, now, config)

        # Apply cool-during-day rule
        if config.get("cool_day_enabled", False):
            result_kelvin = self._apply_cool_day_rule(result_kelvin, now, config)

        return int(max(self.min_color_temp, min(self.max_color_temp, result_kelvin)))

    def _apply_warm_night_rule(
        self,
        kelvin: int,
        now: datetime,
        config: Dict[str, Any]
    ) -> float:
        """Apply warm-at-night rule.

        Forces warmer color temperatures around sunset and before sunrise.
        Supports fade transitions for gradual changes.

        Args:
            kelvin: Current color temperature
            now: Current datetime
            config: Configuration with warm_night settings

        Returns:
            Modified color temperature
        """
        if not self.sunrise_time or not self.sunset_time:
            return kelvin

        mode = config.get("warm_night_mode", "all")
        target = config.get("warm_night_target", 2700)
        fade_minutes = config.get("warm_night_fade", 60)

        # Convert offset minutes to timedelta
        sunset_start_offset = config.get("warm_night_sunset_start", -60)  # Before sunset
        sunrise_end_offset = config.get("warm_night_sunrise_end", 60)  # After sunrise

        sunset_start = self.sunset_time + timedelta(minutes=sunset_start_offset)
        sunrise_end = self.sunrise_time + timedelta(minutes=sunrise_end_offset)

        hour = self.get_clock_hour(now)
        sunset_hour = sunset_start.hour + sunset_start.minute / 60
        sunrise_end_hour = sunrise_end.hour + sunrise_end.minute / 60

        # Check if we're in the warm night period
        in_night = False
        fade_factor = 1.0  # Full effect

        if mode in ("all", "sunset"):
            # Sunset fade-in
            fade_start = sunset_hour - fade_minutes / 60
            if hour >= fade_start and hour <= sunset_hour + 2:
                if hour < sunset_hour:
                    # Fading in
                    fade_factor = (hour - fade_start) / (fade_minutes / 60)
                else:
                    fade_factor = 1.0
                in_night = True

        if mode in ("all", "sunrise"):
            # Sunrise period (night continuing until after sunrise)
            fade_end = sunrise_end_hour
            if hour <= fade_end or hour >= 22:  # Late night or early morning
                if hour <= sunrise_end_hour and hour > self.sunrise_time.hour:
                    # Fading out after sunrise
                    sunrise_hour = self.sunrise_time.hour + self.sunrise_time.minute / 60
                    if hour > sunrise_hour:
                        fade_factor = 1.0 - (hour - sunrise_hour) / (fade_minutes / 60)
                        fade_factor = max(0, min(1, fade_factor))
                else:
                    fade_factor = 1.0
                in_night = True

        if in_night and kelvin > target:
            # Blend towards target based on fade factor
            return kelvin - (kelvin - target) * max(0, min(1, fade_factor))

        return kelvin

    def _apply_cool_day_rule(
        self,
        kelvin: int,
        now: datetime,
        config: Dict[str, Any]
    ) -> float:
        """Apply cool-during-day rule.

        Pushes color temperatures cooler during bright daylight hours.

        Args:
            kelvin: Current color temperature
            now: Current datetime
            config: Configuration with cool_day settings

        Returns:
            Modified color temperature
        """
        if not self.sunrise_time or not self.sunset_time:
            return kelvin

        mode = config.get("cool_day_mode", "all")
        target = config.get("cool_day_target", 6500)
        fade_minutes = config.get("cool_day_fade", 60)

        # Convert offset minutes to timedelta
        sunrise_start_offset = config.get("cool_day_sunrise_start", 0)
        sunset_end_offset = config.get("cool_day_sunset_end", 0)

        day_start = self.sunrise_time + timedelta(minutes=sunrise_start_offset)
        day_end = self.sunset_time + timedelta(minutes=sunset_end_offset)

        hour = self.get_clock_hour(now)
        day_start_hour = day_start.hour + day_start.minute / 60
        day_end_hour = day_end.hour + day_end.minute / 60

        # Check if we're in the cool day period
        in_day = False
        fade_factor = 1.0

        if hour >= day_start_hour and hour <= day_end_hour:
            in_day = True

            # Fade in after sunrise
            fade_in_end = day_start_hour + fade_minutes / 60
            if hour < fade_in_end:
                fade_factor = (hour - day_start_hour) / (fade_minutes / 60)

            # Fade out before sunset
            fade_out_start = day_end_hour - fade_minutes / 60
            if hour > fade_out_start:
                fade_factor = (day_end_hour - hour) / (fade_minutes / 60)

            fade_factor = max(0, min(1, fade_factor))

        if in_day and kelvin < target:
            # Blend towards target based on fade factor
            return kelvin + (target - kelvin) * fade_factor

        return kelvin

    # colour-space helpers ----------------------------------------------
    @staticmethod
    def color_temperature_to_rgb(kelvin: int) -> Tuple[int, int, int]:
        """Convert color temperature to RGB using Krystek polynomial approach."""
        x, y = AdaptiveLighting.color_temperature_to_xy(kelvin)

        Y = 1.0
        X = (x * Y) / y if y != 0 else 0
        Z = ((1 - x - y) * Y) / y if y != 0 else 0

        r =  3.2404542 * X - 1.5371385 * Y - 0.4985314 * Z
        g = -0.9692660 * X + 1.8760108 * Y + 0.0415560 * Z
        b =  0.0556434 * X - 0.2040259 * Y + 1.0572252 * Z

        r = max(0, r)
        g = max(0, g)
        b = max(0, b)

        max_val = max(r, g, b)
        if max_val > 1:
            r /= max_val
            g /= max_val
            b /= max_val

        def linear_to_srgb(c):
            if c <= 0.0031308:
                return 12.92 * c
            else:
                return 1.055 * (c ** (1/2.4)) - 0.055

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
        """Convert color temperature to CIE 1931 x,y using Krystek polynomials."""
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

    @staticmethod
    def rgb_to_xy(rgb: Tuple[int, int, int]) -> Tuple[float, float]:
        r, g, b = [c / 255.0 for c in rgb]
        r = ((r + 0.055) / 1.055) ** 2.4 if r > 0.04045 else r / 12.92
        g = ((g + 0.055) / 1.055) ** 2.4 if g > 0.04045 else g / 12.92
        b = ((b + 0.055) / 1.055) ** 2.4 if b > 0.04045 else b / 12.92
        X = r * 0.4124564 + g * 0.3575761 + b * 0.1804375
        Y = r * 0.2126729 + g * 0.7151522 + b * 0.0721750
        Z = r * 0.0193339 + g * 0.1191920 + b * 0.9503041
        if X + Y + Z == 0:
            return (0.0, 0.0)
        x = X / (X + Y + Z)
        y = Y / (X + Y + Z)
        return (x, y)

# ---------------------------------------------------------------------------
# Activity Preset Helper
# ---------------------------------------------------------------------------

def apply_activity_preset(config: Dict[str, Any], preset_name: str) -> Dict[str, Any]:
    """Apply an activity preset to a configuration dict.

    Args:
        config: Existing configuration dict (will be modified in place)
        preset_name: Name of preset ('young', 'adult', 'nightowl', etc.)

    Returns:
        Modified config dict with preset values applied
    """
    if preset_name not in ACTIVITY_PRESETS:
        logger.warning(f"Unknown activity preset: {preset_name}")
        return config

    preset = ACTIVITY_PRESETS[preset_name]

    # Apply preset values
    config["wake_time"] = preset["wake_time"]
    config["bed_time"] = preset["bed_time"]
    config["ascend_start"] = preset["ascend_start"]
    config["descend_start"] = preset["descend_start"]

    # Reset runtime midpoints to match new wake/bed times
    config["brightness_wake_mid"] = preset["wake_time"]
    config["brightness_bed_mid"] = preset["bed_time"]
    config["color_wake_mid"] = preset["wake_time"]
    config["color_bed_mid"] = preset["bed_time"]

    logger.info(f"Applied activity preset '{preset_name}': wake={preset['wake_time']}, bed={preset['bed_time']}")

    return config


def get_preset_names() -> list:
    """Get list of available activity preset names."""
    return list(ACTIVITY_PRESETS.keys())


def get_preset_details(preset_name: str) -> Optional[Dict[str, Any]]:
    """Get details for a specific preset."""
    return ACTIVITY_PRESETS.get(preset_name)


# ---------------------------------------------------------------------------
# Solar calculation helpers
# ---------------------------------------------------------------------------

def calculate_sun_times(latitude: float, longitude: float, date_str: str) -> Dict[str, float]:
    """Calculate sun times for a specific date.

    Pure calculation based on llm_access.html getSunTimes (lines 1746-1757).
    Used for date slider preview without requiring astral library.

    Args:
        latitude: Location latitude
        longitude: Location longitude
        date_str: Date in ISO format (YYYY-MM-DD)

    Returns:
        Dict with 'sunrise', 'sunset', 'solar_noon', 'solar_midnight' as hours (0-24)
    """
    from datetime import date as date_type

    # Parse date
    if isinstance(date_str, str):
        dt = datetime.fromisoformat(date_str)
    else:
        dt = date_str

    # Day of year (1-366)
    year_start = datetime(dt.year, 1, 1)
    n = (dt - year_start).days + 1

    # Julian date adjustment
    J = n + ((longitude + 360) % 360) / 360

    # Mean anomaly
    M = (357.5291 + 0.9856 * J) % 360
    M_rad = math.radians(M)

    # Equation of center
    C = 1.9148 * math.sin(M_rad) + 0.02 * math.sin(2 * M_rad) + 0.0003 * math.sin(3 * M_rad)

    # Ecliptic longitude
    L = (M + 102.9372 + C + 180) % 360
    L_rad = math.radians(L)

    # Solar declination
    D = math.asin(math.sin(L_rad) * math.sin(math.radians(23.44)))

    # Hour angle at sunrise/sunset
    lat_rad = math.radians(latitude)
    try:
        cos_H0 = (math.cos(math.radians(90.833)) - math.sin(lat_rad) * math.sin(D)) / (math.cos(lat_rad) * math.cos(D))
        cos_H0 = max(-1, min(1, cos_H0))  # Clamp for polar regions
        H0 = math.acos(cos_H0)
    except (ValueError, ZeroDivisionError):
        # Polar day/night
        H0 = 0

    # Daylength in hours
    dl = (2 * H0 * 180 / math.pi) / 15

    # Timezone offset (use local timezone)
    tz_offset = -dt.astimezone().utcoffset().total_seconds() / 3600 if dt.tzinfo else 0

    # Solar noon in local time
    sn = 12 + tz_offset - (longitude / 15)

    return {
        'sunrise': (sn - dl / 2) % 24,
        'sunset': (sn + dl / 2) % 24,
        'solar_noon': sn % 24,
        'solar_midnight': (sn + 12) % 24,
    }

# ---------------------------------------------------------------------------
# Helper: resolve lat/lon/tz from HA-style env vars
# ---------------------------------------------------------------------------

def _auto_location(lat: Optional[float], lon: Optional[float], tz: Optional[str]):
    if lat is not None and lon is not None:
        return lat, lon, tz

    try:
        lat = lat or float(os.getenv("HASS_LATITUDE", os.getenv("LATITUDE", "")))
        lon = lon or float(os.getenv("HASS_LONGITUDE", os.getenv("LONGITUDE", "")))
    except ValueError:
        lat = lon = None

    tz = tz or os.getenv("HASS_TIME_ZONE", os.getenv("TZ", "")) or None
    return lat, lon, tz

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def calculate_dimming_step(
    current_time: datetime,
    action: str,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    timezone: Optional[str] = None,
    max_steps: int = DEFAULT_MAX_DIM_STEPS,
    min_color_temp: int = DEFAULT_MIN_COLOR_TEMP,
    max_color_temp: int = DEFAULT_MAX_COLOR_TEMP,
    min_brightness: int = DEFAULT_MIN_BRIGHTNESS,
    max_brightness: int = DEFAULT_MAX_BRIGHTNESS,
    config: Optional[Dict[str, Any]] = None,
    adjust_brightness: bool = True,
    adjust_color: bool = True,
) -> Dict[str, Any]:
    """Calculate the next dimming step along the adaptive curve.

    Args:
        current_time: Current time
        action: 'brighten'/'step_up' or 'dim'/'step_down'
        latitude: Location latitude
        longitude: Location longitude
        timezone: Timezone string
        max_steps: Maximum number of steps in the dimming arc
        min_color_temp: Minimum color temperature in Kelvin
        max_color_temp: Maximum color temperature in Kelvin
        min_brightness: Minimum brightness percentage
        max_brightness: Maximum brightness percentage
        config: Optional configuration dict with curve parameters
        adjust_brightness: Whether to adjust brightness (for bright up/down)
        adjust_color: Whether to adjust color (for color up/down)

    Returns:
        Dict with target lighting values and midpoint info
    """
    latitude, longitude, timezone = _auto_location(latitude, longitude, timezone)
    if latitude is None or longitude is None:
        raise ValueError("Latitude/longitude not provided and not found in env vars")

    try:
        tzinfo = ZoneInfo(timezone) if timezone else None
    except ZoneInfoNotFoundError:
        logger.warning("Unknown timezone '%s' – falling back to system local", timezone)
        tzinfo = None

    now = current_time.astimezone(tzinfo) if tzinfo else current_time

    loc = LocationInfo(latitude=latitude, longitude=longitude, timezone=tzinfo or "UTC")
    observer = loc.observer
    solar_events = sun(observer, date=now.date(), tzinfo=loc.timezone)

    solar_noon = solar_events["noon"]
    solar_midnight = solar_noon - timedelta(hours=12) if solar_noon.hour >= 12 else solar_noon + timedelta(hours=12)

    # Prepare kwargs for AdaptiveLighting
    kwargs = {
        "min_color_temp": min_color_temp,
        "max_color_temp": max_color_temp,
        "min_brightness": min_brightness,
        "max_brightness": max_brightness,
        "sunrise_time": solar_events["sunrise"],
        "sunset_time": solar_events["sunset"],
        "solar_noon": solar_noon,
        "solar_midnight": solar_midnight,
    }

    # Add ascend/descend parameters from config if provided
    if config:
        for key in ["ascend_start", "descend_start", "wake_time", "bed_time",
                    "wake_speed", "bed_speed",
                    "brightness_wake_mid", "brightness_bed_mid",
                    "color_wake_mid", "color_bed_mid"]:
            if key in config:
                kwargs[key] = config[key]

    al = AdaptiveLighting(**kwargs)

    target_time, lighting_values = al.calculate_step_target(
        now, action, max_steps,
        adjust_brightness=adjust_brightness,
        adjust_color=adjust_color
    )

    time_offset_minutes = (target_time - now).total_seconds() / 60

    logger.debug(f"Dimming step: {action} | brightness={lighting_values['brightness']}%, kelvin={lighting_values['kelvin']}K")

    return {
        **lighting_values,
        'time_offset_minutes': time_offset_minutes,
        'target_time': target_time
    }

def get_adaptive_lighting(
    *,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    timezone: Optional[str] = None,
    current_time: Optional[datetime] = None,
    min_color_temp: int = DEFAULT_MIN_COLOR_TEMP,
    max_color_temp: int = DEFAULT_MAX_COLOR_TEMP,
    min_brightness: int = DEFAULT_MIN_BRIGHTNESS,
    max_brightness: int = DEFAULT_MAX_BRIGHTNESS,
    config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Compute adaptive-lighting values using ascend/descend model.

    Args:
        latitude: Location latitude
        longitude: Location longitude
        timezone: Timezone string
        current_time: Time to calculate for (defaults to now)
        min_color_temp: Minimum color temperature in Kelvin
        max_color_temp: Maximum color temperature in Kelvin
        min_brightness: Minimum brightness percentage
        max_brightness: Maximum brightness percentage
        config: Optional dict with curve parameters

    Config can contain:
        ascend_start, descend_start, wake_time, bed_time,
        wake_speed, bed_speed,
        brightness_wake_mid, brightness_bed_mid,
        color_wake_mid, color_bed_mid
    """
    latitude, longitude, timezone = _auto_location(latitude, longitude, timezone)
    if latitude is None or longitude is None:
        raise ValueError("Latitude/longitude not provided and not found in env vars")

    try:
        tzinfo = ZoneInfo(timezone) if timezone else None
    except ZoneInfoNotFoundError:
        logger.warning("Unknown timezone '%s' – falling back to system local", timezone)
        tzinfo = None

    now = current_time.astimezone(tzinfo) if (current_time and tzinfo) else (
        current_time or datetime.now(tzinfo)
    )

    loc = LocationInfo(latitude=latitude, longitude=longitude, timezone=tzinfo or "UTC")
    observer = loc.observer
    solar_events = sun(observer, date=now.date(), tzinfo=loc.timezone)
    elev = solar_elevation(observer, now)

    solar_noon = solar_events["noon"]
    solar_midnight = solar_noon - timedelta(hours=12) if solar_noon.hour >= 12 else solar_noon + timedelta(hours=12)

    kwargs = {
        "min_color_temp": min_color_temp,
        "max_color_temp": max_color_temp,
        "min_brightness": min_brightness,
        "max_brightness": max_brightness,
        "sunrise_time": solar_events["sunrise"],
        "sunset_time": solar_events["sunset"],
        "solar_noon": solar_noon,
        "solar_midnight": solar_midnight,
    }

    if config:
        for key in ["ascend_start", "descend_start", "wake_time", "bed_time",
                    "wake_speed", "bed_speed",
                    "brightness_wake_mid", "brightness_bed_mid",
                    "color_wake_mid", "color_bed_mid"]:
            if key in config:
                kwargs[key] = config[key]

    al = AdaptiveLighting(**kwargs)

    sun_pos = al.calculate_sun_position(now, elev)
    clock_hour = al.get_clock_hour(now)
    in_ascend = al.is_in_ascend_phase(clock_hour)

    cct = al.calculate_color_temperature(now)
    bri = al.calculate_brightness(now)

    # Apply solar color rules if configured
    if config:
        cct = al.apply_solar_color_rules(cct, now, config)

    rgb = al.color_temperature_to_rgb(cct)
    xy = al.color_temperature_to_xy(cct)

    log_msg = f"{now.isoformat()} – elev {elev:.1f}°, hour {clock_hour:.2f}h"
    log_msg += f" | lighting: {cct}K/{bri}%"
    logger.info(log_msg)

    return {
        "color_temp": cct,
        "kelvin": cct,
        "brightness": bri,
        "rgb": rgb,
        "xy": xy,
        "sun_position": sun_pos,
        "clock_hour": clock_hour,
        "phase": "ascend" if in_ascend else "descend",
        "sunrise": solar_events["sunrise"].hour + solar_events["sunrise"].minute / 60,
        "sunset": solar_events["sunset"].hour + solar_events["sunset"].minute / 60,
    }
