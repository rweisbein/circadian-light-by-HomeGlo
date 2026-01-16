#!/usr/bin/env python3
"""Test basic brain.py functionality - dataclasses and core calculations."""

import pytest
from brain import CircadianLight, Config, AreaState, SunTimes


class TestDataclasses:
    """Test Config, AreaState, and SunTimes dataclasses."""

    def test_config_defaults(self):
        """Test Config has sensible defaults."""
        config = Config()

        # Phase timing defaults
        assert config.ascend_start == 3.0
        assert config.descend_start == 12.0
        assert config.wake_time == 6.0
        assert config.bed_time == 22.0

        # Bounds defaults
        assert config.min_brightness == 1
        assert config.max_brightness == 100
        assert config.min_color_temp == 500
        assert config.max_color_temp == 6500

        # Solar rule defaults
        assert config.warm_night_enabled is False
        assert config.cool_day_enabled is False

    def test_config_custom_values(self):
        """Test Config accepts custom values."""
        config = Config(
            ascend_start=5.0,
            descend_start=20.0,
            min_brightness=10,
            max_brightness=90,
            warm_night_enabled=True,
            warm_night_target=2700
        )

        assert config.ascend_start == 5.0
        assert config.descend_start == 20.0
        assert config.min_brightness == 10
        assert config.max_brightness == 90
        assert config.warm_night_enabled is True

    def test_area_state_defaults(self):
        """Test AreaState has correct defaults."""
        state = AreaState()

        assert state.enabled is False
        assert state.frozen_at is None
        assert state.is_frozen is False
        assert state.brightness_mid is None
        assert state.color_mid is None

    def test_area_state_to_dict(self):
        """Test AreaState serialization."""
        state = AreaState(
            enabled=True,
            frozen_at=14.5,
            brightness_mid=10.5,
            color_mid=11.2,
        )

        d = state.to_dict()

        assert d["enabled"] is True
        assert d["frozen_at"] == 14.5
        assert d["brightness_mid"] == 10.5
        assert d["color_mid"] == 11.2

    def test_area_state_from_dict(self):
        """Test AreaState deserialization."""
        d = {
            "enabled": True,
            "frozen_at": 20.0,
            "brightness_mid": 8.0,
            "color_mid": 9.0,
        }

        state = AreaState.from_dict(d)

        assert state.enabled is True
        assert state.frozen_at == 20.0
        assert state.is_frozen is True
        assert state.brightness_mid == 8.0
        assert state.color_mid == 9.0

    def test_area_state_roundtrip(self):
        """Test AreaState serialization roundtrip."""
        original = AreaState(
            enabled=True,
            frozen_at=14.5,
            brightness_mid=10.5,
            color_mid=11.2,
        )

        restored = AreaState.from_dict(original.to_dict())

        assert restored.enabled == original.enabled
        assert restored.frozen_at == original.frozen_at
        assert restored.brightness_mid == original.brightness_mid
        assert restored.color_mid == original.color_mid

    def test_sun_times_defaults(self):
        """Test SunTimes has defaults."""
        sun = SunTimes()

        assert sun.sunrise == 6.0
        assert sun.sunset == 18.0
        assert sun.solar_noon == 12.0
        assert sun.solar_mid == 0.0

    def test_sun_times_custom(self):
        """Test SunTimes accepts custom values."""
        sun = SunTimes(sunrise=5.5, sunset=20.5, solar_noon=13.0, solar_mid=1.0)

        assert sun.sunrise == 5.5
        assert sun.sunset == 20.5
        assert sun.solar_noon == 13.0
        assert sun.solar_mid == 1.0


