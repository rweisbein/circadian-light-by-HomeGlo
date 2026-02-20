#!/usr/bin/env python3
"""Test alt timing resolution and brightness targets."""

import pytest
from brain import (
    CircadianLight,
    Config,
    AreaState,
    resolve_effective_timing,
    compute_shifted_midpoint,
    SPEED_TO_SLOPE,
)


class TestResolveEffectiveTiming:
    """Test resolve_effective_timing() priority and day-of-week logic."""

    def test_no_alt_returns_primary(self):
        """When alt times are disabled, returns primary wake/bed."""
        config = Config(wake_time=7.0, bed_time=22.0)
        wake, bed = resolve_effective_timing(config, hour=10.0, weekday=0)
        assert wake == 7.0
        assert bed == 22.0

    def test_alt_wake_on_matching_day(self):
        """Alt wake used when weekday matches alt_days."""
        config = Config(
            wake_time=7.0,
            bed_time=22.0,
            wake_alt_time=9.0,
            wake_alt_days=[5, 6],  # Sat, Sun
        )
        # Saturday (weekday=5) → alt wake
        wake, bed = resolve_effective_timing(config, hour=10.0, weekday=5)
        assert wake == 9.0
        assert bed == 22.0

    def test_alt_wake_on_non_matching_day(self):
        """Alt wake NOT used when weekday not in alt_days."""
        config = Config(
            wake_time=7.0,
            bed_time=22.0,
            wake_alt_time=9.0,
            wake_alt_days=[5, 6],
        )
        # Monday (weekday=0) → primary wake
        wake, bed = resolve_effective_timing(config, hour=10.0, weekday=0)
        assert wake == 7.0
        assert bed == 22.0

    def test_alt_bed_on_matching_day(self):
        """Alt bed used when weekday matches alt_days (normal hours)."""
        config = Config(
            wake_time=7.0,
            bed_time=22.0,
            bed_alt_time=23.5,
            bed_alt_days=[4, 5],  # Fri, Sat
        )
        # Friday evening (weekday=4) → alt bed
        wake, bed = resolve_effective_timing(config, hour=20.0, weekday=4)
        assert wake == 7.0
        assert bed == 23.5

    def test_alt_bed_post_midnight_uses_yesterday(self):
        """At 2am Tuesday (post-midnight), bed time uses Monday's weekday."""
        config = Config(
            ascend_start=3.0,
            wake_time=7.0,
            bed_time=22.0,
            bed_alt_time=23.5,
            bed_alt_days=[0],  # Monday only
        )
        # 2am Tuesday (weekday=1), but hour < ascend_start so bed_weekday = Monday (0)
        wake, bed = resolve_effective_timing(config, hour=2.0, weekday=1)
        assert bed == 23.5  # Monday's alt bed applies

    def test_alt_bed_post_midnight_no_match(self):
        """At 2am Wednesday, bed checks Tuesday — not in alt days."""
        config = Config(
            ascend_start=3.0,
            wake_time=7.0,
            bed_time=22.0,
            bed_alt_time=23.5,
            bed_alt_days=[0],  # Monday only
        )
        # 2am Wednesday (weekday=2), bed_weekday = Tuesday (1) → not in [0]
        wake, bed = resolve_effective_timing(config, hour=2.0, weekday=2)
        assert bed == 22.0  # Primary bed

    def test_both_alt_times_different_days(self):
        """Different alt days for wake and bed."""
        config = Config(
            wake_time=7.0,
            bed_time=22.0,
            wake_alt_time=9.0,
            wake_alt_days=[5, 6],  # Sat, Sun
            bed_alt_time=23.5,
            bed_alt_days=[4, 5],  # Fri, Sat
        )
        # Friday evening → primary wake, alt bed
        wake, bed = resolve_effective_timing(config, hour=20.0, weekday=4)
        assert wake == 7.0
        assert bed == 23.5


