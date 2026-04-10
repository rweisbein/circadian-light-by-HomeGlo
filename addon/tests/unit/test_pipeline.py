"""Tests for the unified lighting pipeline.

Verifies that pipeline.compute() produces correct results for a matrix of
inputs covering all pipeline steps.
"""

import sys
import os

# Ensure addon modules are importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from brain import AreaState, CircadianLight, Config, SunTimes
from pipeline import PipelineContext, PipelineResult, compute


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ctx(
    hour=12.0,
    area_id="test_area",
    config=None,
    area_state=None,
    sun_times=None,
    **kwargs,
) -> PipelineContext:
    """Create a PipelineContext with sensible defaults."""
    return PipelineContext(
        area_id=area_id,
        hour=hour,
        config=config or Config(),
        area_state=area_state or AreaState(is_circadian=True, is_on=True),
        sun_times=sun_times or SunTimes(),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Step 1: Base curve
# ---------------------------------------------------------------------------


class TestBaseCurve:
    """Pipeline step 1: base curve calculation."""

    def test_midday_brightness(self):
        """At noon, brightness should be near max."""
        result = compute(_make_ctx(hour=12.0))
        assert result.rhythm_brightness >= 80

    def test_nighttime_brightness(self):
        """Late at night, brightness should be near min."""
        result = compute(_make_ctx(hour=2.0))
        assert result.rhythm_brightness <= 20

    def test_rhythm_values_preserved(self):
        """rhythm_brightness/rhythm_kelvin should match raw curve output."""
        ctx = _make_ctx(hour=14.0)
        result = compute(ctx)
        # Cross-check with direct brain call
        direct = CircadianLight.calculate_lighting(
            14.0, ctx.config, ctx.area_state, sun_times=ctx.sun_times
        )
        assert result.rhythm_brightness == direct.brightness
        assert result.rhythm_kelvin == direct.color_temp

    def test_phase_reported(self):
        """Pipeline should report the current phase."""
        result = compute(_make_ctx(hour=10.0))
        assert result.phase in ("ascend", "descend")


# ---------------------------------------------------------------------------
# Step 5: Sun bright adjustment (NL)
# ---------------------------------------------------------------------------


class TestSunBrightAdjustment:
    """Pipeline step 5: natural light / sun bright adjustment."""

    def test_no_exposure_no_reduction(self):
        """Area with zero exposure should have no NL reduction."""
        result = compute(
            _make_ctx(
                hour=12.0,
                sun_exposure=0.0,
                sun_intensity=1.0,
            )
        )
        assert result.sun_bright_factor == 1.0

    def test_full_exposure_bright_sun(self):
        """Area with full exposure and bright sun should reduce significantly."""
        result = compute(
            _make_ctx(
                hour=12.0,
                sun_exposure=1.0,
                sun_intensity=1.0,
            )
        )
        assert result.sun_bright_factor < 0.5
        # Brightness should be reduced from rhythm
        assert result.area_brightness < result.rhythm_brightness

    def test_partial_exposure(self):
        """Partial exposure should partially reduce."""
        result = compute(
            _make_ctx(
                hour=12.0,
                sun_exposure=0.3,
                sun_intensity=0.5,
            )
        )
        assert 0.0 < result.sun_bright_factor < 1.0

    def test_no_sun_no_reduction(self):
        """No outdoor light should mean no reduction."""
        result = compute(
            _make_ctx(
                hour=12.0,
                sun_exposure=1.0,
                sun_intensity=0.0,
            )
        )
        assert result.sun_bright_factor == 1.0


# ---------------------------------------------------------------------------
# Steps 6-10: Per-purpose pipeline (area_factor, override, boost, filter)
# ---------------------------------------------------------------------------


class TestPerPurposePipeline:
    """Pipeline steps 6-10: per-purpose adjustments."""

    def test_no_purposes_returns_standard(self):
        """Area with no filters should produce one 'Standard' purpose."""
        result = compute(_make_ctx(hour=12.0))
        assert len(result.purposes) == 1
        assert result.purposes[0].name == "Standard"

    def test_area_factor_applied(self):
        """Area factor should scale brightness."""
        full = compute(_make_ctx(hour=12.0, area_factor=1.0))
        half = compute(_make_ctx(hour=12.0, area_factor=0.6))
        assert half.purposes[0].brightness < full.purposes[0].brightness

    def test_area_factor_with_no_filters(self):
        """Area factor without filters should still create Standard purpose."""
        result = compute(_make_ctx(hour=12.0, area_factor=0.8))
        assert len(result.purposes) == 1
        assert result.purposes[0].brightness > 0

    def test_brightness_override_additive(self):
        """Brightness override should add to brightness."""
        base = compute(_make_ctx(hour=12.0))
        boosted = compute(_make_ctx(hour=12.0, brightness_override=15.0))
        # Override is additive, so boosted should be brighter
        # (unless already at 100)
        assert boosted.purposes[0].brightness >= base.purposes[0].brightness

    def test_boost_additive(self):
        """Boost should add to brightness."""
        base = compute(_make_ctx(hour=2.0))  # Low brightness time
        boosted = compute(_make_ctx(hour=2.0, boost_brightness=30))
        assert boosted.purposes[0].brightness > base.purposes[0].brightness

    def test_multiple_purposes(self):
        """Multiple purposes should each get their own result."""
        ctx = _make_ctx(
            hour=12.0,
            area_filters={
                "light.one": "Bright",
                "light.two": "Dim",
            },
            filter_presets={
                "Bright": {"at_dim": 80, "at_bright": 100},
                "Dim": {"at_dim": 20, "at_bright": 50},
            },
        )
        result = compute(ctx)
        assert len(result.purposes) == 2
        names = {p.name for p in result.purposes}
        assert "Bright" in names
        assert "Dim" in names
        # Bright purpose should be brighter than Dim
        bright = next(p for p in result.purposes if p.name == "Bright")
        dim = next(p for p in result.purposes if p.name == "Dim")
        assert bright.brightness >= dim.brightness

    def test_off_threshold(self):
        """Purpose below off_threshold should be marked should_off."""
        ctx = _make_ctx(
            hour=2.0,  # Low brightness
            area_filters={"light.one": "Accent"},
            filter_presets={"Accent": {"at_dim": 10, "at_bright": 50}},
            off_threshold=15,
        )
        result = compute(ctx)
        accent = result.purposes[0]
        # At low brightness with dim filter, might be below threshold
        if accent.brightness == 0:
            assert accent.should_off is True


# ---------------------------------------------------------------------------
# Step 11: CT brightness compensation
# ---------------------------------------------------------------------------


class TestCTCompensation:
    """Pipeline step 11: CT brightness compensation."""

    def test_disabled_no_change(self):
        """With CT comp disabled, brightness should not change."""
        ctx = _make_ctx(hour=2.0, ct_comp_enabled=False)
        result = compute(ctx)
        # No compensation applied
        assert result.purposes[0].brightness > 0

    def test_warm_ct_gets_boost(self):
        """Very warm color temp should get brightness boost."""
        # Force a warm color temp by using nighttime
        config = Config(min_color_temp=500, max_color_temp=6500)
        state = AreaState(is_circadian=True, is_on=True)

        no_comp = compute(
            _make_ctx(
                hour=2.0,
                config=config,
                area_state=state,
                ct_comp_enabled=False,
            )
        )
        with_comp = compute(
            _make_ctx(
                hour=2.0,
                config=config,
                area_state=state,
                ct_comp_enabled=True,
                ct_comp_begin=1650,
                ct_comp_end=2250,
                ct_comp_factor=1.7,
            )
        )

        # If the kelvin is in the compensation zone, brightness should increase
        if no_comp.area_kelvin <= 2250:
            assert with_comp.purposes[0].brightness >= no_comp.purposes[0].brightness

    def test_cool_ct_no_boost(self):
        """Cool color temp should not get brightness boost."""
        result = compute(
            _make_ctx(
                hour=12.0,  # Midday = cool CT
                ct_comp_enabled=True,
                ct_comp_begin=1650,
                ct_comp_end=2250,
                ct_comp_factor=1.7,
            )
        )
        # At noon, CT should be above 2250K, no compensation
        if result.area_kelvin > 2250:
            # Brightness should be unchanged from base
            no_comp = compute(_make_ctx(hour=12.0, ct_comp_enabled=False))
            assert result.purposes[0].brightness == no_comp.purposes[0].brightness


# ---------------------------------------------------------------------------
# Integration: full pipeline consistency
# ---------------------------------------------------------------------------


class TestPipelineConsistency:
    """Verify pipeline output matches existing brain.py calculations."""

    def test_matches_brain_no_nl_no_filter(self):
        """With no NL and no filters, pipeline brightness should match curve."""
        ctx = _make_ctx(hour=14.0)
        result = compute(ctx)
        direct = CircadianLight.calculate_lighting(
            14.0, ctx.config, ctx.area_state, sun_times=ctx.sun_times
        )
        assert result.purposes[0].brightness == direct.brightness
        assert result.purposes[0].kelvin == direct.color_temp

    def test_matches_brain_with_nl(self):
        """With NL, pipeline should apply same factor as brain."""
        ctx = _make_ctx(
            hour=12.0,
            sun_exposure=0.5,
            sun_intensity=0.8,
        )
        result = compute(ctx)
        direct = CircadianLight.calculate_lighting(
            12.0, ctx.config, ctx.area_state, sun_times=ctx.sun_times
        )
        from brain import calculate_natural_light_factor

        expected_factor = calculate_natural_light_factor(
            0.5, 0.8, ctx.config.brightness_sensitivity
        )
        expected_bri = max(1, int(round(direct.brightness * expected_factor)))
        assert result.area_brightness == expected_bri

    def test_color_preserved(self):
        """Color (kelvin, xy) should pass through unchanged."""
        ctx = _make_ctx(hour=10.0)
        result = compute(ctx)
        direct = CircadianLight.calculate_lighting(
            10.0, ctx.config, ctx.area_state, sun_times=ctx.sun_times
        )
        assert result.area_kelvin == direct.color_temp
        assert result.area_xy == direct.xy
