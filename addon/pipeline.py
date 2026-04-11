"""Unified lighting pipeline.

Single pipeline that computes final brightness and color per purpose for an area.
All entry points funnel through `compute()` which returns a `PipelineResult`.

Pipeline steps (in order):
  1. Base curve (time + midpoint → rhythm_brightness, rhythm_kelvin)
  2. Night color adjustment (ceiling toward warm target)
  3. Sun color adjustment (blend toward daylight_cct)
  4. Color override applied (additive on post-solar kelvin)
  5. Sun bright adjustment (multiplicative: intensity × sensitivity × exposure)
  6. Area factor (multiplicative)
  7. Brightness override (additive, decayed)
  8. Boost (additive)
  9. Per-purpose adjustments (multiplicative from rhythm_brightness curve position)
 10. Purpose participation rules (on_above/on_below + fade band)
 11. CT brightness compensation
 12. Prior state tracking (per-purpose)
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from brain import (
    AreaState,
    CircadianLight,
    Config,
    SunTimes,
    apply_light_filter_pipeline,
    calculate_natural_light_factor,
)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class PipelineContext:
    """All inputs needed by the pipeline to compute lighting for one area."""

    area_id: str
    hour: float
    config: Config
    area_state: AreaState
    sun_times: SunTimes

    # Per-area config (from glozone)
    area_factor: float = 1.0
    area_filters: Optional[Dict[str, str]] = None  # {entity_id: purpose_name}
    filter_presets: Optional[Dict[str, dict]] = (
        None  # {preset_name: {at_dim, at_bright, ...}}
    )
    off_threshold: int = 0

    # Sun bright adjustment inputs
    sun_exposure: float = 0.0  # 0.0 (cave) to 1.0 (sunroom)
    sun_intensity: float = 0.0  # 0.0 (dark) to 1.0 (bright sun)

    # Override / boost (already decay-adjusted by caller)
    brightness_override: Optional[float] = None
    boost_brightness: Optional[int] = None
    color_override: Optional[float] = None

    # CT compensation config
    ct_comp_enabled: bool = False
    ct_comp_begin: int = 1650
    ct_comp_end: int = 2250
    ct_comp_factor: float = 1.7

    # Transition
    transition: float = 0.5

    # Weekday for alt-timing
    weekday: Optional[int] = None

    # Fade multiplier (auto on/off transitions, applied post-compute)
    fade_factor: float = 1.0

    # Warning multiplier (motion warning dim, applied post-compute)
    dim_factor: float = 1.0

    # Pre-computed base curve values (skip calculate_lighting when set).
    # Used by primitives that already computed the curve via brain.py.
    precomputed_brightness: Optional[int] = None
    precomputed_kelvin: Optional[int] = None
    precomputed_xy: Optional[Tuple[float, float]] = None
    precomputed_rhythm_brightness: Optional[int] = None


@dataclass
class PurposeResult:
    """Pipeline output for a single purpose (light group) within an area."""

    name: str  # e.g. "Standard", "Accent"
    brightness: int  # Final brightness 0-100 (0 = should be off)
    kelvin: int
    xy: Tuple[float, float]
    should_off: bool = False


@dataclass
class PipelineResult:
    """Complete pipeline output for one area."""

    purposes: List[PurposeResult]
    # Area-level values (pre-purpose, post-sun-bright/factor/override/boost)
    area_brightness: int
    area_kelvin: int
    area_xy: Tuple[float, float]
    # Raw curve output (for limit detection, filter position, etc.)
    rhythm_brightness: int
    rhythm_kelvin: int
    phase: str  # "ascend" or "descend"
    # Sun bright adjustment factor applied
    sun_bright_factor: float = 1.0


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def compute(ctx: PipelineContext) -> PipelineResult:
    """Run the full lighting pipeline for one area.

    Pure computation — no I/O, no async, no side effects.
    """
    # --- Step 1: Base curve ---
    if ctx.precomputed_brightness is not None:
        # Caller already computed the curve (primitives path)
        rhythm_brightness = (
            ctx.precomputed_rhythm_brightness or ctx.precomputed_brightness
        )
        rhythm_kelvin = ctx.precomputed_kelvin or 4000
        kelvin = ctx.precomputed_kelvin or 4000
        xy = ctx.precomputed_xy or CircadianLight.color_temperature_to_xy(kelvin)
        phase = "precomputed"
    else:
        # Compute from scratch (periodic tick path)
        result = CircadianLight.calculate_lighting(
            ctx.hour,
            ctx.config,
            ctx.area_state,
            sun_times=ctx.sun_times,
            weekday=ctx.weekday,
        )
        rhythm_brightness = result.brightness
        rhythm_kelvin = result.color_temp
        # Steps 2-4 (night color, sun color, color override) are currently
        # handled inside calculate_lighting via solar rules + AreaState.color_override.
        kelvin = result.color_temp
        xy = result.xy
        phase = result.phase

    # --- Step 5: Sun bright adjustment ---
    brightness = rhythm_brightness
    sun_bright_factor = calculate_natural_light_factor(
        ctx.sun_exposure,
        ctx.sun_intensity,
        ctx.config.brightness_sensitivity,
    )
    if sun_bright_factor < 1.0:
        brightness = max(1, int(round(brightness * sun_bright_factor)))

    # --- Step 6: Area factor ---
    # Applied inside per-purpose filter pipeline (step 9).
    # For areas without purposes, apply directly here.

    # --- Steps 7-8: Brightness override + Boost ---
    # For areas with purposes, these are applied inside the filter pipeline.
    # For areas without purposes, apply directly.

    # Determine if we have purposes
    purpose_groups = _group_by_purpose(ctx)

    if purpose_groups:
        # --- Steps 6-11: Per-purpose pipeline ---
        purposes = []
        for purpose_name, preset in purpose_groups.items():
            filtered_bri, should_off = apply_light_filter_pipeline(
                base_brightness=brightness,
                min_brightness=ctx.config.min_brightness,
                max_brightness=ctx.config.max_brightness,
                area_factor=ctx.area_factor,
                filter_preset=preset,
                off_threshold=ctx.off_threshold,
                rhythm_brightness=rhythm_brightness,
                brightness_override=ctx.brightness_override,
                boost_brightness=ctx.boost_brightness,
            )

            # --- Step 11: CT brightness compensation ---
            if not should_off and filtered_bri > 0:
                filtered_bri = _apply_ct_compensation(filtered_bri, kelvin, ctx)

            purposes.append(
                PurposeResult(
                    name=purpose_name,
                    brightness=filtered_bri,
                    kelvin=kelvin,
                    xy=xy,
                    should_off=should_off,
                )
            )

        # Area-level brightness = post-sun-bright before purpose split
        area_brightness = brightness
    else:
        # No purposes — apply area_factor, override, boost directly
        area_brightness = brightness * ctx.area_factor
        if ctx.brightness_override is not None:
            area_brightness = max(
                1, min(100, area_brightness + ctx.brightness_override)
            )
        if ctx.boost_brightness is not None and ctx.boost_brightness > 0:
            area_brightness = min(100, area_brightness + ctx.boost_brightness)
        area_brightness = int(round(area_brightness))

        # CT compensation
        comp_brightness = _apply_ct_compensation(area_brightness, kelvin, ctx)

        purposes = [
            PurposeResult(
                name="Standard",
                brightness=comp_brightness,
                kelvin=kelvin,
                xy=xy,
                should_off=False,
            )
        ]

    # --- Post-compute multipliers (fade + warning) ---
    post_factor = ctx.fade_factor * ctx.dim_factor
    if post_factor < 1.0:
        for p in purposes:
            p.brightness = max(1, int(round(p.brightness * post_factor)))
        if purpose_groups:
            area_brightness = max(1, int(round(area_brightness * post_factor)))
        else:
            comp_brightness = max(1, int(round(comp_brightness * post_factor)))

    return PipelineResult(
        purposes=purposes,
        area_brightness=area_brightness if purpose_groups else comp_brightness,
        area_kelvin=kelvin,
        area_xy=xy,
        rhythm_brightness=rhythm_brightness,
        rhythm_kelvin=rhythm_kelvin,
        phase=phase,
        sun_bright_factor=sun_bright_factor,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _group_by_purpose(ctx: PipelineContext) -> Dict[str, dict]:
    """Build {purpose_name: filter_preset} from context.

    Returns empty dict if no purposes configured (fast path).
    """
    if not ctx.area_filters or not ctx.filter_presets:
        if ctx.area_factor != 1.0:
            # Area has a non-default factor but no filters — treat as Standard
            # with a pass-through preset so the filter pipeline applies area_factor.
            return {"Standard": {"at_dim": 100, "at_bright": 100}}
        return {}

    # Collect unique purpose names from the area's light assignments.
    # Always include "Standard" — lights without explicit filter assignments
    # default to Standard at delivery time.
    purpose_names = set(ctx.area_filters.values())
    purpose_names.add("Standard")
    result = {}
    for name in purpose_names:
        normalized = name.replace(" ", "_").lower()
        # Look up the preset; fall back to pass-through
        preset = ctx.filter_presets.get(name) or ctx.filter_presets.get(normalized)
        if preset is None:
            preset = {"at_dim": 100, "at_bright": 100}
        result[name] = preset
    return result


def _apply_ct_compensation(
    brightness: int, color_temp: int, ctx: PipelineContext
) -> int:
    """Apply CT brightness compensation for warm color temperatures."""
    if not ctx.ct_comp_enabled or brightness <= 0:
        return brightness

    if color_temp >= ctx.ct_comp_end:
        return brightness
    if color_temp <= ctx.ct_comp_begin:
        compensated = brightness * ctx.ct_comp_factor
        return min(100, int(round(compensated)))

    # Linear interpolation within handover zone
    position = (ctx.ct_comp_end - color_temp) / (ctx.ct_comp_end - ctx.ct_comp_begin)
    factor = 1.0 + position * (ctx.ct_comp_factor - 1.0)
    compensated = brightness * factor
    return min(100, int(round(compensated)))
