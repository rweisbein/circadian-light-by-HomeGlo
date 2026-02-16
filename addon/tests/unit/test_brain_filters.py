#!/usr/bin/env python3
"""Tests for light filter functions in brain.py."""

import math
import pytest
from brain import (
    calculate_curve_position,
    calculate_filter_multiplier,
    calculate_natural_light_factor,
    angle_to_estimated_lux,
    apply_light_filter_pipeline,
)


class TestCalculateCurvePosition:
    """Tests for calculate_curve_position()."""

    def test_at_min(self):
        assert calculate_curve_position(1, 1, 100) == 0.0

    def test_at_max(self):
        assert calculate_curve_position(100, 1, 100) == 1.0

    def test_midpoint(self):
        pos = calculate_curve_position(50, 0, 100)
        assert pos == 0.5

    def test_quarter(self):
        pos = calculate_curve_position(25, 0, 100)
        assert pos == 0.25

    def test_below_min_clamps_to_zero(self):
        assert calculate_curve_position(0, 5, 100) == 0.0

    def test_above_max_clamps_to_one(self):
        assert calculate_curve_position(120, 1, 100) == 1.0

    def test_equal_min_max_returns_zero(self):
        assert calculate_curve_position(50, 50, 50) == 0.0

    def test_inverted_range_returns_zero(self):
        assert calculate_curve_position(50, 100, 1) == 0.0

    def test_custom_range(self):
        # min=10, max=60, brightness=35 → (35-10)/(60-10) = 0.5
        pos = calculate_curve_position(35, 10, 60)
        assert pos == 0.5


class TestCalculateFilterMultiplier:
    """Tests for calculate_filter_multiplier()."""

    def test_standard_preset(self):
        # at_dim=100, at_bright=100 → always 1.0
        assert calculate_filter_multiplier(0.0, 100, 100) == 1.0
        assert calculate_filter_multiplier(0.5, 100, 100) == 1.0
        assert calculate_filter_multiplier(1.0, 100, 100) == 1.0

    def test_overhead_at_dim(self):
        # at_dim=0, at_bright=100, position=0.0 → 0.0
        assert calculate_filter_multiplier(0.0, 0, 100) == 0.0

    def test_overhead_at_bright(self):
        # at_dim=0, at_bright=100, position=1.0 → 1.0
        assert calculate_filter_multiplier(1.0, 0, 100) == 1.0

    def test_overhead_midpoint(self):
        # at_dim=0, at_bright=100, position=0.5 → 0.5
        assert calculate_filter_multiplier(0.5, 0, 100) == 0.5

    def test_lamp_at_dim(self):
        # at_dim=100, at_bright=30, position=0.0 → 1.0
        assert calculate_filter_multiplier(0.0, 100, 30) == 1.0

    def test_lamp_at_bright(self):
        # at_dim=100, at_bright=30, position=1.0 → 0.3
        assert calculate_filter_multiplier(1.0, 100, 30) == 0.3

    def test_accent_constant(self):
        # at_dim=50, at_bright=50 → always 0.5
        assert calculate_filter_multiplier(0.0, 50, 50) == 0.5
        assert calculate_filter_multiplier(1.0, 50, 50) == 0.5

    def test_nightlight_at_dim(self):
        # at_dim=40, at_bright=0, position=0.0 → 0.4
        assert calculate_filter_multiplier(0.0, 40, 0) == 0.4

    def test_nightlight_at_bright(self):
        # at_dim=40, at_bright=0, position=1.0 → 0.0
        assert calculate_filter_multiplier(1.0, 40, 0) == 0.0

    def test_values_above_100(self):
        # at_dim=200, at_bright=200 → 2.0
        assert calculate_filter_multiplier(0.5, 200, 200) == 2.0

    def test_interpolation_above_100(self):
        # at_dim=100, at_bright=200, position=0.5 → 150/100 = 1.5
        assert calculate_filter_multiplier(0.5, 100, 200) == 1.5


class TestAngleToEstimatedLux:
    """Tests for angle_to_estimated_lux()."""

    def test_zero_elevation(self):
        assert angle_to_estimated_lux(0) == 0.0

    def test_negative_elevation(self):
        assert angle_to_estimated_lux(-5) == 0.0

    def test_30_degrees(self):
        # sin(30°) = 0.5 → 60000
        assert angle_to_estimated_lux(30) == pytest.approx(60000, abs=100)

    def test_45_degrees(self):
        # sin(45°) ≈ 0.707 → ~84853
        assert angle_to_estimated_lux(45) == pytest.approx(84853, abs=100)

    def test_90_degrees(self):
        # sin(90°) = 1.0 → 120000
        assert angle_to_estimated_lux(90) == pytest.approx(120000, abs=1)


