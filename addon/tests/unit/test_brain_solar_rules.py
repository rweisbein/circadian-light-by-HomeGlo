#!/usr/bin/env python3
"""Test solar rules (warm night / daylight blend) in brain.py."""

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


class TestDaylightColorBlend:
    """Test intensity-based daylight color blend (replaces TestCoolDayRule)."""

    @pytest.fixture
    def config(self):
        """Config with daylight_cct set."""
        return Config(
            ascend_start=6.0,
            descend_start=18.0,
            wake_time=8.0,
            bed_time=22.0,
            min_color_temp=2700,
            max_color_temp=6500,
            daylight_cct=5500,
            color_sensitivity=1.68,
        )

    def test_no_outdoor_light_no_blend(self, config):
        """outdoor_normalized=0 → no daylight color shift."""
        state = AreaState()
        sun_no_outdoor = SunTimes(
            sunrise=6.0, sunset=18.0, solar_noon=12.0,
            outdoor_normalized=0.0,
        )
        sun_default = SunTimes(sunrise=6.0, sunset=18.0, solar_noon=12.0)

        color_no = CircadianLight.calculate_color_at_hour(
            10.0, config, state, apply_solar_rules=True, sun_times=sun_no_outdoor
        )
        color_default = CircadianLight.calculate_color_at_hour(
            10.0, config, state, apply_solar_rules=True, sun_times=sun_default
        )
        # Both should be the same (outdoor_normalized=0 by default)
        assert color_no == color_default

    def test_full_outdoor_pushes_toward_daylight_cct(self, config):
        """Full outdoor intensity should push color toward daylight_cct."""
        state = AreaState()
        sun_full = SunTimes(
            sunrise=6.0, sunset=18.0, solar_noon=12.0,
            outdoor_normalized=1.0,
        )
        sun_none = SunTimes(
            sunrise=6.0, sunset=18.0, solar_noon=12.0,
            outdoor_normalized=0.0,
        )

        color_full = CircadianLight.calculate_color_at_hour(
            10.0, config, state, apply_solar_rules=True, sun_times=sun_full
        )
        color_none = CircadianLight.calculate_color_at_hour(
            10.0, config, state, apply_solar_rules=True, sun_times=sun_none
        )

        # Full outdoor should push color higher (closer to daylight_cct=5500)
        assert color_full >= color_none

    def test_half_outdoor_partial_blend(self, config):
        """Half outdoor intensity gives partial blend."""
        state = AreaState()
        sun_full = SunTimes(sunrise=6.0, sunset=18.0, outdoor_normalized=1.0)
        sun_half = SunTimes(sunrise=6.0, sunset=18.0, outdoor_normalized=0.5)
        sun_zero = SunTimes(sunrise=6.0, sunset=18.0, outdoor_normalized=0.0)

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

    def test_daylight_cct_zero_disables_blend(self, config):
        """daylight_cct=0 disables the blend entirely."""
        config.daylight_cct = 0
        state = AreaState()
        sun_full = SunTimes(sunrise=6.0, sunset=18.0, outdoor_normalized=1.0)

        color_base = CircadianLight.calculate_color_at_hour(
            10.0, config, state, apply_solar_rules=False
        )
        color_with = CircadianLight.calculate_color_at_hour(
            10.0, config, state, apply_solar_rules=True, sun_times=sun_full
        )

        # No daylight blend should be applied
        assert color_base == color_with

    def test_no_push_when_base_above_daylight_cct(self, config):
        """When base color is already above daylight_cct, no push occurs."""
        # Set daylight_cct below min_color_temp so base is always above
        config.daylight_cct = 2000
        state = AreaState()
        sun_full = SunTimes(sunrise=6.0, sunset=18.0, outdoor_normalized=1.0)

        color_base = CircadianLight.calculate_color_at_hour(
            12.0, config, state, apply_solar_rules=False
        )
        color_with = CircadianLight.calculate_color_at_hour(
            12.0, config, state, apply_solar_rules=True, sun_times=sun_full
        )

        # Base kelvin at noon should be above 2000, so no daylight shift
        assert color_base == color_with

    def test_low_outdoor_at_sunrise_preserves_warm(self, config):
        """Low outdoor_normalized at sunrise → minimal color shift (warm morning preserved)."""
        state = AreaState()
        sun_low = SunTimes(
            sunrise=6.0, sunset=18.0, solar_noon=12.0,
            outdoor_normalized=0.1,
        )

        color = CircadianLight.calculate_color_at_hour(
            7.0, config, state, apply_solar_rules=True, sun_times=sun_low
        )
        color_base = CircadianLight.calculate_color_at_hour(
            7.0, config, state, apply_solar_rules=False
        )

        # Shift should be small — under 500K (blend ≈ 0.168 × 2620K gap = ~440K)
        assert abs(color - color_base) < 500


class TestSolarRuleInteraction:
    """Test interaction between warm night and daylight blend."""

    def test_warm_night_and_daylight_coexist(self):
        """Both warm night and daylight blend can apply (at different times)."""
        config = Config(
            ascend_start=6.0,
            descend_start=18.0,
            warm_night_enabled=True,
            warm_night_target=2700,
            warm_night_mode="all",
            daylight_cct=5500,
            color_sensitivity=1.68,
            min_color_temp=2700,
            max_color_temp=6500
        )
        state = AreaState()
        sun_times = SunTimes(
            sunrise=6.0, sunset=18.0,
            outdoor_normalized=1.0,
        )

        # In ascend (10am), daylight blend should be active (push up)
        color_morning = CircadianLight.calculate_color_at_hour(
            10.0, config, state, apply_solar_rules=True, sun_times=sun_times
        )

        # In descend (8pm), warm_night should be active (ceiling)
        color_evening = CircadianLight.calculate_color_at_hour(
            20.0, config, state, apply_solar_rules=True, sun_times=sun_times
        )

        # Evening should be clamped by warm night
        assert color_evening <= config.warm_night_target


