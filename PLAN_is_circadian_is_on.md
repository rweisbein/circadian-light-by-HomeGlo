# Implementation Plan: `is_circadian` + `is_on` State Model

## Overview

Replace single `enabled` boolean with two-state model:
- `is_circadian`: Whether Circadian Light controls this area
- `is_on`: Target light power state (only meaningful when `is_circadian: true`)

## Design Summary

### State Model

When `is_circadian: true`, Circadian enforces `is_on` on every periodic update:
- `is_on: true` → apply circadian color/brightness
- `is_on: false` → turn lights off

When `is_circadian` flips **false → true**, reset all properties:
- `is_on` → false
- `brightness_mid` → null (use phase default)
- `color_mid` → null (use phase default)
- `frozen_at` → null
- `boost_*` → cleared
- `motion_expires_at` → null

### Primitives

| Primitive | is_circadian | Reset? | is_on | Action |
|-----------|--------------|--------|-------|--------|
| `circadian_off` | → false | no | unchanged | none |
| `lights_on` | → true | if was false | → true | apply circadian |
| `lights_off` | → true | if was false | → false | turn off |
| `lights_toggle` | → true | if was false | toggle | apply/off |
| `lights_toggle_multiple` | → true (each) | if was false | collective toggle | apply/off all |

### Other Triggers Setting `is_on: true`
- Motion sensor (on_only, on_off modes)
- Boost (sets `is_on: true` + boost values)
- Contact sensor

### Unchanged Primitives
- `step_up` / `step_down` - update midpoints only, no light change
- `reset` - reset midpoints to phase defaults
- `freeze` / `unfreeze` - freeze at time position

---

## Implementation Tasks

### Phase 1: State Layer (`state.py`)

1. **Rename `enabled` → `is_circadian`**
   - `_get_default_area_state()`: add `"is_circadian": False, "is_on": False`
   - Rename `set_enabled()` → `set_is_circadian()`
   - Rename `is_enabled()` → `is_circadian()` (or `get_is_circadian()`)
   - Rename `get_enabled_areas()` → `get_circadian_areas()`
   - Rename `get_unfrozen_enabled_areas()` → `get_unfrozen_circadian_areas()`

2. **Add `is_on` field and helpers**
   - `set_is_on(area_id, is_on: bool)`
   - `get_is_on(area_id) -> bool`

3. **Add reset-on-enable logic**
   - New function: `enable_circadian(area_id)` that:
     - Checks if `is_circadian` was false
     - If so, resets: `is_on=False`, `brightness_mid=None`, `color_mid=None`, `frozen_at=None`, clears boost/motion
     - Sets `is_circadian=True`
   - Or integrate into `set_is_circadian(area_id, True)`

4. **Update reset functions**
   - `reset_area()`: preserve `is_circadian` (was preserving `enabled`)
   - `reset_all_areas()`: preserve `is_circadian` and `is_on`? Or just `is_circadian`?

### Phase 2: Brain Layer (`brain.py`)

1. **Update `AreaState` dataclass**
   - Rename `enabled` → `is_circadian`
   - Add `is_on: bool = False`
   - Update `from_dict()` and `to_dict()`

### Phase 3: Primitives (`primitives.py`)

1. **Rename existing primitives**
   - `circadian_light_on()` → `lights_on()`
   - `circadian_light_off()` → `circadian_off()`
   - `circadian_light_toggle()` → `lights_toggle()`
   - `circadian_toggle_multiple()` → `lights_toggle_multiple()`

2. **Update `lights_on()`**
   - Call `enable_circadian(area_id)` (handles reset if needed)
   - Set `is_on = True`
   - Apply circadian values

3. **Update `lights_off()`**
   - Call `enable_circadian(area_id)` (handles reset if needed)
   - Set `is_on = False`
   - Turn off lights

4. **Update `lights_toggle()`**
   - Call `enable_circadian(area_id)` (handles reset if needed)
   - Toggle `is_on`
   - Apply circadian or turn off

