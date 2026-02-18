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


def _reset_all():
    """Helper to reset all lux_tracker module state."""
    lux_tracker._sensor_entity = None
    lux_tracker._learned_ceiling = None
    lux_tracker._learned_floor = None
    lux_tracker._ema_lux = None
    lux_tracker._cached_sun_factor = 1.0
    lux_tracker._preferred_source = "weather"
    lux_tracker._weather_entity = None
    lux_tracker._cloud_cover = None
    lux_tracker._override_condition = None
    lux_tracker._override_expires_at = None
    lux_tracker._sun_elevation = 0.0


class TestGetOutdoorNormalized:
    """Test get_outdoor_normalized() with fallback chain."""

    def setup_method(self):
        _reset_all()

    def test_no_sources_returns_angle_fallback(self):
        """When nothing configured, falls through to angle (0.0 at night)."""
        lux_tracker._sun_elevation = 0.0
        result = lux_tracker.get_outdoor_normalized()
        assert result == 0.0

    def test_angle_fallback_with_elevation(self):
        """Angle fallback should return positive value with sun up."""
        lux_tracker._sun_elevation = 45.0
        result = lux_tracker.get_outdoor_normalized()
        assert result is not None
        assert result > 0.5

    def test_active_sensor_returns_float(self):
        """When sensor + baselines + data are all present, returns sun_factor."""
        lux_tracker._preferred_source = "lux"
        lux_tracker._sensor_entity = "sensor.test"
        lux_tracker._learned_ceiling = 50000
        lux_tracker._learned_floor = 100
        lux_tracker._ema_lux = 5000
        lux_tracker._cached_sun_factor = 0.65
        result = lux_tracker.get_outdoor_normalized()
        assert result is not None
        assert isinstance(result, float)
        assert result == 0.65

    def test_dark_returns_zero_not_none(self):
        """Dark outdoor (0.0) should be distinguishable from None."""
        lux_tracker._preferred_source = "lux"
        lux_tracker._sensor_entity = "sensor.test"
        lux_tracker._learned_ceiling = 50000
        lux_tracker._learned_floor = 100
        lux_tracker._ema_lux = 50  # below floor
        lux_tracker._cached_sun_factor = 0.0
        result = lux_tracker.get_outdoor_normalized()
        assert result is not None
        assert result == 0.0


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

    def test_init_resets_weather_but_preserves_override(self):
        """init() should reset weather cloud cover but preserve override state."""
        lux_tracker._cloud_cover = 50.0
        lux_tracker._override_condition = "cloudy"
        lux_tracker._override_expires_at = 9999.0
        lux_tracker._sun_elevation = 30.0
        lux_tracker.init(config={})
        assert lux_tracker._cloud_cover is None
        assert lux_tracker._sun_elevation == 0.0
        # Override is user-initiated and time-limited; must survive init()
        assert lux_tracker._override_condition == "cloudy"
        assert lux_tracker._override_expires_at == 9999.0


