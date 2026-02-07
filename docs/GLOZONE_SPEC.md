# GloZone Specification

## Overview

GloZone is a feature that groups multiple Home Assistant areas into zones, allowing coordinated circadian lighting control across rooms. Each GloZone is tied to a Daily Rhythm that defines the lighting behavior (wake/bed times, brightness/color ranges, etc.).

## Core Concepts

### Circadian Rhythm
A named configuration containing all circadian lighting settings:
- Wake time, wake speed
- Bed time, bed speed
- Brightness range (min, max)
- Color temperature range (warm, cool)
- Solar adjustments (warm night, cool day)
- Activity preset reference

Multiple rhythms can exist (e.g., "Adult Schedule", "Kids Schedule", "Weekend").

### GloZone
A named grouping of areas that share a Circadian Rhythm:
- Each zone references exactly one rhythm
- Each area belongs to exactly one zone
- Zones have their own runtime state (midpoints, frozen_at)
- The "Unassigned" zone is the default for areas not explicitly assigned

### Membership Rules
- Every area belongs to exactly 1 zone (exclusive membership)
- New areas in Home Assistant automatically go to "Unassigned" zone
- Areas store `area_id` for stability; `name` is cached and refreshed periodically

---

## Data Model

### Storage: `designer_config.json`

```json
{
  "circadian_rhythms": {
    "Adult Schedule": {
      "wake_time": 7.0,
      "wake_speed": 2.0,
      "bed_time": 22.0,
      "bed_speed": 2.0,
      "brightness_min": 10,
      "brightness_max": 100,
      "color_temp_warm": 1800,
      "color_temp_cool": 5000,
      "warm_night": true,
      "warm_night_temp": 2700,
      "cool_day": false,
      "cool_day_temp": 5000,
      "ascend_start": 5.0,
      "descend_start": 17.0,
      "activity_preset": "relax"
    },
    "Kids Schedule": {
      "wake_time": 6.5,
      "bed_time": 20.0,
      "...": "..."
    }
  },

  "glozones": {
    "Main House": {
      "rhythm": "Adult Schedule",
      "areas": [
        { "id": "living_room", "name": "Living Room" },
        { "id": "kitchen", "name": "Kitchen" },
        { "id": "master_bedroom", "name": "Master Bedroom" }
      ]
    },
    "Kids Rooms": {
      "rhythm": "Kids Schedule",
      "areas": [
        { "id": "kids_bedroom", "name": "Kids Bedroom" },
        { "id": "playroom", "name": "Playroom" }
      ]
    },
    "Unassigned": {
      "rhythm": "Adult Schedule",
      "areas": []
    }
  }
}
```

### Runtime State (In-Memory)

GloZone runtime state is held in memory only (not persisted across restarts):

```python
glozone_runtime_state = {
    "Main House": {
        "brightness_mid": 7.5,   # Hour (0-24) or None
        "color_mid": 7.5,        # Hour (0-24) or None
        "frozen_at": None        # Hour (0-24) or None
    },
    "Kids Rooms": {
        "brightness_mid": None,  # None = use rhythm defaults
        "color_mid": None,
        "frozen_at": None
    }
}
```

Area runtime state (existing, in `state.py`):
```python
area_state = {
    "living_room": {
        "enabled": True,
        "brightness_mid": 7.5,   # Hour or None
        "color_mid": 7.5,        # Hour or None
        "frozen_at": None        # Hour or None
    }
}
```

### Value Semantics
- `brightness_mid`, `color_mid`, `frozen_at`: Hours on 0-24 scale (e.g., 7.5 = 7:30am)
- `None` = use rhythm defaults (wake_time or bed_time based on current phase)

---

## Primitives

### New GloZone Primitives

| Primitive | Description |
|-----------|-------------|
| **GloUp** | Push area's runtime state to its zone, then propagate to all areas in zone |
| **GloDown** | Pull zone's runtime state to the area |
| **GloReset** | Reset zone runtime to None (rhythm defaults), reset all member areas |

#### GloUp Behavior
1. Get area's current runtime state (brightness_mid, color_mid, frozen_at)
2. Set zone's runtime state to match
3. Propagate to ALL areas in the zone (update their runtime state)
4. Trigger light updates for all affected areas
5. Does NOT change `enabled` status of any area

#### GloDown Behavior
1. Get zone's current runtime state
2. Set area's runtime state to match (including frozen_at)
3. Trigger light update for the area
4. Does NOT change `enabled` status

#### GloReset Behavior
1. Set zone's runtime state to None (all fields)
2. Set all member areas' runtime state to None
3. Trigger light updates for all affected areas
4. Does NOT change `enabled` status or `frozen_at` (areas become unfrozen)

### Modified Existing Primitives

