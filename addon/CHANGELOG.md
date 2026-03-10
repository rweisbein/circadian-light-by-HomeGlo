<!-- https://developers.home-assistant.io/docs/add-ons/presentation#keeping-a-changelog -->

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