class TestBrightnessCalculation:
    """Test calculate_brightness_at_hour."""

    def test_brightness_increases_during_ascend(self):
        """Test brightness increases from ascend_start to wake_time."""
        config = Config(
            ascend_start=6.0,
            descend_start=18.0,
            wake_time=8.0,
            bed_time=22.0,
            min_brightness=10,
            max_brightness=100
        )
        state = AreaState()

        bri_6am = CircadianLight.calculate_brightness_at_hour(6.0, config, state)
        bri_7am = CircadianLight.calculate_brightness_at_hour(7.0, config, state)
        bri_8am = CircadianLight.calculate_brightness_at_hour(8.0, config, state)
        bri_12pm = CircadianLight.calculate_brightness_at_hour(12.0, config, state)

        assert bri_6am < bri_7am < bri_8am
        assert bri_12pm == config.max_brightness

    def test_brightness_decreases_during_descend(self):
        """Test brightness decreases from descend_start toward bed_time."""
        config = Config(
            ascend_start=6.0,
            descend_start=18.0,
            wake_time=8.0,
            bed_time=22.0,
            min_brightness=10,
            max_brightness=100
        )
        state = AreaState()

        bri_6pm = CircadianLight.calculate_brightness_at_hour(18.0, config, state)
        bri_8pm = CircadianLight.calculate_brightness_at_hour(20.0, config, state)
        bri_10pm = CircadianLight.calculate_brightness_at_hour(22.0, config, state)

        assert bri_6pm > bri_8pm > bri_10pm

    def test_brightness_respects_bounds(self):
        """Test brightness stays within config bounds."""
        config = Config(
            min_brightness=20,
            max_brightness=80
        )
        state = AreaState()

        for hour in range(24):
            bri = CircadianLight.calculate_brightness_at_hour(float(hour), config, state)
            assert config.min_brightness <= bri <= config.max_brightness

    def test_brightness_with_state_midpoint(self):
        """Test brightness calculation with pushed midpoint."""
        config = Config(
            ascend_start=6.0,
            descend_start=18.0,
            wake_time=8.0,
            min_brightness=10,
            max_brightness=100
        )

        # Without state midpoint
        state_default = AreaState()
        bri_default = CircadianLight.calculate_brightness_at_hour(7.0, config, state_default)

        # With earlier midpoint (should be brighter at same time)
        state_early = AreaState(brightness_mid=6.5)
        bri_early = CircadianLight.calculate_brightness_at_hour(7.0, config, state_early)

        assert bri_early > bri_default


class TestColorCalculation:
    """Test calculate_color_at_hour."""

    def test_color_increases_during_ascend(self):
        """Test color temp increases (warmer to cooler) during ascend."""
        config = Config(
            ascend_start=6.0,
            descend_start=18.0,
            wake_time=8.0,
            min_color_temp=2700,
            max_color_temp=6500
        )
        state = AreaState()

        color_6am = CircadianLight.calculate_color_at_hour(6.0, config, state)
        color_8am = CircadianLight.calculate_color_at_hour(8.0, config, state)
        color_12pm = CircadianLight.calculate_color_at_hour(12.0, config, state)

        assert color_6am < color_8am < color_12pm

    def test_color_respects_bounds(self):
        """Test color stays within config bounds."""
        config = Config(
            min_color_temp=3000,
            max_color_temp=5000
        )
        state = AreaState()

        for hour in range(24):
            color = CircadianLight.calculate_color_at_hour(float(hour), config, state, apply_solar_rules=False)
            assert config.min_color_temp <= color <= config.max_color_temp


class TestColorConversions:
    """Test color space conversions."""

    def test_kelvin_to_xy_valid_range(self):
        """Test XY values are in valid range."""
        for kelvin in [2000, 2700, 4000, 5000, 6500]:
            x, y = CircadianLight.color_temperature_to_xy(kelvin)
            assert 0 <= x <= 1, f"x={x} out of range for {kelvin}K"
            assert 0 <= y <= 1, f"y={y} out of range for {kelvin}K"

    def test_kelvin_to_rgb_valid_range(self):
        """Test RGB values are in valid range."""
        for kelvin in [2000, 2700, 4000, 5000, 6500]:
            r, g, b = CircadianLight.color_temperature_to_rgb(kelvin)
            assert 0 <= r <= 255, f"r={r} out of range for {kelvin}K"
            assert 0 <= g <= 255, f"g={g} out of range for {kelvin}K"
            assert 0 <= b <= 255, f"b={b} out of range for {kelvin}K"

    def test_warm_temps_are_reddish(self):
        """Test warm color temps produce reddish RGB."""
        r, g, b = CircadianLight.color_temperature_to_rgb(2700)
        assert r > b, "Warm temp should have more red than blue"

    def test_cool_temps_are_bluish(self):
        """Test cool color temps produce bluish RGB."""
        r, g, b = CircadianLight.color_temperature_to_rgb(6500)
        assert b >= r * 0.8, "Cool temp should have significant blue"


class TestPhaseInfo:
    """Test get_phase_info helper."""

    def test_ascend_phase_morning(self):
        """Test morning hours are in ascend phase."""
        config = Config(ascend_start=6.0, descend_start=18.0)

        in_ascend, h48, t_ascend, t_descend, slope = CircadianLight.get_phase_info(10.0, config)

        assert in_ascend is True
        assert slope > 0  # Positive slope for ascend

    def test_descend_phase_evening(self):
        """Test evening hours are in descend phase."""
        config = Config(ascend_start=6.0, descend_start=18.0)

        in_ascend, h48, t_ascend, t_descend, slope = CircadianLight.get_phase_info(20.0, config)

        assert in_ascend is False
        assert slope < 0  # Negative slope for descend

    def test_late_night_is_descend(self):
        """Test late night (after midnight) is still in descend phase."""
        config = Config(ascend_start=6.0, descend_start=18.0)

        in_ascend, h48, t_ascend, t_descend, slope = CircadianLight.get_phase_info(2.0, config)

        assert in_ascend is False
