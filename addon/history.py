"""Per-area user-facing event history.

Records discrete, human-meaningful state changes (turn on/off, brightness/color
adjustments, freeze/boost, resets) with source attribution. Distinct from the
Python logging stream — this is NOT a debug log. Periodic-tick recomputes,
motion-extend-timer pings while lights are already on, and other "noise" are
filtered out at the record-call site (caller passes a source string we ignore).

In-memory only — bounded deque per area, lost on restart. Persistence is a
future upgrade if needed; for v1, "what happened recently" is the use case.

Coalescing: rapid same-action/same-source events (brightness/color/phase only)
within a short window collapse into one entry whose `to_value` advances. So a
4-press dim from a switch shows as ONE row, not four.
"""

import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field, asdict
from typing import Deque, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

_MAX_PER_AREA = 100
_COALESCE_WINDOW_SEC = 5.0
_COALESCEABLE_ACTIONS = frozenset({"brightness", "color", "phase"})
# Sources to silently drop. These are produced by paths that run on the
# periodic tick or other non-user-driven code — recording them would flood
# the log with noise the user doesn't care about.
_IGNORE_SOURCES = frozenset({
    "periodic_update", "periodic_tick", "system_init", "history_replay",
})


# ---------------------------------------------------------------------------
# Entry shape
# ---------------------------------------------------------------------------


@dataclass
class HistoryEntry:
    ts: float
    action: str            # e.g. 'turn_on', 'turn_off', 'brightness', 'color', 'phase',
                           # 'freeze', 'unfreeze', 'boost', 'boost_end',
                           # 'circadian_on', 'circadian_off',
                           # 'auto_off_set', 'auto_off_cleared',
                           # 'glo_down', 'glo_up', 'glo_reset', 'full_send',
                           # 'reset_brightness_override', 'reset_color_override', 'reset_phase'
    source_kind: str       # 'switch'|'motion'|'contact'|'app'|'auto_schedule'|
                           # 'timer'|'service_call'|'system'
    source_entity: Optional[str] = None  # entity_id when available
    brightness: Optional[int] = None     # current/landing brightness
    kelvin: Optional[int] = None         # current/landing kelvin
    from_value: Optional[float] = None   # for brightness/color/phase delta
    to_value: Optional[float] = None
    duration_minutes: Optional[int] = None  # freeze/boost/auto_off_set
    intensity: Optional[int] = None      # boost
    is_2step: bool = False               # turn_on: pre-color CT sent before brightness
    is_zone_action: bool = False         # entry was fanned out from a zone-level op


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


_history: Dict[str, Deque[HistoryEntry]] = defaultdict(
    lambda: deque(maxlen=_MAX_PER_AREA)
)

# Process-start timestamp. Stamped into the lazy-seeded "restart" marker
# (see record()) so users can visually anchor the bottom of each area's
# log to "this is when the addon last started; anything before this is
# gone." History is in-memory only — restart wipes the buffer.
_PROCESS_START_TS = time.time()


# ---------------------------------------------------------------------------
# Source normalization
# ---------------------------------------------------------------------------

# Map free-form `source` strings (which primitives have always used) to the
# canonical source_kind enum. Anything not listed falls through as-is, so new
# sources show up sensibly even before we add an alias here.
_KIND_ALIAS = {
    "switch_button": "switch",
    "motion_sensor": "motion",
    "contact_sensor": "contact",
    "webserver": "app",
    "auto_on": "auto_schedule",
    "auto_off": "auto_schedule",
    "timer_expired": "timer",
    "service": "service_call",
    "internal": "system",
}


def _classify_source(source: str) -> Tuple[str, Optional[str]]:
    """Normalize a source string into (source_kind, source_entity).

    Accepts both bare-kind ('switch', 'motion_sensor') and entity-tagged
    forms ('switch:switch.master_bedside'). Unknown kinds pass through.
    """
    if not source:
        return ("system", None)
    if ":" in source:
        kind, entity = source.split(":", 1)
    else:
        kind, entity = source, None
    return (_KIND_ALIAS.get(kind, kind), entity)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def record(
    area_id: str,
    action: str,
    source: str = "system",
    *,
    brightness: Optional[int] = None,
    kelvin: Optional[int] = None,
    from_value: Optional[float] = None,
    to_value: Optional[float] = None,
    duration_minutes: Optional[int] = None,
    intensity: Optional[int] = None,
    is_2step: bool = False,
    is_zone_action: bool = False,
) -> None:
    """Append a history entry for `area_id`.

    Drops periodic-tick noise (sources in _IGNORE_SOURCES). Coalesces with
    the previous entry when both events are the same coalesceable action
    AND same source AND within _COALESCE_WINDOW_SEC — keeps the original
    from_value, advances to_value to the new latest.
    """
    if source in _IGNORE_SOURCES:
        return

    source_kind, source_entity = _classify_source(source)
    buf = _history[area_id]
    now = time.time()

    # Lazy seed: first real event for this area auto-prepends a "restart"
    # marker stamped with the process start time. Anchors the bottom of
    # the visible log so users can tell when history began.
    if not buf:
        buf.append(HistoryEntry(
            ts=_PROCESS_START_TS,
            action="restart",
            source_kind="system",
            source_entity=None,
        ))

    if (
        action in _COALESCEABLE_ACTIONS
        and buf
        and buf[-1].action == action
        and buf[-1].source_kind == source_kind
        and buf[-1].source_entity == source_entity
        and (now - buf[-1].ts) <= _COALESCE_WINDOW_SEC
    ):
        prev = buf[-1]
        if to_value is not None:
            prev.to_value = to_value
        if brightness is not None:
            prev.brightness = brightness
        if kelvin is not None:
            prev.kelvin = kelvin
        prev.ts = now
        return

    buf.append(HistoryEntry(
        ts=now,
        action=action,
        source_kind=source_kind,
        source_entity=source_entity,
        brightness=brightness,
        kelvin=kelvin,
        from_value=from_value,
        to_value=to_value,
        duration_minutes=duration_minutes,
        intensity=intensity,
        is_2step=is_2step,
        is_zone_action=is_zone_action,
    ))


def get(area_id: str, limit: int = 50) -> List[dict]:
    """Return up to `limit` most-recent entries for `area_id`, newest first."""
    buf = _history.get(area_id)
    if not buf:
        return []
    items = list(buf)
    items.reverse()
    if limit and len(items) > limit:
        items = items[:limit]
    return [asdict(e) for e in items]


def clear(area_id: Optional[str] = None) -> None:
    """Clear history for one area, or all areas if `area_id` is None."""
    if area_id is None:
        _history.clear()
    else:
        _history.pop(area_id, None)
