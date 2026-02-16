#!/usr/bin/env python3
"""Tests for lux_tracker module."""

import math
import pytest

import lux_tracker


class TestComputeSunFactor:
    """Test the pure compute_sun_factor function."""

    def test_bright_day_returns_one(self):
        """Lux at ceiling should give sun_factor ~1.0."""
        assert lux_tracker.compute_sun_factor(50000, ceiling=50000, floor=100) == 1.0

    def test_above_ceiling_clamped(self):
        """Lux above ceiling still returns 1.0."""
        assert lux_tracker.compute_sun_factor(80000, ceiling=50000, floor=100) == 1.0

    def test_dark_returns_zero(self):
        """Lux at or below floor should give sun_factor ~0.0."""
        assert lux_tracker.compute_sun_factor(100, ceiling=50000, floor=100) == 0.0

    def test_below_floor_clamped(self):
        """Lux below floor returns 0.0."""
        assert lux_tracker.compute_sun_factor(10, ceiling=50000, floor=100) == 0.0

    def test_mid_range_between_zero_and_one(self):
        """Mid-range lux should give factor between 0 and 1."""
        factor = lux_tracker.compute_sun_factor(5000, ceiling=50000, floor=100)
        assert 0.0 < factor < 1.0

    def test_log_scale_midpoint(self):
        """Geometric mean of ceiling and floor should give ~0.5."""
        ceiling = 50000
        floor = 100
        geometric_mean = math.sqrt(ceiling * floor)
        factor = lux_tracker.compute_sun_factor(
            geometric_mean, ceiling=ceiling, floor=floor
        )
        assert abs(factor - 0.5) < 0.01

    def test_zero_lux_gives_zero(self):
        """Zero lux should give 0.0 (clamped via max(1, lux))."""
        factor = lux_tracker.compute_sun_factor(0, ceiling=50000, floor=100)
        assert factor == 0.0

    def test_ceiling_equals_floor_returns_one(self):
        """When ceiling == floor, should return 1.0 (safe fallback)."""
        assert lux_tracker.compute_sun_factor(5000, ceiling=100, floor=100) == 1.0

    def test_ceiling_less_than_floor_returns_one(self):
        """Bad baselines should return 1.0 fallback."""
        assert lux_tracker.compute_sun_factor(5000, ceiling=50, floor=100) == 1.0

    def test_negative_ceiling_returns_one(self):
        """Negative ceiling should return 1.0 fallback."""
        assert lux_tracker.compute_sun_factor(5000, ceiling=-100, floor=100) == 1.0


class TestEmaSmoothing:
    """Test update() EMA smoothing behaviour."""

    def setup_method(self):
        """Reset module state before each test."""
        lux_tracker._ema_lux = None
        lux_tracker._last_update_time = None
        lux_tracker._cached_sun_factor = 1.0
        lux_tracker._sensor_entity = "sensor.test"
        lux_tracker._learned_ceiling = 50000
        lux_tracker._learned_floor = 100

    def test_first_reading_seeds_directly(self):
        """First reading should set EMA directly (no smoothing)."""
        lux_tracker._smoothing_interval = 300
        result = lux_tracker.update(10000)
        assert result == 10000

    def test_smoothing_dampens_spikes(self):
        """Smoothing should dampen sudden spikes."""
        lux_tracker._smoothing_interval = 300

        lux_tracker.update(10000)
        # Second reading shortly after — should be dampened
        import time

        lux_tracker._last_update_time = time.monotonic() - 1  # 1 second ago
        result = lux_tracker.update(50000)

        # Should be between 10000 and 50000, much closer to 10000
        assert 10000 < result < 50000
        assert result < 15000  # With 1s elapsed / 300s interval, alpha ≈ 0.003

    def test_interval_zero_uses_raw(self):
        """With smoothing_interval=0, should use raw value directly."""
        lux_tracker._smoothing_interval = 0

        lux_tracker.update(10000)
        result = lux_tracker.update(50000)
        assert result == 50000

    def test_sun_factor_updated_after_update(self):
        """sun_factor should be recomputed after each update()."""
        lux_tracker._smoothing_interval = 0

        lux_tracker.update(50000)  # bright
        assert lux_tracker.get_sun_factor() == 1.0

        lux_tracker.update(50)  # dark (below floor)
        assert lux_tracker.get_sun_factor() == 0.0


class TestFallback:
    """Test fallback behaviour when no sensor configured."""

    def test_no_sensor_returns_one(self):
        """When no sensor configured, sun_factor should be 1.0."""
        lux_tracker._sensor_entity = None
        lux_tracker._cached_sun_factor = 1.0
        assert lux_tracker.get_sun_factor() == 1.0

    def test_no_baselines_returns_one(self):
        """When baselines not set, sun_factor should stay 1.0."""
        lux_tracker._sensor_entity = "sensor.test"
        lux_tracker._learned_ceiling = None
        lux_tracker._learned_floor = None
        lux_tracker._smoothing_interval = 0
        lux_tracker._ema_lux = None
        lux_tracker._last_update_time = None
        lux_tracker._cached_sun_factor = 1.0

        lux_tracker.update(5000)
        assert lux_tracker.get_sun_factor() == 1.0

    def test_init_with_no_config_defaults(self):
        """init() with empty config should default to no sensor."""
        lux_tracker.init(config={})
        assert lux_tracker.get_sun_factor() == 1.0
        assert lux_tracker.get_sensor_entity() is None

    def test_init_with_sensor_config(self):
        """init() with sensor config should set entity."""
        lux_tracker.init(
            config={
                "outdoor_lux_sensor": "sensor.outdoor_illuminance",
                "lux_smoothing_interval": 600,
                "lux_learned_ceiling": 40000,
                "lux_learned_floor": 200,
            }
        )
        assert lux_tracker.get_sensor_entity() == "sensor.outdoor_illuminance"
        assert lux_tracker._smoothing_interval == 600.0
        assert lux_tracker._learned_ceiling == 40000.0
        assert lux_tracker._learned_floor == 200.0

    def test_init_with_string_baselines(self):
        """init() should handle string values from UI."""
        lux_tracker.init(
            config={
                "outdoor_lux_sensor": "sensor.lux",
                "lux_learned_ceiling": "50000",
                "lux_learned_floor": "100",
            }
        )
        assert lux_tracker._learned_ceiling == 50000.0
        assert lux_tracker._learned_floor == 100.0
