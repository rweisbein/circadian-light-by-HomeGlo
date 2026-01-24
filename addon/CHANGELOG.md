<!-- https://developers.home-assistant.io/docs/add-ons/presentation#keeping-a-changelog -->

## 6.9.97
**Motion sensor configuration in Controls page**

- Added per-area motion sensor configuration in Controls modal
- Each motion sensor can control multiple areas with different settings
- Per-area options: function (on_only, on_off, boost, disabled) and duration
- Removed motion settings from Areas page (now per-sensor, not per-area)
- Added motion_expires_at state tracking for on_off timer mode
- Implemented on_only and on_off motion handlers in primitives

## 6.9.73
**Smart 2-step turn-on**

- Store color temperature when lights turn off (last_off_ct)
- Only use 2-step turn-on if CT difference >= 500K from last off
- Avoids unnecessary 2-step when CT is similar (faster turn-on)
- Still prevents color arc when CT is significantly different

## 6.9.72
**Inline filters in table headers**

- Moved filters into table header row (below Category, Area, Status column titles)
- Filter dropdowns dynamically populated from data
- All three filters persist to settings
- Removed separate filter row above table

## 6.9.71
**Controls page improvements**

- Added status filter dropdown (All, Active, Not configured, Unsupported) replacing checkbox
- Added device category detection (Switch, Motion, Contact, Unknown)
- Added Category column to controls table with sorting
- Fixed type detection bug - now requires both manufacturer AND model match
  - Motion sensors no longer incorrectly show as "Philips Hue Dimmer"

## 6.9.70
**Reorganize Hue dimmer button mappings**

- on-off 3x: Changed from glo_reset to freeze_toggle
- hue 3x: Changed from wake/bed to glo_reset (reset zone)
- Updated blueprint to match new mappings

New layout:
- on-off: 1x toggle, 2x send to zone, 3x freeze
- up: 1x step_up, 2x color_up, 3x britelite, hold bright_up
- down: 1x step_down, 2x color_down, 3x nitelite, hold bright_down
- hue: 1x cycle scope, 2x glo_down (reset area), 3x glo_reset (reset zone)

## 6.9.69
**Use HA device names for controls (read-only)**

- Removed editable name field from Configure Control modal
- Control names now come from Home Assistant device registry
- Modal title shows device name (e.g., "Configure: Kitchen Dimmer")

## 6.9.68
**Support Hue hub devices (hue_event handling)**

- Added hue_event handling for switches connected via Hue hub (not ZHA)
- Hue dimmers via Hue hub now work the same as ZHA-connected dimmers
- Added get_switch_by_device_id lookup for Hue hub device matching
- Fixed last_action display for unconfigured Hue hub devices

## 6.9.53
**Fix shared.js inlining with simple string replacement**

- Changed from regex to explicit string pattern matching
- Tries multiple quote/path formats for script tag
- More robust detection of script references

## 6.9.52
**Fix shared.js server-side inlining**

- Restored external script reference in home.html (was manually inlined)
- Both home.html and glo-designer.html now use `<script src="./shared.js"></script>`
- Server-side regex replacement inlines shared.js at serve time
- Single source of truth: modify shared.js to change color mapping

## 6.9.50
**Inline shared.js to avoid ingress routing issues**

- shared.js content is now inlined during page serving
- Avoids complex routing patterns for ingress proxy paths

## 6.9.49
**Fix shared.js 404 on ingress paths**

- Added route pattern for `//shared.js` (ingress prefix case)
- Static JS files now served correctly from all page contexts

## 6.9.48
**Consolidate color functions into shared.js**

- Created shared.js with cctToRGB, colorWithAlpha, readableTextColor functions
- Both home.html and glo-designer.html now use the same color mapping
- Single source of truth for color temperature display

## 6.9.47
**Fix brown color on home page area tiles**

- Replaced physics-based kelvinToRgb with perceptual color mapping (matches designer)
- Warm colors now display as warm orange/yellow instead of muddy brown on dark backgrounds

## 6.9.46
**Fix sun times using UTC instead of local time**

- Fixed sun times calculation to convert from UTC to local timezone
- astral library returns UTC times, but we were extracting hours without conversion
- This caused warm_night to think sunrise was 12:39pm instead of 7:08am (5 hour offset)
- Fixed in main.py, zone-states API, and area-status API

## 6.9.45
**Fix solar rules in all display endpoints**

- Fixed area-status API to include sun_times for solar rules
- Fixed zone-states API to include sun_times for solar rules
- Both endpoints were missing sun_times, causing home page to show wrong values
- Added INFO logging to warm_night calculation to debug main.py issue

## 6.9.43
**Fix Glo designer saves not applying**

- Fixed designer save not including min/max color temp (was using nonexistent day_kelvin/night_kelvin fields)
- Fixed preset update API call wrapping settings incorrectly
- Added glozone.reload() when main.py receives circadian_light_refresh event (cross-process config sync)
- Preset updates now fire circadian_light_refresh event to notify main.py to reload config

## 6.9.42
**Fix GloDown for multiple areas + solar rules use actual sun times**

- Fixed GloDown/GloUp/GloReset to process ALL areas when switch controls multiple areas
  (was only processing the first area)
- Solar rules (warm at night, cool day) now use actual sunrise/sunset times from
  configured location instead of defaults (6am/6pm)
- API endpoint /api/sun_times now returns both ISO strings and hour values

## 6.9.41
**UI polish: remove dot, add lock, fix border, sortable last action**

- Removed colored dot from area cards (redundant with CCT background)
- Added lock icon to zone state card when zone is frozen
- Fixed orange out-of-sync border appearing different on warm/cool cards
  (added dark inner shadow for consistent contrast)
- Controls: Last action now shows date/time and is sortable
  (format: "1/21 4:32p Button 1x")

## 6.9.40
**Dim/bright buttons on off lights -> nitelite**

- When step_up, step_down, bright_up, or bright_down is pressed while lights are off
  and not enabled in circadian mode, automatically sets nitelite instead
- Provides a gentle way to turn on lights at night without blinding brightness

## 6.9.39
**Fix zone state visualization using frozen_at**

- Zone state card now correctly uses frozen_at hour when calculating displayed values
- Previously always used current time, showing wrong values for frozen zones

## 6.9.38
**Fix Britelite/Nitelite + Zone header card style update**

- Fixed Britelite/Nitelite to keep circadian mode enabled:
  - Previously disabled circadian mode, breaking step_up/down and 30-second refresh
  - Now uses primitives.set() which properly freezes at curve endpoints
  - Nitelite freezes at ascend_start (warmest/dimmest from your curve)
  - Britelite freezes at descend_start (coolest/brightest from your curve)
