<!-- https://developers.home-assistant.io/docs/add-ons/presentation#keeping-a-changelog -->

## 1.0.25
- **Fix color down not reaching warmest colors**: Color override was double-counted when checking limits, causing color_down to stop far above the configured minimum. Now correctly reaches the full slider range.
- **Fix multi-step brightness/color**: Variable shadowing bug prevented multi-step (2x, 3x) brightness and color actions from working.
- **Match brightness final font size**: Expanded brightness card "Final" value now matches the collapsed header size.

## 1.0.24
- **Redesign switch actions page**: Replaced desktop-only two-panel layout with a mobile-friendly single-column card-per-button design. Added Cheat Sheet mode showing a read-only summary of all assigned actions with copy-to-clipboard. Magic Button Assignments summary shows per-switch moment bindings.

## 1.0.23
- **Reorder navigation**: Controls now appears before Tune in the main header nav across all pages.
- **Move search box below Name header**: On the controls list page, the search field now sits directly below the Name column header instead of the toolbar, keeping filters visually close to the data they affect. Still searches both name and area.
- **Multi-step up/down**: Step Up, Step Down, Bright Up, and Bright Down primitives now accept a `steps` parameter for performing multiple steps in one action. New switch action options: Step Up/Down 2× and 3×, Bright Up/Down 2× and 3×. Color Up/Down also supports the `steps` parameter internally but has no dropdown entries.

## 1.0.22
- **Fix assign picker search focus loss**: Typing in the switch search field no longer loses focus after each keystroke — input element is now preserved while only the results list is updated.
- **Fix assign picker showing "No matching controls"**: Independent error handling for each API fetch (`Promise.allSettled`) prevents one failed request from blocking switch/switchmap data loading.
- **Persist moment ID migration to disk**: Moment ID migration (`emergency_1st_floor` → `moment_1`) now saves to config file on startup instead of only updating in-memory state.
- **Add exception column headers**: Exception section now shows Area, Action, and Auto-off column headers.
- **Add bright and emergency icons**: New moment icon options: lightning bolt (bright) and rotating light (emergency).
- **Show moment icons on control detail**: Magic button dropdowns and orphaned assignment labels now display the assigned moment's icon.

## 1.0.21
- **Stable moment IDs**: Moments now use auto-incrementing IDs (`moment_1`, `moment_2`, ...) instead of name-derived slugs. Renaming a moment no longer breaks switch button assignments. Existing configs are auto-migrated on startup.
- **Defer periodic update after switch action**: Periodic circadian tick is skipped if a switch action occurred within the last 3 seconds, preventing Zigbee mesh flooding that caused lights to flicker after switch presses.
- **Parallelize multi-area turn-off**: `lights_toggle_multiple` now sends all turn-off commands in parallel via `asyncio.gather` instead of sequentially, reducing latency for switches controlling multiple areas.
- **Redesign moment detail page**: Moment editor now uses collapsible card sections (Settings, Exceptions, Usage) matching the area and control detail page style. New Usage section shows which switch buttons have the moment assigned, with inline picker to assign the moment to new controls.

## 1.0.20
- **Fix Hue SML003 motion sensor miscategorization**: Use `device_class` fallback (from entity registry and state attributes) to correctly identify motion sensors whose entity_ids don't contain `_motion`. Skip companion `_opening` entities on motion sensor devices from being cached as contact sensors.
- **Clean up stale sensor configs on save**: When saving a motion sensor config, any old contact sensor config for the same device is automatically removed (and vice versa).
- **Fix slider gradient not showing color range**: Circadian slider gradients on area detail and home pages now show the full achievable color range instead of the solar-rule-clamped range, matching what the slider actually produces via `color_override`.
- **Add third-step retry for two-step turn-on**: Configurable retry after two-step turn-on to catch intermittent cases where ZHA drops the brightness command, leaving lights at 1%.
- **Show and remove stale areas**: Areas deleted from HA now appear in organize mode with a remove option, and are filtered from the area picker.
- **Extend motion timers during cooldown**: Motion detected during cooldown now extends timers for areas with lights already on, without re-triggering dark areas.
- **Show last action in control detail header**: Last action and timestamp displayed below control name.
- **Reduce log noise**: Switch-not-found and per-entity motion detection logs moved to DEBUG level.

