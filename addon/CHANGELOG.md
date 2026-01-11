<!-- https://developers.home-assistant.io/docs/add-ons/presentation#keeping-a-changelog -->

## 6.7.6
**Feature - Add preset parameter to circadian_on**

**Added:**
- `circadian_on` now accepts optional `preset` parameter (nitelite, britelite, wake, bed)
- Enables atomic enable+preset in single call for reliable operation

**Changed:**
- Blueprint now uses single `circadian_on` with `preset: nitelite` instead of two calls
- Fixes issue where lights would turn on with wrong values when off

## 6.7.5
**Improvement - Unified freeze_toggle dim duration**

**Changed:**
- Both freeze and unfreeze now dim over 0.8s
- Freeze: dim 0.8s, flash on instantly
- Unfreeze: dim 0.8s, rise over 1s

## 6.7.4
**Improvement - Fine-tune freeze_toggle animation timing**

**Changed:**
- Freeze (on): dim over 0.8s, flash on instantly
- Unfreeze (off): dim over 0.4s, rise over 1s

## 6.7.3
**Bugfix - Fix unfreeze producing negative midpoints**

**Fixed:**
- Fixed tuple unpacking order in `_unfreeze_internal` for `get_phase_info` return values
- Was incorrectly using hour (h48) as slope, causing negative midpoint calculations
- Unfreeze now correctly re-anchors midpoints and maintains proper lighting values

## 6.7.2
**Bugfix - Debounce freeze_toggle to prevent double-bounce**

**Fixed:**
- Added 3-second debounce guard to freeze_toggle_multiple to prevent double-triggering
- Fixes issue where switch button press caused lights to bounce twice (down-up-down-up)

## 6.7.1
**Improvement - Bundle integration with addon**

**Changed:**
- Custom integration now bundled in addon rootfs for reliable deployment
- Fixes "unknown action" errors when HA cached old integration version

## 6.7.0
**Feature - Long-press hold support and freeze_toggle visual improvements**

**Added:**
- Long-press (hold) support for brighter/dimmer buttons: bright_up/bright_down
- ZHA up_hold and down_hold triggers in hue_dimmer_switch blueprint

**Changed:**
- freeze_toggle timing: freeze brightens instantly (transition=0), unfreeze brightens over 1s
- Added freeze_toggle_multiple for batched operation (all areas dim/brighten together)

## 6.6.0
**Refactor - Full rename from MagicLight to Circadian Light**

**Changed:**
- Renamed all internal references from "magiclight" to "circadian_light"
- Blueprint namespace: `/blueprints/automation/circadian_light/`
- Addon path: `/opt/circadian_light/`
- Updated all documentation, tests, and configuration files

## 6.5.0
**Feature - New button mappings and broadcast primitive**

**Added:**
- New `broadcast` primitive copies settings from source area to all other areas
- New `hue_dimmer_switch.yaml` blueprint with updated button mappings:
  - Power: toggle (1x), broadcast (2x), on+britelite (4x)
  - Brighter: step_up if on, on+nitelite if off
  - Dimmer: step_down if on, on+nitelite if off
  - Hue: freeze_toggle (1x), reset (4x)
- Support for quadruple-press ZHA events

**Changed:**
- Renamed original blueprint to `hue_dimmer_switch_former_magiclight.yaml` (legacy)

## 6.4.0
**Feature - New `set` primitive for state configuration**

**Added:**
- New `set` primitive handles presets, frozen_at, and copy_from in one unified interface
- Presets: `wake`/`bed` (midpoint = current time, NOT frozen), `nitelite`/`britelite` (frozen at phase boundary)
- `copy_from` parameter copies all lighting state from another area (for "share settings" feature)
- Priority order: copy_from > frozen_at > preset

**Removed:**
- `freeze` and `unfreeze` primitives (functionality moved to `set` and `freeze_toggle`)

**Changed:**
- `freeze_toggle` uses internal unfreeze logic (re-anchor midpoints for smooth transition)

## 6.3.1
**Bugfix - Step applies solar rules to color**

**Fixed:**
- Step up/down now applies solar rules (warm_night/cool_day) to calculated color
- Previously, stepping while warm_night was active would jump to cooler temps because solar rules weren't applied to the curve calculation

## 6.3.0
**Feature - Time-based freeze with presets and smooth unfreeze**

**Changed:**
- `frozen` boolean replaced with `frozen_at` (hour 0-24) - freeze now captures a time position
- When frozen, calculations use `frozen_at` instead of current time
- Frozen areas still receive periodic updates (outputting same values)
- Stepping while frozen shifts midpoints but keeps `frozen_at` - allows adjustments without unfreezing
- `reset` now clears `frozen_at` (unfreezes)

**Added:**
- `freeze` accepts `preset` parameter: `"nitelite"` (min values), `"britelite"` (max values), or `None` (current)
- `freeze` accepts `hour` parameter: specific hour (0-24) to freeze at (takes priority over preset)
- `unfreeze` now re-anchors midpoints so curve continues smoothly from frozen position (no sudden jump)
- New `freeze_toggle` primitive with visual effect (dim to 0%, then rise to new state)
- `AreaState.is_frozen` property for convenient frozen status check

**Fixed:**
- Frozen state persists across toggle off, circadian_off, and phase changes (only cleared by explicit unfreeze or reset)

## 6.2.9
**Bugfix - Primitives now load config from files**

**Fixed:**
- Primitives (reset, step_up, step_down, etc.) now load config directly from `designer_config.json`
- Previously relied on `client.config` which wasn't always populated
- Config bounds (min/max brightness, min/max color temp) are now respected by all services

## 6.2.8
**Bugfix - Periodic updater now respects stepped values**

**Fixed:**
- Periodic light updates (every 30s) now respect per-area stepped state
- Step down values no longer reset to default curve values after a few seconds
- Uses `CircadianLight.calculate_lighting()` with area state instead of ignoring stepped midpoints/bounds

## 6.2.7
**Bugfix - Step down wraparound at bounds**

**Fixed:**
- Step down no longer causes brightness to jump to high values when reaching minimum
- Now triggers "pushing bounds" behavior when step would exceed config limits (not just when already at limit)
- Prevents garbage midpoint calculations that caused infinite cycling

## 6.2.6
**UI - Solar rule slider constraints and tooltips**

**Changed:**
- Renamed "Warm at night" to "Warm night" and "Cool during day" to "Cool day"
- Warm night and Cool day target sliders now constrained to color range bounds
- Warm night target cannot go below Cool day target (prevents conflicting rules)
- Slider track gradients update dynamically to reflect valid range
- Added info icon tooltips explaining Warm night and Cool day functionality

