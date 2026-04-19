<!-- https://developers.home-assistant.io/docs/add-ons/presentation#keeping-a-changelog -->

## 1.2.43
- **Fix batch group creation**: Groups are now created per-reach (areas must share balance AND appear in the same reach), not globally pooled. Prevents creating groups for areas that never get commanded together. Deduplicates across reaches when the same area subset appears in multiple scopes. Batch group log now includes area list.
- **Wire glozone_down/full_send/glozone_reset_full for batch dispatch**: These zone-level primitives now use batch groups when available. `glozone_down` accepts `send_command=False` and returns affected areas for batch dispatch.
- **Eliminate `_deliver_fast`**: All light delivery now goes through `_deliver_filtered`, ensuring consistent 2-step detection, state tracking, and logging for all areas regardless of filter configuration.
- **Motion/contact sensor scope storage**: `MotionSensorConfig` and `ContactSensorConfig` now store `scopes` (list of `MotionScope`/`ContactScope`) instead of flat area lists. Legacy configs auto-migrate on load. Enables future batch group creation from motion/contact reaches.

## 1.2.41
- **Balance-based batch groups**: Redesigned ZHA multi-area group creation. Instead of creating groups per exact switch scope, pools all areas from all reaches and groups by shared balance (area_factor). Creates more useful subset groups (e.g., 2 areas with same balance get a group even if no switch targets exactly those two), eliminates useless mixed-balance groups. Dispatch simplified: removes factor_key from matching, compares only computed brightness+kelvin values. Logs per-light group membership count for ZHA limit monitoring. Legacy `Circadian_Reach_*` groups auto-cleaned on first sync.

## 1.2.33
- **Fix fade completion brightness jump**: `compute_fade_target` now clears brightness_override, boost_brightness, and color_override from the synthetic context so the target matches what completion will actually produce.
- **Fix auto_on_light not persisting**: `auto_on_light` was missing from webserver defaults and save handler field list. Britelite/nitelite selection now saves and loads correctly.
- **Fix schedule day mutual exclusivity**: Selecting a day on schedule 1 now removes it from schedule 2 (was only one-directional before).
- **Fade status UI**: Home page and area detail show alarm icon + arrow (▲/▼) + target preset + countdown during active fade. API returns `fade_target_preset` and `fade_remaining` from all status endpoints.
- **Fix zone header alt-day timing**: Zone header now resolves alt-day wake/bed time based on weekday. Areas only show midpoint when actually different from the effective default.
- **Fix slider button gap**: Removed flex:1 and width:100% so buttons sit next to the track.

## 1.2.30
- **Area detail UI overhaul**: Slider up/down buttons closer to track (gap 6px → 2px). Section renamed to "Brightness" (was "Brightness & Lights"). "Curve" → "Circadian curve". "Per-Light" → "Lights". Brightness cascade simplified: shows Circadian curve, Adjustments (net, expandable), Area Brightness. Detail rows collapse by default. New "Controls" section with Feedback light dropdown moved from Lights.

## 1.2.29
- **Auto on/off UI polish**: Reduced days-to-offset/time vertical spacing. Schedule 2 header left-aligned with closer spacing to its time box. Override link text "set override" → "set". Remove link "- remove schedule" → "- remove schedule 2". Auto-off next time shows tomorrow's schedule when today is suppressed by untouched guard (instead of blank).

## 1.2.28
- **Sun dimming hint on step_up bounce**: When step_up hits the circadian curve ceiling AND sun dimming is active, shows a toast hint: "Circadian curve at max — use bright up to override sun dimming". Only fires when all three conditions are true (at limit, trying up, sun_bright_factor < 1.0). Switch handler logs the hint. Area detail page shows a 4-second toast.

## 1.2.25
- **Area detail slider hero values**: Reduced from 1.4rem to 1.1rem (prevents Wake wrapping on mobile). Section labels and hero values now span full column width (slider + buttons). Fixed upper extreme labels ("britelite", "brightest", "coolest") getting covered by thumb — broken CSS selector from earlier refactor.
- **Merge Lights into Brightness section**: Section renamed to "Brightness & Lights". Cascade renamed: "Circadian" → "Curve" (demoted from primary), "Adjustments" → "Area Adjustments", "Final" → "Area Brightness" (stays primary). Lights content (feedback light + per-light filters) moved into brightness card under "Per-Light" sub-header. Separate Lights card removed.

## 1.2.24
- **Suppress auto-off timer when untouched guard would block**: When `auto_off_only_untouched` is enabled and the user has interacted since auto-on fired, `next_auto_off` returns null in the API. Home page and area detail page no longer show a countdown for an auto-off that won't fire.