class TestComputeShiftedMidpoint:
    """Test brightness target midpoint shifting."""

    def test_50pct_no_shift(self):
        """50% target returns the original midpoint unchanged."""
        result = compute_shifted_midpoint(
            target_time_h48=7.0,
            brightness_pct=50,
            slope=3.0,
            b_min_norm=0.01,
            b_max_norm=1.0,
        )
        assert result == 7.0

    def test_30pct_shifts_later(self):
        """30% target shifts midpoint later (ascend: dimmer at wake = midpoint moves forward)."""
        slope = SPEED_TO_SLOPE[8]  # speed 8 = slope 3.0
        result = compute_shifted_midpoint(
            target_time_h48=7.0,
            brightness_pct=30,
            slope=slope,
            b_min_norm=0.01,
            b_max_norm=1.0,
        )
        # 30% brightness at wake → midpoint must be later than 7.0
        assert result > 7.0

    def test_70pct_shifts_earlier(self):
        """70% target shifts midpoint earlier (ascend: brighter at wake = midpoint moves back)."""
        slope = SPEED_TO_SLOPE[8]
        result = compute_shifted_midpoint(
            target_time_h48=7.0,
            brightness_pct=70,
            slope=slope,
            b_min_norm=0.01,
            b_max_norm=1.0,
        )
        # 70% brightness at wake → midpoint must be earlier than 7.0
        assert result < 7.0

    def test_descend_30pct_shifts_earlier(self):
        """For descend (negative slope), 30% at bed shifts midpoint earlier."""
        slope = -SPEED_TO_SLOPE[6]  # negative for descend
        result = compute_shifted_midpoint(
            target_time_h48=22.0,
            brightness_pct=30,
            slope=slope,
            b_min_norm=0.01,
            b_max_norm=1.0,
        )
        # 30% brightness at bed with descending curve → midpoint moves earlier
        assert result < 22.0


