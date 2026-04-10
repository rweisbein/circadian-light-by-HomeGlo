"""Delivery layer for light commands.

Takes pipeline results and sends them to lights via Home Assistant.
Handles 2-step color pre-send, ZHA group dispatch, and prior state tracking.

Phase 1: passes PipelineResult to send_light which routes
to the appropriate delivery path (fast or filtered) without re-computing.
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

    Passes the PipelineResult directly — send_light skips
    all inline computation (sun bright, filters, CT comp) when pipeline_result is set.
    """
    await client.send_light(
        area_id,
        transition=transition,
        include_color=include_color,
        log_periodic=log_periodic,
        pipeline_result=result,
    )