class TestCalculateNaturalLightFactor:
    """Tests for calculate_natural_light_factor().

    New signature: (exposure, outdoor_normalized, brightness_gain).
    nl_factor = max(0, 1 - exposure * outdoor_normalized * brightness_gain)
    """

    def test_no_exposure_returns_one(self):
        """Zero exposure = no reduction regardless of outdoor intensity."""
        assert calculate_natural_light_factor(0.0, 1.0, 5.0) == 1.0

    def test_no_outdoor_returns_one(self):
        """No outdoor light = no reduction regardless of exposure."""
        assert calculate_natural_light_factor(1.0, 0.0, 5.0) == 1.0

    def test_full_sun_full_exposure_gain5(self):
        """Full sun + full exposure + gain 5 → clamped to 0.0."""
        # 1 - 1.0 * 1.0 * 5.0 = -4.0 → clamped to 0.0
        factor = calculate_natural_light_factor(1.0, 1.0, 5.0)
        assert factor == 0.0

    def test_half_exposure_full_sun_gain5(self):
        """Half exposure + full sun + gain 5 → 1 - 0.5 * 1.0 * 5.0 = -1.5 → 0.0."""
        factor = calculate_natural_light_factor(0.5, 1.0, 5.0)
        assert factor == 0.0

    def test_moderate_values(self):
        """Half exposure + half outdoor + gain 2 → 1 - 0.5 * 0.5 * 2.0 = 0.5."""
        factor = calculate_natural_light_factor(0.5, 0.5, 2.0)
        assert factor == pytest.approx(0.5, abs=0.01)

    def test_gain_one_full_exposure_full_sun(self):
        """Gain 1 + full exposure + full sun → 1 - 1.0 * 1.0 * 1.0 = 0.0."""
        factor = calculate_natural_light_factor(1.0, 1.0, 1.0)
        assert factor == 0.0

    def test_low_outdoor_low_gain(self):
        """Low outdoor + low gain → minimal reduction."""
        # 1 - 0.3 * 0.2 * 1.0 = 0.94
        factor = calculate_natural_light_factor(0.3, 0.2, 1.0)
        assert factor == pytest.approx(0.94, abs=0.01)

    def test_result_never_negative(self):
        """Factor should never go below 0.0."""
        factor = calculate_natural_light_factor(1.0, 1.0, 100.0)
        assert factor == 0.0

    def test_default_gain(self):
        """Default gain is 5.0."""
        factor = calculate_natural_light_factor(0.5, 0.5)
        # 1 - 0.5 * 0.5 * 5.0 = 1 - 1.25 = -0.25 → 0.0
        assert factor == 0.0


