<!-- https://developers.home-assistant.io/docs/add-ons/presentation#keeping-a-changelog -->

## 1.0.179
- **Fade indicator on home page**: During an auto fade, area cards show a subtly pulsing filled triangle (▲ fade-in / ▼ fade-out) with progress percentage. The matching auto pill (on/off) is suppressed during its fade so it doesn't jump to the next occurrence.
- **Fade indicator on area detail header**: Filled triangle icon appears alongside freeze/boost buttons during an active fade, with the same subtle pulse animation.
- **Fix auto pill icons**: Replaced SVG chevrons with filled triangles (▲/▼) matching the tune page fade legend convention.

## 1.0.178
- **Remove dead schedule override popover**: Deleted ~280 lines of unused alarm override popover code (CSS, JS functions, click-outside listener) from home page — no longer wired to any UI element.

## 1.0.177
- **Home page: single auto pill**: Show only the nearest auto-on or auto-off pill per area card (saves horizontal space on mobile).
- **Home page: up/down arrows**: Replace sun/moon icons with chevron arrows matching the area detail brightness step buttons; tighter icon-to-time spacing and reduced pill padding.
- **Home page: compact date**: Remove space between month and date in date_short labels (e.g. "Mar30" not "Mar 30").
- **Area detail: rename cards**: "Area Brightness" → "Brightness", "Light Brightness" → "Lights".
- **Area detail: asterisk label**: "Adjusted wake/bed*" → "User-adjusted brightness*".

## 1.0.176
- **Future-date sun times**: Auto schedules with sunrise/sunset source now compute sun times for the actual fire date instead of today. At seasonal latitudes, this fixes significant drift when the next fire day is days/months away. Date-keyed cache avoids repeated calculations on 3-second refreshes.
- **Live header preview**: Auto schedule "next time" in the card header now updates live as you change source, offset, or days — no save required. Cancel restores the saved value; Save fetches the server-authoritative value.

## 1.0.175
- **Remove per-day times under day bubbles**: Sunrise/sunset times were redundant (all identical) and the resolved next time is already shown in the card header.
- **Fix "6:60a" time display**: `formatAutoTime` minute rounding overflow now rolls to next hour correctly.
- **Prevent immediate catch-up on enable**: When toggling a schedule on, if today's trigger time has already passed, marks it as fired so it waits for the next occurrence instead of firing immediately.

## 1.0.174
- **Fade visibility across all pages**: Added `fade_direction` and `fade_progress` to all status API endpoints (full, lite, light-filters). **Tune page**: ADJ column now includes fade delta with ▲/▼ icons alongside existing ⚡ (boost) and * (override); "now" brightness reflects faded value; fade legend shown when active. **Area detail brightness cascade**: Added permanent "Auto-on fade" / "Auto-off fade" row showing fade delta (0% when inactive). **Area detail circadian slider**: Now uses `actual_brightness` (matching home page behavior) so it reflects fade, NL, and all pipeline stages.

## 1.0.173
- **Fix area detail brightness during fade**: Full area-status endpoint was computing `actual_brightness` from the curve (ignoring fade), while only the lite endpoint used `last_sent_brightness`. Now the full endpoint falls back to `last_sent_brightness` when a fade is active, so the area detail header and brightness slider reflect the actual faded brightness.

## 1.0.172
- **Fix auto schedule not re-firing after edit**: `save_area_settings` was writing to disk but not updating the in-memory glozone config cache, so `check_auto_schedules` never saw the new settings. Now calls `glozone.set_config()` after save. Also clears the per-area fired state when auto schedule settings are saved, so edited schedules re-trigger immediately.

## 1.0.171
- **Fix fade-in starting at full brightness**: Auto On with fade was calling `glo_reset` with `send_command=True`, blasting full brightness to lights before the fade timer started. Now uses `send_command=False` so the periodic tick handles the first light command with the fade multiplier applied from near-zero.

## 1.0.170
- **Fix tune section collapse**: Restored `toggleBrightnessBody` and `toggleLightsBody` functions that were accidentally removed during wake alarm → auto schedule replacement.