## 1.2.23
- **Fix fade completion brightness snap**: Fade lerp was using purpose ratios from the actual area state (e.g., nitelite's amplified filter ratios) instead of the target preset's ratios. At completion, ratios snapped to the target's natural ratios causing a visible brightness dip. Now uses target pipeline's purpose ratios throughout the fade for seamless handoff.

## 1.2.22
- **Fix fade target using stale frozen hour**: `compute_fade_target` used the actual area's frozen_at hour for the pipeline context, even for unfrozen targets like circadian. When fading from nitelite (frozen at 3am), the circadian target was computed at 3am (curve minimum) instead of current time — producing the same values as the start. Now uses current time for unfrozen targets.

## 1.2.21
- **Fix auto-on/off firing on save**: `clear_auto_fired_for` now re-marks as fired if trigger time already passed today (uses same `_resolve_auto_time` as the scheduler). Removed redundant mark logic from webserver save handler. Prevents catch-up fire when configuring schedules.
- **Home page zone/area styling**: Zone phase label aligned with area slider right edge. Reduced bed/wake text size (zone 0.9rem, area 0.82rem) — color/opacity provides prominence. Status row left-aligned with slider.

## 1.2.20
- **Fade tick diagnostic**: Added logging to identify why fade tick updates weren't firing. Fixed stale start brightness when fading from off (used last_sent_brightness from before lights turned off instead of 0).

## 1.2.19
- **Fade redesign**: Smooth lerp between any two lighting states (off/circadian/nitelite/britelite). Fast tick drives fade updates every 5s with transition=5s for visually continuous fades. Captures start brightness + kelvin at fade start. Target computed synthetically each tick (circadian tracks live curve). Cancel bakes in current position via set_position so user actions work from there. Fade-out lerps to 0 then turns off.
- **Home page bed/wake prominence**: Zone and area phase labels (Wake/Bed time) made more prominent (~1.0rem, higher opacity). Zone phase label moved from centered-under-name to right-aligned matching area slider position. Zone labels slightly larger than area labels for hierarchy.
- **Home page status row**: Left-aligned with slider (16px indent) instead of area name.

## 1.2.17
- **Fix long-press repeat interval**: Interval now measures step-to-step (not end-to-start). Subtracts delivery time from next sleep so steps fire at the configured rate regardless of how long ZHA delivery takes.

## 1.2.16
- **Fix Hue dimmer zombie repeats after release**: Cluster 8 "stop" (release signal) was being filtered by the Hue duplicate-press filter. Dimming continued 3-4s after button release until the slower cluster 64512 long_release arrived. Now "stop" events pass through the filter.
- **Coalesce rapid switch actions**: Per-switch depth-1 queue with cumulative steps. When ZHA delivery is slow and actions queue up, intermediate actions are merged into one delivery with accumulated step count. Works for step_up/down, bright_up/down, color_up/down, and rapid short presses.
- **Skip identical user-action deliveries**: When pipeline output matches last-sent values (e.g., at curve limit), skip ZHA delivery for user actions. Periodic tick (30s + 3s catch-up) always sends to catch missed calls.

## 1.2.15
- **Fix step_down sun cooling not yielding (multi-area reach path)**: `_compute_pipeline_for_area` (used by reach dispatch in `lights_toggle_multiple` and `_send_via_reach_or_fallback`) used pipeline's precomputed branch, which silently skipped `sun_color_reduction`. Multi-area step-down kept full daylight cooling applied, so lights stayed cold during the day even after stepping down.
- **A+C refactor**: Introduced single `build_pipeline_context_for_area` builder in primitives.py — one source of truth for constructing PipelineContext from area state. Replaced inline context building in `update_lights_in_circadian_mode`, `lights_toggle_multiple`, and `_send_via_reach_or_fallback`. Future pipeline factors only need to be added in one place.
- **Rename `sun_color_reduction` → `sun_cooling_strength`** (semantic flip: 1.0 = full sun cooling, 0.0 = fully overridden by user step-down). Variable renamed in pipeline.py, brain.py (`_apply_solar_rules`, `calculate_color_at_hour`, `calculate_lighting`), and area.html. Cleaned up residual `shift_ratio` comments.

## 1.2.14
- **Fix toggle-on ignoring brightness_sensitivity (complete)**: Both `send_light` dict path AND `_compute_pipeline_for_area` (used by toggle-on reach dispatch) were using `get_zone_config_for_area` (rhythm-only, missing globals). Now both use `get_effective_config_for_area`. v1.2.13 only fixed `send_light` but toggle goes through `_compute_pipeline_for_area`.

## 1.2.13
- **Fix toggle-on ignoring brightness_sensitivity**: `send_light` dict path used `get_zone_config_for_area` (rhythm-only) instead of `get_effective_config_for_area` (includes globals like brightness_sensitivity). Lights turned on dimmer than periodic tick would correct to.

## 1.2.12
- **Auto On/Off spacing fixes**: Days left-aligned under radios (not centered), more vertical space between radios and days, reduced excess spacing below days/offset. Label vertical alignment tuned.

## 1.2.11
- **Auto On/Off layout overhaul**: All fields (Light, Time, Fade, Trigger, Override, Untouched) use unified left-aligned label rows at same hierarchy. Time section has inline radios with shared day buttons that stay in place across source changes. Offset and custom time input swap in the same position. Schedule 2 has "- remove schedule" link. Override moved to bottom.

## 1.2.10
- **Fix color slider not updating chart/sliders**: Frontend `applySolarRule` now matches backend — slider-originated color overrides are applied as direct additive CCT shift instead of incorrectly adjusting solar rule targets.
- **Auto On/Off redesign**: Light preset selector (Circadian/Nitelite/Britelite) at top of Auto On. Renamed "Source" to "Time". Override link moved below time, hidden when auto is off. Custom schedules show single schedule with "+ add schedule" link for second. Default fade changed to 5 min.

## 1.2.6
- **Fix chart override decay**: Override now correctly shows decay within the phase it was set, and 0 for hours beyond the phase boundary. Fixes override appearing only in current phase.
- **Fix adjusted wake/bed lines on chart**: Uses `midpoint_to_time` for accurate time calculation (matching lite API). Lines shift correctly when midpoint is stepped.
- **Remove sun_bright from chart**: Graph shows total room light (curve × area_factor + overrides), not dimmed artificial light.

## 1.2.3
- **Area detail page redesign**: Three unified vertical sliders (Circadian/Brightness/Color) with hero value headers (Bed/Wake time, brightness %, kelvin K). Removed horizontal banner slider and brightness/kelvin from header. Circadian slider has step up/down buttons + britelite/nitelite links.
- **CT compensation fix**: Uses actual delivered kelvin (api_kelvin) instead of reconstructed value. Applied per-purpose after filter multiplier, matching backend pipeline order.
- **Dimming row**: Added dim_factor to API and brightness cascade display as "Dimming" (always visible).
- **Chart shows actual conditions**: Brightness now includes sun_bright reduction (estimated per hour from sun angle + current weather), area_factor, and brightness override with decay projection. Color includes sun_color_reduction (shift_ratio) and color override with decay.

## 1.2.2
- **All delivery through pipeline**: Replaced all `_send_light_add_override_boost` calls with `update_lights_in_circadian_mode` (full pipeline). Fixes CT brightness compensation not applying when color slider changes kelvin. Deleted `_send_light_add_override_boost`. Every light delivery now goes through the pipeline consistently.

## 1.2.1
- **Fix circadian slider space mismatch**: Circadian slider thumb shows actual brightness (post-pipeline) but was sending values in curve space, causing large jumps when area_factor or sun_bright reduce brightness. Now converts actual-brightness position to curve position by undoing pipeline factors before sending. Fixes both area detail page slider and home page set_circadian.

## 1.2.0
- **Step/slide simplification**: Circadian stepping and sliding now use a single midpoint for both brightness and color (no more separate brightness_mid/color_mid divergence). Eliminated color_override from stepping entirely — sun color adjustment is instead linearly reduced based on how far the user steps down (shift_ratio). Deleted `circadian_adjust` P1/P2/P3 engine, `calculate_step`, `calculate_bright_step`, zone step/bright functions. Step buttons now delegate to `set_position(mode="step")`. ~1350 lines removed.

## 1.1.23
- **Fix phase midpoint display**: Home page now shows effective wake/bed time (accounting for configured wake/bed brightness) instead of raw sigmoid midpoint. Added `midpoint_to_time()` reverse computation in brain.py.

## 1.1.21
- **Remove pill containers from action buttons**: Toggle buttons (power, circadian, freeze, boost) keep dark pill background. Action buttons (reset, step up/down, glo up/down/reset, full send) rendered without pill container. Applies to home page area cards, zone headers, and area detail page.

## 1.1.20
- **Sticky zone headers via JS**: Scroll listener clones active zone header to fixed position at top. Works in HA ingress iframe where CSS sticky fails. Reverted CSS sticky and html overflow-y.

## 1.1.18
- **Fix zone dot placement**: Dot now inline with zone name (not below it).

## 1.1.17
- **Fix mismatch dot false positives**: Per-field tolerances (mid/frozen: 0.05, brightness_override: 1, color_override: 10). Fixes red dots from color_override recalibration drift. Zone mismatch dot moved next to zone name. Removed diagnostic logging. Fixed sticky zone headers (removed position:relative on zone-group).

## 1.1.13
- **Sticky zone headers**: Zone headers stick to top of viewport while scrolling through their areas.
- **Simplified sorting**: Replaced three-option sort (on/off, your order, a-z) with a single `on · off` toggle pill. Toggle on = group by on/off, toggle off = user's zone ordering. Removed a-z sort.
- **Zone header style**: Phase midpoint (Wake/Bed) now title case, larger, more prominent — matches area card styling.

## 1.1.12
- **Card polish**: Fix auto-schedule showing wrong next event (display_offset vs fire_offset comparison bug). Remove "rhythm zone" text from zone header — show phase midpoint (Wake/Bed) instead with slightly more prominence. Phase midpoint on area cards aligns with slider end. Compact row padding (2px top/bottom).

## 1.1.11
- **Home page area card redesign**: Phase midpoint (Wake/Bed time) shown on zone headers and area cards (areas only show when they differ from zone default). Status indicators (auto schedule, motion, boost, freeze, fade) moved to dedicated 3rd row that hides when empty. Up/down buttons enlarged (28×28). Auto schedule icon changed to ⏰▲/⏰▼ to differentiate from fade arrows.
- **2-step phase 1+2 detailed logging**: Both phases now log target entity, brightness, kelvin, and direction. Phase 2 skip cases log reason. All gated behind log_periodic.

## 1.1.9
- **Consolidate brightness/color button and slider paths**: `brightness_up`/`brightness_down` and `color_up`/`color_down` now compute a target value and delegate to `set_position`, sharing the same override logic as sliders. Deleted dead midpoint-based `bright_up`/`bright_down` methods (~210 lines removed). Four independent override implementations reduced to two (`set_position` brightness + color). `set_position` gains `_send_command` parameter for reach batching.

## 1.1.8
- **Fix slider override accumulation**: `set_position` brightness mode now accumulates onto existing override instead of replacing it. Previously, each slider drag computed delta from current brightness but stored it as the total override, so successive drags would snap back toward the base curve.

## 1.1.7
- **Area brightness as first-class pipeline concept**: Pipeline now computes `area_brightness` (rhythm × sun_bright × area_factor + override + boost × fade × dim) as an explicit step before per-purpose splits. Purpose brightness derives from area_brightness × filter_multiplier. Fixes slider snap-back bug where `set_position` recomputed brightness independently (missing override, boost, fade, dim), causing the delta to be wrong. `set_position` now reads `last_sent_brightness` from cache. Removed ~90 lines of dead fallback code from `_deliver_filtered`. Eliminated the "without purpose" pipeline path — all areas go through purposes (Standard as default).

## 1.1.6
- **Motion warning through pipeline**: Warning dim now uses `dim_factor` in area state (post-compute multiplier in pipeline) instead of direct `_send_light` side-channel. Eliminates race condition where cancel + fast tick re-triggered warning within 30ms. Periodic tick no longer skips warned areas — pipeline naturally applies the dim. `dim_factor` is a generic multiplier for future use (energy saving, away mode, etc.).

## 1.1.5
- **Wire frontend to pipeline**: `/api/apply-light` (rhythm designer) now sends through `send_light` pipeline instead of inline filter/CT/dispatch (~100 lines removed). `/api/area-status` reads `actual_brightness` and `kelvin` from last-sent cache instead of recomputing (matches what pipeline delivered to lights).

## 1.1.4
- **Fix 2-step not detecting off→on**: `turn_off_lights` now marks all per-purpose states as `is_off=True`. Previously, the 2-step gate thought lights were still on at their last-sent brightness, causing brightness delta to fall below threshold and skipping 2-step on large CT shifts (e.g., nitelite→britelite).

## 1.1.3
- **Fix Standard purpose missing override/boost**: Pipeline's `_group_by_purpose` now always includes implicit "Standard" purpose for unassigned lights. Previously, lights defaulting to Standard at delivery time were computed without brightness_override or boost, causing them to stay at base brightness while other purposes responded correctly.

## 1.1.2
- **Fix silent delivery logging**: All primitive callers of `update_lights_in_circadian_mode` now pass `log_periodic=True` so per-purpose delivery is visible in logs (brightness_step, color_step, circadian_adjust, glo_reset, etc.).

## 1.1.1
- **Reach rebuild**: `_send_via_reach` replaces `_try_reach_turn_on` — uses `pipeline.compute()` instead of inline computation, greedy set cover (largest reach first), direction-aware 2-step with configured transition. Merged `_send_step_via_reach_or_fallback` + `_send_bright_via_reach_or_fallback` into single `_send_via_reach_or_fallback`. Added `_compute_pipeline_for_area` helper for multi-area pipeline computation.

## 1.1.0
- **Pipeline v1.1: single computation engine + clean delivery API.** All light paths now flow through `pipeline.compute()`. Renamed: `turn_on_lights_circadian` → `send_light`, `_dispatch_fast_path` → `_deliver_fast`, `_turn_on_lights_filtered` → `_deliver_filtered`, `_apply_lighting` → `_send_light`, `_apply_circadian_lighting` → `_send_light_add_override_boost`. Deleted outer 2-step (`_apply_lighting_turn_on`, `_apply_lighting_turn_on_multiple`) — inner 2-step handles all off→on and CT shift scenarios. Deleted unused `_apply_step_result`, `_apply_color_only`. Net -290 lines.

## 1.0.287
- **2-step direction-aware phases**: When dimming, phase 1 dims to target (keeps old color), phase 2 changes color at dim level. When brightening, phase 1 sets color at low brightness, phase 2 ramps up. Both phases now use configured transition speed (no more instant `transition=0` jumps).

## 1.0.286
- **Retire "NL" terminology**: Rename all `nl_factor` → `sun_bright_factor`, `_compute_nl_factor` → `_compute_sun_bright_factor`, `nl_exposure` → `sun_exposure` across all Python, HTML, and test files. Comments and log strings updated. Zero logic changes.

## 1.0.285
- **Pipeline re-architecture Phase 2**: All callers (primitives, motion, boost, step, etc.) now compute via `pipeline.compute()`. Added precomputed curve support to pipeline — callers that already computed base values skip `calculate_lighting`. Legacy inline NL/override/boost/filter/CT computation in `turn_on_lights_circadian` replaced with pipeline. 7 new precomputed tests. Zero changes to primitives.py.

## 1.0.284
- **Pipeline re-architecture Phase 1**: Periodic tick now computes via `pipeline.compute()` — NL, filters, CT comp, override, boost all computed once. Extracted `_dispatch_fast_path` helper. Added `pipeline_result` param to `turn_on_lights_circadian` and `precomputed_purposes` to `_turn_on_lights_filtered` to skip redundant re-computation. Fade-in uses pipeline `fade_factor`; fade-out uses post-compute override. 4 new fade tests.

## 1.0.283
- **Pipeline naming cleanup**: Rename `natural_exposure` → `sun_exposure`, `outdoor_normalized` → `sun_intensity`, `nl_factor` → `sun_bright_factor` in new pipeline module.

## 1.0.282
- **Pipeline re-architecture Phase 0**: Add `pipeline.py` (unified compute function), `delivery.py` (thin wrapper), and 21 unit tests. No entry points wired yet — zero risk scaffolding for incremental migration.

## 1.0.281
- **Remove 2-step debug logs**: Clean up all `[2-step]` INFO-level debug logging from filtered path. Error handlers retained with simplified messages.

## 1.0.266
- **Settings page slider styling**: Added full slider CSS (track fill/empty contrast, bigger handles) to settings page. Weather condition and light purpose sliders now match all other pages. Added fill-pct tracking for dynamic sliders.
- **Fix auto on/off fade slider fill**: Fade slider now updates fill-pct on input, so the filled portion tracks the handle position correctly.

## 1.0.270
- **Fix 2-step phase 2 executing immediately**: Phase 2 tasks were built with `asyncio.create_task()` which starts the coroutine immediately when created — not when gathered. Phase 2 commands were sent during wave 1, not after the delay. Now rebuilds and sends phase 2 commands fresh after the delay.

## 1.0.265
- **Remove 2-step debug logging**: Cleaned up temporary INFO/DEBUG logs from the 2-step investigation.

## 1.0.264
- **Fix 2-step never firing in filtered path**: `set_last_sent_kelvin` was called in `turn_on_lights_circadian` BEFORE passing to `_turn_on_lights_filtered`, overwriting the previous kelvin. The 2-step check then saw zero CT delta (target == just-written value) and always skipped. Now saves `prev_kelvin` before updating and passes it to the 2-step check.

## 1.0.259
- **Rhythm zone chart toolbar**: Wake 2/Bed 2 toggles and weather conditions dropdown now on same line (toggles left, conditions right). Saves vertical space.

## 1.0.258
- **Slider styling overhaul**: All range sliders across 4 pages (home, area detail, rhythm design, tune) now have stronger fill/empty contrast (50% vs 12% opacity), thicker track (4px), and bigger handles (30×18px, was 24×14px). Consistent look across all pages.

## 1.0.257
- **Fix 2-step phase 1 still sending OFF**: The `skip_off_threshold` override set `should_off = False` but the OFF send code was in the same `if` block and ran anyway. Split into two separate `if should_off` checks so the override actually prevents the OFF command.

## 1.0.256
- **Fix 2-step skipping purposes below off threshold**: During 2-step phase 1 (at 1% brightness), purposes like "Standard no nitelite" calculated below the off threshold and were skipped — no color pre-set. Bulbs then turned on at their last remembered color (e.g. 500K red from nitelite) in phase 2 and ignored the color command. Now forces a 1% color pre-set for these purposes in phase 1. Also added missing `skip_off_threshold=True` to single-area turn-on phase 1.

## 1.0.255
- **Unified 2-step brightness threshold**: New "Brightness threshold" setting under Zigbee Improvements → 2-step color arc reduction (default 15%). Applied consistently across all 4 code paths: per-area turn-on, batch turn-on, reach group, and `turn_on_lights_circadian`. Off→on transitions below threshold skip 2-step (e.g. nitelite at 1%). Existing "Two-step delay" moved into same subsection.

## 1.0.254
- **Reach 2-step requires brightness delta**: For already-on lights, reach 2-step now requires ≥15% brightness change in addition to CT delta ≥ threshold. Matches `turn_on_lights_circadian` logic. Color-only changes (color_up/down, set_position color) no longer trigger false 2-step.

## 1.0.253
- **Smart reach group 2-step**: Reach groups now do proper 2-step matching the per-area pipeline logic. Off→on: phase 1 at 1%. Already on: phase 1 at current brightness (color shifts at current level, then brightness transitions). If current states differ across areas in a candidate reach, falls back to per-area control (each area gets individual smart 2-step). 2-step and direct commands run in parallel for non-blocking sends.

## 1.0.252
- **Fix reach groups not updating state**: Reach group commands now update `last_sent_kelvin` and per-purpose state (`set_last_sent_purpose`) after sending. Previously reach groups bypassed all state tracking, causing stale CT values that triggered false 2-step on subsequent commands (step_down, glo_down, etc.).
- **Reach 2-step only on turn-on**: Added `is_turn_on` parameter to `_try_reach_turn_on`. Only the `lights_toggle_multiple` caller passes `True`. Step/bright callers skip 2-step entirely since lights are already on.

## 1.0.251
- **Rhythm zone time buttons bigger**: Increased padding and font size, added "min" labels (-30 min, -5 min, +5 min, +30 min). Now button also taller.
- **Battery filter on controls page**: When Battery 4th field is selected, filter dropdown offers: Has battery, < 10%, < 20%, < 30%, < 40%, < 50%, No battery.

## 1.0.250
- **Rhythm zone page: weather dropdown on own line**: Full width on mobile instead of cramped next to date slider. "Current:" prefix hidden when collapsed (shows just condition + percentage), shown when dropdown is open.

## 1.0.249
- **Controls page polish**: Cheatsheet link styled as subtle underlined link with arrow (not a page title). Low battery red dot threshold lowered from ≤20% to <10%. Device count shown in Name column header — e.g. "Name (47)".

## 1.0.248
- **Fix battery not showing on controls page**: `get_controls` was missing `battery` field in response dict — `_fetch_ha_controls` collected it but `get_controls` never passed it through. One-line fix. Removed diagnostic logging.

## 1.0.247
- **Battery debug logging**: Removed name-matching hack. Added diagnostic logs to trace why battery entities aren't linking to devices via entity_registry.

## 1.0.246
- **Battery detection: cached_states fallback scan**: If entity_registry doesn't link a battery sensor to the device, scans cached_states by device name pattern as a last resort. Adds debug logging for battery discovery.
- **Control detail toolbar cleanup**: Removed "Type" (already in subtitle). Last action now shows date/time on first line, action indented below. Copy uses textarea fallback first (works in HA ingress iframe).

## 1.0.245
- **Last action time filters**: New filter dropdown when "Last action" 4th field is selected: Last hour, Today, Past week, Not in past week, Not in past month, Never. "Not in past week/month" excludes items with no last action (use "Never" for those).
- **Fix battery detection**: Now checks device_class from cached_states as fallback. Consolidated sensor entity scanning (battery + illuminance in one block).

## 1.0.244
- **Fix battery not showing**: Battery entity detection now also checks `device_class: battery` (not just `_battery` in entity_id). Covers ZHA/Hue sensors that use device_class instead of naming convention.
- **Swap Cheatsheet and 4th field positions**: Cheatsheet link now on left, 4th field dropdown on right.

## 1.0.243
- **Two-step delay default increased**: 2 → 5 tenths (200ms → 500ms). Gives ZHA lights more time to process color before brightness transition.

## 1.0.242
- **Control detail page redesign**: Subtitle now shows "Area · Type" (moved from header-right and toolbar menu). Last activity moved to toolbar menu (top, muted). Toolbar menu now includes: last action, type, model, battery (color-coded), Copy IEEE, Copy ID, and Reset. Location badge removed from header (cleaner layout with ⋮ alone).

## 1.0.241
- **Battery level on controls page**: New "Battery" option in the 4th field selector. Shows battery percentage color-coded (red ≤20%, yellow ≤50%, grey above). Low battery indicator (red dot) always visible after control name regardless of 4th field selection.
- **Controls page cleanup**: Moved 4th field selector to page header. Removed zone filter and active-only filter. Made "Cheatsheet" link more prominent (white text).
- **Backend: battery entity detection**: `_fetch_ha_controls` now scans for `sensor.*_battery` entities and reads cached battery level for each control device.

## 1.0.240
- **Preserve last_sent_kelvin through state reset**: `last_sent_kelvin` is a physical bulb fact, not runtime state — now survives `reset_area()` and `reset_all_areas()`. Eliminates false 2-step triggers after glo_reset/glo_down. Truly fresh areas (never controlled, kelvin=None) skip 2-step since there's no prior color to arc from.

## 1.0.239
- **Fix reach 2-step not triggering**: The is_on check was always True because state is set to on before reach turn-on runs. Now checks last_sent_kelvin directly regardless of on/off state. Also triggers 2-step when last_sent_kelvin is None (after state reset).

## 1.0.238
- **Add 2-step to reach group turn-on**: Reach groups now use 2-step turn-on (set color at 1% first, pause, then transition to target brightness) when any area in the reach has a CT delta above threshold. Prevents visible color arc when turning on lights that were at a different color temperature. Same CT threshold setting as per-area 2-step.

## 1.0.237
- **Fix reach feedback when lights are off at night**: When lights are off and NL=0, reach feedback now flashes on at bounce percentage with circadian color then off (same pattern as alert bounce). Previously sent turn_off→turn_off which was invisible. Daytime NL-aware flash-up-to-255 path unchanged. Also resets off-confirm counter after flashing so periodic tick catches stuck-on lights.

## 1.0.236
- **Alert bounce color only for off lights**: Circadian xy_color included only when bouncing was_off lights (so they flash at correct color, not white). Was_on lights bounce brightness only, preserving their current color.

## 1.0.235
- **Fix alert bounce leaving lights on/white**: Three fixes: (1) Use internal state (`state.get_is_on`) instead of HA cached_states for was_on detection — prevents stale HA state from treating off lights as on. (2) Include circadian xy_color in was_off turn_on calls so lights bounce at correct color, not cool white. (3) Reset off-confirm counter after was_off bounce so periodic tick re-sends turn_off commands.
- **Concurrent alert bounces**: Multiple alert areas now run via `asyncio.gather` instead of sequentially. 3 areas × 3 bounces drops from ~16s to ~5.5s.

## 1.0.234
- **Fix motion timer not extending on continued motion**: ZHA `on_with_timed_off` events from motion sensors were being silently ignored (anti-triple-trigger guard). Now wired to `_handle_zha_motion_event` which extends the on_off timer. Fixes lights turning off while motion is still active.

## 1.0.233
- **Fix alert bounce not firing**: Target dict passed to HA contained extra keys (filter_name, area_id alongside entity_id) causing silent call rejection. Now strips to clean entity_id only, matching the fix in _bounce_at_limit.

## 1.0.232
- **Alert bounce debug logging**: Added per-phase logging (target entity, brightness, phase 1/2) to diagnose alert bounce visibility issues.

## 1.0.231
- **Alert mode for motion sensors**: New 4th mode option ("Alert") on motion sensor scopes. Performs brightness bounces on the area's feedback target when motion is detected. Parameters: intensity (Low/Med/High — 1x/2x/3x bounce percentage) and count (number of bounces, default 3). Works independently of on_off/on_only — create separate scopes for the same area to combine alert + power behavior.
- **Settings: bounce label rework**: "Limit bounce" renamed to "Bounce" (shared by limit bounce and alert). Sub-fields renamed: "Small bounce (max bright)", "Small bounce (min bright)". Speed split into "Limit bounce speed" and new "Alert bounce speed" (default 1.0s). All sub-fields grey out when bounce is disabled.
- **Lights-off alert**: When lights are off, alert flashes on at the bounce percentage then off (scaled by intensity multiplier).

## 1.0.230
- **Area row buttons: tighter pill shapes**: Reset button and stacked step buttons each get their own pill background that traces their height. Reset pill is shorter, step pill is taller. 1px gap between them reads as one group.

## 1.0.229
- **Fix circadian slider mode**: Circadian slider now uses `set_circadian` (same as area detail page) instead of `set_position` with mode `step`. Maps slider pct to target brightness using area's bMin/bMax range.
- **Live row color preview while dragging**: Row background updates in real-time during slider drag. In circadian mode, shows both brightness and color changes (using slider preview data). In brightness mode, shows brightness change with current color.
- **Remove color from slider options**: Slider dropdown now only offers Brightness and Circadian.

## 1.0.228
- **Configurable homepage controls**: New "Homepage" subsection in Settings → App. Slider mode (Brightness/Circadian/Color) and up/down button mode (Circadian/Brightness/Color) are now user-selectable. Defaults: slider=Brightness, buttons=Circadian.
- **Fix reset button aspect ratio**: Reset buttons back to 28×28 square. Stacked step chevrons remain 28×20 for better touch targets.

## 1.0.227
- **Bigger area row buttons**: Reset button now 28×42px (fills vertical space). Stacked step buttons 28×20px each. Better touch targets on mobile.

## 1.0.226
- **Home page area row: 3 buttons in same space**: Reset button (glo_down) + stacked step up/down chevrons. Container padding tightened from 4px to 2px. Stacked buttons are 13px tall each with compact SVGs.

## 1.0.225
- **Fix auto schedule pill showing wrong next event**: When both auto_on and auto_off had the same day offset (e.g. both tomorrow), auto_on always won the tie. Now compares chronologically using `offset * 24 + decimal_hour`, so tomorrow 6am auto_off correctly beats tomorrow 7pm auto_on.
- **Cheatsheet "Reset to defaults" toned down**: Changed from red-bordered button to small muted text link, left-aligned away from Save/Cancel.

## 1.0.224
- **Home page slider = brightness only**: Thumb drag now calls `set_position` with `mode: 'brightness'` (adjusts brightness override without moving along color curve). Previously used `set_circadian` which changed both brightness and color.
- **Home page area buttons = step up/down**: Right-side buttons changed from GloUp/GloDown to Step Up/Step Down (move along circadian curve — brighter+cooler / dimmer+warmer).
- **Zone header reset = full reset**: Reset button now does `glozone_reset_full` (reset zone + push to all areas). Removed GlozoneDown button from zone header.
- **Cheatsheet Cancel always enabled**: Cancel button no longer greyed out when no changes — always available to exit edit mode.

## 1.0.223
- **Fix power button staying lit on mobile (take 2)**: Added `-webkit-tap-highlight-color: transparent` and `outline: none` to toggle buttons. Blur button after optimistic toggle to release focus state. Fixes iOS sticky focus making the button appear lit after tapping off.

## 1.0.222
- **Fix home page sliders**: Handle is now draggable (grab and slide), but track is not tappable (no accidental brightness changes from touching the bar). Handle enlarged from 30×16px to 44×19px within the existing track space (no padding/margin changes).

## 1.0.221
- **Cheatsheet edit flow**: Edit and Copy are now simple text links. Edit link hidden in edit mode — exit via Cancel (returns to cheatsheet, discards changes) or Save (returns to cheatsheet). Removed toggle button styling.

## 1.0.220
- **"Any motion" shows selected by default**: Empty `trigger_entities` (= no filter, triggers on anything) now renders with the "Any motion" chip visually selected, matching actual behavior. Selecting "Any motion" stores as empty list. Picking a specific type (Person, Pet, etc.) transitions from "any" to that specific filter. Deselecting all specifics reverts to "any".

## 1.0.219
- **Fix trigger entity selections not persisting**: The control detail page's areas→scopes grouping path was dropping `trigger_entities` from loaded configs. Selections (Person, Pet, Vehicle, etc.) now correctly round-trip through save/reload.

## 1.0.218
- **Feedback cues settings hierarchy**: Reach daytime threshold indented under reach feedback and greyed out when disabled. Limit bounce max/min indented under limit bounce and greyed out when disabled. New "Freeze feedback" checkbox controls whether freeze/unfreeze shows visual dip cue; freeze off rise speed indented underneath and greyed out when disabled.

## 1.0.217
- **Remove dead "Reach adjustment learn mode" setting**: Was never wired up — `_is_reach_learn_mode()` defined but never called. Removed from settings UI, backend defaults, and config keys.

## 1.0.216
- **"Add control" moved to bottom of controls list**: Keeps filter bar clean; "Cheatsheet" link replaces "Switch Map" in filter bar.
- **Rename Switch Map → Cheatsheet**: Page title, link, and `<title>` tag updated. Cheatsheet/Edit toggle collapsed to just an "Edit" button (always in cheatsheet mode unless editing).
- **"Confirm zone pushes" defaults to on**: New installs and unset configs now default to showing confirmation dialogs.
- **Fix power button stuck orange on mobile**: Wrapped `:hover` styles in `@media (hover: hover)` so iOS sticky-hover doesn't keep the accent border after tapping power off.
- **Home page sliders are display-only**: Removed touch/pointer interaction to prevent accidental brightness changes. Sliders are now 3px taller and 20px wider (reduced margin) for better visibility.

## 1.0.215
- **Opt-in allowlist for controls discovery**: Replaced heuristic entity scanning (has_motion, has_battery, has_trigger, etc.) with curated manufacturer/model allowlists. Only verified devices auto-appear on the controls page — everything else via "Add control source". Eliminates false positives (phones, shades, Sonos, etc.).
- **New allowlist dicts**: MOTION_SENSOR_MODELS (Hue SML001-004, SwitchBot Hub 3, Lafaer), CONTACT_SENSOR_MODELS (Hue SOC001), CAMERA_MODELS (Eufy T8162, T8214 with trigger patterns).
- **Removed dismissed controls**: No longer needed with allowlist gating discovery. Stale/unsupported items get a delete option instead.
- **"Motion/camera" category label**: Filter dropdown now reads "Motion/camera" to reflect camera support.
- **Removed debug device dump**: Startup device dump and /api/debug/devices endpoint removed (allowlist is built).

## 1.0.210
- **Dismiss controls permanently**: Clicking X on unsupported/stale devices now adds them to a persisted dismissed list. HA discovery won't re-surface them. Dismissed IDs saved in switches_config.json.

## 1.0.209
- **Fix trigger selection: "Any motion" no longer auto-selects when picking Person/Pet/Vehicle**. Selection checking now uses category's own keywords, not the expanded "all" set. Toggling "Any motion" on still correctly adds all presence entities and greys out specific types.
- **Fix "show all" collapsing on selection**: Expanded state is now preserved across re-renders. Toggle text changes to "hide others" when expanded. Auto-expands if any uncategorized entity is selected.

## 1.0.208
- **Categorized trigger selector**: Per-reach trigger chips organized into Presence (Any motion, Person, Pet, Vehicle) and Events (Package, Doorbell). "Any motion" greys out specific presence types when selected. Uncategorized entities available via "show all" toggle.
- **Dismiss X for unsupported devices**: Same remove button that stale devices have, now also shown on unsupported devices in the controls list.

## 1.0.207
- **Fix switches showing as stale**: Restored `has_battery and not has_light` for zha/hue/matter integrations only (ZHA remotes need this). WiFi battery devices (Sonos, shades) still filtered out.
- **Presence sensor support**: Re-added `has_presence` for non-mobile_app integrations. Real presence sensors (Aqara FP2, ESPHome) auto-appear; phones/iPads (mobile_app integration) stay filtered.

## 1.0.206
- **Tighter controls list filter**: Removed `has_presence` (was catching phones/iPads) and `has_battery and not has_light` (was catching Sonos, shades, temp meters). Cameras with person/pet detection still auto-appear via `has_trigger`.
- **Trigger selector on auto-discovered devices**: Control detail page now shows the per-reach trigger entity selector for any device with binary_sensors, not just manually added ones. Cameras that auto-appear on the controls list now show their triggers when you click in.

## 1.0.205
- **Camera trigger UI**: Controls list page: "Add control" button with device search modal — browse HA devices, pick trigger entities, add as control source. Control detail page: per-reach trigger entity selector (chip-style) for devices with trigger_entities. Only shown for manually added devices; existing motion sensors unchanged.

## 1.0.204
- **Camera/rich trigger backend**: Full backend for non-ZHA control sources (cameras, ESPHome, etc.):
  - Data model: `trigger_entities` field on both `MotionAreaConfig` (per-scope) and `MotionSensorConfig` (device-level). Empty = backward compatible.
  - Widened device discovery: `_fetch_ha_controls` now accepts any integration, not just zha/hue/matter. Cameras and other devices with binary_sensors now appear.
  - Entity classification: recognizes `_person`, `_human`, `_pet`, `_vehicle`, `_ringing`, `_package` etc. as trigger entities.
  - New API: `GET /api/devices/search?q=` for device picker, `POST /api/controls/add` for manual device addition.
  - Event wiring: manually added trigger entities registered in `motion_sensor_ids` cache. Scope-level `trigger_entities` filter in `_handle_motion_event`.
  - Save path: `configure_control` reads `trigger_entities` per scope and computes device-level union.

## 1.0.203
- **New solar exposure steps**: 0, 0.25, 0.40, 0.60, 0.75, 0.90, 1.00, 1.25, 1.60, 2.00 (10 stops). Existing saved values auto-migrate to closest step. Updated on both area detail and tune pages.
- **Fix exposure display rounding**: Was `.toFixed(1)` which showed 0.25 as "0.3". Now `.toFixed(2)`.
- **Prominent slider readouts**: Solar exposure and room balance label+value text changed from muted to full text color on both area detail and tune pages.
- **Fix area detail wake/bed label**: Reverted "User-adjusted brightness*" back to "Adjusted wake" / "Adjusted bed" (no asterisk). The asterisk footnote change was for the tune page override legend only.

## 1.0.202
- **Fix double bounce on step_up/down too**: Same issue as bright_up/down — single-area step_up/step_down also had both primitive and caller bouncing. Now skip_bounce=True for all switch-dispatched step/bright actions; caller's `_feedback_cue` is the single bounce source. Color was already correct (caller bounce guarded by `if multi:`).

## 1.0.201
- **Fix double bounce on bright_up/down**: Single-area bright_up/down was bouncing twice — once inside `_brightness_step` and again from the caller's `_feedback_cue`. Now always passes `skip_bounce=True` to the primitive and lets the caller handle bounce via `_feedback_cue` (consistent with multi-area path). Reverted unnecessary phase 2 sleep from v1.0.200.

## 1.0.200
- **Fix bounce wobble**: Periodic tick was released immediately after phase 2 dispatch, before the 0.3s transition completed on the bulb. The tick then sent a competing brightness command mid-transition, causing extra visual pulses. Now holds the defer for the transition duration after phase 2.

## 1.0.199
- **Fix feedback fallback targeting all area lights**: When a purpose has multiple lights but no ZHA group (e.g. Hue hub lights), the bounce now targets each light in the purpose individually instead of the entire area. Eliminates cross-purpose bounce bleed.

## 1.0.198
- **Fix bounce hitting all lights instead of feedback target**: When the feedback purpose has only 1 light (no ZHA group), the bounce fallback was targeting the entire area. Now resolves to the individual light entity for single-light purposes.

## 1.0.197
- **Feedback selector: section groups**: Dropdown now uses `<optgroup>` labels "Purposes" and "Individual lights" for clearer organization.

## 1.0.196
- **Feedback light selector in area details**: Dropdown at top of Lights card lets you choose which purpose or specific light receives visual feedback cues (bounce, reach flash). Defaults to "Auto" which picks the most popular purpose dynamically. Saves on change, no save button needed.

## 1.0.195
- **Fix bright_down false bounce when override is large**: When override was +9.9 (from bright_up) and one step down would cross the floor, the clamp engaged and the code treated it as "at limit" — bouncing instead of applying the partial step. Now only bounces if the clamped value didn't actually move from the current override. So bright_up → bright_down correctly undoes the override.

## 1.0.194
- **Debug: brightness override limit logging**: Added raw_override, set_at, decayed value, base, and scaled_base to the brightness limit/clamped log lines to diagnose the bright_down false-limit bug.

## 1.0.193
- **Home page: hide auto pill during fade**: During an active fade, only the fade pill is shown — the other type's auto pill is now also suppressed to avoid showing two pills.

## 1.0.192
- **Bulk purpose save**: New `/api/light-filters/bulk` endpoint accepts all changed filters for an area in a single request. Config is saved once, refreshed once, device sync runs once — instead of N times for N purpose changes. Updated both area detail page and tune page.

## 1.0.191
- **Fix auto schedule catch-up at phase change**: The noon descend phase crossing blanket-cleared all fired states, causing any auto_on that already fired this morning to re-fire (e.g. master turning on at noon). Now after clearing, immediately re-marks any schedules whose trigger time already passed today.

## 1.0.190
- **Fix solar rules missing on glo_reset, glo_down, preset apply, and toggle-on**: Four `calculate_lighting` calls were missing the `sun_times` parameter, so solar rules (e.g. Cool Day clamping CT to 5000K) weren't applied. The periodic tick 3 seconds later would correct it. Now all calls pass `sun_times`.

## 1.0.189
- **Fix bright_up/down 4x/5x not recognized**: Action dispatch in main.py had a hardcoded tuple that only included up to 3x. Added 4x and 5x.

## 1.0.188
- **Bright Up/Down 4x and 5x**: Added `bright_up_4`, `bright_up_5`, `bright_down_4`, `bright_down_5` to action dropdowns. Dynamic step count parsing in main.py already handles them.
- **New Hue 4-button default mapping**: On: 1x toggle, 2x cycle scope, 3x magic, hold full send. Up: 1x–5x bright_up 1–5x (1x when_off: nitelite), hold step_up (when_off: britelite). Down: mirror of up with bright_down/step_down (hold when_off: nitelite). Hue: 1x glo_reset, 2x glozone_reset_full, 3x magic, hold magic.

## 1.0.187
- **Fix custom time inputs not showing dirty state**: Added `oninput` alongside `onchange` on all 4 time inputs so save/cancel buttons appear immediately while typing, not just on blur.
- **Fix auto schedule catch-up on settings change**: Previously, catch-up prevention only ran when toggling the enabled switch. Now any auto schedule save (including auto-save on collapse) marks today's trigger as fired if the time already passed, preventing accidental immediate fire.

## 1.0.186
- **Fix live preview not updating**: Source radio, offset +/- buttons, and day toggles were calling `showResolvedAutoTime` directly instead of `onAutoFieldChanged`, so the header time never updated. Now all auto schedule controls route through `onAutoFieldChanged`.
- **Auto-save on collapse**: Auto schedule cards save dirty state when collapsed — no more hidden save buttons or lost changes on back navigation.
- **Fix fade indicator styling**: Moved from a button-like element in the header to a pill in the timer-status bar (matching freeze/boost presentation), with pulsing "▲ Fade in" / "▼ Fade out" text.
- **Optimistic button toggle**: Power and freeze buttons update immediately on click instead of waiting 500ms for server refresh.
- **Fix trigger mode and untouched not saving**: Backend save handler now accepts `auto_on_trigger_mode` and `auto_off_only_untouched` fields.
- **Broader user action tracking**: Added `mark_user_action` to `bright_up`, `bright_down`, `color_up`, `color_down`, `freeze_toggle`, and `bright_boost` for proper "only if untouched" detection.

## 1.0.185
- **Fix "only if untouched" detection**: Previous check only looked for brightness override/boost/midpoint shift, missing the most common interaction — turning lights on/off. Now tracks `last_user_action_at` timestamp in area state, set on any user-initiated action (toggle, on, off, step, boost, reset). Auto-off compares this against auto-on fire timestamp.

## 1.0.184
- **Auto schedule defaults**: Auto On defaults to sunset, Auto Off defaults to sunrise (was reversed).
- **Fade slider non-linear steps**: 0, 1, 2, 3, 5, 10, 15, 30 minutes (was linear 0-60 in 5-min steps).
- **Auto On trigger mode dropdown**: Replaces "Skip if already brighter" checkbox with 3-option dropdown: Always, Skip if already brighter, Skip if on at all. Backward-compatible with old boolean setting.
- **Auto Off "only if untouched"**: New checkbox skips auto-off if user has interacted since auto-on (brightness override, boost, or midpoint shift). Useful for vacation mode.

## 1.0.183
- **Fix on_only + boost turning off lights**: When an area appeared in both an `on_only` reach and an `on_off` boost reach, the merged mode correctly picked `on_only`, but the boost timer still had `started_from_off=True`. When boost expired after 60s, it turned lights off — defeating the `on_only` intent. Now `motion_on_only` overrides `started_from_off=False` after setting boost, so boost expiry just removes the extra brightness instead of powering off.

## 1.0.182
- **Fade pill shows trigger time**: Home page fade pill now shows the time the fade started (e.g. "▲ 7:06a") instead of brightness percentage, matching the normal auto pill format.

## 1.0.181
- **Fix home page fade pill showing 0%**: Was displaying `fade_progress` (a 0–1 fraction) rounded to integer. Now shows `actual_brightness` instead, matching what the area detail page displays.

## 1.0.180
- **Fix fade not cancelled on power toggle**: `lights_toggle_multiple` did its own inline state management without calling `cancel_fade()`, so toggling power during an active fade left the fade state running. Now cancels fade in both the turn-off and turn-on branches.
- **Fix fade not cancelled on circadian_off**: `circadian_off()` cleared boost and motion but not fade state, so disabling Circadian during a fade left the fade ghost-running. Now calls `cancel_fade()`.

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