class TestBrightnessTargetIntegration:
    """Test that brightness targets actually affect calculate_brightness_at_hour."""

    def _make_config(self, wake_brightness=50, bed_brightness=50):
        return Config(
            ascend_start=3.0,
            descend_start=12.0,
            wake_time=7.0,
            bed_time=22.0,
            wake_speed=8,
            bed_speed=6,
            min_brightness=1,
            max_brightness=100,
            wake_brightness=wake_brightness,
            bed_brightness=bed_brightness,
        )

    def test_50pct_identical_to_default(self):
        """wake_brightness=50 produces same result as no target (default behavior)."""
        config_default = self._make_config(wake_brightness=50)
        config_explicit = Config(
            ascend_start=3.0,
            descend_start=12.0,
            wake_time=7.0,
            bed_time=22.0,
            wake_speed=8,
            bed_speed=6,
            min_brightness=1,
            max_brightness=100,
        )
        state = AreaState()

        for hour in [5.0, 6.0, 7.0, 8.0, 10.0]:
            bri_default = CircadianLight.calculate_brightness_at_hour(
                hour, config_default, state, weekday=0
            )
            bri_explicit = CircadianLight.calculate_brightness_at_hour(
                hour, config_explicit, state, weekday=0
            )
            assert bri_default == bri_explicit, f"Mismatch at hour {hour}"

    def test_30pct_dimmer_at_wake(self):
        """wake_brightness=30 produces dimmer output at wake time."""
        config_normal = self._make_config(wake_brightness=50)
        config_dim = self._make_config(wake_brightness=30)
        state = AreaState()

        bri_normal = CircadianLight.calculate_brightness_at_hour(
            7.0, config_normal, state, weekday=0
        )
        bri_dim = CircadianLight.calculate_brightness_at_hour(
            7.0, config_dim, state, weekday=0
        )

        assert bri_dim < bri_normal, f"Expected dimmer: {bri_dim} < {bri_normal}"

    def test_70pct_brighter_at_wake(self):
        """wake_brightness=70 produces brighter output at wake time."""
        config_normal = self._make_config(wake_brightness=50)
        config_bright = self._make_config(wake_brightness=70)
        state = AreaState()

        bri_normal = CircadianLight.calculate_brightness_at_hour(
            7.0, config_normal, state, weekday=0
        )
        bri_bright = CircadianLight.calculate_brightness_at_hour(
            7.0, config_bright, state, weekday=0
        )

        assert (
            bri_bright > bri_normal
        ), f"Expected brighter: {bri_bright} > {bri_normal}"

    def test_bed_brightness_30pct_dimmer_at_bed(self):
        """bed_brightness=30 means only 30% brightness at bed time (dimmer)."""
        config_normal = self._make_config(bed_brightness=50)
        config_dim = self._make_config(bed_brightness=30)
        state = AreaState()

        bri_normal = CircadianLight.calculate_brightness_at_hour(
            22.0, config_normal, state, weekday=0
        )
        bri_dim = CircadianLight.calculate_brightness_at_hour(
            22.0, config_dim, state, weekday=0
        )

        assert (
            bri_dim < bri_normal
        ), f"bed_brightness=30 should be dimmer at bed time: {bri_dim} < {bri_normal}"

    def test_stepping_override_ignores_brightness_target(self):
        """When state.brightness_mid is set (stepping), brightness target is bypassed."""
        config = self._make_config(wake_brightness=30)
        state_no_step = AreaState()
        state_stepped = AreaState(brightness_mid=7.0)

        # With brightness_mid set to exactly wake_time, result should match
        # default 50% behavior (stepping override wins)
        config_default = self._make_config(wake_brightness=50)
        bri_stepped = CircadianLight.calculate_brightness_at_hour(
            7.0, config, state_stepped, weekday=0
        )
        bri_default = CircadianLight.calculate_brightness_at_hour(
            7.0, config_default, state_stepped, weekday=0
        )
        assert bri_stepped == bri_default

    def test_color_follows_brightness_target(self):
        """Color shifts with brightness target (circadian: both curves move together)."""
        config_normal = self._make_config(wake_brightness=50)
        config_shifted = self._make_config(wake_brightness=30)
        state = AreaState()

        cct_normal = CircadianLight.calculate_color_at_hour(
            7.0, config_normal, state, apply_solar_rules=False, weekday=0
        )
        cct_shifted = CircadianLight.calculate_color_at_hour(
            7.0, config_shifted, state, apply_solar_rules=False, weekday=0
        )
        assert (
            cct_shifted < cct_normal
        ), f"Color should be cooler with wake_brightness=30: {cct_shifted} < {cct_normal}"


class TestAltTimingIntegration:
    """Test that alt times flow through to brightness/color calculations."""

    def test_alt_wake_changes_brightness_curve(self):
        """Alt wake time shifts the brightness curve."""
        config_early = Config(wake_time=6.0, bed_time=22.0, wake_speed=8)
        config_late = Config(
            wake_time=6.0,
            bed_time=22.0,
            wake_speed=8,
            wake_alt_time=9.0,
            wake_alt_days=[0],  # Monday
        )
        state = AreaState()

        # At 7am Monday with alt wake=9, should be dimmer than with wake=6
        bri_early = CircadianLight.calculate_brightness_at_hour(
            7.0, config_early, state, weekday=0
        )
        bri_late = CircadianLight.calculate_brightness_at_hour(
            7.0, config_late, state, weekday=0
        )
        assert (
            bri_late < bri_early
        ), f"Alt wake 9am should be dimmer at 7am: {bri_late} < {bri_early}"

    def test_alt_wake_no_effect_on_other_days(self):
        """Alt wake only applies on selected days."""
        config = Config(
            wake_time=6.0,
            bed_time=22.0,
            wake_speed=8,
            wake_alt_time=9.0,
            wake_alt_days=[0],  # Monday only
        )
        config_plain = Config(wake_time=6.0, bed_time=22.0, wake_speed=8)
        state = AreaState()

        # Tuesday (weekday=1) → no alt, same as plain
        bri_alt = CircadianLight.calculate_brightness_at_hour(
            7.0, config, state, weekday=1
        )
        bri_plain = CircadianLight.calculate_brightness_at_hour(
            7.0, config_plain, state, weekday=1
        )
        assert bri_alt == bri_plain