## 1.0.169
- **Fix auto schedule save button**: Snapshot capture was reading stale `autoState.days` instead of current DOM state, so dirty check always returned true after save. Now reads day button state from DOM to match the dirty check.

## 1.0.168
- **Auto On/Off UI (Phase 2)**: Replaced wake alarm card with two collapsible Auto On / Auto Off cards on area detail page. Each card has source selection (Sunrise/Sunset/Custom), day-of-week bubbles, offset controls, fade slider (0-60 min), and override popover (pause/custom time with through-date). Auto On includes "Skip if already brighter" option. Custom mode supports two sub-schedules with mutually exclusive days. Home page pills updated with sun/moon icons for auto on/off times. Backend `_compute_next_auto_time` replaces `_compute_next_wake_alarm`.

## 1.0.167
- **Auto On/Off backend (Phase 1)**: Replaced wake alarm system with per-area Auto On and Auto Off schedule infrastructure. New config schema (`auto_on_*`, `auto_off_*`), schedule checker with sunrise/sunset/custom modes, fade-in/fade-out support via periodic tick multiplier, skip-if-brighter logic, per-area override support. Migrates existing wake alarm configs automatically. UI update pending.

## 1.0.166
- **Fix motion boost stuck forever**: `motion_on_only` with boost was setting `from_motion=True` which uses the "motion" sentinel for expiry, but on_only mode never creates a motion timer to clear it. Changed to `from_motion=False` so the boost gets a real timestamp-based expiry.
- **Eliminate triple motion trigger**: ZHA motion events (`attribute_updated`, `on_with_timed_off`) are now skipped — motion sensors are handled exclusively via `binary_sensor` state changes. Eliminates redundant triple-processing of each motion detection.

## 1.0.165
- **Rename cooldown label**: "Wait" → "Cooloff" on control details page.
- **Update default settings**: Circadian refresh 30→20s, burst count 3→1, periodic transition day →1, multi-click speed →15 tenths, long-press repeat →7 (synced backend), motion warning →20s, limit bounce max 30→25%, min 10→13%, two-step delay 3→2, CT comp max 1.4→1.7, sun saturation 25→40% squared.

## 1.0.164
- **Fix cooldown not persisting**: Cooldown was saved to disk correctly but not mapped back into the editing state when the control page loaded. Added `cooldown` to both scope-mapping paths.

## 1.0.163
- **Fix rhythm page color_sensitivity snapping**: The discrete sensitivity slider was snapping stored values (e.g. 1.10) to the nearest step (1.00) on page load, causing a K mismatch vs backend. Now preserves the stored value through the UI round-trip.
- **Remove zone-states debug spam**: Demoted v1.0.162 diagnostic log back to debug level.

## 1.0.162
- **Debug zone-states K computation**: Added info-level log showing outdoor_norm, elev_factor, condition_multiplier, weather condition, cloud cover, and color sensitivity for each zone-states request.

## 1.0.161
- **Revert toggle buttons to orange**: Changed power/circadian/freeze/boost toggle borders from green back to orange accent color on home, tune, and area detail pages.

## 1.0.160
- **Compute sun elevation locally**: Replaced HA `sun.sun` entity dependency with geometric solar computation matching the rhythm page JS formula. Both frontend and backend now use identical math for sun elevation, eliminating the outdoor normalization discrepancy. Removed `update_sun_elevation()`, HA sun entity elevation tracking/logging.
- **Remove diagnostic logging**: Cleaned up console.log statements and parseSafe band-aid from v1.0.159.

## 1.0.159
- **Debug rhythm page K**: Added console logging for warm night config values, sun times, and cursor computation. Added defensive NaN handling for warm night slider parsing.

## 1.0.158
- **Fix rhythm page sun times**: Fetch sunrise/sunset from backend API (astral library) instead of computing with simplified JS solar math. Eliminates warm night window timing discrepancy between rhythm page and actual light control.
- **Fix solar rule application order**: Warm night and cool day effects now computed from original base K and applied simultaneously, matching backend brain.py. Previously JS applied warm night first, making cool day overcompensate.

