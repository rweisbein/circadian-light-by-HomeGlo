#!/usr/bin/env python3
"""Test step calculation functions in brain.py."""

import pytest
from brain import CircadianLight, Config, AreaState, SunTimes


class TestCalculateColorStep:
    """Test calculate_color_step (color only)."""

    @pytest.fixture
    def config(self):
        """Standard test config."""
        return Config(
            ascend_start=6.0,
            descend_start=18.0,
            wake_time=8.0,
            bed_time=22.0,
            min_brightness=10,
            max_brightness=100,
            min_color_temp=2700,
            max_color_temp=6500,
            max_dim_steps=10
        )

    def test_color_step_only_updates_color_mid(self, config):
        """Test color step only updates color_mid, not brightness_mid."""
        state = AreaState()

        result = CircadianLight.calculate_color_step(8.0, "up", config, state)

        assert result is not None
        assert "color_mid" in result.state_updates
        assert "brightness_mid" not in result.state_updates

    def test_color_step_up_increases_color_temp(self, config):
        """Test color step up increases color temperature (cooler)."""
        state = AreaState()

        current_color = CircadianLight.calculate_color_at_hour(8.0, config, state)
        result = CircadianLight.calculate_color_step(8.0, "up", config, state)

        assert result is not None
        assert result.color_temp > current_color

    def test_color_step_down_decreases_color_temp(self, config):
        """Test color step down decreases color temperature (warmer)."""
        state = AreaState()

        current_color = CircadianLight.calculate_color_at_hour(8.0, config, state)
        result = CircadianLight.calculate_color_step(8.0, "down", config, state)

        assert result is not None
        assert result.color_temp < current_color

    def test_color_step_preserves_brightness(self, config):
        """Test color step doesn't change brightness output."""
        state = AreaState()

        current_bri = CircadianLight.calculate_brightness_at_hour(8.0, config, state)
        result = CircadianLight.calculate_color_step(8.0, "up", config, state)

        assert result is not None
        assert result.brightness == current_bri

class TestStepResult:
    """Test StepResult structure."""

    def test_step_result_has_all_fields(self):
        """Test StepResult contains all required fields."""
        config = Config(max_dim_steps=10)
        state = AreaState()

        result = CircadianLight.calculate_set_position(12.0, 30, "step", config, state)

        assert result is not None
        assert hasattr(result, "brightness")
        assert hasattr(result, "color_temp")
        assert hasattr(result, "rgb")
        assert hasattr(result, "xy")
        assert hasattr(result, "state_updates")

    def test_step_result_rgb_is_valid(self):
        """Test StepResult RGB values are valid."""
        config = Config(max_dim_steps=10)
        state = AreaState()

        result = CircadianLight.calculate_set_position(12.0, 30, "step", config, state)

        assert result is not None
        r, g, b = result.rgb
        assert 0 <= r <= 255
        assert 0 <= g <= 255
        assert 0 <= b <= 255

    def test_step_result_xy_is_valid(self):
        """Test StepResult XY values are valid."""
        config = Config(max_dim_steps=10)
        state = AreaState()

        result = CircadianLight.calculate_set_position(12.0, 30, "step", config, state)

        assert result is not None
        x, y = result.xy
        assert 0 <= x <= 1
        assert 0 <= y <= 1


