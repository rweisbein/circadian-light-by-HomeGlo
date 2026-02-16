#!/usr/bin/env python3
"""Test solar rules (warm night / cool day) in brain.py."""

import pytest
from brain import CircadianLight, Config, AreaState, SunTimes


class TestWarmNightRule:
    """Test warm_night solar rule."""

    @pytest.fixture
    def config(self):
        """Config with warm night enabled."""
        return Config(
            ascend_start=6.0,
            descend_start=18.0,
            wake_time=8.0,
            bed_time=22.0,
            min_color_temp=2700,
            max_color_temp=6500,
            warm_night_enabled=True,
            warm_night_target=2700,
            warm_night_mode="all",
            warm_night_start=-60,
            warm_night_end=120,
            warm_night_fade=30
        )

    @pytest.fixture
    def sun_times(self):
        """Standard sun times."""
        return SunTimes(sunrise=6.0, sunset=18.0, solar_noon=12.0, solar_mid=0.0)

    def test_warm_night_disabled_no_effect(self, sun_times):
        """Test warm night has no effect when disabled."""
        config = Config(
            warm_night_enabled=False,
            min_color_temp=2700,
            max_color_temp=6500
        )
        state = AreaState()

        # At 8pm (in descend), without warm night the color should still be
        # following the normal curve
        color = CircadianLight.calculate_color_at_hour(
            20.0, config, state, apply_solar_rules=True, sun_times=sun_times
        )

        # Without warm night, color at 8pm should be somewhere in range
        # (not clamped to 2700)
        assert color > 2700

    def test_warm_night_all_mode_clamps_in_descend(self, config, sun_times):
        """Test warm night 'all' mode clamps color during descend."""
        config.warm_night_mode = "all"
        state = AreaState()

        # At 8pm (descend phase), warm night should clamp to target
        color = CircadianLight.calculate_color_at_hour(
            20.0, config, state, apply_solar_rules=True, sun_times=sun_times
        )

        assert color <= config.warm_night_target

    def test_warm_night_window_mode_inside_window(self, config, sun_times):
        """Test warm night 'window' mode clamps inside window."""
        config.warm_night_mode = "window"
        config.warm_night_start = -60  # 60 min before sunset = 5pm
        config.warm_night_end = 120  # 120 min after sunset = 8pm
        state = AreaState()

        # At 7pm (inside window), should be clamped
        color = CircadianLight.calculate_color_at_hour(
            19.0, config, state, apply_solar_rules=True, sun_times=sun_times
        )

        assert color <= config.warm_night_target

    def test_warm_night_window_mode_outside_window(self, config, sun_times):
        """Test warm night 'window' mode doesn't clamp outside window."""
        config.warm_night_mode = "window"
        config.warm_night_start = -30  # 30 min before sunset = 5:30pm
        config.warm_night_end = 60  # 60 min after sunset = 7pm
        state = AreaState()

        # At 4pm (before window), should NOT be clamped
        color_before = CircadianLight.calculate_color_at_hour(
            16.0, config, state, apply_solar_rules=True, sun_times=sun_times
        )

        # At noon, definitely not in window
        color_noon = CircadianLight.calculate_color_at_hour(
            12.0, config, state, apply_solar_rules=True, sun_times=sun_times
        )

        # These should be at max (6500K) since we're in ascend/early descend
        assert color_noon == config.max_color_temp

    def test_warm_night_fade_at_window_edge(self, config, sun_times):
        """Test warm night fade at window edges."""
        config.warm_night_mode = "window"
        config.warm_night_start = 0  # At sunset (6pm)
        config.warm_night_end = 60  # 60 min after sunset (7pm)
        config.warm_night_fade = 30  # 30 min fade
        state = AreaState()

        # At 30 minutes after sunset (past fade-in), should be fully clamped
        color_inside = CircadianLight.calculate_color_at_hour(
            18.5, config, state, apply_solar_rules=True, sun_times=sun_times
        )

        # Inside window (past fade), should be clamped
        assert color_inside <= config.warm_night_target