## 1.0.157
- **Fix rhythm page K mismatch**: Replaced log-lux outdoor normalization formula with backend's elev_factor model (linear/squared ramp with sun saturation). "Current conditions" now uses condition_multiplier directly from API instead of reverse-engineering it. Rhythm page K values now match backend/color tab.

## 1.0.156
- **Fix color tab column header width**: Missing `%` in `width:100` caused truncated column headers.

## 1.0.155
- **Fix color tab area K values**: Area rows now use authoritative `kelvin` from API instead of recomputing from solar cache (which could be stale for warm night timing). Aligns with area detail page.
- **Sticky color tab headers**: Color tab zone header + column headers now sticky on scroll.
- **Fix Live Design fade**: Added 2.2s delay after fade-to-off before applying live values, so the fade is visible.

## 1.0.154
- **Fix sun saturation not loaded on startup**: `init()` in lux_tracker wasn't reading `sun_saturation` and `sun_saturation_ramp` from config, always using default 25%. Caused lights to be too dim on restart until settings were touched.
- **Fix sticky column headers on tune page**: Column headers moved inside the sticky zone header so they persist during scroll.

## 1.0.153
- **Fix per-light brightness on tune page**: Was missing override and boost in per-light calculation, showing ~57% instead of ~96%. Now matches area detail page.
- **Fix sticky zone headers**: Changed `overflow: hidden` to `overflow: clip` on zone-group so `position: sticky` works.

## 1.0.152
- **Tune page: sort preserves unsaved changes**: Slider positions captured and restored across sort re-renders.
- **Tune page: sticky zone headers**: Zone headers with column labels stick to top while scrolling.
- **Fix zone K on color page**: Zone header was showing curve CT instead of final CT (missing warm night/cool day shifts).
- **Tune page: save button feedback**: Shows "Saving..." immediately on click, reverts when done.

## 1.0.151
- **Standardized balance and solar sliders**: Area balance now uses 9 direct factor steps (0.60–1.40) with rounder numbers and tighter range. Solar exposure aligned to 9 steps (0–2.0) matching sun sensitivity ticks. Both on area detail and tune pages. Existing values convert to closest tick.
- **Fix bright bounce cancelled by hold release**: All bounce cues now run as detached tasks so button release can't cancel them mid-flash.

## 1.0.149
- **Fix bounce color using xy instead of mireds**: Both bounce paths (`_feedback_cue` and `_bounce_at_limit`) now use `xy_color` for color shift and restore, matching the pipeline. Fixes wrong color on restore for sub-2000K values where mireds were out of range.
- **Controls page default sort**: After session expiry, defaults to Last Action descending (most recent first).

## 1.0.148
- **Debug logging**: Bounce logs now show full phase1/phase2 payloads (brightness + color). Bright reach path logs results for all-at-limit diagnosis. Star feedback area moves to front of chip list.

## 1.0.147
- **Fix bounce restore missing color**: Multi-area bounce (via `_feedback_cue`) restored brightness but not color temp, leaving lights at wrong color until next periodic tick. Now restores both.

## 1.0.146
- **Fix double bounce on reach path**: Non-reach all-at-limit check was outside the else block, causing it to run after the reach path bounce too. Fixed indentation for step and bright. Added all-at-limit bounce for color up/down multi-area.

## 1.0.145
- **Fix multi-area bounce**: Per-area bounce now suppressed for multi-area reaches; only bounces when ALL areas hit the limit. Prevents false bounces when one area maxes out but others still adjust.
- **Remove dead color_up/color_down code**: Old midpoint-shift versions were shadowed by override+decay versions. Removed ~200 lines of dead code.
- **Fix color reach path**: `send_command=False` was incorrectly passed as `steps` parameter. Now properly accepted by active color functions.

## 1.0.144
- **Fix reach flash when lights off**: Between-flash restore now goes to off (not cached brightness) when lights were off, preventing visible brightness between flashes.
- **Sync ZHA groups on purpose change**: Changing a light's purpose now triggers a full device sync so ZHA group membership updates immediately.