- Zone header state card now matches area chip style:
  - Removed redundant colored circle
  - Uses CCT background fill like area chips
  - Slightly larger font for visual hierarchy

## 6.9.37
**Configurable turn-on transition + GloUp propagation fix**

- Added Settings page "Transitions" section with configurable "Turn on lights" duration
  - Measured in tenths of a second (default: 3 = 0.3 seconds)
  - Applies to: Circadian On, Circadian Toggle, Britelite, Nitelite
- Fixed GloUp after Britelite/Nitelite:
  - Britelite/Nitelite now set frozen_at so GloUp can propagate the state to other areas
  - Britelite sets frozen_at to descend_start (max brightness hour)
  - Nitelite sets frozen_at to ascend_start (min brightness hour)

## 6.9.35
**Fix: Cross-process state sharing for zone state and last action**

Root cause: main.py and webserver.py run as separate Python processes, so in-memory
state wasn't shared between them. Fixed by persisting state to JSON files:
- `glozone_runtime_state.json` - Zone runtime state (brightness_mid, color_mid, frozen_at)
- `switch_last_actions.json` - Last button action per switch

This fixes:
- Zone state visualization not updating after GloUp
- Last action always showing blank in Controls

## 6.9.33
**Debug logging for zone state and last action**

- Added module ID tracking to zone state SET/GET operations to debug state not persisting
- Added logging when looking up last_action for Controls (shows IEEE being searched)
- Added logging when last_action not found (shows stored keys to identify format mismatch)

## 6.9.32
**Area card redesign with CCT visualization**

- Area chips now display their color temperature visually:
  - Background shaded to match the CCT color (warm amber to cool white)
  - Left-to-right brightness gradient shows brightness percentage (like Glo designer buttons)
  - Smaller, more compact brightness/kelvin numbers
- Sync indicator borders made more subtle (50% opacity)
- Overall cleaner look that matches Glo designer aesthetic

## 6.9.30
**Debug logging for last_action and zone state issues**

- Fixed blue border clipping at top corners of zone card header
- Added debug logging:
  - `[LastAction] Set for {ieee}: {event}` - when button event is recorded
  - `[Controls] IEEE {ieee} last_action: {action}` - when API returns last_action
  - `[ZoneStates] Zone '{name}' runtime_state: {...}` - zone runtime state used in calculation
- Check add-on logs after pressing buttons to verify events are being recorded

## 6.9.29
**UI refinements: Color consistency, dropdown improvements**

- Swapped sync indicator colors: blue for in-sync, orange for out-of-sync
- State visualization pill now has blue border (matching in-sync)
- Neutralized sun display colors (sunrise, sunset, timeline now use muted gray)
- Dropdown improvements:
  - "Edit [Glo name]" moved to top of list
  - Same font styling as other items (no underline)
- Wake/bed times now show defaults (7am/10pm) when not set in preset

## 6.9.28
**UI refinements: Border placement, debug logging**

- Moved orange "in-sync" border from zone card to the state visualization pill
- Made all sync borders thinner (1px) for more subtle appearance
- Added debug logging to zone-states API to investigate calculation issues
- Fixed Config creation to use from_dict() method with proper defaults

## 6.9.27
**Home page fixes: Zone state, sync borders, last action**

- Zone state visualization now shows **per-zone** calculated values
  - Previously showed first enabled area's values, which was incorrect
  - New `/api/zone-states` endpoint returns calculated circadian values per zone
  - Accounts for zone's Glo preset AND runtime state (GloUp/GloDown adjustments)
  - Two zones sharing the same Glo will show different values if adjusted independently
- Area sync borders:
  - Orange border for in-sync areas
  - Blue (Dawn Blue) border for out-of-sync areas
  - Removed lightning bolt icon - borders are cleaner visual indicator
- Zone card styling:
  - Added orange border around Glo zone cards
  - Fixed dropdown cutoff (overflow: visible)
- Controls "Last action":
  - Now tracks button presses even for unconfigured switches
  - Also records action when command mapping fails (shows raw command)
  - Previously only worked for configured switches with mapped commands

## 6.9.26
**UI Refinements: In-sync, Controls, Glo dropdown**

- Home page area chips:
  - In-sync threshold: 2% brightness, 100K color temp
  - Off areas now count as "in sync" (not fighting the zone)
  - Out-of-sync areas show ⚡ icon instead of green border
- Glo zone headers:
  - Simplified: click Glo name for dropdown with presets + edit link
  - Removed redundant "change" link
- Controls page:
  - "Active" status now shows white ✓ instead of green badge
  - Added "Last action" column (e.g., "Bottom 4x")
