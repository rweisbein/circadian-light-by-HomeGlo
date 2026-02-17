#!/usr/bin/env python3
"""Test step calculation functions in brain.py."""

import pytest
from brain import CircadianLight, Config, AreaState, SunTimes


class TestCalculateStep:
    """Test calculate_step (brightness + color together)."""

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

    def test_step_down_updates_both_midpoints(self, config):
        """Test step down updates both brightness and color midpoints."""
        state = AreaState()

        result = CircadianLight.calculate_step(12.0, "down", config, state)

        assert result is not None
        assert "brightness_mid" in result.state_updates
        assert "color_mid" in result.state_updates
        assert result.brightness < 100  # Should be less than max
        assert result.color_temp < 6500  # Should be less than max

    def test_step_up_at_max_returns_none(self, config):
        """Test step up at absolute max returns None."""
        state = AreaState()

        # At noon with default config, brightness is 100% (absolute max)
        result = CircadianLight.calculate_step(12.0, "up", config, state)

        assert result is None

    def test_step_down_from_max(self, config):
        """Test step down from max brightness."""
        state = AreaState()

        # At noon, brightness is at max
        result = CircadianLight.calculate_step(12.0, "down", config, state)

        assert result is not None
        assert result.brightness < 100
        # Step should be approximately 9% (90/10 steps)
        assert 85 <= result.brightness <= 95

    def test_multiple_steps_down(self, config):
        """Test multiple consecutive steps down."""
        state = AreaState()
        brightness_values = []

        for _ in range(5):
            result = CircadianLight.calculate_step(12.0, "down", config, state)
            if result is None:
                break

            brightness_values.append(result.brightness)

            # Update state with new midpoints
            if result.state_updates.get("brightness_mid") is not None:
                state.brightness_mid = result.state_updates["brightness_mid"]
            if result.state_updates.get("color_mid") is not None:
                state.color_mid = result.state_updates["color_mid"]

        # Should have decreasing brightness
        for i in range(len(brightness_values) - 1):
            assert brightness_values[i] > brightness_values[i + 1]

    def test_step_preserves_color_override(self):
        """Combined step should render color with existing color_override.

        Regression: calculate_step was dropping color_override when building
        the test-render state, causing the immediate light command to ignore
        the override (solar rule applies in full → warm flash) even though
        the periodic update would restore it.
        """
        config = Config(
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
        )
        sun_times = SunTimes()
        hour = 22.0  # Warm night active

        # Simulate: user has color-stepped up, accumulating override
        state = AreaState(color_override=1500)

        # Get rendered color with override (should be well above 2700)
        rendered_before = CircadianLight.calculate_color_at_hour(
            hour, config, state, apply_solar_rules=True, sun_times=sun_times
        )
        assert rendered_before > 3000, f"Override should raise CCT, got {rendered_before}K"

        result = CircadianLight.calculate_step(hour, "down", config, state, sun_times=sun_times)

        if result is not None:
            # The returned color_temp must respect the override, not drop to 2700
            assert result.color_temp > 3000, (
                f"Step result dropped color_override: got {result.color_temp}K, "
                f"expected >3000K (rendered_before={rendered_before}K)"
            )

    def test_step_down_recalibrates_override(self):
        """Combined step down should reduce override toward zero.

        After color-upping past a solar rule, stepping down should gradually
        reduce the override so the solar rule re-engages when back in range.
        """
        config = Config(
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
        )
        sun_times = SunTimes()
        hour = 22.0

        # Start with a large override (as if user color-upped several times)
        state = AreaState(color_override=1500)

        # Step down multiple times
        overrides = [state.color_override]
        for _ in range(5):
            result = CircadianLight.calculate_step(hour, "down", config, state, sun_times=sun_times)
            if result is None:
                break
            for key, value in result.state_updates.items():
                setattr(state, key, value)
            overrides.append(state.color_override)

        # Override should be reduced (or cleared) from initial 1500
        final = overrides[-1]
        assert final is None or final < 1500, (
            f"Override should decrease on step down: {overrides}"
        )