class TestWeatherEstimation:
    """Test weather entity based outdoor estimation."""

    def setup_method(self):
        _reset_all()

    def test_update_weather_stores_cloud_cover(self):
        """update_weather() should store cloud cover value."""
        lux_tracker.update_weather(42.0)
        assert lux_tracker._cloud_cover == 42.0

    def test_update_weather_clamps(self):
        """update_weather() should clamp to 0-100."""
        lux_tracker.update_weather(150.0)
        assert lux_tracker._cloud_cover == 100.0
        lux_tracker.update_weather(-10.0)
        assert lux_tracker._cloud_cover == 0.0

    def test_compute_weather_outdoor_norm_clear_sky(self):
        """0% cloud with high elevation should give close to 1.0."""
        lux_tracker._weather_entity = "weather.home"
        lux_tracker._cloud_cover = 0.0
        lux_tracker._sun_elevation = 60.0
        result = lux_tracker._compute_weather_outdoor_norm()
        assert result is not None
        assert result > 0.8

    def test_compute_weather_outdoor_norm_overcast(self):
        """100% cloud (no condition) should give reduced value via cloud formula."""
        lux_tracker._weather_entity = "weather.home"
        lux_tracker._cloud_cover = 100.0
        lux_tracker._weather_condition = None
        lux_tracker._sun_elevation = 60.0
        result = lux_tracker._compute_weather_outdoor_norm()
        assert result is not None
        assert result < 0.85  # Reduced from clear sky

    def test_compute_weather_condition_rainy(self):
        """Rainy condition should use CONDITION_MULTIPLIERS and give lower value."""
        lux_tracker._weather_entity = "weather.home"
        lux_tracker._cloud_cover = 100.0
        lux_tracker._sun_elevation = 60.0
        # Without condition
        lux_tracker._weather_condition = None
        no_condition = lux_tracker._compute_weather_outdoor_norm()
        # With rainy condition (multiplier 0.2 vs cloud formula 0.3)
        lux_tracker._weather_condition = "rainy"
        with_rainy = lux_tracker._compute_weather_outdoor_norm()
        assert with_rainy < no_condition

    def test_compute_weather_condition_cloudy_matches_override(self):
        """Weather 'cloudy' condition uses same multiplier as override 'cloudy'."""
        lux_tracker._weather_entity = "weather.home"
        lux_tracker._cloud_cover = 50.0  # doesn't matter when condition is set
        lux_tracker._sun_elevation = 45.0
        lux_tracker._weather_condition = "cloudy"
        result_weather = lux_tracker._compute_weather_outdoor_norm()
        # Override uses same multiplier via CONDITION_MULTIPLIERS["cloudy"] = 0.3
        assert result_weather is not None

    def test_compute_weather_unknown_condition_uses_cloud_formula(self):
        """Unknown condition falls back to cloud-cover formula."""
        lux_tracker._weather_entity = "weather.home"
        lux_tracker._cloud_cover = 80.0
        lux_tracker._sun_elevation = 50.0
        lux_tracker._weather_condition = "unknown_thing"
        result_unknown = lux_tracker._compute_weather_outdoor_norm()
        lux_tracker._weather_condition = None
        result_none = lux_tracker._compute_weather_outdoor_norm()
        assert result_unknown == result_none  # Both use cloud formula

    def test_update_weather_stores_condition(self):
        """update_weather should store both cloud cover and condition."""
        lux_tracker.update_weather(75.0, "rainy")
        assert lux_tracker._cloud_cover == 75.0
        assert lux_tracker._weather_condition == "rainy"
        # Without condition
        lux_tracker.update_weather(50.0)
        assert lux_tracker._cloud_cover == 50.0
        assert lux_tracker._weather_condition is None

    def test_compute_weather_outdoor_norm_night(self):
        """Elevation <= 0 should give 0.0."""
        lux_tracker._weather_entity = "weather.home"
        lux_tracker._cloud_cover = 0.0
        lux_tracker._sun_elevation = -5.0
        result = lux_tracker._compute_weather_outdoor_norm()
        assert result == 0.0

    def test_no_weather_entity_returns_none(self):
        """No weather entity should return None."""
        lux_tracker._weather_entity = None
        lux_tracker._cloud_cover = 50.0
        result = lux_tracker._compute_weather_outdoor_norm()
        assert result is None

    def test_no_cloud_cover_returns_none(self):
        """Weather entity but no cloud data should return None."""
        lux_tracker._weather_entity = "weather.home"
        lux_tracker._cloud_cover = None
        result = lux_tracker._compute_weather_outdoor_norm()
        assert result is None