class TestCoolDayRule:
    """Test cool_day solar rule."""

    @pytest.fixture
    def config(self):
        """Config with cool day enabled."""
        return Config(
            ascend_start=6.0,
            descend_start=18.0,
            wake_time=8.0,
            bed_time=22.0,
            min_color_temp=2700,
            max_color_temp=6500,
            cool_day_enabled=True,
            cool_day_target=5000,
            cool_day_mode="all",
            cool_day_start=0,
            cool_day_end=0,
            cool_day_fade=30
        )

    @pytest.fixture
    def sun_times(self):
        """Standard sun times."""
        return SunTimes(sunrise=6.0, sunset=18.0, solar_noon=12.0, solar_mid=0.0)

    def test_cool_day_disabled_no_effect(self, sun_times):
        """Test cool day has no effect when disabled."""
        config = Config(
            cool_day_enabled=False,
            min_color_temp=2700,
            max_color_temp=6500
        )
        state = AreaState()

        # At 8am (in ascend), without cool day the color should follow curve
        color = CircadianLight.calculate_color_at_hour(
            8.0, config, state, apply_solar_rules=True, sun_times=sun_times
        )

        # Color can be anything on the curve
        assert config.min_color_temp <= color <= config.max_color_temp

    def test_cool_day_all_mode_clamps_in_ascend(self, config, sun_times):
        """Test cool day 'all' mode clamps color during ascend."""
        config.cool_day_mode = "all"
        state = AreaState()

        # At 8am (ascend phase), cool day should set floor at target
        color = CircadianLight.calculate_color_at_hour(
            8.0, config, state, apply_solar_rules=True, sun_times=sun_times
        )

        # If base curve would be below target, it should be raised
        assert color >= config.cool_day_target

    def test_cool_day_window_mode_inside_window(self, config, sun_times):
        """Test cool day 'window' mode clamps inside window."""
        config.cool_day_mode = "window"
        config.cool_day_start = 60  # 60 min after sunrise = 7am
        config.cool_day_end = 300  # 300 min after sunrise = 11am
        state = AreaState()

        # At 9am (inside window), should have floor applied
        color = CircadianLight.calculate_color_at_hour(
            9.0, config, state, apply_solar_rules=True, sun_times=sun_times
        )

        assert color >= config.cool_day_target



class TestSolarRuleInteraction:
    """Test interaction between warm night and cool day."""

    def test_only_one_rule_active_per_phase(self):
        """Test that only one solar rule applies per phase."""
        config = Config(
            ascend_start=6.0,
            descend_start=18.0,
            warm_night_enabled=True,
            warm_night_target=2700,
            warm_night_mode="all",
            cool_day_enabled=True,
            cool_day_target=5000,
            cool_day_mode="all",
            min_color_temp=2700,
            max_color_temp=6500
        )
        state = AreaState()
        sun_times = SunTimes(sunrise=6.0, sunset=18.0)

        # In ascend (8am), cool_day should be active (floor)
        color_morning = CircadianLight.calculate_color_at_hour(
            8.0, config, state, apply_solar_rules=True, sun_times=sun_times
        )

        # In descend (8pm), warm_night should be active (ceiling)
        color_evening = CircadianLight.calculate_color_at_hour(
            20.0, config, state, apply_solar_rules=True, sun_times=sun_times
        )

        # Morning should be at or above cool_day target
        assert color_morning >= config.cool_day_target

        # Evening should be at or below warm_night target
        assert color_evening <= config.warm_night_target


