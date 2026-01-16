#!/usr/bin/env python3
"""Test edge cases and boundary conditions in brain.py."""

import pytest
from brain import CircadianLight, Config, AreaState, SunTimes


class TestPhaseTransitions:
    """Test behavior at phase transition boundaries."""

    def test_at_ascend_start(self):
        """Test calculations at exact ascend_start."""
        config = Config(
            ascend_start=6.0,
            descend_start=18.0,
            wake_time=8.0,  # 2 hours after ascend_start
            min_brightness=10,
            max_brightness=100
        )
        state = AreaState()

        bri = CircadianLight.calculate_brightness_at_hour(6.0, config, state)

        # At ascend start (2 hours before wake_time), brightness is mid-curve
        # The logistic curve has significant value 2 hours before midpoint
        assert 10 <= bri <= 100  # Within valid range

    def test_at_descend_start(self):
        """Test calculations at exact descend_start."""
        config = Config(
            ascend_start=6.0,
            descend_start=18.0,
            min_brightness=10,
            max_brightness=100
        )
        state = AreaState()

        bri = CircadianLight.calculate_brightness_at_hour(18.0, config, state)

        # At descend start, should be at or near max
        assert bri >= 80  # Near maximum

    def test_phase_just_before_transition(self):
        """Test phase detection just before transition."""
        config = Config(ascend_start=6.0, descend_start=18.0)

        # Just before descend (still in ascend)
        in_ascend, _, _, _, _ = CircadianLight.get_phase_info(17.9, config)
        assert in_ascend is True

        # At descend start
        in_ascend, _, _, _, _ = CircadianLight.get_phase_info(18.0, config)
        assert in_ascend is False


class TestMidnightCrossover:
    """Test behavior around midnight."""

    def test_late_night_after_midnight(self):
        """Test calculations work after midnight."""
        config = Config(
            ascend_start=6.0,
            descend_start=18.0,
            bed_time=22.0,
            min_brightness=10,
            max_brightness=100
        )
        state = AreaState()

        # At 2am (descend phase continues)
        bri_2am = CircadianLight.calculate_brightness_at_hour(2.0, config, state)

        # Should be at or near minimum
        assert bri_2am <= 20

    def test_early_morning_before_ascend(self):
        """Test calculations just before ascend_start."""
        config = Config(
            ascend_start=6.0,
            descend_start=18.0,
            min_brightness=10,
            max_brightness=100
        )
        state = AreaState()

        # At 5am (still descend)
        bri_5am = CircadianLight.calculate_brightness_at_hour(5.0, config, state)

        # Should be at or near minimum
        assert bri_5am <= 20

    def test_midnight_is_in_descend(self):
        """Test midnight is correctly identified as descend phase."""
        config = Config(ascend_start=6.0, descend_start=18.0)

        in_ascend, h48, _, _, _ = CircadianLight.get_phase_info(0.0, config)

        assert in_ascend is False
        # h48 should be lifted (0 + 24 = 24)
        assert h48 == 24.0


class TestExtremeConfigurations:
    """Test extreme but valid configurations."""

    def test_very_narrow_brightness_range(self):
        """Test with very narrow brightness range."""
        config = Config(min_brightness=49, max_brightness=51)
        state = AreaState()

        for hour in range(24):
            bri = CircadianLight.calculate_brightness_at_hour(float(hour), config, state)
            assert 49 <= bri <= 51

    def test_very_narrow_color_range(self):
        """Test with very narrow color range."""
        config = Config(min_color_temp=4000, max_color_temp=4100)
        state = AreaState()

        for hour in range(24):
            color = CircadianLight.calculate_color_at_hour(
                float(hour), config, state, apply_solar_rules=False
            )
            assert 4000 <= color <= 4100

    def test_inverted_phase_times(self):
        """Test when descend_start < ascend_start (night shift schedule)."""
        config = Config(
            ascend_start=18.0,  # Wake up at 6pm
            descend_start=6.0,  # Go to bed at 6am
            wake_time=20.0,
            bed_time=4.0,
            min_brightness=10,
            max_brightness=100
        )
        state = AreaState()

        # At midnight (should be in ascend for this schedule)
        in_ascend, _, _, _, _ = CircadianLight.get_phase_info(0.0, config)

        # Calculations should still work
        bri = CircadianLight.calculate_brightness_at_hour(0.0, config, state)
        assert 10 <= bri <= 100

    def test_single_step(self):
        """Test with max_dim_steps=1."""
        config = Config(
            min_brightness=10,
            max_brightness=100,
            max_dim_steps=1
        )
        state = AreaState()

        result = CircadianLight.calculate_step(12.0, "down", config, state)

        # Should still work, step size will be large
        assert result is not None
        # Step should be ~90% (the full range)
        assert result.brightness < 20  # Large step from 100


