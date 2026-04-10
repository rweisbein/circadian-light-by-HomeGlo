"""Delivery layer for light commands.

Takes pipeline results and sends them to lights via Home Assistant.
Handles 2-step color pre-send, ZHA group dispatch, and prior state tracking.

Phase 0: thin wrapper delegating to existing turn_on_lights_circadian.
Later phases will implement delivery logic directly.
"""

from pipeline import PipelineResult


async def deliver(
    result: PipelineResult,
    area_id: str,
    client,
    transition: float = 0.5,
    include_color: bool = True,
    log_periodic: bool = False,
) -> None:
    """Deliver pipeline results to lights.

    Phase 0: delegates to existing turn_on_lights_circadian via client.
    """
    # Build circadian_values dict matching existing interface
    circadian_values = {
        "brightness": result.area_brightness,
        "kelvin": result.area_kelvin,
        "xy": result.area_xy,
        "rhythm_brightness": result.rhythm_brightness,
    }

    await client.turn_on_lights_circadian(
        area_id,
        circadian_values,
        transition=transition,
        include_color=include_color,
        log_periodic=log_periodic,
    )