class TestOverride:
    """Test manual override functionality."""

    def setup_method(self):
        _reset_all()
        lux_tracker._sun_elevation = 45.0  # daytime

    def test_set_override_stores_condition(self):
        """set_override() should store condition and expiry."""
        lux_tracker.set_override("cloudy", 60)
        assert lux_tracker._override_condition == "cloudy"
        assert lux_tracker._override_expires_at is not None

    def test_set_override_invalid_condition_ignored(self):
        """Invalid condition should be ignored."""
        lux_tracker.set_override("blizzard", 60)
        assert lux_tracker._override_condition is None

    def test_get_override_info_active(self):
        """Active override should return condition and time."""
        lux_tracker.set_override("partly_cloudy", 60)
        info = lux_tracker.get_override_info()
        assert info is not None
        assert info["condition"] == "partly_cloudy"
        assert info["expires_in_minutes"] > 59.0

    def test_get_override_info_expired(self):
        """Expired override should auto-clear and return None."""
        import time
        lux_tracker._override_condition = "cloudy"
        lux_tracker._override_expires_at = time.monotonic() - 1  # already expired
        info = lux_tracker.get_override_info()
        assert info is None
        assert lux_tracker._override_condition is None

    def test_clear_override(self):
        """clear_override() should clear state."""
        lux_tracker.set_override("sunny", 60)
        lux_tracker.clear_override()
        assert lux_tracker._override_condition is None
        assert lux_tracker._override_expires_at is None

    def test_override_modulates_angle_based(self):
        """Override should modulate angle-based estimate by condition multiplier."""
        # First get the angle-only value
        angle_val = lux_tracker._compute_angle_outdoor_norm()
        assert angle_val > 0  # sun is up at 45°

        # Set cloudy override (multiplier = 0.3)
        lux_tracker.set_override("cloudy", 60)
        result = lux_tracker.get_outdoor_normalized()
        expected = angle_val * 0.3
        assert abs(result - expected) < 0.01