## 1.0.143
- **Fix limit bounce at low brightness**: Bounce math was using "% of current brightness" instead of "% of full range", making bounces invisible at low levels (e.g., 1-unit change at 5/255). Now uses range-based delta. Regression from v1.0.85.
- **Fix sun saturation settings not saving**: `sun_saturation` and `sun_saturation_ramp` were missing from GLOBAL_SETTINGS, causing them to be silently dropped on save.

## 1.0.142
- **Fix tick suppression after light actions**: The 3-second quiet period after button presses was bypassed when burst refreshes were active, allowing ticks to fire immediately after switch actions. Now ALL ticks (burst and periodic) are unconditionally suppressed for the full post_switch_refresh delay after any light action.

## 1.0.141
- **Post-switch burst count setting**: Configurable 0-3 burst refreshes after switch actions (Settings → Refresh). Set to 0 to disable burst refreshes for Zigbee troubleshooting.

## 1.0.140
- **Fix invisible limit bounce**: Target dict passed to HA contained extra keys (filter_name, area_id) that HA doesn't accept, causing silent call rejection. Now strips to clean entity_id/area_id only. Also defers periodic tick during bounce to prevent overwriting.

## 1.0.139
- **Debug bounce timing**: Bounce log now includes speed and delay values to diagnose invisible bounces.

## 1.0.138
- **Improved feedback logging**: All feedback cues (bounce, freeze, reach) now log area and purpose. Feedback target resolution logged at info level instead of invisible debug level. Bounce logs target entity.

## 1.0.137
- **Feedback always in target reach**: All feedback cues (reach, bounce, freeze) now flash in the active reach's starred feedback area, not the switch's physical location.
- **Star on all reaches**: Feedback star shows on single-area reaches too for visual consistency.

## 1.0.136
- **Feedback cue revamp**: Feedback routing now varies by cue type — reach indicator uses switch's own area, action feedback (bounce/freeze) uses active reach's feedback area. Per-reach feedback area selectable via star icon on switch detail. Removed per-switch indicator_light/area/filter fields.
- **NL-aware reach flashing**: When natural light is active and brightness is below the daytime threshold, reach feedback flashes UP to 100% instead of off, ensuring visibility in bright rooms.
- **Settings reorganized**: Motion warning time moved to Feedback Cues section. Renamed "Warning blink threshold" → "Motion blink threshold", "Reach feedback dip" → "Reach daytime threshold". Added "Reach feedback" on/off toggle.
- **Area-level feedback target**: Areas can store a feedback target (purpose or light). Defaults to most popular purpose dynamically.
- **Green power buttons on home page**: Power button hover/active uses green border.
- **Control detail action order**: Hue switch actions now display in order: Short, 2×, 3×, 4×, 5×, Long (matching switch map).

## 1.0.135
- **Integration logo**: Added icon.png and logo.png to the custom integration so it shows the Circadian Light logo in HA integrations list.

## 1.0.134
- **Fix controls page auto-refresh**: Poll URL used undefined `basePath` variable, causing silent fetch failures. This bug predates v1.0.132 — the old last-actions poll never worked either.

## 1.0.133
- **Action dropdowns**: "No Action" and "Magic" appear at top without a section header. Removed "Special" category.

## 1.0.132
- **Green toggle buttons on area detail**: Circadian, power, freeze, boost buttons use green border on hover/active.
- **Rhythm cursor stays put**: Cursor on rhythm detail page no longer auto-advances to "now" when user has navigated to a different time. Resets on page load or clicking "Now".
- **New zone defaults**: Wake/bed brightness 30%, warm night on (2300K, 2hr fade), no-sun max 3600K, coolest 5000K, primary days selected by default.
- **Controls page filters**: Status and Pause columns get filter dropdowns. Switching field clears prior filter.
- **Switch map save returns to cheat sheet**: After saving switch map edits, view returns to cheat sheet mode.
- **Area purge fixes**: Purge now removes areas from switches_config.json (was incorrectly targeting designer config). Prevents deleted areas from reappearing.
- **Settings page**: Refresh section moved below General.
- **Controls page optimization**: In-memory cache for last_actions (no disk reads on poll). New `/api/controls/refresh` endpoint returns only last_actions + pause states. Auto-refresh uses home_refresh_interval setting. Switch Map promoted to top-right, removed menu.
- **Unified action lists**: Magic button assignments on switch detail page now show all actions (not just moments). Fixed moments not appearing on switch map (import bug). Renamed "1×" to "Short", "Glo" to "Circadian". Consistent "No Action" label.