## 1.0.19
- **Fix large reach group creation failure**: ZHA's `group/add` API times out when creating groups with 32+ members in a single call. Now creates groups empty first, then adds members in batches of 16. Also checks return values — if group creation fails, skips member add and area move (preventing orphaned entities).
- **Fix motion cooldown timer not visible on controls list page**: Cooldown countdown now displays for both `motion_detected` and `motion_cleared` actions, with live 1-second countdown and 15-second background poll for new triggers.
- **Expand Magic Moments actions**: Add "On" (lights on to circadian) and "BriteLite" actions to moment action list.
- **Add auto-off timer to Magic Moments**: Configure a timer (in minutes) that auto-turns-off lights after a moment applies, using existing motion timer infrastructure. Timer cancels if lights are turned off by any other means.
- **Remove motion-specific labels from timer display**: Timer badges no longer show "M" prefix or "Motion:" prefix since the timer is now shared between motion sensors and moments.
- **Add switch entity support**: Areas with only `switch.*` domain entities (relays, smart plugs) can now be toggled via the power button. Switch entities are controlled on explicit on/off/toggle, motion timer expiry, presets, and moments — but not during periodic circadian updates.

## 1.0.18
- **Fix breathing caused by stale reach group entities**: Orphaned ZHA reach group entities (from failed 32-member group creation) were never moved to `Circadian_Zigbee_Groups` and inherited the coordinator's area (Office). Office's periodic turn_off commands hit these multi-area group entities, turning off lights in Kitchen/Family/Entry/etc. every 20 seconds. Fix: skip any entity with `_circadian_` in its entity_id from area light enumeration — these are group entities, never real lights.

## 1.0.16
- **Fix ZHA group entities counted as area lights**: ZHA group entities (e.g., `Circadian_Kitchen_Standard_color`) were inheriting the coordinator device's area instead of using the entity registry's area override (`Circadian_Zigbee_Groups`). This caused the coordinator area (Office) to report 20 ZHA lights instead of 4, adding the coordinator's IEEE to area groups. Periodic updates to those groups sent conflicting commands to other areas' devices, causing breathing/oscillation.

## 1.0.14
- **Fix override decay after midnight**: Brightness and color overrides (from step_up/down, Full Send, GloDown) no longer decay instantly after midnight — `set_at` time is now correctly converted to h48 space before computing decay

## 1.0.11
- **Fix breathing on non-Standard filter lights**: Lights with Overhead/Lamp/etc. filters now use individual commands instead of ZHA group broadcasts, preventing stale group ID cross-talk
- **Fix ZHA group cleanup**: Remove members before deleting obsolete groups; smart color_temp_kelvin clamping using actual light attributes
- **Fix shed/switch-only area visibility**: Areas configured in glozones now appear even without light entities
- **Apply brightness_override on all turn-on paths**: `circadian_on`, `lights_on`, and `lights_toggle_multiple` now apply decayed brightness_override immediately
- **Fix cooldown countdown**: Timer display now works correctly; areas with only switch entities show properly
- **Add configurable motion sensor cooldown**: New setting for motion sensor cooldown duration
- **Fix motion/contact sensor config persistence**: Config now persists after save

## 1.0.0
**Initial public release**

- **Rhythm Designer**: Visual curve editor for brightness and color temperature schedules
  - Interactive gradient sliders for color temperature and brightness ranges
  - Draggable handles with real-time chart preview
  - Wake/Bed sub-sections with per-day scheduling and alternate times
  - Warm Night and Cool Day solar rules with start/end/fade controls
  - Live Design mode: preview changes on real lights in real time
  - Cursor pill shows current values at any time position
- **Tune page**: Per-zone overview of color temperature and brightness settings
  - Color tab with gradient visualization showing warmest/coolest/night max ranges
  - Sun exposure column for zones with Cool Day enabled
- **Controls page**: Switch and button management for ZHA devices
- **Magic Moments**: Whole-home lighting presets with per-area exceptions
- **Settings page**: Location, timezone, and integration configuration
- **Area management**: Group lights into zones with custom ordering
- **Multi-protocol support**: ZHA, Z-Wave, WiFi, and Matter light control
- **Mobile optimized**: Touch-friendly controls and responsive layout