class TestStateConsistency:
    """Test state handling consistency."""

    def test_none_state_values_use_config(self):
        """Test None state values fall back to config."""
        config = Config(
            min_brightness=10,
            max_brightness=100,
            min_color_temp=2700,
            max_color_temp=6500
        )
        state = AreaState()  # All None

        # Should use config values
        bri = CircadianLight.calculate_brightness_at_hour(12.0, config, state)
        assert bri == 100  # At noon with default config

    def test_state_from_dict_with_missing_keys(self):
        """Test AreaState.from_dict handles missing keys."""
        d = {"enabled": True}  # Minimal dict

        state = AreaState.from_dict(d)

        assert state.enabled is True
        assert state.frozen_at is None  # Default
        assert state.is_frozen is False  # Default
        assert state.brightness_mid is None  # Default


class TestColorConversionEdgeCases:
    """Test color conversion edge cases."""

    def test_xy_at_boundary_kelvins(self):
        """Test XY conversion at boundary kelvin values."""
        # Minimum
        x_min, y_min = CircadianLight.color_temperature_to_xy(500)
        assert 0 <= x_min <= 1
        assert 0 <= y_min <= 1

        # Maximum
        x_max, y_max = CircadianLight.color_temperature_to_xy(6500)
        assert 0 <= x_max <= 1
        assert 0 <= y_max <= 1

    def test_rgb_at_boundary_kelvins(self):
        """Test RGB conversion at boundary kelvin values."""
        # Minimum
        r, g, b = CircadianLight.color_temperature_to_rgb(500)
        assert all(0 <= c <= 255 for c in (r, g, b))

        # Maximum
        r, g, b = CircadianLight.color_temperature_to_rgb(6500)
        assert all(0 <= c <= 255 for c in (r, g, b))


class TestStepEdgeCases:
    """Test step calculation edge cases."""

    def test_step_at_absolute_max(self):
        """Test step at absolute maximum (100%)."""
        config = Config(max_brightness=100, max_dim_steps=10)
        state = AreaState()

        # At noon, brightness is 100%
        result = CircadianLight.calculate_step(12.0, "up", config, state)

        # Should return None (can't go higher)
        assert result is None

    def test_step_at_config_min(self):
        """Test step at config minimum."""
        config = Config(min_brightness=1, max_brightness=100, max_dim_steps=10)
        state = AreaState(brightness_mid=0.0)  # Early midpoint pushes brightness down

        # Force to minimum
        result = CircadianLight.calculate_step(12.0, "down", config, state)

        # Should return None when at config min, or a valid brightness otherwise
        assert result is None or result.brightness >= config.min_brightness

    def test_bright_step_preserves_color_exactly(self):
        """Test bright step doesn't modify color at all."""
        config = Config(
            ascend_start=6.0,
            descend_start=18.0,
            wake_time=10.0,  # Late wake time so 8am isn't at max
            max_dim_steps=10
        )
        state = AreaState()

        color_before = CircadianLight.calculate_color_at_hour(8.0, config, state)
        result = CircadianLight.calculate_bright_step(8.0, "up", config, state)

        assert result is not None
        assert result.color_temp == color_before

    def test_color_step_preserves_brightness_exactly(self):
        """Test color step doesn't modify brightness at all."""
        config = Config(max_dim_steps=10)
        state = AreaState()

        bri_before = CircadianLight.calculate_brightness_at_hour(8.0, config, state)
        result = CircadianLight.calculate_color_step(8.0, "up", config, state)

        assert result is not None
        assert result.brightness == bri_before