class TestApplyLightFilterPipeline:
    """Tests for apply_light_filter_pipeline()."""

    STANDARD = {"at_bright": 100, "at_dim": 100}
    OVERHEAD = {"at_bright": 100, "at_dim": 0}
    LAMP = {"at_bright": 30, "at_dim": 100}
    ACCENT = {"at_bright": 50, "at_dim": 50}
    NIGHTLIGHT = {"at_bright": 0, "at_dim": 40}

    # --- Standard preset ---

    def test_standard_passthrough(self):
        """Standard preset with factor 1.0 → unchanged brightness."""
        bri, off = apply_light_filter_pipeline(50, 1, 100, 1.0, self.STANDARD, 3)
        assert bri == 50
        assert off is False

    def test_standard_at_max(self):
        bri, off = apply_light_filter_pipeline(100, 1, 100, 1.0, self.STANDARD, 3)
        assert bri == 100
        assert off is False

    def test_standard_at_min(self):
        bri, off = apply_light_filter_pipeline(1, 1, 100, 1.0, self.STANDARD, 3)
        assert bri == 0  # below threshold returns 0
        assert off is True  # 1 < 3 threshold

    # --- Area brightness factor ---

    def test_area_factor_reduction(self):
        # 80 * 0.5 = 40
        bri, off = apply_light_filter_pipeline(80, 1, 100, 0.5, self.STANDARD, 3)
        assert bri == 40
        assert off is False

    def test_area_factor_boost(self):
        # 80 * 1.3 = 104 → capped at 100
        bri, off = apply_light_filter_pipeline(80, 1, 100, 1.3, self.STANDARD, 3)
        assert bri == 100
        assert off is False

    def test_area_factor_triggers_off(self):
        # 5 * 0.5 = 2.5 < 3 → off
        bri, off = apply_light_filter_pipeline(5, 1, 100, 0.5, self.STANDARD, 3)
        assert bri == 0
        assert off is True

    # --- Overhead preset ---

    def test_overhead_at_full_brightness(self):
        """At max brightness, overhead = full (multiplier 1.0)."""
        bri, off = apply_light_filter_pipeline(100, 1, 100, 1.0, self.OVERHEAD, 3)
        assert bri == 100
        assert off is False

    def test_overhead_at_min_brightness(self):
        """At min brightness, overhead multiplier = 0 → off."""
        bri, off = apply_light_filter_pipeline(1, 1, 100, 1.0, self.OVERHEAD, 3)
        assert bri == 0
        assert off is True

    def test_overhead_midpoint(self):
        """At midpoint brightness, overhead = ~50% multiplier."""
        # brightness=50, range 1-100, pos≈0.495, multiplier≈0.495
        # result = 50 * 1.0 * 0.495 ≈ 24.7 → 25
        bri, off = apply_light_filter_pipeline(50, 1, 100, 1.0, self.OVERHEAD, 3)
        assert off is False
        assert 24 <= bri <= 26  # approximately 25

    # --- Lamp preset ---

    def test_lamp_at_dim(self):
        """At min brightness, lamp multiplier = 1.0."""
        # brightness=1, pos=0.0, multiplier=100/100=1.0, result=1*1.0*1.0=1 < 3 → off
        bri, off = apply_light_filter_pipeline(1, 1, 100, 1.0, self.LAMP, 3)
        assert off is True

    def test_lamp_at_bright(self):
        """At max brightness, lamp multiplier = 0.3."""
        # brightness=100, pos=1.0, multiplier=30/100=0.3, result=100*1.0*0.3=30
        bri, off = apply_light_filter_pipeline(100, 1, 100, 1.0, self.LAMP, 3)
        assert bri == 30
        assert off is False

    def test_lamp_midpoint(self):
        """Lamp at midpoint: multiplier interpolates between 100 and 30."""
        bri, off = apply_light_filter_pipeline(50, 1, 100, 1.0, self.LAMP, 3)
        assert off is False
        # pos≈0.495, multiplier≈100+(30-100)*0.495 = 100-34.65 = 65.35/100 = 0.6535
        # result = 50 * 0.6535 ≈ 32.7 → 33
        assert 32 <= bri <= 34

    # --- Accent preset ---

    def test_accent_always_half(self):
        """Accent is 50/50 → always 0.5 multiplier."""
        bri, off = apply_light_filter_pipeline(80, 1, 100, 1.0, self.ACCENT, 3)
        assert bri == 40
        assert off is False

    def test_accent_at_max(self):
        bri, off = apply_light_filter_pipeline(100, 1, 100, 1.0, self.ACCENT, 3)
        assert bri == 50
        assert off is False

    # --- Nightlight preset ---

    def test_nightlight_at_dim(self):
        """At min brightness, nightlight multiplier = 0.4."""
        # brightness=1, pos=0.0, multiplier=40/100=0.4, result=1*0.4=0.4 < 3 → off
        bri, off = apply_light_filter_pipeline(1, 1, 100, 1.0, self.NIGHTLIGHT, 3)
        assert off is True

    def test_nightlight_at_bright(self):
        """At max brightness, nightlight multiplier = 0 → off."""
        bri, off = apply_light_filter_pipeline(100, 1, 100, 1.0, self.NIGHTLIGHT, 3)
        assert bri == 0
        assert off is True

    def test_nightlight_low_brightness(self):
        """Nightlight at low brightness has noticeable output."""
        # brightness=10, range 1-100, pos≈0.091
        # multiplier = (40 + (0-40)*0.091)/100 = (40-3.64)/100 = 0.3636
        # result = 10 * 0.3636 ≈ 3.6 → 4
        bri, off = apply_light_filter_pipeline(10, 1, 100, 1.0, self.NIGHTLIGHT, 3)
        assert off is False
        assert 3 <= bri <= 5

    # --- Off threshold ---

    def test_off_threshold_exact(self):
        """Brightness exactly at threshold is NOT turned off."""
        # Use Standard so multiplier is 1.0; factor=1.0; brightness=3 → result=3 == threshold
        bri, off = apply_light_filter_pipeline(3, 1, 100, 1.0, self.STANDARD, 3)
        assert bri == 3
        assert off is False

    def test_off_threshold_just_below(self):
        """Brightness just below threshold → off."""
        bri, off = apply_light_filter_pipeline(2, 1, 100, 1.0, self.STANDARD, 3)
        assert bri == 0
        assert off is True

    def test_off_threshold_zero(self):
        """Threshold 0 → nothing is turned off (except 0 brightness)."""
        bri, off = apply_light_filter_pipeline(1, 1, 100, 1.0, self.STANDARD, 0)
        assert bri == 1
        assert off is False

    # --- Cap at 100 ---

    def test_capped_at_100(self):
        """High area factor + high preset → capped at 100."""
        boosted = {"at_bright": 200, "at_dim": 200}
        bri, off = apply_light_filter_pipeline(80, 1, 100, 1.5, boosted, 3)
        assert bri == 100
        assert off is False

    # --- Missing/partial preset dict ---

    def test_empty_preset_defaults_to_standard(self):
        """Empty preset dict defaults to at_dim=100, at_bright=100."""
        bri, off = apply_light_filter_pipeline(50, 1, 100, 1.0, {}, 3)
        assert bri == 50
        assert off is False

    # --- Combined area factor + filter ---

    def test_combined_factor_and_filter(self):
        """Area factor 0.85 + Overhead at max → 100 * 0.85 * 1.0 = 85."""
        bri, off = apply_light_filter_pipeline(100, 1, 100, 0.85, self.OVERHEAD, 3)
        assert bri == 85
        assert off is False

    def test_combined_factor_and_accent(self):
        """Area factor 1.2 + Accent → 100 * 1.2 * 0.5 = 60."""
        bri, off = apply_light_filter_pipeline(100, 1, 100, 1.2, self.ACCENT, 3)
        assert bri == 60
        assert off is False

    def test_combined_pushes_below_threshold(self):
        """Factor + filter combine to push below threshold → off."""
        # brightness=10, factor=0.5, accent multiplier=0.5 → 10*0.5*0.5=2.5 < 3 → off
        bri, off = apply_light_filter_pipeline(10, 1, 100, 0.5, self.ACCENT, 3)
        assert bri == 0
        assert off is True

    # --- Per-preset off_threshold ---

    def test_preset_off_threshold_turns_off(self):
        """Preset with off_threshold=10 turns off at brightness 9."""
        preset = {"at_bright": 100, "at_dim": 100, "off_threshold": 10}
        bri, off = apply_light_filter_pipeline(9, 1, 100, 1.0, preset, 3)
        assert bri == 0
        assert off is True

    def test_preset_off_threshold_stays_on(self):
        """Preset with off_threshold=10 stays on at brightness 10."""
        preset = {"at_bright": 100, "at_dim": 100, "off_threshold": 10}
        bri, off = apply_light_filter_pipeline(10, 1, 100, 1.0, preset, 3)
        assert bri == 10
        assert off is False

    def test_preset_off_threshold_fallback_to_global(self):
        """Preset without off_threshold key falls back to global value."""
        preset = {"at_bright": 100, "at_dim": 100}
        # Global threshold is 5; brightness 4 should be off
        bri, off = apply_light_filter_pipeline(4, 1, 100, 1.0, preset, 5)
        assert bri == 0
        assert off is True
        # brightness 5 should stay on
        bri, off = apply_light_filter_pipeline(5, 1, 100, 1.0, preset, 5)
        assert bri == 5
        assert off is False

    def test_different_presets_different_thresholds(self):
        """Two presets with different thresholds at the same base brightness."""
        overhead = {"at_bright": 100, "at_dim": 100, "off_threshold": 10}
        lamp = {"at_bright": 100, "at_dim": 100, "off_threshold": 0}
        base = 8
        # Overhead: 8 < 10 → off
        bri, off = apply_light_filter_pipeline(base, 1, 100, 1.0, overhead, 3)
        assert bri == 0
        assert off is True
        # Lamp: 8 >= 0 → stays on
        bri, off = apply_light_filter_pipeline(base, 1, 100, 1.0, lamp, 3)
        assert bri == 8
        assert off is False

    def test_preset_off_threshold_zero_nothing_off(self):
        """Preset with off_threshold=0 never turns off (even at brightness 1)."""
        preset = {"at_bright": 100, "at_dim": 100, "off_threshold": 0}
        bri, off = apply_light_filter_pipeline(1, 1, 100, 1.0, preset, 3)
        assert bri == 1
        assert off is False