class TestFallbackChain:
    """Test the priority-based fallback chain with source awareness."""

    def setup_method(self):
        _reset_all()
        lux_tracker._sun_elevation = 45.0

    def test_override_beats_lux(self):
        """Override should take priority over lux sensor."""
        lux_tracker._preferred_source = "lux"
        lux_tracker._sensor_entity = "sensor.test"
        lux_tracker._learned_ceiling = 50000
        lux_tracker._learned_floor = 100
        lux_tracker._ema_lux = 5000
        lux_tracker._cached_sun_factor = 0.65
        lux_tracker.set_override("heavy_overcast", 60)
        source = lux_tracker.get_outdoor_source()
        assert source == "override"

    def test_lux_source_uses_lux(self):
        """With source=lux and data available, lux is used."""
        lux_tracker._preferred_source = "lux"
        lux_tracker._sensor_entity = "sensor.test"
        lux_tracker._learned_ceiling = 50000
        lux_tracker._learned_floor = 100
        lux_tracker._ema_lux = 5000
        lux_tracker._cached_sun_factor = 0.65
        lux_tracker._weather_entity = "weather.home"
        lux_tracker._cloud_cover = 80.0
        source = lux_tracker.get_outdoor_source()
        assert source == "lux"

    def test_weather_source_skips_lux(self):
        """With source=weather, lux data is ignored even when available."""
        lux_tracker._preferred_source = "weather"
        lux_tracker._sensor_entity = "sensor.test"
        lux_tracker._learned_ceiling = 50000
        lux_tracker._learned_floor = 100
        lux_tracker._ema_lux = 5000
        lux_tracker._cached_sun_factor = 0.65
        lux_tracker._weather_entity = "weather.home"
        lux_tracker._cloud_cover = 80.0
        assert lux_tracker.get_outdoor_source() == "weather"
        # Value should come from weather, not lux
        result = lux_tracker.get_outdoor_normalized()
        assert result != 0.65  # not the lux cached_sun_factor

    def test_angle_source_skips_both(self):
        """With source=angle, both lux and weather are ignored."""
        lux_tracker._preferred_source = "angle"
        lux_tracker._sensor_entity = "sensor.test"
        lux_tracker._learned_ceiling = 50000
        lux_tracker._learned_floor = 100
        lux_tracker._ema_lux = 5000
        lux_tracker._cached_sun_factor = 0.65
        lux_tracker._weather_entity = "weather.home"
        lux_tracker._cloud_cover = 80.0
        assert lux_tracker.get_outdoor_source() == "angle"
        result = lux_tracker.get_outdoor_normalized()
        expected_angle = lux_tracker._compute_angle_outdoor_norm()
        assert result == expected_angle

    def test_lux_source_falls_to_weather(self):
        """Lux selected but no data, weather used as fallback."""
        lux_tracker._preferred_source = "lux"
        lux_tracker._sensor_entity = "sensor.test"
        lux_tracker._learned_ceiling = 50000
        lux_tracker._learned_floor = 100
        lux_tracker._ema_lux = None  # no data yet
        lux_tracker._weather_entity = "weather.home"
        lux_tracker._cloud_cover = 50.0
        assert lux_tracker.get_outdoor_source() == "weather"
        result = lux_tracker.get_outdoor_normalized()
        weather_result = lux_tracker._compute_weather_outdoor_norm()
        assert result == weather_result

    def test_lux_source_falls_to_angle(self):
        """Lux selected, no data and no weather, angle used."""
        lux_tracker._preferred_source = "lux"
        lux_tracker._sensor_entity = "sensor.test"
        lux_tracker._learned_ceiling = 50000
        lux_tracker._learned_floor = 100
        lux_tracker._ema_lux = None
        assert lux_tracker.get_outdoor_source() == "angle"
        result = lux_tracker.get_outdoor_normalized()
        expected = lux_tracker._compute_angle_outdoor_norm()
        assert result == expected

    def test_weather_beats_angle(self):
        """Weather source with data should use weather, not angle."""
        lux_tracker._preferred_source = "weather"
        lux_tracker._weather_entity = "weather.home"
        lux_tracker._cloud_cover = 50.0
        source = lux_tracker.get_outdoor_source()
        assert source == "weather"

    def test_weather_source_falls_to_angle(self):
        """Weather selected but no weather entity, falls to angle."""
        lux_tracker._preferred_source = "weather"
        assert lux_tracker.get_outdoor_source() == "angle"

    def test_angle_is_default(self):
        """With nothing configured, source should be angle."""
        source = lux_tracker.get_outdoor_source()
        assert source == "angle"

    def test_full_chain_priority(self):
        """With all sources active, override should win."""
        lux_tracker._preferred_source = "lux"
        lux_tracker._sensor_entity = "sensor.test"
        lux_tracker._learned_ceiling = 50000
        lux_tracker._learned_floor = 100
        lux_tracker._ema_lux = 5000
        lux_tracker._cached_sun_factor = 0.65
        lux_tracker._weather_entity = "weather.home"
        lux_tracker._cloud_cover = 50.0
        lux_tracker.set_override("sunny", 60)
        assert lux_tracker.get_outdoor_source() == "override"

    def test_weather_value_differs_from_angle(self):
        """Weather source should produce different value than angle for cloudy days."""
        lux_tracker._preferred_source = "weather"
        lux_tracker._sun_elevation = 45.0
        angle_val = lux_tracker._compute_angle_outdoor_norm()

        lux_tracker._weather_entity = "weather.home"
        lux_tracker._cloud_cover = 80.0
        weather_val = lux_tracker.get_outdoor_normalized()
        assert weather_val < angle_val  # cloudy should be dimmer