class TestSunFactorModulation:
    """Test sun_factor modulation of cool day via _apply_solar_rules."""

    @pytest.fixture
    def config(self):
        """Config with cool day enabled, target above max_color_temp."""
        return Config(
            ascend_start=6.0,
            descend_start=18.0,
            wake_time=8.0,
            bed_time=22.0,
            min_color_temp=2700,
            max_color_temp=6500,
            cool_day_enabled=True,
            cool_day_target=5000,
            cool_day_mode="all",
            cool_day_start=0,
            cool_day_end=0,
            cool_day_fade=0,
        )

    def test_sun_factor_one_same_as_before(self, config):
        """sun_factor=1.0 should give same result as default (no modulation)."""
        state = AreaState()
        sun_full = SunTimes(sunrise=6.0, sunset=18.0, solar_noon=12.0, sun_factor=1.0)
        sun_default = SunTimes(sunrise=6.0, sunset=18.0, solar_noon=12.0)

        color_full = CircadianLight.calculate_color_at_hour(
            10.0, config, state, apply_solar_rules=True, sun_times=sun_full
        )
        color_default = CircadianLight.calculate_color_at_hour(
            10.0, config, state, apply_solar_rules=True, sun_times=sun_default
        )
        assert color_full == color_default

    def test_sun_factor_zero_cancels_cool_day(self, config):
        """sun_factor=0.0 should cancel cool day push entirely."""
        state = AreaState()
        sun_dark = SunTimes(sunrise=6.0, sunset=18.0, solar_noon=12.0, sun_factor=0.0)
        sun_none = SunTimes(sunrise=6.0, sunset=18.0, solar_noon=12.0)

        # With sun_factor=0, cool day has no effect — should match no-cool-day curve
        config_no_cool = Config(
            ascend_start=6.0, descend_start=18.0,
            wake_time=8.0, bed_time=22.0,
            min_color_temp=2700, max_color_temp=6500,
            cool_day_enabled=False,
        )

        color_dark = CircadianLight.calculate_color_at_hour(
            10.0, config, state, apply_solar_rules=True, sun_times=sun_dark
        )
        color_no_cool = CircadianLight.calculate_color_at_hour(
            10.0, config_no_cool, state, apply_solar_rules=True, sun_times=sun_none
        )
        assert color_dark == color_no_cool

    def test_sun_factor_half_gives_partial_effect(self, config):
        """sun_factor=0.5 should give roughly half the cool day push."""
        state = AreaState()
        sun_full = SunTimes(sunrise=6.0, sunset=18.0, solar_noon=12.0, sun_factor=1.0)
        sun_half = SunTimes(sunrise=6.0, sunset=18.0, solar_noon=12.0, sun_factor=0.5)
        sun_zero = SunTimes(sunrise=6.0, sunset=18.0, solar_noon=12.0, sun_factor=0.0)

        color_full = CircadianLight.calculate_color_at_hour(
            10.0, config, state, apply_solar_rules=True, sun_times=sun_full
        )
        color_half = CircadianLight.calculate_color_at_hour(
            10.0, config, state, apply_solar_rules=True, sun_times=sun_half
        )
        color_zero = CircadianLight.calculate_color_at_hour(
            10.0, config, state, apply_solar_rules=True, sun_times=sun_zero
        )

        # Half should be between zero and full
        assert color_zero <= color_half <= color_full

    def test_warm_night_not_affected_by_sun_factor(self):
        """Warm night should NOT be modulated by sun_factor."""
        config = Config(
            ascend_start=6.0, descend_start=18.0,
            wake_time=8.0, bed_time=22.0,
            min_color_temp=2700, max_color_temp=6500,
            warm_night_enabled=True, warm_night_target=2700,
            warm_night_mode="all", warm_night_start=-60,
            warm_night_end=120, warm_night_fade=0,
            cool_day_enabled=False,
        )
        state = AreaState()
        sun_full = SunTimes(sunrise=6.0, sunset=18.0, sun_factor=1.0)
        sun_zero = SunTimes(sunrise=6.0, sunset=18.0, sun_factor=0.0)

        color_full = CircadianLight.calculate_color_at_hour(
            20.0, config, state, apply_solar_rules=True, sun_times=sun_full
        )
        color_zero = CircadianLight.calculate_color_at_hour(
            20.0, config, state, apply_solar_rules=True, sun_times=sun_zero
        )

        # Warm night should be identical regardless of sun_factor
        assert color_full == color_zero


class TestSolarRuleHelpers:
    """Test solar rule helper functions."""

    def test_get_window_weight_inside_window(self):
        """Test _get_window_weight returns 1.0 inside window."""
        # Test the calculation logic implicitly through calculate_color_at_hour
        config = Config(
            warm_night_enabled=True,
            warm_night_target=2700,
            warm_night_mode="window",
            warm_night_start=-60,  # 1hr before sunset
            warm_night_end=60,  # 1hr after sunset
            warm_night_fade=0,  # No fade
            min_color_temp=2700,
            max_color_temp=6500
        )
        state = AreaState()
        sun_times = SunTimes(sunset=18.0)

        # At sunset (middle of window, no fade), should be fully clamped
        color = CircadianLight.calculate_color_at_hour(
            18.0, config, state, apply_solar_rules=True, sun_times=sun_times
        )

        assert color == config.warm_night_target

    def test_wrap24_handles_negative(self):
        """Test _wrap24 handles negative hours correctly."""
        # This is tested implicitly - windows with negative start times
        # should work correctly
        config = Config(
            warm_night_enabled=True,
            warm_night_target=2700,
            warm_night_mode="window",
            warm_night_start=-120,  # 2hrs before sunset (4pm for 6pm sunset)
            warm_night_end=0,  # At sunset
            warm_night_fade=0,
            min_color_temp=2700,
            max_color_temp=6500
        )
        state = AreaState()
        sun_times = SunTimes(sunset=18.0)

        # At 5pm (inside window), should be clamped
        color = CircadianLight.calculate_color_at_hour(
            17.0, config, state, apply_solar_rules=True, sun_times=sun_times
        )

        assert color == config.warm_night_target

    def test_without_sun_times_uses_defaults(self):
        """Test solar rules work without explicit sun_times (uses defaults)."""
        config = Config(
            warm_night_enabled=True,
            warm_night_target=2700,
            warm_night_mode="all",
            min_color_temp=2700,
            max_color_temp=6500
        )
        state = AreaState()

        # Call without sun_times - should use defaults
        color = CircadianLight.calculate_color_at_hour(
            20.0, config, state, apply_solar_rules=True
        )

        # Should still clamp with default sunset (18.0)
        assert color <= config.warm_night_target