class TestSunFactorModulation:
    """Test outdoor_normalized on SunTimes drives daylight color blend."""

    @pytest.fixture
    def config(self):
        """Config with daylight_cct set."""
        return Config(
            ascend_start=6.0,
            descend_start=18.0,
            wake_time=8.0,
            bed_time=22.0,
            min_color_temp=2700,
            max_color_temp=6500,
            daylight_cct=5500,
            color_sensitivity=1.68,
        )

    def test_outdoor_zero_cancels_daylight_blend(self, config):
        """outdoor_normalized=0.0 should cancel daylight color blend entirely."""
        state = AreaState()
        sun_dark = SunTimes(sunrise=6.0, sunset=18.0, solar_noon=12.0, outdoor_normalized=0.0)

        # With outdoor_normalized=0, daylight blend has no effect
        color_dark = CircadianLight.calculate_color_at_hour(
            10.0, config, state, apply_solar_rules=True, sun_times=sun_dark
        )
        color_no_rules = CircadianLight.calculate_color_at_hour(
            10.0, config, state, apply_solar_rules=False
        )
        assert color_dark == color_no_rules

    def test_warm_night_not_affected_by_outdoor_normalized(self):
        """Warm night should NOT be modulated by outdoor_normalized."""
        config = Config(
            ascend_start=6.0, descend_start=18.0,
            wake_time=8.0, bed_time=22.0,
            min_color_temp=2700, max_color_temp=6500,
            warm_night_enabled=True, warm_night_target=2700,
            warm_night_mode="all", warm_night_start=-60,
            warm_night_end=120, warm_night_fade=0,
            daylight_cct=0,  # disable daylight blend
        )
        state = AreaState()
        sun_full = SunTimes(sunrise=6.0, sunset=18.0, outdoor_normalized=1.0)
        sun_zero = SunTimes(sunrise=6.0, sunset=18.0, outdoor_normalized=0.0)

        color_full = CircadianLight.calculate_color_at_hour(
            20.0, config, state, apply_solar_rules=True, sun_times=sun_full
        )
        color_zero = CircadianLight.calculate_color_at_hour(
            20.0, config, state, apply_solar_rules=True, sun_times=sun_zero
        )

        # Warm night should be identical regardless of outdoor_normalized
        assert color_full == color_zero


class TestSolarRuleBreakdown:
    """Test get_solar_rule_breakdown returns correct new fields."""

    def test_breakdown_has_daylight_keys(self):
        """Breakdown should include daylight_blend, daylight_shift, daylight_cct."""
        config = Config(
            ascend_start=6.0, descend_start=18.0,
            daylight_cct=5500, color_sensitivity=1.68,
            min_color_temp=2700, max_color_temp=6500,
        )
        state = AreaState()
        sun_times = SunTimes(sunrise=6.0, sunset=18.0, outdoor_normalized=0.8)

        breakdown = CircadianLight.get_solar_rule_breakdown(
            4000, 10.0, config, state, sun_times
        )

        assert 'daylight_blend' in breakdown
        assert 'daylight_shift' in breakdown
        assert 'daylight_cct' in breakdown
        assert 'outdoor_normalized' in breakdown
        assert 'warm_night_enabled' in breakdown
        assert breakdown['outdoor_normalized'] == 0.8

    def test_breakdown_no_cool_day_keys(self):
        """Breakdown should NOT include old cool_day keys."""
        config = Config(
            ascend_start=6.0, descend_start=18.0,
            min_color_temp=2700, max_color_temp=6500,
        )
        state = AreaState()
        sun_times = SunTimes(sunrise=6.0, sunset=18.0)

        breakdown = CircadianLight.get_solar_rule_breakdown(
            4000, 10.0, config, state, sun_times
        )

        assert 'cool_day_enabled' not in breakdown
        assert 'cool_day_target' not in breakdown
        assert 'day_strength' not in breakdown


class TestSolarRuleHelpers:
    """Test solar rule helper functions."""

    def test_get_window_weight_inside_window(self):
        """Test _get_window_weight returns 1.0 inside window."""
        config = Config(
            warm_night_enabled=True,
            warm_night_target=2700,
            warm_night_mode="window",
            warm_night_start=-60,
            warm_night_end=60,
            warm_night_fade=0,
            min_color_temp=2700,
            max_color_temp=6500
        )
        state = AreaState()
        sun_times = SunTimes(sunset=18.0)

        color = CircadianLight.calculate_color_at_hour(
            18.0, config, state, apply_solar_rules=True, sun_times=sun_times
        )

        assert color == config.warm_night_target

    def test_wrap24_handles_negative(self):
        """Test _wrap24 handles negative hours correctly."""
        config = Config(
            warm_night_enabled=True,
            warm_night_target=2700,
            warm_night_mode="window",
            warm_night_start=-120,
            warm_night_end=0,
            warm_night_fade=0,
            min_color_temp=2700,
            max_color_temp=6500
        )
        state = AreaState()
        sun_times = SunTimes(sunset=18.0)

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

        color = CircadianLight.calculate_color_at_hour(
            20.0, config, state, apply_solar_rules=True
        )

        assert color <= config.warm_night_target
