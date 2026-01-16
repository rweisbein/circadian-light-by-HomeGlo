#!/usr/bin/env python3
"""Test step calculation functions in brain.py."""

import pytest
from brain import CircadianLight, Config, AreaState


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

        # Step down multiple times to reach config min
        for _ in range(15):
            result = CircadianLight.calculate_bright_step(12.0, "down", config, state)
            if result is None:
                break  # At config min

            for key, value in result.state_updates.items():
                setattr(state, key, value)

        # One more step should return None (at config min)
        result = CircadianLight.calculate_bright_step(12.0, "down", config, state)
        assert result is None


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