**Fixed:**
- Rebuilt test suite to match current brain.py API (139 tests passing)
- Fixed blueprint manager test environment variable name
- Added platform skip markers for Linux-only integration tests

## 6.2.5
**Refactor - Rename "adaptive" to "circadian" throughout codebase**

**Changed:**
- Renamed `AdaptiveLighting` class to `CircadianLight` (alias kept for backwards compatibility)
- Renamed `get_adaptive_lighting()` to `get_circadian_lighting()` (alias kept)
- Renamed `turn_on_lights_adaptive()` to `turn_on_lights_circadian()`
- Renamed `get_adaptive_lighting_for_area()` to `get_circadian_lighting_for_area()`
- Updated all documentation to use "circadian" terminology
- Updated test class and function names

## 6.2.4
**Bugfix - Accurate Step button labels with solar rules**

**Fixed:**
- Step Up/Down button labels now correctly show predicted CCT values
- Labels properly reflect curve traversal with solar rules (warm at night, cool during day)
- Step Down no longer incorrectly shows cooler/higher CCT when warm at night is active
- Added `getStepPreview()` function as single source of truth for step calculations
- Added `applySolarRuleAtHour()` for single-point solar rule application

## 6.2.3
**UI - Reduce vertical space below chart**

**Changed:**
- Reduced chart bottom margin from 140px to 60px
- Moved cursor label closer to x-axis (y=-0.10 instead of -0.26)

## 6.2.2
**Bugfix - Fix area filtering for device-assigned lights**

**Fixed:**
- Areas now correctly detected when lights are assigned via device (not entity)
- Fetches device registry to map device_id → area_id
- Checks both direct entity area and area inherited from device

## 6.2.1
**Enhancement - Filter areas by lights**

**Changed:**
- Live Design dropdown now only shows areas that have lights
- Areas without `light.*` entities are filtered out

## 6.2.0
**Enhancement - Live Design pauses Circadian updates**

**Added:**
- Live Design now automatically pauses Circadian mode for the selected area
- When enabled, periodic updates won't override your Live Design changes
- Circadian mode is automatically re-enabled when you disable Live Design
- Switching areas while Live Design is active properly swaps Circadian state
- `/api/circadian-mode` endpoint to enable/disable Circadian for an area
- Status indicator shows "Circadian paused - designing" when active

## 6.1.0
**Feature - Live Design Mode**

**Added:**
- Live Design: Preview lighting changes in real-time on actual lights
- Area selector dropdown in Designer UI (populated from Home Assistant areas)
- Enable/Disable toggle for Live Design mode
- `/api/areas` endpoint to fetch Home Assistant areas
- `/api/apply-light` endpoint to control lights via HA REST API

**Usage:**
1. Select an area from the dropdown in the Designer
2. Click "Enable" to activate Live Design
3. Click anywhere on the chart to set lights to that position's values
4. Use Step/Bright/Color buttons - lights update in real-time
5. Click "Disable" when done designing

## 5.0.27-alpha
**Enhancement - Color Stepping Works with Solar Rules**

**Changed:**
- Color Up/Down now operates on DISPLAYED color (after solar rules), not base curve
- At 7:30pm with warm_night showing 2700K: Color Down → 2100K (actually changes the color)
- Color Up can now override warm_night ceiling: 2700K → 3300K raises the temporary ceiling

**Added:**
- `runtimeState.warm_night_ceiling`: Can only increase above config target (via Color Up)
- `runtimeState.cool_day_floor`: Can only decrease below config target (via Color Down)
- Temporary ceiling/floor chips appear next to target chips when values differ
- Graph reflects the temporary ceiling/floor values

**Reset behavior:**
- Ceiling/floor reset on: page refresh, Reset button, phase transition (ascend↔descend)
- Clicking cursor from Ascend to Descend (or vice versa) resets all runtime state

## 5.0.26-alpha
**Bugfix - Cursor Button Stepping Fixes**