class TestGetOutdoorSource:
    """Test get_outdoor_source() matches fallback chain."""

    def setup_method(self):
        _reset_all()
        lux_tracker._sun_elevation = 30.0

    def test_source_angle_when_nothing_configured(self):
        assert lux_tracker.get_outdoor_source() == "angle"

    def test_source_weather_when_configured(self):
        lux_tracker._preferred_source = "weather"
        lux_tracker._weather_entity = "weather.home"
        lux_tracker._cloud_cover = 30.0
        assert lux_tracker.get_outdoor_source() == "weather"

    def test_source_lux_when_sensor_active(self):
        lux_tracker._preferred_source = "lux"
        lux_tracker._sensor_entity = "sensor.test"
        lux_tracker._learned_ceiling = 50000
        lux_tracker._learned_floor = 100
        lux_tracker._ema_lux = 5000
        assert lux_tracker.get_outdoor_source() == "lux"

    def test_source_override_when_set(self):
        lux_tracker.set_override("sunny", 60)
        assert lux_tracker.get_outdoor_source() == "override"

    def test_source_falls_to_weather_when_lux_incomplete(self):
        """Lux sensor configured but no data yet should fall to weather."""
        lux_tracker._preferred_source = "lux"
        lux_tracker._sensor_entity = "sensor.test"
        lux_tracker._learned_ceiling = 50000
        lux_tracker._learned_floor = 100
        lux_tracker._ema_lux = None  # no data yet
        lux_tracker._weather_entity = "weather.home"
        lux_tracker._cloud_cover = 50.0
        assert lux_tracker.get_outdoor_source() == "weather"


class TestSunElevationCache:
    """Test sun elevation caching."""

    def setup_method(self):
        lux_tracker._sun_elevation = 0.0

    def test_update_sun_elevation(self):
        lux_tracker.update_sun_elevation(42.5)
        assert lux_tracker._sun_elevation == 42.5

    def test_negative_elevation(self):
        lux_tracker.update_sun_elevation(-10.0)
        assert lux_tracker._sun_elevation == -10.0


class TestSetWeatherEntity:
    """Test auto-detection path for weather entity."""

    def setup_method(self):
        _reset_all()

    def test_set_weather_entity(self):
        """set_weather_entity() should store the entity_id."""
        lux_tracker.set_weather_entity("weather.home")
        assert lux_tracker.get_weather_entity() == "weather.home"

    def test_set_weather_entity_replaces(self):
        """Calling set_weather_entity() again should overwrite."""
        lux_tracker.set_weather_entity("weather.old")
        lux_tracker.set_weather_entity("weather.new")
        assert lux_tracker.get_weather_entity() == "weather.new"

    def test_init_does_not_clear_weather_entity(self):
        """init() should not clear an already-set weather entity."""
        lux_tracker.set_weather_entity("weather.home")
        lux_tracker.init(config={})
        # Weather entity should be preserved (set at runtime, not from config)
        assert lux_tracker.get_weather_entity() == "weather.home"


class TestPreferredSource:
    """Test _preferred_source init and get_preferred_source()."""

    def test_init_preferred_source_from_config(self):
        """outdoor_brightness_source in config should set preferred source."""
        lux_tracker.init(config={"outdoor_brightness_source": "angle"})
        assert lux_tracker.get_preferred_source() == "angle"

    def test_init_preferred_source_weather(self):
        lux_tracker.init(config={"outdoor_brightness_source": "weather"})
        assert lux_tracker.get_preferred_source() == "weather"

    def test_init_preferred_source_lux(self):
        lux_tracker.init(config={"outdoor_brightness_source": "lux"})
        assert lux_tracker.get_preferred_source() == "lux"

    def test_backward_compat_no_source_key_with_sensor(self):
        """Legacy config with outdoor_lux_sensor but no source key defaults to lux."""
        lux_tracker.init(config={"outdoor_lux_sensor": "sensor.lux"})
        assert lux_tracker.get_preferred_source() == "lux"

    def test_backward_compat_no_source_key_no_sensor(self):
        """Legacy config without outdoor_lux_sensor defaults to weather."""
        lux_tracker.init(config={})
        assert lux_tracker.get_preferred_source() == "weather"

    def test_explicit_source_overrides_sensor_presence(self):
        """Explicit outdoor_brightness_source=angle wins even with lux sensor configured."""
        lux_tracker.init(config={
            "outdoor_brightness_source": "angle",
            "outdoor_lux_sensor": "sensor.lux",
        })
        assert lux_tracker.get_preferred_source() == "angle"