class TestColorStepWithSolarRules:
    """Test calculate_color_step with active solar rules."""

    @pytest.fixture
    def warm_night_config(self):
        """Config with WarmNight active (clamps CCT down at night)."""
        return Config(
            ascend_start=6.0,
            descend_start=18.0,
            wake_time=8.0,
            bed_time=22.0,
            min_brightness=10,
            max_brightness=100,
            min_color_temp=2700,
            max_color_temp=6500,
            max_dim_steps=10,
            warm_night_enabled=True,
            warm_night_mode="all",
            warm_night_target=2700,
            warm_night_start=-60,
            warm_night_end=60,
            warm_night_fade=60,
            daylight_cct=0,  # Disable daylight blend to isolate warm_night
        )

    @pytest.fixture
    def daylight_config(self):
        """Config with daylight blend active (pushes CCT up during day)."""
        return Config(
            ascend_start=6.0,
            descend_start=18.0,
            wake_time=8.0,
            bed_time=22.0,
            min_brightness=10,
            max_brightness=100,
            min_color_temp=2700,
            max_color_temp=6500,
            max_dim_steps=10,
            daylight_cct=5500,
            color_sensitivity=1.68,
        )

    @pytest.fixture
    def sun_times(self):
        """Default sun times with outdoor light for daylight blend."""
        return SunTimes(outdoor_normalized=1.0)

    def test_step_up_succeeds_during_warm_night(self, warm_night_config, sun_times):
        """Step up (cooler) should succeed when WarmNight is clamping CCT down."""
        state = AreaState()
        hour = 22.0  # Deep in warm night window, full strength

        rendered_before = CircadianLight.calculate_color_at_hour(
            hour, warm_night_config, state, apply_solar_rules=True, sun_times=sun_times
        )

        result = CircadianLight.calculate_color_step(
            hour, "up", warm_night_config, state, sun_times=sun_times
        )

        assert result is not None, (
            f"Step up returned None during WarmNight (rendered={rendered_before}K)"
        )
        assert result.color_temp > rendered_before
        assert "color_override" in result.state_updates
        assert result.state_updates["color_override"] > 0  # Positive = raises warm ceiling

    def test_step_down_succeeds_during_daylight_blend(self, daylight_config, sun_times):
        """Step down (warmer) should succeed when daylight blend is pushing CCT up."""
        state = AreaState()
        hour = 7.5  # Early morning, natural < daylight_cct, outdoor bright

        rendered_before = CircadianLight.calculate_color_at_hour(
            hour, daylight_config, state, apply_solar_rules=True, sun_times=sun_times
        )

        result = CircadianLight.calculate_color_step(
            hour, "down", daylight_config, state, sun_times=sun_times
        )

        assert result is not None, (
            f"Step down returned None during daylight blend (rendered={rendered_before}K)"
        )
        assert result.color_temp < rendered_before
        assert "color_override" in result.state_updates
        assert result.state_updates["color_override"] < 0  # Negative = lowers daylight push

    def test_multiple_steps_up_increase_override(self, warm_night_config, sun_times):
        """Multiple step-ups through WarmNight should increase override."""
        state = AreaState()
        hour = 22.0
        overrides = []

        for _ in range(3):
            result = CircadianLight.calculate_color_step(
                hour, "up", warm_night_config, state, sun_times=sun_times
            )
            assert result is not None
            for key, value in result.state_updates.items():
                setattr(state, key, value)
            overrides.append(state.color_override)

        # Each step should push override higher
        for i in range(len(overrides) - 1):
            assert overrides[i + 1] > overrides[i], (
                f"Override didn't increase: {overrides}"
            )

    def test_stepping_back_reduces_override(self, warm_night_config, sun_times):
        """Color-stepping up then down should reduce override back toward zero."""
        state = AreaState()
        hour = 22.0

        # Step up 3 times to build override
        for _ in range(3):
            result = CircadianLight.calculate_color_step(
                hour, "up", warm_night_config, state, sun_times=sun_times
            )
            assert result is not None
            for key, value in result.state_updates.items():
                setattr(state, key, value)

        peak_override = state.color_override
        assert peak_override is not None and peak_override > 0

        # Step down 3 times — override should shrink
        overrides_down = []
        for _ in range(3):
            result = CircadianLight.calculate_color_step(
                hour, "down", warm_night_config, state, sun_times=sun_times
            )
            assert result is not None
            for key, value in result.state_updates.items():
                setattr(state, key, value)
            overrides_down.append(state.color_override)

        # Override should decrease (or clear to None)
        last = overrides_down[-1]
        assert last is None or last < peak_override, (
            f"Override didn't decrease: peak={peak_override}, after down={overrides_down}"
        )

    def test_no_override_without_solar_rules(self):
        """With no solar rules, stepping should not set color_override."""
        config = Config(
            ascend_start=6.0,
            descend_start=18.0,
            wake_time=8.0,
            bed_time=22.0,
            min_color_temp=2700,
            max_color_temp=6500,
            max_dim_steps=10,
        )
        state = AreaState()

        result = CircadianLight.calculate_color_step(8.0, "up", config, state)

        assert result is not None
        assert "color_override" not in result.state_updates

    def test_at_config_bound_returns_none(self):
        """Step up at max CCT returns None."""
        config = Config(
            ascend_start=6.0,
            descend_start=18.0,
            wake_time=8.0,
            bed_time=22.0,
            min_color_temp=2700,
            max_color_temp=6500,
            max_dim_steps=10,
        )
        state = AreaState()

        # At noon, natural CCT is near max (~6500K)
        result = CircadianLight.calculate_color_step(12.0, "up", config, state)

        assert result is None

    def test_brightness_preserved_with_solar_rules(self, warm_night_config, sun_times):
        """Color step should not change brightness even with solar rules active."""
        state = AreaState()
        hour = 22.0

        bri_before = CircadianLight.calculate_brightness_at_hour(
            hour, warm_night_config, state
        )

        result = CircadianLight.calculate_color_step(
            hour, "up", warm_night_config, state, sun_times=sun_times
        )

        assert result is not None
        assert result.brightness == bri_before