5. **Update `lights_toggle_multiple()`**
   - Check if ANY lights on in ANY area
   - For each area: `enable_circadian()`, set `is_on` based on collective decision
   - Apply/turn off all

6. **Update `circadian_off()`**
   - Set `is_circadian = False`
   - No light change
   - No state reset (values become stale but ignored)

7. **Update `step_up()` / `step_down()`**
   - Check `is_circadian` instead of `enabled`
   - Update midpoints only
   - **Remove** any code that turns on lights
   - Should work even if `is_on: false` (prep for next turn-on)

8. **Update `reset()`**
   - Check `is_circadian` instead of `enabled`
   - Reset midpoints to defaults
   - Don't change `is_on`

9. **Update `boost()`**
   - Should set `is_on = True` when triggered
   - Clear boost → check `boost_started_from_off` to decide `is_on`

10. **Update motion handlers**
    - `motion_on_only`: set `is_on = True`
    - `motion_on_off`: set `is_on = True`, when timer expires set `is_on = False`
    - `motion_boost`: set `is_on = True` + boost

11. **Update contact sensor handlers**
    - Similar to motion: set `is_on = True` on trigger

### Phase 4: Main Loop (`main.py`)

1. **Update periodic update loop**
   - Get `get_unfrozen_circadian_areas()` (renamed)
   - For each area:
     - If `is_on: true` → apply circadian values (current behavior)
     - If `is_on: false` → turn off lights (new enforcement)

2. **Update button handlers**
   - Replace `state.is_enabled()` → `state.is_circadian()`
   - Update logic for checking enabled state

3. **Update Hue switch handlers**
   - Replace calls to old primitive names

4. **Update service call handlers**
   - Rename service mappings if needed

5. **Startup behavior**
   - On startup, for all `is_circadian: true` areas, enforce `is_on` state
   - This solves the power-failure scenario

### Phase 5: Web Server (`webserver.py`)

1. **Update API responses**
   - Change `enabled` → `is_circadian` in area status responses
   - Add `is_on` to responses

2. **Update API handlers**
   - Rename `/api/area/.../enable` endpoint or update to use new state
   - Handle both `is_circadian` and `is_on` in requests

3. **Update UI data**
   - Areas page needs to show `is_circadian` and `is_on` status

### Phase 6: Tests

1. **Update `test_brain_*.py`**
   - Update `AreaState` construction to use `is_circadian`
   - Add tests for `is_on` behavior

2. **Add new tests**
   - Test reset-on-enable logic
   - Test `is_on` enforcement in periodic updates
   - Test lights_toggle behavior when `is_circadian` was false

### Phase 7: Integration Components

1. **Check `custom_components/circadian/`**
   - Update service definitions if primitives renamed
   - Update `services.yaml`

---

## Migration

No backward compatibility needed (not released). Clean rename throughout.

---

## Open Questions

1. **`reset_all_areas()` on phase change**: Should it preserve `is_on`?
   - Current: preserves `enabled` and `frozen_at`
   - Proposed: preserve `is_circadian`, `is_on`, and `frozen_at`?

2. **Boost expiry when `boost_started_from_off: true`**: Currently turns off lights. With new model, should it set `is_on: false`?
   - Yes, this aligns with the model.

3. **Motion `on_off` expiry**: Sets `is_on: false` - correct.

4. **What if `is_circadian: false` and step_up/step_down called?**
   - Option A: No-op (can't adjust if not in control)
   - Option B: Still adjust midpoints (prep for when control taken)
   - Recommend A: require `is_circadian: true`

---

## Estimated Scope

- **state.py**: ~50 lines changed
- **brain.py**: ~10 lines changed
- **primitives.py**: ~200 lines changed (heaviest)
- **main.py**: ~100 lines changed
- **webserver.py**: ~30 lines changed
- **tests**: ~50 lines changed
- **custom_components**: ~10 lines changed

Total: ~450 lines across 7+ files
