"""Unified lighting pipeline.

Single pipeline that computes final brightness and color per purpose for an area.
All entry points funnel through `compute()` which returns a `PipelineResult`.

Pipeline steps (in order):
  1. Base curve (time + midpoint → rhythm_brightness, rhythm_kelvin)
  2. Night color adjustment (ceiling toward warm target)
  3. Sun cooling (blend toward daylight_cct, modulated by sun_cooling_strength)
  4. Color override applied (additive on post-solar kelvin)
  5. Sun bright adjustment (multiplicative: intensity × sensitivity × exposure)
  --- Area-level brightness (steps 6-8) ---
  6. Area factor (multiplicative)
  7. Brightness override (additive, decayed)
  8. Boost (additive)
  9. Fade / dim factor (multiplicative)
  --- Per-purpose brightness (steps 10-12) ---
 10. Purpose filter multiplier (from rhythm_brightness curve position)
 11. Purpose off-threshold check
 12. CT brightness compensation
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from brain import (
    AreaState,
    CircadianLight,
    Config,
    SunTimes,
    calculate_curve_position,
    calculate_filter_multiplier,
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
        # Compute from scratch (periodic tick / step / toggle paths)
        # sun_cooling_strength: 0-1 modifier on sun cooling effect.
        # 1.0 = full sun cooling; decreases as user steps below natural curve
        # (allows curve's natural warmth to come through when user dims).
        sun_cooling_strength = 1.0
        if ctx.area_state.brightness_mid is not None:
            natural_bri = CircadianLight.calculate_brightness_at_hour(
                ctx.hour, ctx.config,
                AreaState(is_circadian=True, is_on=True),
                weekday=ctx.weekday,
            )
            stepped_bri = CircadianLight.calculate_brightness_at_hour(
                ctx.hour, ctx.config, ctx.area_state,
                weekday=ctx.weekday,
            )
            if stepped_bri < natural_bri and natural_bri > ctx.config.min_brightness:
                step_below = (natural_bri - stepped_bri) / (
                    natural_bri - ctx.config.min_brightness
                )
                sun_cooling_strength = max(0.0, 1.0 - step_below)

        result = CircadianLight.calculate_lighting(
            ctx.hour,
            ctx.config,
            ctx.area_state,
            sun_times=ctx.sun_times,
            weekday=ctx.weekday,
            sun_cooling_strength=sun_cooling_strength,
        )
        rhythm_brightness = result.brightness
        rhythm_kelvin = result.color_temp
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

    # --- Steps 6-8: Area brightness (area_factor + override + boost) ---
    area_brightness = brightness * ctx.area_factor
    if ctx.brightness_override is not None:
        area_brightness = max(1, min(100, area_brightness + ctx.brightness_override))
    if ctx.boost_brightness is not None and ctx.boost_brightness > 0:
        area_brightness = min(100, area_brightness + ctx.boost_brightness)
    area_brightness = int(round(area_brightness))

    # --- Step 9: Fade / dim factor ---
    post_factor = ctx.fade_factor * ctx.dim_factor
    if post_factor < 1.0:
        area_brightness = max(1, int(round(area_brightness * post_factor)))

    # --- Steps 10-12: Per-purpose pipeline ---
    purpose_groups = _group_by_purpose(ctx)
    purposes = []
    for purpose_name, preset in purpose_groups.items():
        purpose_bri, should_off = _apply_purpose_filter(
            area_brightness=area_brightness,
            rhythm_brightness=rhythm_brightness,
            min_brightness=ctx.config.min_brightness,
            max_brightness=ctx.config.max_brightness,
            filter_preset=preset,
            off_threshold=ctx.off_threshold,
            brightness_override=ctx.brightness_override,
        )

        # CT brightness compensation
        if not should_off and purpose_bri > 0:
            purpose_bri = apply_ct_compensation(
                purpose_bri,
                kelvin,
                enabled=ctx.ct_comp_enabled,
                begin=ctx.ct_comp_begin,
                end=ctx.ct_comp_end,
                factor=ctx.ct_comp_factor,
            )

        purposes.append(
            PurposeResult(
                name=purpose_name,
                brightness=purpose_bri,
                kelvin=kelvin,
                xy=xy,
                should_off=should_off,
            )
        )

    return PipelineResult(
        purposes=purposes,
        area_brightness=area_brightness,
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

    Always returns at least Standard with a passthrough preset.
    """
    if not ctx.area_filters or not ctx.filter_presets:
        return {"Standard": {"at_dim": 100, "at_bright": 100}}

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


def _apply_purpose_filter(
    area_brightness: int,
    rhythm_brightness: int,
    min_brightness: int,
    max_brightness: int,
    filter_preset: dict,
    off_threshold: int,
    brightness_override: float = None,
) -> tuple:
    """Apply purpose filter multiplier to area brightness.

    Pipeline: area_brightness × filter_multiplier → clamp → off check.

    Args:
        area_brightness: Pre-computed area-level brightness (post factor/override/boost/fade/dim)
        rhythm_brightness: Pure curve brightness for filter curve position calculation
        min_brightness: Configured min brightness for the rhythm
        max_brightness: Configured max brightness for the rhythm
        filter_preset: Dict with "at_bright" and "at_dim" keys (percent values)
        off_threshold: Brightness below which lights should be turned off
        brightness_override: Used only to prevent auto-off when user explicitly brightened

    Returns:
        Tuple of (final_brightness: int, should_turn_off: bool)
    """
    at_dim = filter_preset.get("at_dim", 100)
    at_bright = filter_preset.get("at_bright", 100)

    pos = calculate_curve_position(rhythm_brightness, min_brightness, max_brightness)
    multiplier = calculate_filter_multiplier(pos, at_dim, at_bright)

    result = area_brightness * multiplier

    preset_threshold = filter_preset.get("off_threshold", off_threshold)
    if result < preset_threshold:
        # If user explicitly brightened (positive override), don't auto-off.
        if brightness_override is not None and brightness_override > 0:
            result = max(1, result)
        else:
            return (0, True)

    has_override = brightness_override is not None
    final = (
        int(min(100, max(1, round(result))))
        if has_override
        else int(min(100, round(result)))
    )
    return (final, False)


def apply_ct_compensation(
    brightness: int,
    color_temp: int,
    *,
    enabled: bool,
    begin: int,
    end: int,
    factor: float,
) -> int:
    """Apply CT brightness compensation for warm color temperatures.

    Public so callers outside the pipeline (e.g. Live Design's raw broadcast
    in webserver.py) can apply the same perception-correction without
    reimplementing the curve. Anyone tuning CT comp behavior changes only
    this function and both call sites pick up the change.

    Args:
        brightness: Pre-comp brightness (0-100).
        color_temp: Color temperature in Kelvin.
        enabled: CT comp on/off.
        begin: Below this kelvin, full `factor` boost applies.
        end: Above this kelvin, no boost. Linear interpolation between.
        factor: Multiplier applied at `begin` and below (e.g. 1.7 = 70% boost).
    """
    if not enabled or brightness <= 0:
        return brightness

    if color_temp >= end:
        return brightness
    if color_temp <= begin:
        compensated = brightness * factor
        return min(100, int(round(compensated)))

    # Linear interpolation within handover zone
    position = (end - color_temp) / (end - begin)
    interp_factor = 1.0 + position * (factor - 1.0)
    compensated = brightness * interp_factor
    return min(100, int(round(compensated)))