class TestSetPositionWithSolarRules:
    """Test calculate_set_position color dimension with active solar rules."""

    @pytest.fixture
    def warm_night_config(self):
        """Config with WarmNight active."""
        return Config(
            ascend_start=6.0,
            descend_start=18.0,
            wake_time=8.0,
            bed_time=22.0,
            min_brightness=10,
            max_brightness=100,
            min_color_temp=2700,
            max_color_temp=6500,
            max_dim_steps=10,
            warm_night_enabled=True,
            warm_night_mode="all",
            warm_night_target=2700,
            warm_night_start=-60,
            warm_night_end=60,
            warm_night_fade=60,
            daylight_cct=0,  # Disable daylight blend to isolate warm_night
        )

    @pytest.fixture
    def daylight_config(self):
        """Config with daylight blend active."""
        return Config(
            ascend_start=6.0,
            descend_start=18.0,
            wake_time=8.0,
            bed_time=22.0,
            min_brightness=10,
            max_brightness=100,
            min_color_temp=2700,
            max_color_temp=6500,
            max_dim_steps=10,
            daylight_cct=5500,
            color_sensitivity=1.68,
        )

    @pytest.fixture
    def sun_times(self):
        return SunTimes(outdoor_normalized=1.0)

    def test_color_slider_achieves_target_through_warm_night(self, warm_night_config, sun_times):
        """Color slider should reach target CCT even when WarmNight is active."""
        state = AreaState()
        hour = 22.0  # Warm night active

        # Set slider to 75% (should be ~5550K)
        target_cct = 2700 + (6500 - 2700) * 0.75  # 5550K
        result = CircadianLight.calculate_set_position(
            hour, 75, "color", warm_night_config, state, sun_times=sun_times
        )

        # Should achieve close to the target through deficit override
        assert abs(result.color_temp - target_cct) < 100, (
            f"Slider target={target_cct:.0f}K but got {result.color_temp}K"
        )
        # Override should be set (positive to raise warm ceiling)
        assert result.state_updates.get("color_override") is not None
        assert result.state_updates["color_override"] > 0

    def test_color_slider_achieves_target_through_daylight_blend(self, daylight_config, sun_times):
        """Color slider should reach target CCT even when daylight blend is active."""
        state = AreaState()
        hour = 7.5  # Daylight blend active, natural is low

        # Set slider to 25% (should be ~3650K, below daylight_cct of 5500)
        target_cct = 2700 + (6500 - 2700) * 0.25  # 3650K
        result = CircadianLight.calculate_set_position(
            hour, 25, "color", daylight_config, state, sun_times=sun_times
        )

        # Should achieve close to the target through deficit override
        assert abs(result.color_temp - target_cct) < 100, (
            f"Slider target={target_cct:.0f}K but got {result.color_temp}K"
        )
        # Override should be set (negative to lower daylight push)
        assert result.state_updates.get("color_override") is not None
        assert result.state_updates["color_override"] < 0

    def test_color_slider_no_override_without_solar_rules(self):
        """Color slider with no solar rules should set no override."""
        config = Config(
            ascend_start=6.0,
            descend_start=18.0,
            wake_time=8.0,
            bed_time=22.0,
            min_color_temp=2700,
            max_color_temp=6500,
            max_dim_steps=10,
        )
        state = AreaState()

        result = CircadianLight.calculate_set_position(
            8.0, 50, "color", config, state
        )

        assert result.state_updates.get("color_override") is None

    def test_step_slider_no_override_from_scratch(self, warm_night_config, sun_times):
        """Step slider with no existing override should not create one."""
        state = AreaState(color_override=None)
        hour = 22.0

        result = CircadianLight.calculate_set_position(
            hour, 87, "step", warm_night_config, state, sun_times=sun_times
        )

        # Override should stay None — warm night caps naturally
        assert result.state_updates.get("color_override") is None
        assert result.color_temp <= warm_night_config.warm_night_target + 50

    def test_step_slider_recalibrates_existing_override(self, warm_night_config, sun_times):
        """Step slider should recalibrate (not clear) an existing override.

        After color slider sets an override, dragging step slider to a low
        position should reduce the override as the curve target drops below
        warm_night_target.
        """
        state = AreaState(color_override=1500)
        hour = 22.0

        # Drag slider to low position (5%) — natural curve near warm target,
        # override should clear or shrink significantly
        result_low = CircadianLight.calculate_set_position(
            hour, 5, "step", warm_night_config, state, sun_times=sun_times
        )
        override_low = result_low.state_updates.get("color_override", state.color_override)
        assert override_low is None or override_low < 500, (
            f"Override should clear/shrink at low position, got {override_low}"
        )
