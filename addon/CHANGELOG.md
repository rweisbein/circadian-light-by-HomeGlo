<!-- https://developers.home-assistant.io/docs/add-ons/presentation#keeping-a-changelog -->

## 1.0.60
- **Fix glozones endpoint fetching from HA on every poll**: Area name enrichment now reads from shared in-memory cache instead of opening a WebSocket to HA on every `/api/glozones` call. Eliminates ~20 WebSocket connections/min at 3s polling.

## 1.0.59
- **2-step color pre-send in filter pipeline**: When a purpose group has a large color temperature shift (configurable, default 500K) and brightness is changing significantly (>=15%), the color change is applied first at the dimmer brightness to hide the visible color arc. Handles off-to-on (always), brightening (color first, then brighten), and dimming (dim first, then color). Already-on groups with small changes update immediately with no delay.
- **Fix missing 2-step on toggle turn-on**: `lights_toggle_multiple` now routes through `_apply_lighting_turn_on_multiple` for proper 2-step behavior when turning on areas.
- **Configurable CT threshold**: `two_step_ct_threshold` setting (default 500K) controls when 2-step fires, used across all 2-step paths.

## 1.0.58
- **Direct method calls replace HA event round-trips**: Web UI actions (switch presses, boost, sync devices, config saves, etc.) now call main process methods directly instead of firing events through Home Assistant. Faster response, fewer WebSocket connections, simpler code. Removed ~60 lines of event plumbing.

## 1.0.57
- **Eliminate polling overhead**: Home page no longer opens WebSocket connections to HA or re-reads state from disk on every poll. Shared in-memory state means polling endpoints are now pure computation with zero I/O.
- **Faster home page refresh**: Default refresh interval reduced from 10s to 3s. Existing users are migrated automatically. Switch presses and motion triggers now appear on the home page almost immediately.
- **Suppress access logging**: HTTP request logs from polling disabled to keep logs clean at higher poll rates.

## 1.0.56
- **Unified process architecture**: Webserver now runs embedded in the main process instead of as a separate background process. This is a structural change (Phase 1 of process merge) — no behavior changes yet, but lays the groundwork for eliminating redundant computation and WebSocket connections in the polling endpoints.

## 1.0.33
- **Direct weather outdoor brightness formula**: Replaced log-compressed lux estimation with a direct `elevation_factor × condition_multiplier` formula for weather and angle sources. This dramatically improves differentiation between weather conditions — sunny vs rainy spread goes from ~12% to ~46%. The lux sensor path is unchanged.
- **Configurable weather condition strengths**: Settings > Outdoor Brightness now shows slider controls for each weather condition group (Sunny, Partly cloudy, Cloudy, Rainy, Snow, Fog, Pouring, Storm) when source is Weather or Sun Angle. Adjustments are saved as `weather_condition_map` in config.
- **Latitude-aware elevation scaling**: Max summer solstice elevation is computed from your Home Assistant latitude, so the elevation factor correctly reaches 1.0 at your location's peak sun angle rather than using a fixed reference.

## 1.0.32
- **Cancellable post-command nudge**: After every light command (switch press, motion trigger, step, color change), the same values are re-sent 1 second later to catch dropped Zigbee commands. Per-area tracking means a new action cancels only that area's pending nudge. Replaces the old third-step retry with broader coverage across all command types. Configurable in Settings > Zigbee Improvements (0 = disabled).
- **New Zigbee Improvements settings section**: Two-step delay and post-command nudge settings are now grouped under their own section, separate from Feedback Cues.

## 1.0.31
- **Fix Hue motion sensors being disabled**: Switch entity collection for area on/off now skips entities with `entity_category` of "config" or "diagnostic". Previously, Hue motion sensor enable/disable switches (`switch.*_sensor_enabled`) were included as area switch entities, causing them to be turned off whenever the area turned off — disabling the motion sensors on the Hue hub.

## 1.0.30
- **Cheat sheet default view**: Switch Map page now opens in Cheat Sheet mode by default, with the Edit toggle second.
- **Cheat sheet visual improvements**: Button name and icon are now vertically centered across all action rows for that button. Stronger visual separators between button sections.
- **Sticky column headers**: Controls page table headers stay visible below the nav bar when scrolling.
- **Filter coordinator from area lights**: Service devices (coordinators, bridges) no longer appear in the area detail light list.
- **Time-based filter expiry**: Controls page sort/filter preferences expire after 5 minutes, so returning after a break or opening a new tab starts fresh.
- **Fix filtered lights not turning off with negative override**: Lights with off_threshold (e.g., Day accent) now correctly turn off when stepped down below the threshold. Previously, any brightness override (including negative/dimming) blocked auto-off; now only positive overrides (user brightened) prevent it.