**Fixed:**
- Fixed `getBrightnessAtCursor()` using `window.graphData` instead of local `graphData` variable
- Bright Down button now works correctly (was silently failing due to undefined graphData)
- Added `getDisplayedCCTAtCursor()` function to read CCT after solar rules are applied
- Color buttons now correctly detect when solar rules are blocking changes
- Color Up shows × when warm_night is pulling displayed CCT below base curve
- Color Down shows × when at warm_night_target (can't go warmer)
- Step buttons now use solar-aware color extreme detection

## 5.0.25-alpha
**Enhancement - Fixed Value Step Increments**

**Changed:**
- Bright Up/Down now changes brightness by fixed increment: `(max - min) / steps`
  - With 10 steps and 1-100% range: each click = 10% change
- Color Up/Down now changes CCT by fixed increment: `(max_K - min_K) / steps`
  - With 10 steps and 500-6500K range: each click = 600K change
- Step Up/Down still shifts both midpoints together by time (keeps them locked)
- Uses inverse logistic function to calculate midpoint needed for target value

**Added:**
- "At extreme" visual indicator (×) on buttons when value is at min/max
- Button becomes semi-transparent and non-functional at extremes
- Bright Up shows × when at max brightness
- Bright Down shows × when at min brightness
- Color Up shows × when at max CCT
- Color Down shows × when at min CCT
- Step buttons show × only when BOTH brightness and color at same extreme

## 5.0.20-alpha
**UI - Timeline Badge Positioning**

**Added:**
- Ascend/Descend start time badges now slide along a horizontal timeline
- Position reflects time of day (0h=left, 12h=center, 24h=right)
- Subtle line provides visual context for time placement
- Smooth transition animation when switching presets

## 5.0.17-alpha
**Enhancement - Hover Callouts for X-Axis Labels**

**Added:**
- Hovering over phase labels (ascend starts, wake, descend starts, bed) shows time callout
- Hovering over solar labels (sunrise, sunset, solar noon, solar midnight) shows time callout
- Phase label callouts use phase colors (blue for ascend, gold for descend)
- Solar label callouts use neutral grey background
- Cursor callout already shows: time • brightness% • CCT K • phase

## 5.0.16-alpha
**Enhancement - Solar-Based Preset Times**

**Added:**
- Young Child preset now uses solar midnight (rounded) for ascend start
- Young Child and Adult presets now use solar noon (rounded) for descend start
- Times are calculated dynamically based on configured location and selected date
- Other presets (Night Owl, Dusk Bat, Shift workers) use fixed times as before

## 5.0.14-alpha
**UI - Subtle Yellow Tint for Descend**

**Changed:**
- Descend section block now has a very subtle warm yellow tint (6% opacity)
- Descend phase on graph now shaded with subtle yellow (8% opacity)
- Previous: dark gray/black; now: barely perceptible warm glow

## 5.0.13-alpha
**UI - Time Badges in Section Headers**

**Added:**
- Ascend and Descend section headers now show start time as a badge/pill
- Example: `Ascend [4:00a]` and `Descend [12:00p]`
- Badges update automatically when switching activity presets
- Styled with phase-appropriate colors (blue for ascend, gold for descend)

## 5.0.12-alpha
**UI - Hide Ascend/Descend Start Sliders**

**Changed:**
- Ascend starts and Descend starts sliders are now hidden
- Controls remain in code for future "custom" activity preset
- Users adjust timing via activity presets; wake/bed times remain adjustable

## 5.0.11-alpha
**Bugfix - Preset Slider Constraint Order**

**Fixed:**
- Switching presets now correctly applies wake/bed times regardless of previous preset
- Previously, slider constraints from the old preset would clamp new values incorrectly
- Example: Switching from Adult to Overnight Shift Early showed noon instead of 10am bedtime
- New `updateWakeBedSliderConstraints()` function updates min/max BEFORE setting values

## 5.0.10-alpha
**Enhancement - Solar Rules in Activity Presets**

**Added:**
- Activity presets now include "Warm at night" and "Cool during day" settings
- Young, Adult, Night Owl: warm_night_enabled = true
- Dusk Bat, Overnight Shift Early/Late: warm_night_enabled = false
- All presets: cool_day_enabled = false (per llm_access reference)
- Selecting a preset now automatically updates the solar rule checkboxes

## 5.0.9-alpha
**Bugfix - Activity Preset Midnight Wrap**

**Fixed:**
- Activity presets with bed times after midnight (Night Owl 2am, Dusk Bat 6am) now display correctly
- Previously, bed times like 2:00am were incorrectly clamped to descend_start (e.g., 4pm)
- Slider values now properly add 24 hours when bed_time wraps around midnight
- Affected presets: Night Owl, Dusk Bat

## 5.0.8-alpha
**Enhancement - Phase Name Labels on Graph**

**Ascend/Descend Labels:**
- Added "Ascend" and "Descend" labels above the curve at y=115 (above 100% brightness)
- Labels appear in the center of each phase segment
- If a phase wraps around midnight (spans > 1 hour on each side), it shows labels on both sides
- Labels use phase colors: blue for Ascend, gold for Descend
- Segments shorter than 1 hour are skipped to avoid clutter

## 5.0.7-alpha
**Enhancement - Location Section, Always Show Wake/Bed Labels**

**Collapsible Location Section:**
- Added collapsible "Location" section in Brightness & Color panel
- Shows current lat/long in collapsed header (e.g., "35.00°N, 78.60°W")
- "Use Home Assistant location" checkbox (default: on)
- When unchecked, lat/long fields become editable for manual override
- Location changes re-render the chart with updated solar times

**Wake/Bed Labels Always Visible:**
- Bright and Color button stacks now always show wake/bed time label
- Previously only showed when adjusted; now shows even at base value
- Label displays "wake X:XXa" during ascend phase, "bed X:XXp" during descend

## 5.0.6-alpha
**Enhancement - Solar Rule Mode Dropdown, Midpoint Labels**

**Warm-at-Night Mode Dropdown:**
- "all night" - applies warming from sunset to sunrise (full night)
- "before sunrise" - applies warming from solar midnight to sunrise only
- "after sunset" - applies warming from sunset to solar midnight only

**Cool-During-Day Mode Dropdown:**
- "all day" - applies cooling from sunrise to sunset (full day)
- "after sunrise" - applies cooling from sunrise to solar noon only
- "before sunset" - applies cooling from solar noon to sunset only

**Midpoint Labels Under Buttons:**
- Bright and Color button stacks now show midpoint label when adjusted
- Label shows "wake X:XXa" or "bed X:XXa" depending on cursor phase
- Label only appears when runtime midpoint differs from base wake/bed time
- Label clears when cursor is removed or reset

## 5.0.5-alpha
**Enhancement - Button NEXT Values, Dual Sliders, UI Reorganization**

**Cursor Button Colors:**
- Buttons now show what action WILL DO (next step values) instead of current state
- Brightness buttons show next brightness percentage fill
- Color buttons show next CCT color
- Step buttons show next values for both brightness and color

**Dual Range Sliders:**
- Fixed left handle not being grabbable (z-index and pointer-events fix)
- Both handles now properly draggable on color range and brightness range sliders

**UI Reorganization:**
- Removed separate "Solar Color Rules" section
- Warm-at-night and Cool-during-day now integrated into "Brightness & Color" section
- Grouped layout with label on left, controls on right (like llm_access)
- Controls grey out when checkbox is unchecked
- Removed "Enable" label (checkbox presence is sufficient)

**Label Changes:**
- "Step increments" renamed to just "Increments"

**Cursor Callout:**
- Callout now positioned at fixed Y above 100% brightness line (like llm_access)
- Follows cursor horizontally but stays at consistent vertical position

**Cursor Ball:**
- Added CCT-colored ball marker at cursor intersection with graph
- Ball has white border ring for visibility
- Ball color matches the CCT at that time point

**Reset Button:**
- Reset button now clears the cursor (hides step/bright/color buttons)
- Also resets runtime midpoints as before

## 5.0.4-alpha
**Enhancement - Cursor Controls and Graph Lines**

**Solar Color Rules:**
- Warm-at-night fade now applies at BOTH sunrise and sunset (was only sunset)
- Cool-during-day fade now applies at both ends as well
- Proper fade-in and fade-out transitions

**Cursor Buttons:**
- Buttons now stacked vertically (up above down) like reference design
- Color buttons show CCT-colored background
- Bright buttons show brightness fill gradient
- Step buttons show both color AND brightness visual
- `tintColorByBrightness` function dims colors based on brightness level

**Cursor Line:**
- Line is now dotted (dash: 'dot') instead of solid
- Line extends below x-axis to "cursor" label at y=-0.26
- Line has gap around the cursor point
- White (#fdfdfd) color for visibility

**Graph Vertical Lines:**
- Wake and Bed times now have dotted vertical lines extending up the full graph
- Sunrise and Sunset now have muted grey dotted lines extending up the full graph
- Solar noon and solar midnight lines stop at x-axis (don't extend up)
- All phase labels (ascend/descend starts, wake, bed) have lines going up

## 5.0.3-alpha
**Enhancement - Light Designer Comprehensive Improvements**

**X-Axis Labels:**
- Phase labels (ascend starts, wake, descend starts, bed) now at y=-0.14
- Solar labels (sunrise, sunset, solar noon/midnight) now at y=-0.20
- Proper vertical separation between time, phase, and solar labels

**Click Cursor:**
- Fixed click detection using capture phase events
- Multiple fallback selectors for Plotly plot area
- Now properly places cursor on graph click

**Slider Constraints:**
- Wake time slider constrained between ascend_start and descend_start
- Bed time slider constrained between descend_start and next ascend_start
- Values automatically clamped when boundaries change

**Color Range Slider:**
- Track now displays full CCT color gradient (500K-6500K)
- Masks show inactive range outside selected min/max

**Solar Color Rules - Warm at Night:**
- Color adjustment now applies to graph when enabled
- New offset sliders: Start (before sunset), End (after sunrise), Fade duration
- Button opens colored popup slider to select target temperature
- Chip button shows current temperature with CCT-colored background

**Solar Color Rules - Cool During Day:**
- Color adjustment now applies to graph when enabled
- Mode options: All day, After sunrise, Before sunset
- New offset sliders: Start (from sunrise), End (from sunset), Fade duration
- Button opens colored popup slider to select target temperature
- Chip button shows current temperature with CCT-colored background

## 5.0.2-alpha
**Fix - Light Designer Chart Rendering**

**Bug Fixes:**
- Fixed click cursor not responding to clicks (event listener now on chart wrapper)
- Fixed x-axis label layering: time labels at baseline, phase labels below, solar labels at bottom
- Solar time labels now use consistent muted grey color
- Sun brightness curve now renders as line-only (removed fill)
- Phase shading now renders ABOVE the curve (ascend blue, descend dark)
- Hover callout now shows CCT-colored background with format: `{pct}% • {kelvin}K • {ascending/descending}`
- Time hover label now separate at top with phase-colored background

## 5.0.1-alpha
**Enhancement - Light Designer Visual Improvements**

**UI Changes:**
- Added color-gradient curve showing actual CCT colors along the lighting curve
- Added sun brightness curve (Haurwitz model) for solar irradiance visualization
- Added solar time markers (sunrise, sunset, solar noon, solar midnight)
- Added clickable cursor system for adjusting midpoints on the graph
- Improved chart styling to match reference design

## 5.0.0-alpha
**Major Release - Ascend/Descend Lighting Model**

**BREAKING CHANGE**: Complete redesign of the adaptive lighting model. Existing configurations will be reset.

**New Features:**
- **Ascend/Descend Model**: Replaced rise/fall terminology with clearer ascend/descend phases
  - Ascend phase: Light brightness and color temperature rise (morning)
  - Descend phase: Light brightness and color temperature fall (evening)
- **Activity Presets**: Pre-configured timing patterns for different lifestyles
  - Young Child, Adult, Night Owl, Dusk Bat, Early Shift Worker, Late Shift Worker
- **Solar Color Rules**: New rules for automatic color temperature adjustments
  - "Warm at night" rule: Force warmer colors around sunset and before sunrise
  - "Cool during day" rule: Push colors cooler during bright daylight hours
  - Configurable fade transitions between modes
- **Cursor Controls**: Independent brightness and color adjustments
  - Step Up/Down: Adjust both brightness and color midpoints
  - Bright Up/Down: Adjust only brightness midpoint
  - Color Up/Down: Adjust only color midpoint
  - Reset: Return to base wake/bed time positions
- **48-Hour Unwrapping**: Cross-midnight schedule handling for shift workers and night owls
- **Speed-to-Slope Mapping**: New 1-10 speed scale for intuitive curve steepness control

**UI Changes:**
- Rebuilt Light Designer with Ascend/Descend panels
- Activity preset selector for quick configuration
- Date slider for previewing seasonal variations
- Solar color rules configuration
- New x-axis labels: "ascend starts", "wake", "descend starts", "bed"

**Technical Changes:**
- New configuration schema with `ascend_start`, `descend_start`, `wake_time`, `bed_time`
- Speed parameters use 1-10 scale mapped to logistic slopes
- Separate runtime midpoints for brightness and color (not persisted)
- New API endpoints: `/api/presets`, `/api/sun_times`
- Updated webserver configuration defaults

**Migration:**
- Old configurations will be ignored; users start fresh with new model
- Legacy designer preserved as `designer_legacy.html` for reference

## 4.2.024-alpha
**Enhancement - Hue Room Group Targeting**

**Improvements:**
- Detect and register Hue grouped-light resources alongside existing Magic_ ZHA groups, capturing area metadata for each entity.
- Prefer Hue room entities when issuing `light.turn_on` calls or checking area state, falling back to ZHA groups or area coverage when required.
- Preserve legacy aliases and logging so previously managed mappings and test hooks continue to function.

**Testing:**
- `pytest addon/tests/unit/test_main_websocket.py::TestHomeAssistantWebSocketClientAsync::test_determine_light_target_hue_group`
- `pytest addon/tests/unit/test_main_websocket.py::TestHomeAssistantWebSocketClient::test_update_zha_group_mapping_magic_prefix`

## 4.2.023-alpha
**Enhancement - Blueprint Sync Refresh**

**Improvements:**
- Track SHA-256 checksums for bundled blueprint YAML files and refresh deployments whenever content changes, ensuring Home Assistant picks up updates even when filenames stay the same.

**Testing:**
- Not run (not requested).

## 4.2.022-alpha
**Fix - Hue Dimmer Blueprint Detection**

**Improvements:**
- Allow the bundled Hue dimmer blueprint to match devices whose model string is reported as plain `Hue dimmer switch`, ensuring switches paired via the official Hue integration are eligible while keeping existing RWL021/RWL022 entries.

## 4.2.017-alpha
**Enhancement - Blueprint Disable Cleanup**

**Improvements:**
- Added double-press OFF handling to the bundled Hue dimmer blueprint, routing the action to `circadian.circadian_off` for a fast shutoff.
- When `manage_blueprints` is disabled the add-on now removes previously deployed Circadian Light blueprints and purges managed automations on startup, keeping Home Assistant free of stale artifacts.

**Testing:**
- `pytest addon/tests/unit/test_blueprint_manager.py addon/tests/unit/test_integration_manager.py`

## 4.2.016-alpha
**Feature - Magic Mode State Persistence**

**Improvements:**
- Persist magic mode areas, time offsets, and brightness offsets in `magic_mode_state.json` so active rooms and their positioning survive restarts.
- Load saved state during startup and resave automatically whenever offsets change, including solar-midnight resets and manual dimming adjustments.
- Solar-midnight maintenance now clears stored brightness offsets alongside time offsets to avoid stale dimming.
- Step up/down primitives now re-query adaptive lighting after adjusting the time offset so any stored brightness adjustments are applied consistently.

## 4.2.014-alpha
**Enhancement - Brightness Offset Handling**

**Improvements:**
- Reworked `dim_up`/`dim_down` to store brightness offsets as percentages of the active curve span, matching the Light Designer model.
- Allow offsets to push all the way to configured brightness limits, removing the previous ±50% clamp while still respecting area min/max bounds.
- Apply the same percentage offset when fetching adaptive lighting so live updates reflect the stored adjustments immediately.

**Testing:**
- `pytest addon/tests/unit/test_primitives.py`

## 4.2.013-alpha
**Enhancement - Designer Color Output Controls**

**Improvements:**
- Added a Color Output selector to the Light Designer UI, letting users choose Kelvin, RGB, or XY directly from the interface.
- Startup now reads the chosen color mode from `designer_config.json`, keeping the runtime and designer in sync without relying on supervisor options.

**Documentation:**
- Updated README and docs to point users at the Designer for color behaviour and clarify remaining add-on options.

**Notes:**
- The legacy `color_mode` add-on option has been removed; saving settings from the Designer migrates existing installs automatically.

## 4.2.012-alpha
**Maintenance - Alpha Tag & Hotfix**

**Enhancements:**
- Added `manage_blueprints` option so the add-on can automatically create Hue dimmer switch automations for every lit area.
- Integration downloads now derive from `repository.yaml`; removed the legacy `integration_repo` option.

**Documentation:**
- Simplified installation instructions to focus on installing the add-on and restarting Home Assistant.

**Notes:**
- Carries forward the blueprint deployment enhancements introduced in 4.2.007 while we stabilize the release.

## 4.2.007
**Enhancement - Blueprint Deployment Sync**

**Improvements:**
- Added runtime blueprint installer so add-on deployments (and remote repo downloads) copy `circadian` automation/script blueprints into Home Assistant's `/config/blueprints` tree automatically.
- Reorganized repository blueprints to follow Home Assistant's directory structure, eliminating duplicate storage and simplifying packaging.

## 4.2.0
**Feature - Automatic Integration Management**

**Improvements:**
- Add-on now deploys the `circadian` custom integration on startup by default, installing updates automatically and removing the managed copy when the toggle is disabled.
- Added `manage_integration` option to let advanced users opt out of automatic deployment while still providing a clean uninstall path.
- Added `integration_repo` option (branch via optional `owner/repo#branch` format) so release vs. staging sources can be switched without rebuilding the add-on. *(Removed in 4.2.007-alpha; the add-on now infers the repository from `repository.yaml`.)*
- Relocated the local build helper to the repository root to package both add-on and integration assets from a single entry point.
- Added dedicated `dim_up`/`dim_down` primitives for smoother curve-based dimming without relying on switch automations.

## 4.1.01
**Fix - Designer Now Marker Layering**

**Bug Fixes:**
- Ensured the pulsing "now" indicator renders above step markers so it remains visible while stepping through the curve.

## 4.1.0
**Enhancement - Philips Hue Button Support**

**Improvements:**
- Added automatic handling for Philips/Signify ROM001 and RDM003 Hue buttons so they register with the Circadian Light switch blueprint while avoiding Zigbee light grouping.
- Prevented these button devices from being misidentified as lights when building ZHA groups, keeping Zigbee lighting parity accurate.
- Added optional triple-press action that triggers a random-color splash while pausing Circadian Light control.

## 4.0.9
 - Revert designer to client side curve render

## 4.0.8
**Bug Fix - Light Designer Interface**

**Bug Fixes:**
- Fixed designer bug affecting the Light Designer interface functionality

## 4.0.7
**Simplification - Remove Recall Offset Concept**

**BREAKING**: Removed dual offset system for simplified state management
- Eliminated "recall offsets" - there is now only one offset per area
- Offsets are preserved in `magic_mode_time_offsets` whether magic mode is on or off
- No more automatic saving/restoring of offsets when toggling magic mode
- Removed file I/O for `saved_offsets.json`

**Improvements:**
- Simplified offset management - step adjustments persist across magic mode toggles
- More predictable behavior - offsets don't get lost when disabling/enabling magic mode
- Cleaner codebase - removed ~50 lines of save/restore logic
- Better user experience - manual adjustments are preserved

**Technical Changes:**
- Removed `recall_time_offsets` dictionary and related methods
- Simplified `enable_magic_mode()` and `disable_magic_mode()` method signatures
- Updated all service primitives to use single offset system
- Simplified solar midnight reset to only handle active offsets
- Updated all tests to reflect new single-offset behavior

## 4.0.6
**Bug Fix - UI/Backend Time Synchronization**

**Bug Fixes:**
- Fixed timezone synchronization between Light Designer UI and backend
- UI now fetches server time from Home Assistant instead of using browser time
- Resolved issue where UI showed different lighting values than backend would apply
- Fixed curve visualization to use clock time consistently across all API endpoints
- Fixed step calculation markers to align with corrected curve data

**Technical Details:**
- Added `/api/time` endpoint to provide server time in Home Assistant timezone
- Updated curve generation (`/api/curve`) to use clock time instead of mixing solar/clock time
- Fixed step sequences (`/api/steps`) to interpret input as clock time
- UI now syncs with server time on load and periodically re-syncs to prevent drift

## 4.0.5
**Bugs + UI Backend**

**BREAKING**: Removed automatic ZHA switch detection and handling
- Addon now operates exclusively through Home Assistant integration service calls
- Periodic light updates now target all areas in magic mode instead of areas with switches

**Improvements:**
- UI now uses python backend for data instead of separate calculations in the JS

## 4.0.4
**Bug Fix - Solar Midnight Recall Offset Reset**

**Bug Fixes:**
- Fixed solar midnight reset to also clear recall offsets (renamed from "saved offsets")
- Resolved issue where recall offsets from previous day persisted after solar midnight
- Solar midnight now provides true fresh start by clearing both current and recall TimeLocation offsets
- Updated reset primitive to clear recall offsets by default (added `clear_saved` parameter for special cases)

**Improvements:**
- Renamed "saved_time_offsets" to "recall_time_offsets" for clarity
- Added comprehensive tests for solar midnight reset behavior
- Enhanced logging to distinguish between current and recall offset operations

## 4.0.3
**Bug Fix - Circadian Light On State Preservation & Light Designer Enhancement**

**Bug Fixes:**
- Fixed Circadian Light On to preserve stepped-down state when Circadian Light is already enabled
- Resolved issue where motion-triggered Circadian Light On would reset lights to current time instead of maintaining user's stepped adjustments
- Circadian Light On now only updates lights when Circadian Light was previously disabled, preserving any manual step adjustments when already active

**Enhancements:**
- Added live pulsing "now" marker in Light Designer that automatically tracks current time
- Now marker updates every minute and includes smooth pulsing animation for better visibility

## 4.0.1
**Bug Fix - Reset State Management**

**Bug Fixes:**
- Fixed reset primitive to properly clear saved TimeLocation offsets
- Resolved issue where stepped-down state persisted after reset when Circadian Light was re-enabled
- Reset now correctly ensures area starts fresh at current time without restoring previous offsets

## 4.0.0
**Major Release - Circadian Light & Test Suite**

**Testing Infrastructure:**
- Added comprehensive test suite with 2,400+ lines of test coverage
- Implemented unit tests for all core components:
  - Brain edge cases and adaptive lighting calculations
  - Light controller multi-protocol support
  - WebSocket connection and event handling
  - Service primitives functionality
  - Web server and Light Designer interface
- Relocated tests to `addon/tests/` for better organization
- Added pytest configuration and coverage reporting

**CI/CD & Development:**
- Added GitHub Actions workflows for automated testing
- Implemented build, lint, and CI pipelines
- Enhanced documentation structure
- Improved code organization and maintainability

**Bug Fixes:**
- Fixed potential bugs in primitives service handling
- Resolved issues in switch command processing
- Improved error handling across components

**Developer Experience:**
- Added comprehensive testing commands to CLAUDE.md
- Enhanced local development workflow
- Improved build scripts and Docker configuration

## 3.2.0
 - Fix toggling

## 3.1.0

- **Refined Primitives Behavior**: Simplified and clarified primitive actions
  - `homeglo_on`: Turn on lights with adaptive lighting and enable HomeGlo mode
  - `homeglo_off`: Disable HomeGlo mode only (lights remain unchanged)
  - `homeglo_toggle`: Smart toggle - turns off lights and disables HomeGlo if on, turns on lights with HomeGlo if off
  - Removed `homeglo_deactivate` (redundant with new `homeglo_off` behavior)
- **Improved Blueprint**: Simplified automation using new primitives
  - ON button: Uses `homeglo_toggle` for smart light/HomeGlo control
  - OFF button: Reset to current time
  - UP/DOWN buttons: Step along glo curve
  - All services now pass multiple areas at once for better performance
- **Service Updates**: Updated all service descriptions
  - Replaced "adaptive lighting" terminology with "glo" throughout
  - Clarified behavior of each service in descriptions

## 3.0.0
- **HomeGlo Primitives System**: Complete restructure of service calls into primitive actions
  - `homeglo_on`: Enable HomeGlo mode and turn on lights with adaptive lighting
  - `homeglo_off`: Turn off lights and disable HomeGlo mode  
  - `homeglo_deactivate`: Disable HomeGlo mode without changing light state
  - `step_up`/`step_down`: Adjust brightness along the glo curve
  - `reset`: Reset to current time and enable HomeGlo
- **Blueprint Automation**: Home Assistant blueprint for ZHA switch control
  - Multiple switch device support
  - Multiple area targeting
  - ON button: Smart toggle (lights on → homeglo_off, lights off → homeglo_on)
  - OFF button: Reset to current time
  - UP/DOWN buttons: Step along glo curve
- **Custom Integration**: HACS-installable Home Assistant integration
  - Service registration and validation
  - Multi-area support for all services
  - Proper internationalization strings

## 2.5.1

- Changed default color mode to Kelvin (CT) for better bulb compatibility
  - Most bulbs support color temperature (CT) mode
  - Previous default was XY which some bulbs don't support well
  - Updated configuration defaults and documentation

## 2.5.0

- Simplified brightness stepping algorithm
  - Replaced complex arc-based perceptual stepping with straightforward percentage-based approach
  - Step size now calculated as (max_brightness - min_brightness) / steps
  - Removed gamma/perceptual brightness adjustments for more predictable behavior
  - Python implementation now matches JavaScript designer exactly
  - Stepping behavior is now linear and intuitive

- Designer interface improvements
  - Added "Show steps" checkbox to visualize step markers on the graph
  - Step markers show where each button press will land with proper color coding
  - Enhanced click precision using correct plot area detection
  - Fixed graph rendering issues
  - Removed "Prioritize dim steps" control (no longer needed with simplified algorithm)

- Code simplification
  - Removed perceptual weight constants and calculations
  - Eliminated complex arc distance computations
  - Cleaner, more maintainable codebase
  - Better alignment between Python and JavaScript implementations

## 2.4.0

- New simplified adaptive lighting algorithm
  - Replaced complex logistic curves with simplified midpoint/steepness parameters
  - Removed gain/offset/decay parameters for cleaner configuration
  - Added arc-based stepping for perceptually uniform dim/brighten transitions
  - Added gamma-based brightness perception (controlled via "Prioritize dim steps" slider)
  - Smoother and more predictable lighting transitions

- Designer improvements
  - Save Configuration button moved to top for better visibility
  - Added "Prioritize dim steps" control for customizing step behavior
  - Visual hash marks on sliders showing default values
  - Location parameters (lat/lon/timezone) now display-only from Home Assistant
  - Test month selector no longer saved (always defaults to current month)
  - Sun power curve visually dimmed for better contrast
  - Fixed midpoint labels to refresh when sun position changes

- Testing improvements
  - Added comprehensive pytest test suite
  - Tests organized in tests/unit/ directory
  - Added TESTING.md documentation
  - Fixed async test issues

## 2.3.5

- Startup optimization
  - Eliminated redundant device registry loading during startup
  - Reduced state queries from 3 to 2 during initialization  
  - Areas data is now shared between sync and parity cache operations
  - Added `refresh_devices` parameter to control when device registry is reloaded
  - Faster startup with less duplicate work

## 2.3.4

- Performance improvements
  - Fixed duplicate ZHA group synchronization on startup
  - Removed redundant parity cache refresh calls in event handlers
  - Consolidated sync flow to prevent multiple unnecessary operations
  - Added clearer logging with separators for sync operations

- Area naming update
  - Changed dedicated area name from "Glo" to "Glo_Zigbee_Groups" for clarity
  - Better identifies the purpose of the organizational area

## 2.3.3

- ZHA group organization improvements
  - Automatically creates a "Glo_Zigbee_Groups" area to organize all ZHA group entities
  - Moves ZHA group entities to Glo_Zigbee_Groups area after creation to prevent random placement
  - Moves existing group entities to Glo_Zigbee_Groups area during sync
  - Excludes Glo_Zigbee_Groups area from parity checks and light control operations
  - Prevents Home Assistant from placing groups in random areas

- Better group entity management
  - Finds and moves group entities using entity registry
  - Ensures consistent organization of all Glo_ prefixed groups
  - Properly updates entity area assignments after group creation

## 2.3.2

- Fixed WebSocket concurrency issues
  - Added area parity caching to prevent concurrent WebSocket calls during light control
  - Cache is refreshed during initialization and when areas/devices change
  - Eliminates "cannot call recv while another coroutine is already waiting" errors

- Consolidated light control logic
  - Single `determine_light_target` method decides between ZHA group or area control
  - All light operations now use the same consistent logic
  - Removed duplicate code across switch operations

- Improved code structure
  - Simplified switch.py by removing unused light controller code
  - All light control now goes through unified service calls
  - Better separation of concerns between parity checking and light control

## 2.3.1

- Smart light control method selection
  - Added ZHA parity checking to determine optimal control method per area
  - Areas with only ZHA lights use efficient ZHA group control
  - Areas with mixed light types (ZHA + WiFi/Matter/etc) use area-based control
  - Automatically selects best method to ensure all lights are controlled
  - Enhanced logging to show which control method is used and why

- Improved light compatibility
  - Better support for mixed-protocol rooms (ZHA, WiFi, Matter, Z-Wave, etc)
  - ZHA groups only created for areas with 100% ZHA lights
  - Non-ZHA light detection and tracking for proper control method selection

## 2.3.0

- Adaptive lighting dimming improvements
  - Fixed dimming buttons to respect min/max color temperature boundaries
  - Fixed dimming buttons to respect min/max brightness boundaries
  - Added support for configurable min/max values via environment variables
  - Dimming step calculations now properly use user-configured limits

- Time offset persistence
  - Time offsets are now saved when lights are turned off
  - Saved offsets are automatically restored when lights are turned on
  - Offsets persist across addon restarts
  - Each room maintains its own independent time offset preference

- Code improvements
  - Removed flash functionality from disable_magic_mode
  - Consolidated data directory handling into single method
  - Improved offset management for better user experience

## 2.2.2

- Auto-sync ZHA groups when devices change areas
  - Added event listeners for device_registry_updated events
  - Added event listeners for area_registry_updated events  
  - Added event listeners for entity_registry_updated events
  - Automatically resync ZHA groups when devices are added, removed, or moved between areas
  - Fixed bug where existing group members were not properly detected (nested device structure)
  - Enhanced logging to show group membership changes during sync
  - Groups now properly remove devices when they're moved to different areas

## 2.2.1

- Fixed initialization and ZHA group mapping
  - Fixed latitude/longitude data not loading (now properly waits for config response)
  - Fixed ZHA group discovery (now loads states before device registry)
  - Improved ZHA group to area mapping with multiple name variations
  - Added random 16-bit group ID generation for new ZHA groups
  - Enhanced logging for debugging group and location loading
  - Removed duplicated ZHA group mapping code

- Code refactoring
  - Centralized ZHA group mapping logic into single method
  - Converted async fire-and-forget methods to proper await patterns
  - Added comprehensive debug logging with ✓/⚠ status indicators

## 2.2.0

- Major refactor: Multi-protocol light controller architecture
  - Created modular light_controller.py with protocol abstraction layer
  - Support for multiple lighting protocols (ZigBee, Z-Wave, WiFi, Matter, HomeAssistant)
  - Protocol-agnostic LightCommand interface for unified light control
  - Automatic protocol detection based on device type
  - Future-ready architecture for mixed-protocol environments

- ZHA group synchronization with Home Assistant areas
  - Automatically creates/updates ZHA groups to match HA areas on startup
  - Groups named with "Glo_" prefix to avoid conflicts with other integrations
  - Only creates groups for areas that have switches installed
  - Syncs group membership when lights are added/removed from areas
  - Removes obsolete groups when areas are deleted
  - Improved device discovery using device registry identifiers
  - Enhanced IEEE address extraction from HA device identifiers
  - Better endpoint detection for different light types (Hue uses endpoint 11)

- Enhanced debugging and logging
  - Detailed logging for ZHA device discovery and group operations
  - IEEE address and endpoint information logged for troubleshooting
  - Group synchronization status reporting

- Fixed WebSocket API implementation
  - Corrected service call parameter structure for light control
  - Added send_message_wait_response for synchronous WebSocket operations
  - Improved error handling for WebSocket messages

- Switch handling improvements
  - Abstracted switch operations to use light controller
  - Protocol-aware switch commands
  - Better separation of switch logic from light implementation

## 2.1.11

- Fix dimming to use saved designer curve parameters
  - Fixed critical issue where dimming used default curves while main lighting used saved curves
  - Dimming now properly uses the same curve parameters as configured in Light Designer
  - Eliminates brightness jumps caused by curve parameter mismatch
- Enable designer configuration saving in development environment
  - Development mode now uses .data/ directory for configuration persistence
  - Designer settings can now be saved and tested locally

## 2.1.10

- Fix dimming calculation to prevent large brightness jumps
  - Fixed issue where dimming could jump from 90% to 4% brightness
  - Brightness now correctly follows the adaptive curve without interpolation artifacts
  - Recalculates actual curve values instead of interpolating between samples

## 2.1.9

- Bottom button behavior changes
  - Bottom button now always resets to time offset 0 and enables magic mode
  - Removed toggle behavior - bottom button consistently returns to present time
  - Dim up button no longer turns on lights when they're off

## 2.1.8

- Fix Light Designer configuration persistence again

## 2.1.7

- Fix Light Designer configuration persistence
  - Designer now properly loads all configuration values
  - MAX_DIM_STEPS value correctly synchronized between Python and web interface
  - Configuration reliably persists across container restarts and updates
  - Improved error handling when loading saved configuration
  - Move Save Configuration button below chart, above controls

## 2.1.6

- Add adaptive / step arc support + update designer
  - Dimmer switches now adjust brightness along the new step arc
  - Light Designer updated to visualize and test dimming behavior with offset controls
  - Shows real-time preview of how dimming affects lighting values

## 2.0.5

- Auto-reset manual offsets at solar midnight
  - Manual adjustments from dimmer switches now automatically reset to 0 at solar midnight
  - Ensures lighting curves start fresh each day without accumulated offsets
  - Reset happens seamlessly in background during periodic updates
  - Lights in magic mode will update to correct values when offsets reset

## 2.0.4

- Simplify Light Designer interface
  - Removed latitude, longitude, and timezone controls (automatically provided by Home Assistant)
  - Renamed "Sun Position" section to "Display Settings"
  - Added informational note about automatic location detection
  - Kept month selector for testing seasonal variations
  - Cleaner, more focused interface for curve configuration

## 2.0.3

- Improve Light Designer configuration handling and feedback
  - Designer now fetches current configuration via API on page load
  - Added cache-control headers to prevent browser caching issues
  - Enhanced save confirmation with clearer visual feedback
  - Save button shows loading state during save operation
  - Success/error messages are more prominent with animations
  - Configuration always shows the most recent saved values

## 2.0.2

- Fix API routing for POST requests in Light Designer
  - Fixed 405 Method Not Allowed errors when saving configuration
  - Added proper route handlers for ingress-prefixed API paths
  - Routes now correctly handle both GET and POST methods with ingress prefixes
  - Configuration changes apply in real-time without addon restart

## 2.0.1

- Fix ingress routing for Light Designer interface
  - Fixed 404 errors when accessing through Home Assistant sidebar
  - Added catch-all route to handle ingress path prefixes
  - Updated API routes to work with relative paths
  - Reordered route registration to ensure API endpoints work correctly

## 2.0.0

- Add Home Assistant ingress support with Light Designer interface
  - New web-based Light Designer accessible through Home Assistant sidebar
  - Interactive graph showing real-time preview of lighting curves
  - Visual controls for all 20 curve parameters with live updates
  - Separate morning and evening controls for brightness and color temperature
  - Save configuration directly from the web interface
  - Visualizes solar events (sunrise, sunset, solar noon, solar midnight)
  - Shows current time marker and interactive time selection
  - Drag-to-select time on graph for instant value preview

## 1.4.0

- Replace cubic smoothstep formula with advanced morning/evening curves
  - Replaced simple gamma-based cubic formula with separate morning and evening logistic curves
  - Added 20 new curve parameters for fine-grained control over lighting transitions
  - Morning curves control lighting from solar midnight to solar noon
  - Evening curves control lighting from solar noon to solar midnight
  - Each curve has independent controls for midpoint, steepness, decay, gain, and offset
  - Allows for asymmetric lighting patterns (e.g., slower sunrise, faster sunset)
  - Better matches natural circadian rhythms with customizable transitions
  - Removed deprecated sun_cct_gamma and sun_brightness_gamma parameters

## 1.3.6

- Fix multi-area switch control bug
  - Magic mode is no longer automatically enabled at startup for all areas
  - Magic mode is now properly managed per-area based on light state
  - Fixes issue where switches in one area could interfere with other areas
  - Each area now maintains independent magic mode state

## 1.3.5

- Version skipped

## 1.3.4

- Improved color temperature conversion accuracy
  - Rewrote color_temperature_to_rgb using Krystek polynomial approach
  - Now converts CCT → xy → XYZ → RGB for better accuracy
  - Added proper sRGB gamma correction
  - Enhanced color_temperature_to_xy with more precise coefficients
  - Added separate polynomial ranges for improved accuracy (2222K and 4000K breakpoints)

## 1.3.3

- Fix sun position calculation to match expected behavior
  - Changed from sun elevation angle to time-based cosine wave
  - Now uses local solar time for proper solar noon alignment
  - Provides smooth -1 to +1 progression over 24 hours
  - Matches the HTML visualization formula exactly

## 1.3.2

- Fix gamma parameters not being passed from addon configuration
  - Added sun_cct_gamma and sun_brightness_gamma to run script
  - Now properly exports configuration values as environment variables
  - Gamma parameters will correctly affect adaptive lighting curves

## 1.3.1

- Add configurable gamma parameters for adaptive lighting curves
  - New sun_cct_gamma parameter to control color temperature curve (default: 0.9)
  - New sun_brightness_gamma parameter to control brightness curve (default: 0.5)
  - Allows fine-tuning of how lighting changes throughout the day
  - Lower gamma values = warmer/dimmer during day, higher = cooler/brighter

## 1.3.0

- Add configurable color mode support
  - New dropdown configuration to choose between kelvin, rgb, or xy color modes
  - Direct color temperature to CIE xy conversion without RGB intermediate step
  - Centralized light control function for consistent color handling
  - Default color mode changed to RGB for wider device compatibility
- Add configurable color temperature range
  - Min and max color temperature now adjustable in addon configuration
  - Allows customization for different lighting preferences and hardware
  - Default range: 500K (warm) to 6500K (cool)
- Remove lux sensor adjustment feature
  - Simplified configuration by removing lux_adjustment option
  - Cleaner codebase focused on core adaptive lighting functionality

## 1.2.9

- Add support for ZHA group light entities
  - Automatically detects and uses ZHA group entities (Light_AREA pattern)
  - Searches both entity_id and friendly_name for Light_ pattern
  - Uses single ZHA group entity instead of controlling individual lights
  - Improved logging to show all discovered light entities for debugging

## 1.2.8

  - Triple press OFF random RGB!

## 1.2.7

- Enhanced magic mode dimming behavior
  - Dim up/down buttons now move along the adaptive lighting curve when in magic mode
  - Before solar noon: dim up moves forward in time (brighter), dim down moves backward (dimmer)
  - After solar noon: dim up moves backward in time (brighter), dim down moves forward (dimmer)
  - Bottom button now toggles magic mode: turns it off with flash if on, or enables it with adaptive lighting if lights are on
  - Brightness adjustments never turn lights off, maintaining minimum 1% brightness

## 1.2.6

- Implement global magic mode management
  - Magic mode is now enabled by default on startup for all areas with switches
  - Top button press toggles lights and enables/disables magic mode
  - Bottom button press disengages magic mode without turning lights off
  - Visual flash indication when magic mode is disabled
  - Centralized magic mode disable function with consistent behavior

## 1.2.5

- Version skipped

## 1.2.4

- Add configuration toggle for lux adjustment
  - New "Lux adjustment" checkbox in Home Assistant configuration tab
  - When enabled, applies lux-based brightness and color temperature adjustments
  - Disabled by default for backward compatibility
  - Lux adjustment remains optional and only applies when lux sensors are available

## 1.2.3

- Add lux sensor support for adaptive lighting
  - Automatically detects and uses lux sensors (area-specific or general)
  - Lux adjustments applied as post-processing stage for better modularity
  - Bright environments shift toward cooler colors and reduced brightness
  - Dark environments maintain warmer colors and appropriate brightness
  - Configurable lux boundaries and adjustment weights

## 1.2.2

- Remove sleep mode functionality from adaptive lighting
- Fix color temperature to continue fading through negative sun positions
- Simplify lighting formula for smoother transitions throughout day/night cycle

## 1.2.1

- Fix magic mode not being disabled when using ON button to toggle lights off
- Ensure magic mode is only active when lights are on

## 1.2.0

- Add "Magic Mode" feature for automatic adaptive lighting updates
  - Areas enter magic mode when lights are turned on via switch
  - Areas exit magic mode when lights are turned off via switch
  - Background task only updates lights in areas that are in magic mode
- Add support for off button press to turn off lights and disable magic mode
- Remove requirement for all lights to be on before background updates
- Improve logging for magic mode state changes

## 1.0.0

- Initial release