| Primitive | New Behavior |
|-----------|--------------|
| **circadian_toggle (enabling)** | Enable area + copy zone runtime state to area |
| **circadian_toggle (disabling)** | Disable area (keep runtime state as-is) |
| **circadian_on** | Enable area + copy zone runtime state to area |
| **circadian_off** | Disable area (keep runtime state as-is) |
| **bright_up/down** | Adjust area only (area deviates from zone) |
| **color_up/down** | Adjust area only (area deviates from zone) |
| **step_up/down** | Adjust area only (area deviates from zone) |
| **freeze_toggle** | Freeze/unfreeze area only (area deviates from zone) |
| **nitelite/britelite/wake/bed presets** | Apply to area only (area deviates from zone) |

### Daily Resets (Ascend/Descend Start)
- Reset all GloZone runtime states to None
- Reset all area runtime states to None
- Exception: frozen zones/areas are NOT reset (frozen_at is preserved)

---

## Sync Detection

To determine if an area is "in sync" with its zone:

```python
SYNC_TOLERANCE = 0.1  # 6 minutes

def is_synced(area_state, zone_state):
    def values_match(a, z):
        if a is None and z is None:
            return True
        if a is None or z is None:
            return False
        return abs(a - z) < SYNC_TOLERANCE

    return (
        values_match(area_state.brightness_mid, zone_state.brightness_mid) and
        values_match(area_state.color_mid, zone_state.color_mid) and
        values_match(area_state.frozen_at, zone_state.frozen_at)
    )
```

---

## Switch Button Mapping

Updated Hue Dimmer Switch blueprint:

| Button | 1x | 2x | 3x | Long Press |
|--------|----|----|-----|------------|
| **ON/OFF** | Circadian toggle | GloUp | GloReset | RESERVED (magic) |
| **UP** | Bright up | Color up | BriteLite | Step up |
| **DOWN** | Bright down | Color down | NiteLite | Step down |
| **HUE** | GloDown | Wake/Bed | Freeze toggle | RESERVED (magic) |

### Button Behavior Notes
- **GloUp/GloDown/GloReset**: Infer zone from switch's target area(s)
- If switch controls multiple areas in different zones: use first area's zone
- Switch controls areas, not zones directly (zone is derived)

---

## Designer UI Changes

### Rhythms Tab (replaces current single-config view)
- List of rhythms on left (starts with "Daily Rhythm 1" migrated from current settings)
- Add/rename/delete rhythms
- Selecting a rhythm opens full curve editor (current designer view)
- Each rhythm has all current settings (wake/bed times, curves, ranges, etc.)

### Zones Tab
- Single view showing:
  - List of all zones
  - Areas assigned to each zone
  - Rhythm dropdown for each zone
  - Wake/bed times displayed (from selected rhythm)
- Area assignment UI (drag-drop or dropdown)
- "Unassigned" zone always exists (cannot be deleted)

---

## Implementation Plan

### Phase 1: Data Model & Storage
1. Update `designer_config.json` schema
2. Create migration: current settings → "Daily Rhythm 1"
3. Create `glozone_state.py` for zone runtime state
4. Update `state.py` with zone-aware helpers

### Phase 2: Core Logic
5. Update `brain.py` to accept rhythm config (not global)
6. Add resolution helpers: area → zone → rhythm → settings
7. Update `get_circadian_values()` to be rhythm-aware

### Phase 3: Primitives
8. Add `glo_up()`, `glo_down()`, `glo_reset()` to `primitives.py`
9. Modify `circadian_toggle()`, `circadian_on()` to copy zone state
10. Update daily reset logic to include zones

### Phase 4: API & Services
11. Add webserver endpoints for rhythm CRUD
12. Add webserver endpoints for zone CRUD and area assignment
13. Register new services in custom integration

### Phase 5: Blueprint
14. Update `hue_dimmer_switch.yaml` with new button mappings

### Phase 6: Designer UI
15. Implement Rhythms tab with rhythm selector
16. Implement Zones tab with area assignment
17. Migrate existing settings on first load

---

## Edge Cases

### New Area Added in HA
- Automatically added to "Unassigned" zone on next area list refresh

### Zone Deleted
- All member areas move to "Unassigned" zone

### Rhythm Deleted
- Zones using that rhythm switch to first available rhythm (or "Daily Rhythm 1")

### Cross-Zone Switch
- If switch targets areas in multiple zones, GloZone primitives use first area's zone

### Area Removed from HA
- On refresh, area is removed from zone membership (flagged or cleaned up)

---

## Migration Path

When upgrading from pre-GloZone version:
1. Current `designer_config.json` settings become "Daily Rhythm 1"
2. Single "Unassigned" zone created, referencing "Daily Rhythm 1"
3. All existing areas assigned to "Unassigned" zone
4. User can then create zones and reassign areas

---

## Future Considerations (Not in Initial Implementation)

- **Zone Scheduling**: Switch zone's rhythm based on time/day (weekday vs weekend)
- **Zone Templates**: Pre-built zone configurations
- **Multi-home Support**: Multiple independent zone hierarchies