- Settings page:
  - Removed non-functional Timing settings (weren't being saved/used)
  - Page now directs to Glo design and Home for actual settings

## 6.9.25
**UI Enhancements: Home page visualization**

- Updated accent colors: Dawn Blue (#2e6cba) replaces purple/indigo accents
- Sun timeline improvements:
  - Wider bar (6px) with sunrise-to-sunset gradient
  - Position dot shows current time in the day (faded when outside daylight hours)
- Glo Zone headers now show current state in center:
  - Color swatch with current temperature
  - Brightness % and Kelvin values
- Area alignment indicator:
  - Subtle green left border on areas matching zone's current state
  - Shows at a glance which areas are "in sync" with Circadian Light
- Fixed: "Remove configuration" now works (was calling wrong function)

## 6.9.24
**Feature: Controls page refactor**

- Renamed "Switches" to "Controls" throughout UI
- Controls are now fetched directly from Home Assistant device registry
  - Identifies remotes, motion sensors, occupancy sensors, contact sensors
  - No longer requires button press to detect new devices
- Added Status column: Active, Not configured, Unsupported
- Unsupported devices show "Request support" email link
- "Update" button refreshes control list from HA
- "Delete" renamed to "Remove configuration" (controls stay in list)
- Removed pending_switches system entirely

## 6.9.23
**Feature: Switch area lookup**

- Added device_id to switch config for area tracking
- Area column now looks up device's current area from HA dynamically
- If user moves switch to different area in HA, it reflects on next page load
- Area shows "—" for switches without device_id (older configs)

## 6.9.22
**Fixes: Sun times, switches table**

- Fixed sunrise/sunset display on Home page (was showing --:--)
- Simplified switches table: removed Area column, moved Delete to edit modal
- Sun divider now shows gradient line between sunrise and sunset

## 6.9.21
**UI Updates: Navigation, switches table**

- Renamed nav "Glo" to "Glo design" across all pages
- Removed blue background from active nav links (golden hour text only)
- Changed default Glo Zone name to "Main" instead of "Home"
- Simplified Switches page: replaced cards with sortable table
  - Columns: Name (clickable), Area, Scopes, Type
  - Click any column header to sort ascending/descending
- Zone card: changed wake/bed arrows to "wake"/"bed" text labels

## 6.9.20
**UI Refresh: Home page, settings persistence, golden hour accent**

- Renamed "Glo Zones" to "Home" in navigation
- Moved Location settings to Home page with sunrise/sunset times display
- Streamlined zone card layout: Glo info now on same row as zone name
- Glo preset is now a clickable link with "change" toggle for dropdown
- Wake/bed icons changed to cleaner arrows (↗/↘)
- Simplified "Add Glo Zone" button styling
- Settings page: removed Location (moved to Home), renamed "Advanced" to "Timing"
- Fixed settings persistence: wake_time, bed_time, color/brightness ranges, warm_night now save correctly
- Changed accent color to Golden Hour (#feac60)

## 6.9.19
**Fix: Step down color, settings persistence, switch actions**

- Fixed step_down color regression: color now stays at warm_night ceiling (e.g., 2700K) until natural curve drops below it
- Fixed settings persistence: removed duplicate preset values from top level that could override saved settings
- Fixed triple-press britelite/nitelite: now uses correct color_temp format (mireds)
- Fixed scope cycling restore: lights that were on but had no xy data now restore properly

## 6.9.7
**Remove Blueprint Management, Update Button Mapping**

- Removed automatic blueprint/automation management - switches now handled directly by addon
- Removed `manage_blueprints` config option
- Updated Hue Dimmer button mapping to final layout

**Button mapping (Hue Dimmer):**
| Button | 1x | 2x | 3x | 4x | Long |
|--------|----|----|----|----|------|
| ON | circadian_toggle | glo_up | glo_reset | - | reserved |
| UP | step_up | color_up | set_britelite | - | bright_up |
| DOWN | step_down | color_down | set_nitelite | - | bright_down |
| OFF | cycle_scope | glo_down | toggle_wake_bed | freeze_toggle | reserved |

## 6.9.6
**Feature: Switch Management (beta)**

- New Switches page for configuring switches directly in the addon
- Switches can have up to 3 scopes (sets of areas to control)
- Cycle through scopes with OFF button short-press (visual pulse feedback)
- Auto-detects unconfigured switches when buttons are pressed
- "Just pressed!" indicator helps identify which switch you're configuring
- ZHA event handling built into addon

## 6.8.96
**Fix: Step down near phase boundaries**

- Fixed bug where stepping down near phase boundaries caused values to jump back
- Midpoints now clamped to phase boundaries instead of wrapping

## 6.8.95
**Fix: Store config in visible /config folder**

- Config files now stored in `/config/circadian-light/` instead of hidden `/data/`
- This folder is visible in HA config folder and included in HA backups
- Automatically migrates existing config from `/data/` if present
- You can now see and backup `designer_config.json` directly

## 6.8.94
**Fix: Prevent config data loss from failed loads**

- Track whether designer_config.json was loaded successfully
- Refuse to save if config load failed (prevents overwriting good data with incomplete data)
- This fixes the bug where zones could be lost if config file was temporarily unreadable

## 6.8.93
**Fix: Make area migration safe (one-time only)**

- Area migration now only runs once, tracked by `areas_migrated_v1` flag
- Added safety checks to prevent accidental data loss if config load fails
- Migration skipped if no zones exist (prevents overwriting valid config)

## 6.8.92
**Fix: Auto-migrate unassigned areas to default zone**

- On page load, all Home Assistant areas not in any zone are automatically added to the default zone
- This is a one-time migration that runs when viewing the Glo Zones page
- Eliminates the "Unassigned Areas" section for existing installations

## 6.8.91
**Fix: Glo Zones page now properly uses default zone flag**

- Fixed `home.html` to use `is_default` flag instead of hardcoded "Unassigned" zone name
- "Unassigned Areas" section now hidden when all areas are assigned to zones
- Default zone shown with ⭐ indicator; non-default zones show ☆ to set as default
- Delete button hidden for last remaining zone (must always have at least one)
- Existing configs get `is_default: true` added to first zone on load

## 6.8.90
**Feature: Default zone replaces "Unassigned" concept**

- Every area is now always in exactly one zone - no more "Unassigned" areas
- One zone is marked as the default (`is_default: true`) where new areas are automatically added
- User can change which zone is the default via the API (`PUT /api/glozones/{name}` with `is_default: true`)
- New areas discovered when Circadian is enabled are automatically added to the default zone
- Cannot delete the last zone; deleting default zone transfers default status to another zone
- Initial zone is named "Home" instead of "Unassigned"
- glo_up/glo_down/glo_reset now work correctly because all areas are explicitly in zones

## 6.8.87
**Fix: Auto-repair corrupted designer_config.json**

- Detects "Extra data" JSON errors from duplicate/corrupted writes
- Automatically extracts the first valid JSON object and repairs the file
- Backs up corrupted file as designer_config.json.corrupted
- This fixes the bug where GloZones would disappear after editing

## 6.8.85
**Fix: GloZone changes now take effect immediately**

- Added glozone.reload() to refresh config from disk before glo_up/glo_down/glo_reset
- The webserver and main.py run as separate processes with separate memory
- Now glozone operations reload fresh data from disk, so UI changes are seen immediately

## 6.8.81
**Update: Hue Dimmer Switch blueprint button remapping**

- **on-off**: 1x toggle, 2x glo_up, 3x glo_reset, 5x [emergency toggle], hold RESERVED
- **up**: 1x step_up, 2x color_up, 3x britelite, hold bright_up
- **down**: 1x step_down, 2x color_down, 3x nitelite, hold bright_down
- **hue**: 1x [cycle scope], 2x glo_down, 3x wake/bed, 4x freeze_toggle, 5x [sleep], hold RESERVED

## 6.8.80
**Fix: Download integration if bundled version is outdated**

- Added minimum version check for bundled integration (3.5.0)
- If bundled version is older, automatically downloads from GitHub instead
- This works around Docker caching issues that prevent integration updates

## 6.8.79
**Fix: Force Docker cache bust for integration updates**

- Added ADDON_VERSION build arg to force rebuild of custom_components layer
- This ensures integration updates (like glo_up service) are properly deployed
- Includes debug logging from 6.8.78

## 6.8.78
**Debug: Integration deployment diagnostics**

- Added debug logging to run script for integration deployment troubleshooting
- Logs show: bundled source path, whether source exists, expected vs current versions
- This will help diagnose why `glo_up` service isn't being deployed

## 6.8.74
**Fix: Area status uses per-area state**

- Area status API now uses each area's actual state (brightness_mid, color_mid, frozen_at)
- Previously was using zone-level values, now correctly shows per-area brightness and kelvin
- Uses same calculation path as main.py (CircadianLight.calculate_lighting with AreaState)

## 6.8.72
**UI Tweaks**

- **Kelvin value displayed**: Area chips now show "85% • 3200K" format
- **Simplified Glo info**: Zone cards now only show wake (🌅) and bed (🛏️) times

## 6.8.71
**UI Improvements: Glo Zones Page Redesign**

- **CCT-colored status dots**: Area chips now show color temperature as dot color (warm orange to cool white)
- **Renamed navigation**: "Home" → "Glo Zones", "Glo Designer" → "Glo"
- **Black backgrounds**: Glo Zones and Settings pages now match Glo page styling
- **GloZone card redesign**: Glo dropdown on its own row with timing info
- **Removed subtitle** from Glo Zones page header
- **Removed location settings from Glo page** (now only in Settings - no duplication)

## 6.8.70
**Fix: Area status now reflects real-time enabled state**

- Fixed area status showing stale data (always `enabled: false`)
- Root cause: webserver runs as separate process from main.py, each had own in-memory state
- Fix: API now reloads state from disk before returning, ensuring it sees main.py's updates

## 6.8.69
**Debug Logging for Area Status**

- Added detailed logging to `/api/area-status` endpoint to diagnose grey status circles
- Logs glozone names and areas, area ID extraction, and state lookups
- Added frontend console logging for API response and area ID matching
- This will help identify any ID mismatch between glozones and HA areas

## 6.8.68
**Behavior Fixes**

- **Removed state reset from circadian_on and circadian_toggle**: These no longer copy zone state to area on enable. Area state is preserved. Use reset or GloDown to reset state.
- **Fixed area status for Unassigned areas**: Areas in "Unassigned" zone now show status (enabled, brightness) in Home page instead of grey circles.
- **Fixed area ID extraction**: Area status API now correctly handles areas stored as `{id, name}` objects.

## 6.8.65
**Settings: Use Home Assistant Location Toggle**

- Added "Use Home Assistant location" checkbox to Settings page
- When enabled (default), uses HA's configured location for sunrise/sunset calculations
- When disabled, allows manual entry of latitude/longitude
- Lat/lon inputs are disabled and dimmed when using HA location
- Tip box hidden when using HA location (not needed)

## 6.8.64
**Glo Designer: Full Curve Visualization**

- Added full curve visualization and settings from original designer to Glo Designer page
- Glo dropdown at top to switch between Glos (or create new)
- Rename and Delete buttons for Glo management
- "Used by" display shows which zones use the selected Glo
- URL-based Glo selection: `/glo/MyGlo` opens that Glo directly
- Save button saves to selected Glo (not global config)
- All original curve controls: Ascend/Descend timing, brightness, color temperature
- Plotly chart with interactive cursor and step controls

## 6.8.63
**Multi-Page Web UI Restructure**

Restructured the add-on into a clean multi-page web application:

**New Pages:**
- **Home** (`/`): Zone management with drag & drop, live area status indicators
- **Glo Designer** (`/glo`): Edit Glo settings (times, brightness, colors) with Glo dropdown
- **Settings** (`/settings`): Location, timezone, and global settings

**Features:**
- Shared navigation bar across all pages
- Live status per area: enabled indicator, brightness %, frozen lock icon
- Area status uses Circadian Light state (no HA polling overhead)
- Brightness calculated from circadian curve in real-time
- Auto-refresh every 30 seconds

**Technical:**
- New `/api/area-status` endpoint using state modules instead of polling HA
- Updated webserver routes for multi-page structure
- Updated tests for new page structure

## 6.8.62
**Improved Area Management with Drag & Drop**

- Fixed X button to remove areas from Glo Zones (using event delegation)
- Added drag and drop support for area management
- Drag areas between "Areas in this Glo Zone" and "Available areas"
- Visual feedback during drag operations (dashed outline on drop zones)
- Better console logging for debugging area operations

## 6.8.61
**Terminology: Rename "Glo Preset" to "Glo"**

- "Glo Preset" → "Glo" throughout UI
- Default preset: "Glo Preset 1" → "Glo 1"
- Tab label: "Glo Presets" → "Glos"
- Button: "+ Add Glo Preset" → "+ Add Glo"

## 6.8.60
**UI Improvements: Rename Support & Terminology Updates**

**Rename Functionality:**
- Added rename support for Glo Zones via detail panel Rename button
- Added rename support for Glos via Rename button in list
- API endpoints now support renaming via `name` field in PUT requests
- Renaming a Glo automatically updates all Glo Zones using it

**Terminology Updates:**
- "Zone" → "Glo Zone" throughout UI
- "Preset" → "Glo" throughout UI
- "Activity Preset" → "Circadian Pattern"
- Default preset renamed from "Preset 1" to "Glo 1"

**UI Labels Updated:**
- Section header: "Glo Zones & Glos"
- Tab labels: "Glo Zones", "Glos"
- Buttons: "+ Add Glo Zone", "+ Add Glo"
- Detail panel label: "Glo" dropdown
- Modal titles: "Create Glo Zone", "Rename Glo", etc.

## 6.8.59
**GloZone Phase 6: Designer UI**

Added Zones & Presets management UI to Light Designer:

**New UI Section:**
- Tabbed interface with Zones and Presets tabs
- Zone list showing name, preset, and area count
- Zone detail panel with preset selection dropdown
- Area assignment via clickable chips
- Modal dialogs for creating zones and presets

**Zone Management:**
- View all zones with their assigned preset and area count
- Click a zone to see full details
- Change zone preset from dropdown
- Add areas by clicking available area chips
- Remove areas by clicking X on assigned area chips
- Delete zones with confirmation

**Preset Management:**
- View all circadian presets
- Create new presets
- Delete presets (zones using them move to default)

**API Integration:**
- Fetches zones, presets, and areas from REST API
- Real-time updates on create/update/delete operations
- Console logging for debugging

## 6.8.58
**GloZone Phase 5: Blueprint Updates**

Updated Hue Dimmer Switch blueprint with GloZone button mappings:

**New Button Mapping:**
```
ON/OFF: 1x=toggle, 2x=glo_up, 3x=glo_reset, hold=RESERVED
UP:     1x=bright_up, 2x=color_up, 3x=britelite, hold=step_up
DOWN:   1x=bright_down, 2x=color_down, 3x=nitelite, hold=step_down
HUE:    1x=glo_down, 2x=wake/bed, 3x=freeze_toggle, hold=RESERVED
```

**Changes from Previous:**
- ON/OFF 2x: `broadcast` → `glo_up` (push area state to zone)
- ON/OFF 3x: reserved → `glo_reset` (reset zone + all areas)
- HUE 1x: reserved → `glo_down` (pull zone state to area)
- HUE 2x: `reset` → `wake/bed` preset
- HUE 4x: `wake/bed` → reserved (moved to 2x)

**Usage:**
- Press ON/OFF 2x to sync all areas in your zone to current area's state
- Press ON/OFF 3x to reset entire zone to preset defaults
- Press HUE 1x to sync this area back to zone's state

## 6.8.57
**GloZone Phase 4: API & Services**

**Webserver API Endpoints:**
- `GET /api/circadian-presets` - List all circadian presets
- `POST /api/circadian-presets` - Create a new preset
- `PUT /api/circadian-presets/{name}` - Update a preset
- `DELETE /api/circadian-presets/{name}` - Delete a preset (moves zones to default)

- `GET /api/glozones` - List all zones with areas and runtime state
- `POST /api/glozones` - Create a new zone
- `PUT /api/glozones/{name}` - Update a zone (preset, areas)
- `DELETE /api/glozones/{name}` - Delete a zone (moves areas to Unassigned)
- `POST /api/glozones/{name}/areas` - Add an area to a zone
- `DELETE /api/glozones/{name}/areas/{area_id}` - Remove an area from a zone

- `POST /api/glozone/glo-up` - Execute glo_up primitive
- `POST /api/glozone/glo-down` - Execute glo_down primitive
- `POST /api/glozone/glo-reset` - Execute glo_reset primitive

**Custom Integration Services:**
- `circadian.glo_up` - Push area state to zone, propagate to all areas
- `circadian.glo_down` - Pull zone state to area
- `circadian.glo_reset` - Reset zone and all member areas

**Technical:**
- All API endpoints support ingress prefixes
- Webserver fires `circadian_light_service_event` for GloZone actions
- main.py handles both HA service calls and webserver events
- Services defined in services.yaml with proper selectors

## 6.8.56
**GloZone Phase 3: Primitives - Zone Sync Actions**

**Added:**
- `glo_up(area_id)` - Push area's runtime state to its zone, propagate to all areas in zone
- `glo_down(area_id)` - Pull zone's runtime state to this area (rejoin zone settings)
- `glo_reset(area_id)` - Reset zone runtime state and all member areas to preset defaults

**Changed:**
- `circadian_on()` now copies zone state to area on enable (inherits zone's current settings)
- `circadian_toggle_multiple()` now copies zone state when turning areas on
- `_get_config()` is now zone-aware - takes optional `area_id` to return zone-specific config
- All primitives (step_up/down, bright_up/down, color_up/down, set, freeze_toggle, reset) now use zone-aware config

**Technical:**
- Added `import glozone` and `import glozone_state` to primitives.py
- Runtime state (brightness_mid, color_mid, frozen_at) syncs between zones and areas
- When an area joins Circadian mode, it inherits the current zone state
- GloZone primitives enable multi-room synchronization via switch buttons

## 6.8.55
**GloZone Phase 2: Core Logic - Zone-Aware Config**

**Added:**
- `glozone.load_config_from_files()` - Centralized config loading with migration
- `glozone.get_effective_config_for_area()` - Get merged preset + global config for an area
- `glozone.reload_config()` - Force reload from disk

**Changed:**
- `main.py` now uses zone-aware config for all circadian calculations
- `get_circadian_lighting_for_area()` uses area's zone preset
- `update_lights_in_circadian_mode()` uses area's zone preset
- `reset_state_at_phase_change()` now also resets GloZone runtime state
- Phase boundary check uses first preset's times (note: future enhancement for per-zone)

**Technical:**
- Config loading moved from inline file reads to `glozone.load_config_from_files()`
- Preset settings and global settings properly merged for backward compatibility
- Areas now get their lighting values based on their zone's preset

## 6.8.54
**GloZone Phase 1: Data Model & Storage**

**Added:**
- `glozone_state.py` - In-memory runtime state for GloZones (brightness_mid, color_mid, frozen_at)
- `glozone.py` - Zone configuration management (zone lookup, preset lookup, area membership)
- Zone-aware helpers in `state.py` (get_runtime_state, set_runtime_state, copy_state_from_zone)

**Changed:**
- Config now stored in GloZone format with `circadian_presets` and `glozones` sections
- Automatic migration from flat config to new format on first load
- Existing settings become "Glo 1", all areas go to "Unassigned" zone
- `load_config()` returns effective flat config for backward compatibility
- `save_config()` properly handles both flat and structured saves

**Technical:**
- PRESET_SETTINGS and GLOBAL_SETTINGS define which settings go where
- Sync tolerance of 0.1 hours (6 minutes) for state comparison
- Tests updated to verify new config structure

## 6.8.53
**Add GloZone specification document**

**Added:**
- `docs/GLOZONE_SPEC.md` - Complete specification for GloZone feature
- Defines Circadian Presets (named configurations)
- Defines GloZones (area groupings tied to presets)
- New primitives: GloUp, GloDown, GloReset
- Updated button mappings for Hue Dimmer Switch
- Data model, implementation plan, and migration path

## 6.8.52
**Adjust CCT color mapping - tighter red, more orange**

**Changed:**
- Tightened pure red range: 500-700K (was 500-1000K)
- Red to deep orange: 700-1000K (was 1000-1500K)
- Deep orange range: 1000-1600K (was 1500-1800K)
- Orange to yellow: 1600-2200K (was 1800-2400K)
- Yellow to off-white: 2200-3000K (was 2400-3000K)
- 3000K+ ranges unchanged

## 6.8.51
**Extend CCT color mapping to include red range**

**Improved:**
- UI color display now extends down to 500K (pure red)
- Added 500-1000K pure red range
- Added 1000-1500K red-to-orange transition
- Previous minimum was 1500K

## 6.8.50
**Fix time callout showing "6:60a" instead of "7:00a"**

**Fixed:**
- Graph time callout now correctly displays times on the hour (e.g., "7:00a" not "6:60a")
- Fixed floating-point precision issue where `Math.round()` could produce 60 minutes
- Both `formatHour()` and `formatTime()` functions now handle the edge case

## 6.8.49
**Reduce Live Design transition time to 2 seconds**

**Changed:**
- Live Design enter/exit transitions reduced from 3 seconds to 2 seconds

## 6.8.48
**Live Design visual feedback transitions**

**Added:**
- **Entering Live Design**: Lights fade to off, then fade to Live Design values
- **Exiting Live Design**: Lights fade to off, then fade to saved state
- Status shows "Entering..." and "Exiting..." during transitions
- `apply_light` endpoint now accepts `transition` parameter

**Technical:**
- Added `_turn_off_lights()` helper for fade-to-off transitions
- `_restore_light_states()` now accepts transition parameter
- Frontend tracks `liveDesignFirstApply` flag for initial transition

## 6.8.47
**Refactor button previews to use shared functions**

**Refactored:**
- Created `getBrightnessPreview()` and `getColorPreview()` functions
- Button display values now come from the same logic as click handlers
- Eliminates code duplication and ensures previews always match actual behavior
- Cleaner code with fewer inline calculations

## 6.8.46
**Fix color button previews with solar rules + Live Design fade transition**

**Fixed:**
- Color up/down button tooltips and callouts now respect Warm Night ceiling and Cool Day floor
- Previously showed "+350K to 3050K" when warm night capped it at 2700K
- Now correctly shows "at max" when solar rules prevent further color change

**Improved:**
- Live Design restore now fades lights over 1 second instead of instant snap
- Smoother transition when ending Live Design or switching areas

## 6.8.45
**Fix - Warm night/Cool day toggles no longer reset midpoints**

**Fixed:**
- Toggling Warm night or Cool day checkboxes no longer resets brightness/color midpoints
- Previously, these controls called `syncConfigFromUI()` which reset stepped position
- Now they update only the relevant config values without affecting runtime state

## 6.8.44
**Improved UI color temperature display**

**Changed:**
- Adjusted CCT-to-color mapping for more intuitive visual representation
- 4000K now displays as white (was yellowish)
- 6500K now displays as baby blue (was near-white)
- Warmer temperatures (2000-3000K) show deeper orange/amber tones

This is purely cosmetic - affects graph colors, sliders, buttons, and callouts.
Light control values remain unchanged.

## 6.8.43
**Enhanced Live Design experience**

**Changed:**
- **Auto-enable on area selection**: Selecting an area from dropdown immediately starts Live Design
- **Pause button replaces Enable/Disable**: Subtler UX - button only appears when an area is selected
- **Pause/Resume toggle**: Clicking Pause restores lights to prior state; Resume continues designing

**Added:**
- **Suppress periodic updates**: Area being designed is excluded from 30-second update cycle
- **State restoration**: Lights return to their prior settings when Live Design ends (via Pause or area deselect)

**Technical:**
- webserver.py saves light states when Live Design starts, restores on end
- webserver.py fires `circadian_light_live_design` event to signal main.py
- main.py tracks `live_design_area` and skips it in `periodic_light_updater`

## 6.8.42
**Fix - Designer Save button now immediately refreshes lights (v2)**

**Fixed:**
- Save button now fires a `circadian_light_refresh` event directly via WebSocket
- No longer depends on integration having the `refresh` service registered
- Works immediately without needing to update the integration or rebuild Docker image

**Technical:**
- webserver.py fires event via `fire_event` WebSocket API
- main.py listens for `circadian_light_refresh` event and signals refresh

## 6.8.41
**Add circadian.refresh service to integration**

**Added:**
- Added `circadian.refresh` service to the custom integration
- Synced bundled integration to v3.4.0

## 6.8.40
**Fix - Manually enabled automations stay enabled after addon restart**

**Fixed:**
- Automations that were manually enabled no longer get disabled when addon restarts
- Removed `initial_state` from existing automations before persisting to YAML
- `initial_state: False` only applies to newly created automations, not existing ones

## 6.8.39
**Swap step and bright for up/down buttons**

**Changed:**
- **Up button**: 1x bright_up (was step_up), hold step_up (was bright_up)
- **Down button**: 1x bright_down (was step_down), hold step_down (was bright_down)

Single press now adjusts brightness only; hold steps along the curve (brightness + color).

## 6.8.38
**Fix - Step button preview shows wrong CCT near brightness bounds**

**Fixed:**
- Step up/down button tooltips now show correct CCT when near max/min brightness
- Previously, stepping up near max brightness would preview 500K (min CCT) instead of current CCT
- Widened the bounds-detection threshold in `getStepResultCCT` from 0.999 to 0.99
- This prevents the virtual time calculation from extrapolating to extreme values

## 6.8.37
**Fix - Frozen lights stay frozen across phase transitions**

**Fixed:**
- Phase changes (ascend/descend) no longer unfreeze lights
- `reset_all_areas()` now preserves `frozen_at` state (only resets midpoints)
- Explicit reset primitive (`reset_area()`) still clears frozen state as expected

## 6.8.36
**Reorganize Hue dimmer switch button mappings (v2)**

**Changed:**
- **Power button**: 1x toggle, 2x broadcast, 3x-5x reserved, hold RESERVED (magic button)
- **Up button**: 1x step_up, 2x color_up, 3x britelite, 4x-5x reserved, hold bright_up
- **Down button**: 1x step_down, 2x color_down, 3x nitelite, 4x-5x reserved, hold bright_down
- **Hue button**: 1x reserved (scope), 2x reset, 3x freeze_toggle, 4x wake/bed, 5x reserved, hold RESERVED

**Key changes from v6.8.30:**
- Up/Down 2x now does color step (was brightness step)
- Up/Down 3x now sets preset (was color step)
- Up/Down hold now does brightness step (was preset)
- Hue 1x now reserved for scope (was freeze_toggle)
- Hue 3x now freeze_toggle (was wake/bed)
- Hue 4x now wake/bed (new)

**Added:**
- Quadruple-press and quintuple-press triggers for all buttons (reserved for future use)

## 6.8.35
**Feature - Live Design capability-based color mode**

**Added:**
- Live Design now detects light capabilities when enabled for an area
- Color-capable lights receive XY color for full warm range (including orange/red below 2000K)
- CT-only lights receive color_temp_kelvin (clamped to 2000K minimum)
- Capability cache is per-area, fetched lazily when Live Design is activated
- Concurrent service calls prevent "popcorning" effect in mixed areas

**Technical Details:**
- `_fetch_area_light_capabilities()` queries HA via WebSocket for lights in the area
- Checks `supported_color_modes` attribute to classify lights as color vs CT-only
- Cache variables (`live_design_color_lights`, `live_design_ct_lights`) hold entity IDs
- Cache cleared when Live Design is disabled or area changes

## 6.8.34
**Feature - Extended warm color range into red**

**Added:**
- Extended `color_temperature_to_xy` to interpolate beyond Planckian locus limits
- Below 1200K, colors now smoothly transition from orange towards red (at 500K)
- Documented the physics: Planckian locus peaks at ~1200K then starts cooling;
  we extend it by interpolating towards a target red point for circadian lighting

**Technical Details:**
- 1200K+: Standard Planckian locus formula (blackbody radiation)
- 500K-1200K: Linear interpolation from warmest Planckian (0.5946, 0.3881) to target red (0.675, 0.322)
- This creates a perceptually smooth orange → red gradient for nighttime/mood lighting

## 6.8.33
**Fix - Live Design now uses XY color mode**

**Fixed:**
- Designer's Live Design feature now uses XY color instead of kelvin
- Enables full warm color range (orange/red below 2000K) when previewing in designer

## 6.8.32
**Fix - Periodic updater now uses XY color mode**

**Fixed:**
- Periodic light updater (60-second refresh) now uses capability-based color mode
- Color-capable lights receive XY color, CT-only lights receive color_temp_kelvin

## 6.8.31
**Feature - Extended warm color range for color-capable bulbs**

**Added:**
- Light capability detection: caches `supported_color_modes` for each light on startup
- Area-to-light mapping for per-bulb control
- Color-capable lights now use XY color mode for full color range (including warm orange/red below 2000K)
- CT-only lights continue to use color_temp_kelvin (clamped to 2000K minimum)
- Mixed areas send concurrent commands: one for color lights, one for CT lights (no popcorning)

**Changed:**
- Updated deprecated `kelvin` parameter to `color_temp_kelvin` for HA 2026.1 compatibility

## 6.8.30
**Reorganize Hue dimmer switch button mappings**

**Changed:**
- **Power button**: 1x toggle, 2x broadcast, hold reserved
- **Up button**: 1x step, 2x bright_up, 3x color_up, hold britelite
- **Down button**: 1x step, 2x bright_down, 3x color_down, hold nitelite
- **Hue button**: 1x freeze_toggle, 2x reset, 3x wake/bed preset, hold reserved

**Added:**
- Triple-press triggers for up, down, and on buttons

## 6.8.29
**Improvement - Blueprint automations preserve user customizations**

**Changed:**
- Automations are now only created, never updated after initial creation
- User customizations (added areas, removed buttons) are preserved across addon restarts
- To reset an automation to stock, delete it and the addon will recreate it

## 6.8.28
**Fix - Color jumps to wrong value after stepping at bounds**

**Fixed:**
- Step operations now calculate color proportionally instead of using virtual time
- Prevents color jumping to extreme values (e.g., 922K) after repeated step-ups
- Both brightness and color now step by their respective step sizes
- Freeze toggle timing: dim reduced to 0.3s, unfreeze rise reduced to 1s

## 6.8.27
**Fix - Step operations wrap-around at bounds**

**Fixed:**
- Step operations no longer wrap around to dim values when repeatedly stepping up
- Added safe margin (1% of range) to prevent asymptotic midpoint calculations
- Midpoint values are now clamped to valid range instead of wrapping with % 24
- Stepping to the bound now works correctly without causing wrap-around on subsequent steps

## 6.8.26
**Improvement - Smooth bounce depth scaling**

**Changed:**
- Bounce depth now scales smoothly with brightness (no more abrupt threshold)
- Lower brightness = deeper dip for consistent visual feedback at all levels
- At 100%: dip to 50% (50% depth)
- At 50%: dip to 12.5% (75% depth)
- At 20%: dip to 2% (90% depth)
- At 10%: dip to ~0% (95% depth)
- Always 0.3s down, 0.3s up

## 6.8.25
**Feature - Visual bounce when hitting bounds**

**Added:**
- Lights now bounce when step/bright/color operations hit their configured limits
- Provides clear visual feedback that you've reached the min or max bound

## 6.8.24
**Simplification - Remove "pushing bounds" functionality**

**Removed:**
- Removed ability for step/bright/color buttons to push beyond configured min/max bounds
- Removed 4 lock checkboxes from designer UI (brightness-range-locked, color-range-locked, warm-night-locked, cool-day-locked)
- Removed temporary ceiling/floor chips for solar rules
- Removed temp-bounds-row display showing pushed min/max values
- Removed 5 state fields: `min_brightness`, `max_brightness`, `min_color_temp`, `max_color_temp`, `solar_rule_color_limit`

**Changed:**
- Step, Bright, and Color operations now strictly operate within configured min/max bounds
- Solar rules (warm_night, cool_day) now always use their configured targets directly
- Midpoint-based curve traversal preserved - buttons still shift along the circadian curve
- Simplified state management: AreaState now only tracks `enabled`, `frozen_at`, `brightness_mid`, `color_mid`
- Cleaner, more predictable behavior - configured bounds are always respected

**Why:**
- The "pushing" feature added complexity without clear user benefit
- Temporary bound adjustments were confusing and difficult to understand
- Simpler model: set your desired min/max in config, and that's what you get

## 6.8.23
**Fix - Step down only moving by small amounts near minimum**

**Fixed:**
- Step down from 9% to 1% was only moving 2% per press instead of going to 1%
- Root cause: `at_config_min` triggered when step would OVERSHOOT the bound, not just when AT the bound
- This caused "pushing mode" to activate when far from the bound, limiting step to headroom (2%)
- Fix: only enter pushing mode when current_bri is actually AT the config bound (within 0.5%)
- Now stepping from 9% properly traverses curve to 1% in one step

## 6.8.22
**Fix - Step down stuck when bounds already at absolute limit**

**Fixed:**
- When min_brightness bound was already pushed to 1% (absolute limit), stepping from 8% did nothing
- Issue: code entered "pushing mode" but had no headroom to push, so target stayed at bound
- Fix: only use pushing mode if there's >0.5% headroom to push; otherwise use curve traversal
- This allows stepping to reach 1% even after bounds are fully pushed

## 6.8.21
**Fix - Step down getting stuck near minimum**

**Fixed:**
- Step down now reaches absolute minimum (1%) even when step size overshoots
- Previously returned None when target_bri went below 1 (e.g., 12% - 16.5% = -4.5%)
- Now clamps to 1% and continues, only returns None if already at 1%

## 6.8.20
**Transition timing refinements**

**Changed:**
- 30-second periodic refresh: 2s → 0.5s (faster response)
- Freeze/unfreeze dim phase: 0.8s → 0.5s (snappier)
- Unfreeze rise phase: 1s → 2s (intentionally slow, signals resuming circadian)
- Freeze rise phase: instant (0s) - unchanged

## 6.8.19
**Fix - Warm Night CT persistence + faster transitions**

**Fixed:**
- Warm Night CT (and other solar rule settings) now persist after leaving designer
- Bug: `updateSolarTargetSliderConstraints()` was called before slider values were set from config, causing it to read HTML defaults and overwrite the loaded config

**Changed:**
- Light transitions reduced from 1s to 0.5s for turn_on and turn_off operations

## 6.8.18
**Fix - Save button now properly triggers light refresh**

**Fixed:**
- Changed circadian.refresh call from REST API to WebSocket API
- REST API was returning 400 because `circadian` isn't a registered HA service domain
- WebSocket call_service events are properly intercepted by main.py

## 6.8.17
**Fix - asyncio.Event "different loop" error causing log spam**

**Fixed:**
- Created `refresh_event` lazily inside the running event loop instead of in `__init__`
- Prevents "got Future attached to a different loop" errors that were flooding logs
- Added null check in refresh service handler for safety

## 6.8.16
**Feature - Save triggers immediate light refresh + UI polish**

**Added:**
- `circadian.refresh` service that signals the 30s periodic updater to run immediately
- Save button now triggers refresh of all enabled areas using same code path as 30s loop
- Button callouts show "-" when delta rounds to 0 (instead of "+0%" or "-0K")
- Button callouts show "at max"/"at min" when at extreme bounds
- Button tooltips show "at maximum/minimum" text when at extremes

**Changed:**
- "Save Configuration" button renamed to "Save"
- Refresh uses asyncio.Event to wake periodic updater (truly same code path, not duplicate)

**Fixed:**
- Removed `reset_all_areas()` from config save - was incorrectly clearing user's stepped positions

## 6.8.15
**Feature - Separate increment controls for Step, Bright, and Color buttons**

**Added:**
- Individual increment inputs next to Step, Bright, and Color button labels in designer
- `step_increments`, `brightness_increments`, `color_increments` config fields (default to master Increments value)
- Master Increments slider now updates all three individual inputs when changed
- Button tooltips now show target values (e.g., "Step Up to 46% at 3600K")

**Fixed:**
- Speed clamping (1-10 range) applied consistently across all designer calculations
- Step button callouts now correctly use step_increments instead of brightness_increments
- Changing increment values no longer resets cursor midpoints

## 6.8.11
**Feature - Designer cursor time navigation buttons**

**Added:**
- Time navigation buttons in cursor controls: -5, Now, +5
- "Now" sets cursor to current time
- +5/-5 moves cursor by 5 minutes with wrap-around at midnight

## 6.8.10
**Fix - Designer step wrap-around prevention**

**Fixed:**
- Added absolute limit check in designer's "within bounds" stepping path
- Prevents step down from wrapping around to top of curve (matching brain.py fix from 6.8.5)

## 6.8.9
**Fix - Designer step down minimum now matches backend (1%)**

**Fixed:**
- Changed ABSOLUTE_MIN_BRI from 0 to 1 in designer.html to match brain.py
- Step down now stops at 1% instead of 0%

## 6.8.8
**Fix - circadian_toggle and circadian_on now respect frozen_at**

**Fixed:**
- `circadian_toggle` and `circadian_on` now use frozen_at if set when turning lights on
- Previously used current time, causing frozen areas to flash wrong values before periodic update corrected them
- Example: bathroom frozen for party → turn off → turn on → now correctly restores frozen lighting

## 6.8.7
**Debug - Add logging for preset apply troubleshooting**

**Added:**
- Debug logging for nitelite/britelite preset application
- Logs frozen_at, calculated values, and service_data sent to HA

## 6.8.6
**Fix - Step/bright/color operations now use frozen hour when frozen**

**Fixed:**
- step_up, step_down, bright_up, bright_down, color_up, color_down now use the frozen hour if area is frozen
- Previously used current real time, which caused inconsistent behavior when stepping from nitelite/britelite
- Now stepping from nitelite (frozen at min) properly steps up from that position

## 6.8.5
**Fix - Step down wrapping around to top at bottom**

**Fixed:**
- Added absolute limit check in "within bounds" traversal path
- Previously, midpoint wrapping (`% 24`) caused brightness to flip from min back to max
- Step now properly returns None (at limit) when target brightness would exceed absolute limits

## 6.8.4
**Refactor - Clean up reset and preset behavior**

**Changed:**
- `reset` primitive no longer forces enable - preserves enabled status, only applies lighting if already enabled
- All presets now call `reset_area()` first, then apply preset-specific settings (thin presets)
- `wake`/`bed` presets now also reset bounds (previously only set midpoints)
- Consistent behavior: presets clear all adjustments before applying

## 6.8.3
**Fix - Britelite/nitelite presets now reset pushed bounds**

**Fixed:**
- Britelite and nitelite presets now reset all area state (bounds, midpoints) before applying
- Previously, pushed min/max bounds from stepping would persist, causing britelite to not be bright

## 6.8.2
**Fix - Prevent step_down from turning lights off**

**Fixed:**
- Changed `ABSOLUTE_MIN_BRI` from 0 to 1 to match designer limits
- Stepping down to minimum now keeps lights at 1% instead of turning them off

## 6.8.1
**Fix - Remove global debounce from freeze_toggle**

**Fixed:**
- Removed 3-second debounce from freeze_toggle that was blocking different areas
- The debounce was added for duplicate automation issue but that was fixed by removing duplicate automations

## 6.8.0
**Fix - Force automation reload when blueprint files are updated**

**Fixed:**
- Blueprint file updates now properly trigger `automation.reload` in Home Assistant
- Previously, if blueprint content changed but automation configuration (area/device mappings) stayed the same, HA would not reload and use stale blueprint
- Added debug logging when blueprint files are skipped due to matching checksums

## 6.7.9
**Update - Add long-press Power button for britelite**

**Added:**
- Power long-press → britelite preset

**Button mapping:**
| Button | 1x | 2x | 3x | Long-press |
|--------|----|----|-----|------------|
| Power | Toggle | Broadcast | - | Britelite |
| Up | Step up (off: nitelite) | - | - | Bright up |
| Down | Step down (off: nitelite) | - | - | Bright down |
| Hue | Freeze toggle | Wake/bed | Reset | - |

## 6.7.8
**Update - Revised button mappings for Hue Dimmer Switch**

**Changed:**
- Hue button: 2x → wake/bed preset, 3x → reset (was 4x)
- Removed: Power 4x → britelite
- Removed: Hue 4x → reset (moved to 3x)

## 6.7.7
**Feature - Add enable parameter to set primitive**

**Added:**
- `set` now accepts optional `enable` parameter to enable area atomically with preset
- Added `set`, `freeze_toggle`, and `broadcast` service definitions to integration

**Changed:**
- Blueprint now uses `circadian.set` with `preset` and `enable: true` for nitelite/britelite
- Fixes issue where lights would turn on with wrong values when off
- Fixed tuple unpacking bug in `set` for wake/bed presets

## 6.7.6
**Feature - Add preset parameter to circadian_on** (reverted in 6.7.7)

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