## 1.0.131
- **Sync bundled integration to 3.10.3**: The addon's bundled copy of `custom_components/circadian` was stale at 3.10.2, preventing the integration from updating on restart.

## 1.0.130
- **Green toggle buttons on area detail**: Circadian, power, freeze, and boost buttons use green border on hover and active state.

## 1.0.129
- **Fix ungrouped light turn-off for mismatched area name/id**: `_ungrouped_lights` was keyed by area name (e.g., `sunoffice`) but looked up by area id (e.g., `test_1`). Resolve name → id via `area_name_to_id` so ungrouped ZHA lights are found during turn-off.

## 1.0.128
- **Fix sun info panel auto-opening**: Panel div was missing its CSS class, so `display:none` wasn't applied. Content rendered visibly on auto-refresh.

## 1.0.127
- **Fix sun info icon**: Use HTML entity (&#x2600;) instead of JS unicode escape for initial render. Remove buildConditionsPanel from panel content (was rendering inline). Panel shows angle/conditions/intensity + status.

## 1.0.126
- **Sun info persistent icon**: Sun/cloud icon with intensity % in top-right corner, visible on both tabs. Click opens popup with angle × conditions = intensity breakdown + conditions config. Replaces the Sun section in the multiplier card.
- **Sun multiplier card simplified**: Now just sensitivity slider + math formula in header.
- **Color tab: removed cool/warm columns**: Warm night and cool day are now part of the rhythm CT (baked into zone header). Zone header shows final CT from zone-states (matches rhythm page). Area rows show only Shift, Adj, Final.
- **Sun divider 2x longer**: 80px → 180px.

## 1.0.125
- **Fix color tab CT math**: Always compute final CT from formula (base + cool + warm + adj) instead of using stale `last_sent_kelvin`. Fixes wrong final values for off rooms. Zone-synced areas (full send/reset) correctly use zone base, only individually shifted areas derive from last_sent_kelvin.

## 1.0.124
- **CT picker popup**: Warm night and cool day target badges open gradient slider popup on click.
- **Color zone header cleanup**: Removed redundant impact values (shown per-area). Added "Sun sensitivity" label before slider.
- **Sun multiplier card compact**: Indented angle/conditions/intensity formula to 120px, tightened vertical spacing.

## 1.0.123
- **CT picker popup**: Warm night and cool day target badges now open a popup slider with CT gradient background on click. Slider updates badge color, kelvin display, and all area CTs live. Closes on outside click.

## 1.0.122
- **Tune page auto-refresh**: Automatic periodic refresh using home page refresh interval setting (default 3s). Only refreshes the active tab. Pauses when user has unsaved changes. Removed manual refresh button.

## 1.0.121
- **Zone solar cache**: Periodic tick now caches zone-level solar breakdown (base_kelvin, night_strength, daylight_blend, warm_target, cool_target) in memory. Zone-states API includes solar_cache. Color tab reads cached data — no expensive area-status recomputation on refresh.
- **Light-filters API extended**: Added last_sent_kelvin, color_mid, color_override, color_override_set_at per area for client-side CT computation.

## 1.0.120
- **Tab restore on back navigation**: Color tab persists when navigating away and back (was resetting to brightness).
- **Row dividers visible on bright rows**: Added box-shadow on area rows for visibility against brightness shading.
- **Sort highlight fix**: Active sort column now correctly highlighted orange on brightness tab.
- **Color tab sorting**: All columns sortable (Area, Shift, Cool, Warm, Adj, Final) with click-to-sort, click-to-reverse.
- **Color zone header shows base CT**: Zone header displays rhythm curve base (pre-solar) so cool/warm columns read as additive from that base.

## 1.0.119
- **Fix last reach flash cut off**: Added 300ms dwell after every flash (including last) so the light visually completes before restore/cleanup. Only affected lights that were off.
- **Power button moved to Final column**: Off areas show brightness % with small power icon below (replacing "(off)" text). Saves horizontal space on mobile, keeps final value visible.

## 1.0.118
- **Fix feedback cue vs periodic tick collision**: Added `_defer_periodic_tick` flag that prevents periodic light updates during feedback cue sequences (reach flashes, bounce, freeze). Flag set at cue start, cleared in `finally` block, then `record_light_action()` starts fresh burst refresh. Prevents periodic tick from overwriting flash sequence mid-animation.

## 1.0.117
- **Fix color zone base CT**: Uses unshifted area for zone reference (fixes all areas showing shift when one area has circadian slider adjustment).
- **Brightness: off area visibility**: Removed opacity dimming — off areas now fully visible with power button + (off) label as only indicators.
- **Brightness: rename Brightness→Intensity** in sun multiplier card to avoid confusion with page purpose.
- **Brightness: right-align math formula** in multiplier card header.
- **Color: sensitivity slider moved to Cool Day row**, sun brightness row removed.
- **Color: wider target inputs** with hidden spin buttons, fits full kelvin values.
- **Both tabs: clickable zone headers** — click anywhere on zone header to collapse/expand (except zone name link which opens rhythm page).

## 1.0.116
- **Color tab: collapsible zones**: Chevron + animation with separate collapsed state from brightness tab.
- **Color tab: cool/warm columns restored**: Per-area Cool Day and Warm Night columns show individual impacts (differ when areas have circadian shifts).
- **Color tab: fix live update bug**: All areas now update colors when sensitivity slider moves (was only updating first area due to scoping bug).
- **Color tab: solid CT target badges**: Warm night/cool day targets shown as solid CT-colored chips with readable text, updating live as values change.
- **Color tab: per-area live cool/warm**: Sensitivity slider recalculates per-area cool/warm shifts individually.

## 1.0.115
- **Color tab: solid CT coloring**: Area rows and zone headers now use the same solid CT-colored backgrounds as the home page (at 100% brightness). Readable text colors computed per row. Live updates maintain solid coloring.

## 1.0.114
- **Color tab: visible CT shading**: Increased row background alpha from 0.06 to 0.15 and border from 0.4 to 0.6. CT colors now clearly visible on area rows and during live updates.

## 1.0.113
- **Fix color tab crash**: Variable ordering bug (zoneCoolShift used before declaration). Color tab now loads correctly.
- **Off area rework**: Off areas show full impacts and brightness shading as if on, with "(off)" label below the brightness %. Squared power button with green hover. Adj column shows "0%" instead of dash for zero values.

## 1.0.112
- **Off area treatment**: Areas with lights off show power button (⏻), "OFF" in final column, "NA" for SE/Balance impacts. Power button calls lights_on primitive and triggers full refresh. Off areas dimmed at 50% opacity with 0% brightness shading. Sliders and labels remain visible (settings, not state).
- **API**: Added `is_on` field to light-filters response per area.

## 1.0.111
- **Color tab: per-zone save/cancel**: Each zone has its own Save/Cancel buttons that appear when changes are made. Save persists settings and triggers light refresh. Cancel restores snapshot.
- **Color tab: live sensitivity updates**: Dragging the sensitivity slider live-updates cool day impact, zone header CT, and all area final CT values + colors. Same for toggling warm night / cool day and changing target kelvin.
- **Color tab: target kelvin inputs**: Warm night and cool day targets are now editable number inputs with CT-colored badges. Changes update impact and area colors in real-time.

## 1.0.110
- **Brightness area grid layout**: CSS grid for area rows — name vertically centered across all 3 rows, columns perfectly aligned with headers. Stronger brightness shading. Less left padding. Sun/Sensitivity sections swapped in multiplier card. Math formula shown in header when open (80% × 1.0 =).
- **Color tab CT shading**: Zone header and area rows now CT-color-shaded. Warm night and cool day on separate rows with colored target badges and impact values. Sun sensitivity on its own row with brightness factor.

## 1.0.109
- **Brightness tab**: Row shading based on final brightness (black→white). Off rooms dimmed at 50% opacity. Fix column header alignment (use same flex classes as data rows). Tighter slider-to-label spacing. Fixed-width sun divider line. Purpose dropdown in light list now works (removed stopPropagation that blocked clicks).
- **Color tab restructure**: Removed Cool Day/Warm Night columns from area rows — their impact values now shown in zone controls next to toggles with target kelvin (→ 2700K). Only 3 area columns: Shift, Adj, Final (larger, less spreadsheet). Sensitivity on its own row with sun brightness factor. CT-colored left border accent on rows.

## 1.0.108
- **Fix color tab**: Zone base CT now uses rhythm curve value (pre-solar-rules) not post-solar final. Fixes shift column showing wrong values. Column headers aligned with data rows. Subtle CT color shading with left border accent instead of full blue tint. Area names use standard text color. Snap color_sensitivity on load.
- **Brightness tab polish**: Alternating row shading. Column headers hidden when zone collapsed. More spacing between data row and sliders. Slider labels show multiplier in parens: "Moderate (× 0.5)", "Soft (× 0.75)".

## 1.0.107
- **Color tab diagnostic view**: Full CT pipeline breakdown per area — Shift (area offset from zone base), Cool Day (daylight shift), Warm Night (ceiling shift), Adj (color override), Final CT. Zone headers show base CT with color shading. Per-zone controls: warm night toggle, cool day toggle, cool day sensitivity slider. All rows color-shaded by CT value. Save/cancel with shared action bar.

## 1.0.106
- **Fix boost pipeline in tune preview**: Boost and override are now additive after NL×factor (matching brain.py), not before. Boost+override indicators moved from Final to Adj column.
- **Tune page polish**: SE→"Sun Exposure" header. Impact deltas centered and prominent (same weight as Final). Area names wrap instead of truncate. Removed "rhythm zone" sub-label. Sensitivity slider amber to match sun exposure sliders. Sun divider line shortened. Adj column widened for icons.

## 1.0.105
- **Redesign tune area rows**: New 3-row layout — data row (name, SE impact, balance impact, adj, final brightness), slider row, centered label row. Swapped column order: SE first, Balance second. Added Adj column showing combined boost + override. Renamed Bri to Final. Custom-styled sliders matching rhythm/area pages with amber track for SE sliders. Sortable headers: Area, SE (slider value), Balance (slider value), Adj (combined impact), Final (computed brightness).

## 1.0.104
- **Sun multiplier card polish**: Header value stays visible when card is open. Removed redundant bottom multiplier row. Indented sun params, dropped "Sun" prefix. Multiplication-style layout (× on conditions, divider line, bold Brightness result). Aligned percentage values across all rows. Auto-snaps and persists stored sensitivity to nearest valid step on load.

## 1.0.103
- **Redesign sun sensitivity card as Sun multiplier**: Card now shows the sun multiplier (brightness × sensitivity) in the header. Open card has two sections: Sensitivity (slider) and Sun (angle, conditions, brightness). Conditions row opens a popup for source/override config. Sun brightness = angle × conditions shown as breakdown.
- **New sensitivity stops (0–2)**: Replaced 10-stop 0–5 range with 9 cleaner stops: 0, 0.10, 0.25, 0.50, 0.75, 1.00, 1.25, 1.50, 2.00. Default changed to 1.0 for both brightness and color sensitivity. Existing users auto-migrate via nearest-step snapping.

## 1.0.102
- **Fix motion sensor config save error**: Removed invalid `cooldown` kwarg passed to MotionSensorConfig (cooldown is per-scope on MotionAreaConfig, not per-sensor).

## 1.0.101
- **Fix ZHA motion boost using wrong amount**: ZHA motion path didn't zero out boost_brightness when boost was disabled, so the default 50% leaked through the max() merge when an area appeared in multiple motion scopes.

## 1.0.100
- **Burst refresh after light actions**: After any light command, the periodic tick fires 3 times at short intervals (post-switch refresh delay) before returning to the normal cycle. Each refresh recalculates from current state, giving 3 chances to catch missed Zigbee commands. New actions during the burst reset the counter to 3.

## 1.0.99
- **Post-action refresh for all light commands**: Moved defer + refresh logic from switch-only into turn_on_lights_circadian and turn_off_lights. Now any light action (switch, motion, contact, HA service, webserver) automatically defers the periodic tick and schedules a follow-up refresh. Uses _in_periodic_tick flag to prevent the periodic updater from re-triggering itself.

## 1.0.98
- **Outdoor brightness breakdown on tune page**: Sun sensitivity popup now shows condition multiplier and angle factor as separate rows. Area detail source info simplified to just "outdoor brightness: X%".

## 1.0.97
- **Sun saturation setting**: New "Sun saturation" setting (1-100%, default 25%) with ramp dropdown (linear/squared) in Location section. Controls at what percentage of peak sun elevation the angle factor saturates to 1.0. At 25%, full outdoor brightness is reached by mid-morning and lasts until late afternoon.
- **Tune section shows outdoor breakdown**: Source info now shows condition multiplier (e.g., "partlycloudy 60%") and angle factor alongside outdoor_normalized.
- **Fix rhythm page "current" outdoor modeling**: "Current" dropdown now uses backend's actual outdoor_normalized instead of re-deriving from weather condition string, fixing ~1000K color discrepancy between rhythm page and actual areas.

## 1.0.96
- **Fix double-send in bright_down/up reach fallback**: Partially-handled areas (e.g., kitchen with Standard + Accent) were re-sending all filters via per-area fallback, doubling Zigbee traffic for reach-handled filters. Now passes skip_filters so only unhandled filters get per-area sends.

## 1.0.95
- **Auto-sync reach groups on balance/exposure change**: Saving room balance or solar exposure now triggers a reach group sync, so ZHA group membership stays in sync with area_factor changes.

## 1.0.94
- **Replace nudge with post-switch refresh**: Removed all per-command nudge infrastructure (schedule_nudge, cancel_nudge, reach nudge, off-nudge). After a switch action, schedules a delayed refresh_event that triggers a full periodic update — sequential per-area re-send using fresh calculated values. Eliminates stale-value race conditions. New "Post-switch refresh" setting in Refresh section (default 3s) replaces nudge_delay/nudge_transition.

## 1.0.93
- **Fix nudge race in reach path**: Stale nudges were firing during reach group call_service await points (before turn_on_lights_circadian cancel could run). Now cancels all area nudges at the top of _send_step_via_reach_or_fallback and _send_bright_via_reach_or_fallback before any sends.

## 1.0.92
- **Fix nudge race condition**: Old nudges could fire during a new command's async execution, reverting lights to stale values. Now cancels pending nudge at the start of turn_on_lights_circadian before any sends. Fixes visible revert-then-step behavior during rapid step up/down.
- **Remove dead code**: Removed unused _compute_reach_value method.

## 1.0.91
- **Fix boost bypassing pipeline**: Boost brightness was pre-added before entering the pipeline, causing area_factor and NL to crush the boost. Now passes boost_brightness separately so it's applied after area_factor (matching periodic updater). Fixes bright_boost, _apply_current_boost, and _apply_circadian_lighting.

## 1.0.90
- **Banner shows actual brightness**: Area detail banner now displays actual brightness (includes NL, area factor, override, boost) instead of raw curve value.
- **Fix tune cascade order**: Area brightness computation section now matches backend pipeline order: curve → NL → area factor → override → boost. Previously boost was applied before area factor, showing incorrect values.
- **Boost return speed setting**: Configurable transition speed when boost ends and lights return to circadian (default 6s). New "Light Effects" settings section groups power speed, boost return speed, and motion warning time.

## 1.0.61
- **Fix spurious 2-step on already-on lights**: Color lights set via xy_color don't have `color_temp_kelvin` in HA state, causing unknown CT to trigger unnecessary 2-step on every brightness change >= 15%. Now skips 2-step for already-on lights with unknown CT (off-to-on still 2-steps as safety default).
- **Bounce at limit uses switch indicator target**: Limit bounce now targets the switch's configured indicator purpose group (single ZHA group) instead of all lights in the area. Reduces Zigbee traffic and matches other visual feedback behavior.

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