class TestCalculateBrightStep:
    """Test calculate_bright_step (brightness only)."""

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

    def test_bright_step_only_updates_brightness_mid(self, config):
        """Test bright step only updates brightness_mid, not color_mid."""
        state = AreaState()

        # At 8am where we're not at max
        result = CircadianLight.calculate_bright_step(8.0, "up", config, state)

        assert result is not None
        assert "brightness_mid" in result.state_updates
        assert "color_mid" not in result.state_updates

    def test_bright_step_up_increases_brightness(self, config):
        """Test bright step up increases brightness."""
        state = AreaState()

        current_bri = CircadianLight.calculate_brightness_at_hour(8.0, config, state)
        result = CircadianLight.calculate_bright_step(8.0, "up", config, state)

        assert result is not None
        assert result.brightness > current_bri

    def test_bright_step_down_decreases_brightness(self, config):
        """Test bright step down decreases brightness."""
        state = AreaState()

        current_bri = CircadianLight.calculate_brightness_at_hour(8.0, config, state)
        result = CircadianLight.calculate_bright_step(8.0, "down", config, state)

        assert result is not None
        assert result.brightness < current_bri

    def test_bright_step_preserves_color(self, config):
        """Test bright step doesn't change color output."""
        state = AreaState()

        current_color = CircadianLight.calculate_color_at_hour(8.0, config, state)
        result = CircadianLight.calculate_bright_step(8.0, "up", config, state)

        assert result is not None
        assert result.color_temp == current_color

    def test_bright_step_at_max_returns_none(self, config):
        """Test bright step at max returns None."""
        state = AreaState()

        # At noon, brightness is at max (100%)
        result = CircadianLight.calculate_bright_step(12.0, "up", config, state)

        # Should return None since we're at config max
        assert result is None

    def test_bright_step_at_min_returns_none(self, config):
        """Test bright step at min returns None."""
        state = AreaState()

        # Step down multiple times until we hit the bound
        none_count = 0
        for _ in range(15):
            result = CircadianLight.calculate_bright_step(12.0, "down", config, state)
            if result is None:
                none_count += 1
                if none_count >= 2:
                    break  # Confirmed at min (returns None consistently)
            else:
                none_count = 0
                for key, value in result.state_updates.items():
                    setattr(state, key, value)

        # Should have hit the bound and returned None
        assert none_count >= 1


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

        result = CircadianLight.calculate_step(12.0, "down", config, state)

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

        result = CircadianLight.calculate_step(12.0, "down", config, state)

        assert result is not None
        r, g, b = result.rgb
        assert 0 <= r <= 255
        assert 0 <= g <= 255
        assert 0 <= b <= 255

    def test_step_result_xy_is_valid(self):
        """Test StepResult XY values are valid."""
        config = Config(max_dim_steps=10)
        state = AreaState()

        result = CircadianLight.calculate_step(12.0, "down", config, state)

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

    def test_step_slider_recalibrates_override(self, warm_night_config, sun_times):
        """Combined slider should recalibrate override, not clear it blindly.

        After color-upping past a solar rule, dragging the combined slider
        to a low position should reduce/clear the override. Then dragging
        back up should let the solar rule re-engage (override stays gone).
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

        # Apply state updates, then drag back to 50%
        for key, value in result_low.state_updates.items():
            setattr(state, key, value)

        result_back_up = CircadianLight.calculate_set_position(
            hour, 50, "step", warm_night_config, state, sun_times=sun_times
        )

        # Solar rule should now re-engage — CCT should be clamped toward warm
        # (not at 4200K+ like it was with override=1500)
        assert result_back_up.color_temp < 3500, (
            f"Solar rule should re-engage after override cleared, got {result_back_up.color_temp}K"
        )