## 1.0.29
- **Step collapse**: Multi-step commands (step_down_3, bright_up_2, etc.) now compute all steps in a single loop and send one light command at the end, instead of recursively sending per step.
- **Reach groups for toggle on**: Multi-area switch toggle-on uses reach groups when all areas produce identical lighting values (no filters, same NL factor), with 2-step warm flash prevention.
- **Reach groups for step/bright**: Step and brightness commands on multi-area switches compute values without sending, then dispatch via reach groups when all areas match. A 3-area step_down_3 drops from 18 Zigbee commands to 2.

## 1.0.28
- **Filter service devices from area lights**: Devices with `entry_type: "service"` (coordinators, bridges) are now excluded from area light lists and light commands, without affecting legitimate on/off-only lights like smart plugs.
- **Detect stale switches**: Switches whose device no longer exists in Home Assistant are marked stale and filtered from the moment assign picker, preventing duplicate entries from old config data.
- **Power icon visible on moment detail header**: Fixed ⏻ icon not rendering in header button by using inherited font-family instead of browser button defaults.
- **Moments list mobile-friendly**: Removed Category column from moments list for a cleaner layout.
- **Cheat sheet compact layout**: Button badge and label now appear inline to the left of action rows, saving vertical space.
- **Magic summary single-line layout**: Each magic assignment now shows on one line (switch · slot → moment) instead of two lines.
- **Usage section styling**: Switch name is bolder; button press label is more muted for better hierarchy.
- **Remove magic assignment from moment detail**: × button on each usage row lets you remove a magic button assignment directly.
- **Session-only filter persistence**: Controls page sort/filter preferences now use sessionStorage instead of the config API, so preferences don't leak across devices or users.
- **Fourth column sort button**: Added a visible sort arrow next to the fourth column dropdown, making it easier to sort by that column.
- **Status column on controls page**: New "Status" option in the 4th column dropdown shows Active, Paused, Setup, Unsupported, or Stale for each control.
- **Surface stale controls**: Config-only entries whose device no longer exists in HA now appear in the controls list as "Stale" with a × button to remove them from config.

## 1.0.27
- **Sort assign picker by name**: Controls in the moment "assign to control" picker are now sorted alphabetically.
- **Run button on moment detail page**: Play button in the header lets you run a magic moment directly from its detail page.
- **Back navigation returns to moment page**: Clicking "back" on a control detail page opened from a moment's Usage section now returns to that moment.
- **Filter stale switches from assign list**: Switches with no assigned areas are excluded from the moment assign picker.
- **Switch name as link in Usage section**: Switch name is now a clickable link (white, orange on hover) replacing the separate "Edit" link.
- **Add power-off icon for moments**: New ⏻ icon option in the moment icon picker for "off" presets.
- **Replace Exceptions with Usage on moments list**: Moments list now shows a Usage column (number of controls using each moment) instead of exception count.
- **Fix search field on controls list**: Search input no longer loses focus after each keystroke; clear button works correctly.
- **Fourth-field dropdown sorts by column**: Selecting a value in the 4th column dropdown now also sorts by that column. Re-selecting the same value toggles sort direction.
- **Fix Exceptions header alignment**: Action and Auto-off column headers now align with their data fields.
- **Cheat sheet print optimization**: Tighter spacing, print-friendly colors, switch type title shown, page breaks avoided within cards.
- **Fix magic button alignment on cheat sheet**: Long switch names truncate with ellipsis instead of wrapping and clipping.

## 1.0.26
- **Rename Switch Map page**: Page title and Controls menu link now say "Switch Map".
- **Group action variants in dropdown**: Step Up/2x/3x now listed contiguously, same for Step Down, Bright Up, Bright Down.
- **Fix clipboard copy on Safari**: Use textarea fallback for Safari compatibility.
- **Improve magic summary layout**: Switch name on first line, button slot indented on second line; moment right-aligned. Removed redundant "Button" suffix.
- **Always show User brightness adjustment**: Brightness card now always shows "User brightened" or "User dimmed" row, even when zero.
- **Filter out Zigbee coordinator**: Coordinator device (e.g., ZBT-1) no longer appears as a light in area details and no longer receives light commands.

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
