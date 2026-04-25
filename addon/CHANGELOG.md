<!-- https://developers.home-assistant.io/docs/add-ons/presentation#keeping-a-changelog -->

## 1.2.158
- **Sleep card: Pattern dropdown promoted into the expanded header; Wake/Bed sub-section bodies indented 20px** — restructures the Sleep card so the pattern picker is a first-class control accessible from the card header rather than a body row that competed visually with Wake/Bed for top-of-card real estate. Two coordinated changes. (1) **Pattern in header (expanded only).** Old layout had `Pattern` + `<select id="activity-preset" class="rhythm-select">` as the first row inside `#rhythm-sleep-body` — visible only after expanding the card, took its own row above Wake, semantically a meta-setting (configures the bed/wake defaults) but visually leveled with the body sections. New layout splits the card title and val cells into collapsed/expanded variants. Title: `<span class="rhythm-sleep-title-collapsed">Sleep</span>` / `<span class="rhythm-sleep-title-expanded">Sleep pattern:</span>` toggle via `.rhythm-card.is-open` selectors — collapsed reads "Sleep", expanded reads "Sleep pattern:". Right-anchored val: existing `#rhythm-sleep-val` (`9:00p – 7:00a` window) hides on `.is-open`; a new `.rhythm-sleep-pattern-val` wrapper containing the moved `<select id="activity-preset">` shows in its place. Select restyled inline with `.rhythm-pattern-inline-select`: `background: transparent; border: none; appearance: none` strips the native dropdown chrome, custom SVG chevron (10×10 inline data URI) lives on the right via `background-image`, font matches the card title (`var(--font-card-title)`, weight 600, `var(--text)` color) so the selected option text reads as a clickable continuation of the title — "Sleep pattern: **Adult ▾**" with the value being the visible interactive surface. Clicking the value opens the native dropdown — keyboard accessibility, system styling, and platform-conventional pick UX come for free. `onclick="event.stopPropagation()"` on the select prevents the header's `toggleRhythmCard` from firing when the user opens the dropdown (otherwise tapping the dropdown would also collapse the card). All existing JS bindings (`document.getElementById('activity-preset')` reads in `renderUIFromConfig` and `change` handler in DOMContentLoaded) work unchanged because the element ID is preserved — the select element just lives in the header now instead of the body. Body Pattern row deleted (no duplicate select needed). (2) **Wake / Bed sub-section bodies indented 20px.** Old layout: `.sub-section-header` (the "Wake" / "Bed" title row) and `.sub-section-body` (the day-pills + time rows + brightness/speed rows) shared the same left edge — section titles were horizontally indistinguishable from the rows beneath them, so the eye couldn't easily parse "where does Wake start, where does Bed start." Added `.sub-section-body { padding-left: 20px }` — body content shifts right 20px while the section header stays anchored at the parent's left edge. Wake and Bed now read as two prominent sections with clearly subordinate content beneath each. 20px chosen as the smallest amount that visually registers as an indent without eating the horizontal space the day-pill block (186px wide) and 210px label column need. The internal `.tune-control-row` 210px col-1 + value col-2 grid geometry is preserved; the whole grid simply shifts right by 20px. The slider rows (`.tune-slider-row` with its own 44px left padding) shift along with the rest of the body content — net left offset of 64px from sub-section header is acceptable since slider tracks were already deeply indented relative to the labels above them. No JS changes for the indent; pure CSS scoped to `.sub-section-body` (used only by Wake and Bed sub-sections — `.bri-sub-section` in the Brightness card uses a different class and is unaffected).

## 1.2.157
- **Color-temp checkbox repositioned, info-icon glyph + tooltip text-transform fixed, slider-release no longer closes row, Brightness/Speed row spacing matches time rows** — four targeted fixes from the v1.2.156 review. (1) **Color-temp `Night warming` / `Sun cooling` headers restructured.** Old layout: `.color-rule-stack-label` was a `grid-template-columns: 140px 1fr` grid with a single child `.color-rule-label-left` (flex of label + checkbox), so the entire label/checkbox combo lived in col 1 and col 2 was unused. Result: long labels like "Night warming" + the info-icon "I" were wrapping inside the 140px and pushing the checkbox down a row. New structure splits into two grid cells: `<label class="color-rule-label">` lives in col 1 (110px — same width as the rows below for clean vertical alignment), and a new `.color-rule-controls` flex wrapper holds the checkbox + info-icon together in col 2 (so the checkbox left-aligns with values like "1 hr before sunset" / "1.00: standard" in the rows below). The info-icon is now placed AFTER the checkbox (per spec) instead of inside the label glob. Tooltip clipping fix scoped to header info-icons: `.color-rule-stack-label .info-tooltip { left: auto; right: 0; transform: none }` — anchors the 280px tooltip to the icon's right edge so it extends leftward into the card body instead of off-edge. (2) **`.info-icon` glyph and `.info-tooltip` text rendered uppercase + letter-spaced.** Both elements live inside `<label class="color-rule-label">` which has `text-transform: uppercase` + `letter-spacing: 0.1em` — those properties cascade through the icon's "i" character and the tooltip's body text, so the circle showed "I" and the tooltip read like a header. Added `text-transform: none` and `letter-spacing: 0` resets directly on `.info-icon` and `.info-tooltip` rules so the cascade stops at the icon boundary regardless of which uppercase context contains them. (3) **Sub-section body unchecked state now greys out instead of hiding.** `syncColorRuleRows()` previously toggled `.is-hidden` on `#warm-night-body` / `#daylight-body` when the corresponding checkbox went off — body collapsed via `max-height: 0; opacity: 0` so the rows below disappeared. Per spec, the rows should stay visible (so users can see what's configured) but visibly inactive. Switched the toggle target to a new `.is-disabled` class with `opacity: 0.4; pointer-events: none` — fields stay laid out + readable, but interaction is blocked until the checkbox flips back on. (4) **`initAutoHideSliders()` no longer closes the row when the user releases the slider.** v1.2.156's tap-toggle (`wasOpen ? close : open`) had a regression: dragging a `<input type=range>` and releasing dispatches a synthetic `click` event whose target is the range input. The doc-level handler called `closest('.reveal-group')` which matches the same group that's currently open, read `wasOpen = true`, and closed the row mid-edit. Added an early return guard at the top of the listener: `if (e.target.tagName === 'INPUT' && e.target.type === 'range') return` — slider clicks fall through (the input handles its own value updates), nothing toggles. Same fix applied identically in `area.html`'s `initAutoHideSliders` so Auto On/Off Fade rows behave consistently. (5) **Sleep-card Brightness/Speed rows now have vertical breathing room matching the time rows above.** Day-pill rows are ~26px tall (24px circles + 2px margin-top). Brightness/Speed rows were just text — `.tune-control-row` default `padding: 4px 14px 2px 16px` made them ~16px tall, so the four-row stack felt visually unbalanced (top two breathy, bottom two cramped). Added `.sub-section-body .sleep-summary-row > .tune-control-row { padding-top: 10px; padding-bottom: 4px }` — bumps Brightness/Speed row total height to ~26px to match the day-pill rows. Doesn't affect the value column geometry (still 210px col-1 from v1.2.156), just the per-row vertical space.

## 1.2.156
- **Reveal-group toggle on second click + Sleep all-rows alignment + Sun response inline label** — three follow-up fixes spanning rhythm-design and area-details. (1) **Tap reveals slider; tap again closes.** Previously `initAutoHideSliders()` always added `is-revealing` to the clicked group — once a group was open, the only way to close it was to click a *different* reveal-group (which then opened that one) or click outside any group entirely. Counter-intuitive when the user wants to dismiss the slider they just opened: their natural instinct is to tap the row again, but that was a no-op (still revealing). Changed both rhythm-design.html and area.html handlers to read the clicked group's current state first (`wasOpen = rg.classList.contains('is-revealing')`), clear all *other* groups, then `rg.classList.toggle('is-revealing', !wasOpen)` — same group + already open → close; same group + closed → open; different group → open the new one and close others. Click outside any group → still closes everything (unchanged). Applies to all reveal-group instances on both pages: rhythm sleep time/brightness/speed rows, warm-night/cool-day Start/End/Fade/Sun-response rows, brightness Sun-response row, and area.html Auto card On/Off Fade rows. (2) **Sleep card all 4 rows in each sub-section now share a single left-aligned value column.** v1.2.153's fix only re-aligned Brightness/Speed rows (`.sleep-summary-row > .tune-control-row { grid-template-columns: 90px 1fr }`) — time rows above (Wake/Bed × primary/alt) kept the original `1fr auto` grid, so the time values "7:00a" / "8:00a" sat flush right at the card edge while "25%" / "8: snappy" sat left-aligned in the middle. Visual disconnect: the eye couldn't trace a clean column down the four rows. Per user direction, broadened the rule to scope the entire sub-section body: `.sub-section-body .tune-control-row { grid-template-columns: 210px 1fr; gap: 0 12px }` + `.sub-section-body .tune-control-row .tune-control-impact { text-align: left; min-width: 0 }`. The 210px col-1 width fits the day-pill block (7 × 24px + 6 × 3px = 186px) plus a ~24px buffer so col 2 starts "a bit after Sunday" — time values land left-aligned right after the Su pill, Brightness/Speed labels (~75px) leave whitespace within col 1 but their values land in the same col-2 column as the times. Now Wake's "7:00a", "8:00a", "25%", "8: snappy" all start at the same x-position; Bed mirrors the same. The per-row label+value pair stays tight (no big right-edge gap) AND the four rows align vertically. Dropped the now-redundant `.sleep-summary-row > .tune-control-row` rule. (3) **Brightness Sun response: SUN RESPONSE label moved inline with the value** — fixes the awkward "uppercase header on row 1, value right-aligned on row 2" layout from v1.2.154. Restructure: the `.bri-sub-section-header` div is gone; the `<label class="color-rule-label">Sun response</label>` (with info-icon) now lives inside `.tune-control-left` of the existing `.tune-control-row`, sitting flex-inline with the reset link. The `.tune-control-impact` ("1.00: standard") sits in col 2 of a `grid-template-columns: max-content 1fr` grid, left-aligned via `text-align: left`. Result: one row reads `SUN RESPONSE [i] reset    1.00: standard` — uppercase label retains visual weight (color-rule-label styling: muted, letter-spaced, uppercase — same as Night warming / Sun cooling sub-section labels in Color temp), value sits immediately to the right left-aligned, slider expands below on tap. The `.bri-sub-section { border-top: 1px solid var(--line) }` divider above the row preserves the visual separation from the min/max gradient (gives the section equal-weight presence without needing a standalone header row). Tightened wrapper padding from `padding-top: 14px` to `6px` since the row no longer needs breathing room above a separate header.

## 1.2.155
- **Area-details Auto card header: two-row stacked On/Off layout, hide inactive sides, drop "Off" placeholder** — three coordinated changes to the merged Auto-card header (`#auto-outer-next`). (1) **Layout switched from single-row inline to two-row stacked.** Previously: `On Sunset+30m • Off 11p` rendered horizontally with a `•` separator. The single row competed with the card title for horizontal space and was hard to scan when only one side was meaningful. Changed `.auto-outer-next` from `display: flex; gap: 6px` to `display: flex; flex-direction: column; align-items: flex-end; gap: 1px` — On lands above Off (since loop iteration order pushes 'on' first), both right-justified to mirror the existing header value-anchoring. The 1px row gap echoes the previous Sleep-card `.rhythm-sleep-summary` row spacing for visual consistency across cards (even though that specific Sleep layout was just consolidated to a single row in v1.2.154 — Auto retains the stacked form because On and Off carry distinct schedule semantics and can't be summarized into one combined string the way Sleep's bed→wake naturally does). (2) **Disabled sides no longer render at all.** Previously `formatMergedAutoSide` for a disabled type returned `<span>${label} —</span>` (e.g. `Off —`), and `updateMergedAutoHeader` always emitted both sides regardless of enabled state. Now `updateMergedAutoHeader` reads the `.enabled` flag returned by `formatMergedAutoSide` and only includes enabled sides in the rendered rows array. If only On is scheduled, only the On row appears; if only Off is scheduled, only the Off row. The `formatMergedAutoSide` disabled-case return shape is preserved (still `{enabled: false, html: ...}`) for safety, just no longer consumed — full removal can come in a later cleanup pass. (3) **Empty header instead of "Off" placeholder when both sides disabled.** Previously when neither `auto-on-enabled` nor `auto-off-enabled` was checked, the header rendered `<span class="auto-outer-off-label">Off</span>`. This collided semantically with the "Off" label that designates the Off schedule sub-card — users couldn't tell whether "Off" in the header meant "the entire Auto card is off" or "the Off schedule fires at this time." Now: when both sides are disabled, `rows` is empty and `el.innerHTML = ''` — header value chip simply doesn't render. The card title "Auto" alone communicates the card identity; the absence of stacked schedule lines communicates "no schedules active" without ambiguity. The expand affordance (chevron) remains so users can still open the card and configure schedules from the empty state. CSS rule `.auto-sched-card--auto.is-open .auto-outer-next { display: none }` already hides the merged header when the card is open (where users see the per-side cards instead) — unaffected.

## 1.2.154
- **Rhythm-design polish: color-temp renames + impact swap, sleep header consolidation, brightness card sub-section, multi-card open** — five-item UI sweep on the rhythm-design page. (1) **Color-temp section labels renamed**: "Warm night" → "Night warming", "Cool day" → "Sun cooling". DOM `<label>` text updates only — kept the underlying `warm-night-*` / `daylight-*` element IDs and config key names untouched (renaming the IDs would have rippled into webserver.py field validation, glozone.py RHYTHM_SETTINGS allowlist, primitives.py read paths, and any saved configs in users' /config dirs — out of scope for a UI label change). Tooltip copy unchanged because the descriptive content still applies regardless of the new noun. (2) **Color-temp Start/End impact ↔ slider-word swapped**: previously the always-visible impact (in collapsed `.tune-control-row`) showed `7:57 PM` (clock time) and the slider-word below the slider (visible when expanded) showed `1 hr before sunset` (natural-language offset). Inverted: collapsed view now shows `1 hr before sunset` / `at sunrise` (concept), expanded view shows `7:57 PM` (concrete time the user is editing toward). The collapsed natural-language form communicates intent at a glance — "this triggers an hour before sunset" is more legible than "7:57 PM" when scanning a configuration; the clock time becomes secondary detail surfaced on tap. Implementation: swapped which destinations `formatOffset()` and `fmt12()` write to in `updateOffsetDisplays()` and `updateSolarImpacts()` respectively. Fade impacts unchanged (still show `1 hr` / `2.5 hrs` collapsed). (3) **Cool day "Sun sensitivity" relabeled to "Sun response"** — verb form reads as "how the system responds to sun" rather than "how sensitive it is to sun." Same control, more directional language. ID `color-sensitivity` and config key `color_sensitivity` preserved (same scope-protection rationale as #1). (4) **Brightness card restructured into stacked sub-sections to give Sun response equal weight to the min/max gradient.** The min/max gradient is visually dominant — large color band, edge-to-edge, three-row vertical footprint with handles + labels + endpoint values — so a single-row sensitivity control beneath it (label + slider) read as a footnote regardless of full-width tweaks. Mirrored the Color-temp card's sub-section pattern: gradient stays at top (it's the "range" — already labeled by the card-val "1 – 91%"), then a `border-top: 1px solid var(--line)` + `padding-top: 14px` separator, then a `<label class="color-rule-label">SUN RESPONSE</label>` header (uppercase, muted, letter-spaced — same treatment as the "NIGHT WARMING" / "SUN COOLING" labels in Color temp), then the sensitivity slider beneath. The dedicated section header gives the control its own visual anchor — no longer reads as an addendum to the gradient. New CSS: `.bri-sub-section { margin-top: 18px; padding-top: 14px; border-top: 1px solid var(--line) }` + `.bri-sub-section-header { padding: 0 14px 4px 16px }`. Brightness card "Sun sensitivity" label inside the slider row dropped (the section header replaces it — duplicate label would be redundant); kept the `reset` link and `1.00: standard` impact text in the row. Added a tooltip to the new section header (`Sun response`info) explaining what high vs low sensitivity does. (5) **Sleep card header consolidated to single-row sleep window** like `9:00p – 7:00a`. Previously two stacked rows (`WAKE 25% 8:00a` / `BED 25% 10:30p`) competed with the card-title for visual prominence; the brightness % was rarely the answer to "when is the next sleep cycle?" Replaced with a single `.rhythm-card-val` showing bed → wake using phase-aware logic: when the user is awake (cursor-time within ascend phase), shows the upcoming sleep window (next bed → next wake); when asleep, shows the current sleep window (current bed → current wake — i.e. when they fell asleep → when they'll wake). Reused the existing `getSleepPhase()` + alt-day picking logic from `updateSleepSummary` but with `headerUseNext = (phase.bed === 'next')` shared across both endpoints — different from the inline summary's per-prefix phase, because the header treats bed+wake as one window with a unified phase. Sleep state itself is not annotated — per user direction, "if we're in sleep window, don't call that out." Old `.rhythm-sleep-summary` block kept in DOM with `display:none` so legacy ID references (`sleep-sum-wake-bri` etc., still written to in `updateSleepSummary`) don't NPE — full removal can come in a later cleanup pass. (6) **Rhythm cards no longer mutually exclusive — multiple can be open at once.** `toggleRhythmCard()` previously closed all `.rhythm-card.is-open` siblings before opening the clicked one (accordion). Removed the close-siblings loop; now just `card.classList.toggle('is-open')`. Lets users compare Sleep and Color settings side-by-side, or keep Brightness expanded while editing Sleep without losing context. No CSS changes needed — `.rhythm-card.is-open .rhythm-card-body { max-height: 1200px; opacity: 1 }` already operates per-card.

## 1.2.153
- **Label-value alignment pass: Sleep Brightness/Speed, warm-night/cool-day rows, and Brightness-card gradient width** — three alignment regressions surfaced by v1.2.152's UI sweep. (1) **Sleep Brightness/Speed label-value gap fix replaced with left-aligned value column.** v1.2.152's `.sleep-summary-row > .tune-control-row { max-width: 260px }` capped the row width so values floated leftward — but pulled them into mid-card while the time rows above (Wake/Bed) kept their values flush right at the card edge, so "25%" / "8: snappy" looked disconnected from "7:00a" / "8:00a". Reverted the max-width cap; replaced with a fixed label column: `.sleep-summary-row > .tune-control-row { grid-template-columns: 90px 1fr; gap: 0 12px }` plus `.tune-control-impact { text-align: left; min-width: 0 }`. Now "Brightness" + "Speed" labels share one ~90px column (fits widest of the two, "Brightness", with breathing room) and values sit in a left-aligned column right after — Wake and Bed sub-sections both render with the same column geometry. Time rows are left untouched: their `.day-indicators` chunk on the left needs the full row width (7 × 24px circles + gaps ≈ 186px) and the time value already feels naturally anchored at right; forcing them into the same fixed-column grid would either clip the days or push values too far left. Visual outcome: tight label-value pairs for Brightness/Speed, time rows continue to right-anchor — the eye reads them as two distinct row types, not a misaligned single type. (2) **Warm night + Cool day: 7 rows now share one label column.** Same problem: "Start" / "End" / "Fade" / "Sun sensitivity" labels were left-indented inside `.color-rule-stack-body` (22px padding) while values flushed right at the card edge — wide gap, labels and values disconnected. Both bodies are siblings under `.color-rule-grid`, so a single rule on `.color-rule-stack-body .reveal-group > .tune-control-row` covers all 7 rows: `grid-template-columns: 110px 1fr; gap: 0 12px` with `.tune-control-impact { text-align: left; min-width: 0 }`. 110px fits the widest label ("Sun sensitivity" — wider than "Color sensitivity" since it's used in both warm-night and cool-day sensitivity for consistency) with breathing room. Warm night's Start/End/Fade now align column-wise with cool day's Start/End/Fade/Sun sensitivity — values land at the same x-position regardless of which sub-card they're in. (3) **Brightness-card gradient slider narrowed to match label-row padding.** v1.2.152 made the sun-sensitivity slider full-width (`.brightness-sensitivity-group > .tune-slider-row { padding: 0 14px }`) to match the min/max gradient. But this exposed the inverse problem: the gradient (`.ct-gradient-wrap` direct child of `#rhythm-brightness-body`, no horizontal margin) bled to the card body's 14px-padded edges, while the Sun sensitivity label/value row sat inside `.tune-control-row`'s additional `padding: 4px 14px 2px 16px` — so the row was visibly inset 16px L / 14px R relative to the gradient. Picked option A (narrow the gradient) over option B (bleed the row): added `#rhythm-brightness-body > .ct-gradient-wrap { margin-left: 16px; margin-right: 14px }` to match `.tune-control-row` padding exactly. Gradient now spans the same horizontal range as the Sun sensitivity label/value row above/below it — left edge of gradient = left edge of "Sun sensitivity" label, right edge of gradient = right edge of "1.00: standard" value column. Three-element column read clean: gradient handles → label/value row → sensitivity slider, all sharing one width. Time rows in Sleep card preserve full-width because their day-indicators legitimately need the horizontal span (no change there). No JS changes; pure CSS pass scoped to three selectors.

## 1.2.152
- **Seven-item UI polish sweep: Auto dim-when-off restored, fade readout right-anchored, reveal-on-tap extended to warm-night/cool-day/brightness-sensitivity, Sleep card flattened, sub-card header live-projects edits pre-save** — bundled UX cleanup from visual regressions + gaps identified on area-details Auto card and rhythm-design Sleep/Brightness/Color cards. (1) **Auto sub-card dim-when-off was not firing.** v1.2.148 added `.auto-sched-card--sub.is-disabled > .auto-sched-body { opacity: 0.5 }` to fade the sub-card body when its enable toggle is off. But `.auto-sched-card.is-open .auto-sched-body { opacity: 1 }` (v1.2.137's outer expand/collapse rule) has the same specificity (0,2,1) and is defined later in the stylesheet — so it won override tie-break. When outer Auto was expanded (the only state where the sub-cards are visible to begin with), opacity was always forced back to 1 regardless of `.is-disabled`. Fixed by raising the disabled rule's specificity: `.auto-sched-card.is-open .auto-sched-card--sub.is-disabled > .auto-sched-body { opacity: 0.5 }` — now 0,4,1. (2) **Fade "5 min" readout landed under Tu/We day bubbles instead of anchored to the right edge.** The `.auto-fade-row` content flex container used default `justify-content: flex-start`. When the slider collapsed (`flex: 0 0 0` in `.reveal-group` collapsed state), the "5 min" value packed left next to the zero-width slider — visually floating mid-row, under the Tu/We day pills of the schedule row above. Added `.auto-fade-row .auto-sched-field-content { justify-content: flex-end }` — slider still fills free space when expanded (flex: 1 1 auto beats justify-content), and when collapsed the value snaps to the right edge, aligning vertically with the time-input above. (3) **Warm night + Cool day sliders now reveal-on-tap.** v1.2.150's reveal-group extension explicitly scoped out warm-night and daylight slider rows; scope miss corrected here. Wrapped each `.tune-control-row` + `.tune-slider-row` pair (warm-night-start/-end/-fade, daylight-start/-end/-fade, color-sensitivity) in `.reveal-group` so the sliders collapse by default and tap-to-reveal expands only the tapped row. The impact readouts ("1 hr after sunrise", "1.00: standard", etc.) remain the always-visible summary inside the control-row — users see every setting's current value without the slider column hogging vertical space. Brightness-card sun sensitivity also wrapped (carried class `.brightness-sensitivity-group` for the full-width override described below). (4) **Sleep card Brightness/Speed label-to-value gap compressed.** `.tune-control-row`'s `grid-template-columns: 1fr auto` was pushing the value ("25%") to the card's far-right edge while the label ("Brightness") lived at the indented column-left, leaving ~300px of visually unexplained whitespace between — on Safari especially (wider rendered gaps), the label and value read as disconnected. Added `.sleep-summary-row` class to the Brightness/Speed reveal-groups and a scoped rule `.sleep-summary-row > .tune-control-row { max-width: 260px }` — caps the grid width so the value floats left, close enough to the label that the eye connects them without a visual leader. Time rows retain their full-width layout since the day-indicators column legitimately fills the horizontal span. (5) **Brightness-card sun sensitivity was narrower than min/max gradient — now full-width, and reveal-on-tap.** The min/max slider uses `.ct-gradient-wrap` which spans the full card body width. The sensitivity slider inherited the default `.tune-slider-row { max-width: 75% }` — visually smaller, which subconsciously suggested it was a lesser/secondary control. Added scoped override on the wrapped reveal-group: `.brightness-sensitivity-group > .tune-slider-row { max-width: none; padding-left: 14px; padding-right: 14px }` + `input[type=range] { width: 100% }`. Same width as min/max now. Reveal-on-tap wrap ensures default collapsed state matches other per-zone sliders — the "1.00: standard" impact readout stays visible as the summary. (6) **Sleep card flattened: inner Wake/Bed chevron-collapse removed; single visible body with divider.** The Sleep card had two layers of expand/collapse — the outer rhythm-card chevron + inner per-sub-section (`.sub-section.is-open`) chevrons on Wake and Bed. User had to click Sleep open, then Wake open, then Bed open to see all settings — three clicks to reach something as basic as "what time does bed start." Mirrored the v1.2.137 Auto-card consolidation: dropped the inner chevron, made Wake+Bed always-visible side-by-side inside the expanded Sleep card body, separated by a horizontal rule. CSS: removed `.sub-section-chevron` rule, removed `.sub-section-body { max-height: 0; opacity: 0 }` collapse + `.sub-section.is-open .sub-section-body { max-height: 800px; opacity: 1 }` reveal, removed `#rhythm-sleep-body .sub-section.is-open .sub-section-val { display: none }` (summary-hiding on open). Added `#rhythm-sleep-body .sub-section + .sub-section { margin-top: 14px; padding-top: 14px; border-top: 1px solid var(--line) }` — standard "+ next sibling" pattern gives exactly one divider between Wake and Bed (first sub-section has no top border). HTML: removed `onclick="toggleSubSection(...)"` from both headers, removed the `.sub-section-chevron` span, removed the `.sub-section-val` span (was cleared to empty by `updateSubSectionSummaries` on every edit anyway — dead after chevron-collapse dropped). JS: removed `toggleSubSection()` and `updateSubSectionSummaries()` functions and the caller site that followed `initAllDayIndicatorClicks`. Sleep card is now taller by default (since both groups render at once), but matches Auto-card info density and saves two clicks. (7) **Auto sub-section header time now updates live during edits, pre-save.** Previously `#auto-{on,off}-next` (the resolved-time chip in each sub-card header, e.g. "6:19p Fri") was bound to `_cachedNextAuto[type]` which is populated by the `/api/area-status` backend call — so it only refreshed with saved settings. Changing the sunset offset slider or flipping source to Sunrise or typing a new custom time left the header showing the pre-edit value until save. Added `projectAutoHeaderFromUI(type)`: for sun-based modes, computes `base + offset/60` using `getAutoSunBase()` (which reads from cached sun times or falls back to 6a/6p); for custom, parses the time-1 input as HH:MM. `updateAutoHeaderText` now checks `isAutoDirty(type)` first — if dirty, writes the projection; if clean, falls back to `_cachedNextAuto`. `onAutoFieldChanged` now calls `updateAutoHeaderText` directly (before the server refresh) so the header updates instantly on every field change. Merged outer header (`formatMergedAutoSide`) gets the same treatment: when clock-mode + dirty, uses the projection instead of the cached backend time, keeping sub-card header and merged header in sync as the user edits. Day-suffix is dropped from the projected form (custom-mode day routing would require duplicating backend day-selection logic client-side — not worth the complexity for a preview; day suffix returns once the user saves and the backend round-trip completes).

## 1.2.151
- **`brightness_sensitivity` relocated from home-level global to per-zone rhythm setting; home-level Sun multiplier card removed** — third pass of the rhythm/area-details convergence plan. The setting previously lived as a single top-level `brightness_sensitivity` in `config.yaml` — a global multiplier that scaled every area's sun-driven brightness pullback identically. But different zones (e.g. a sunlit living room with 4.0 sensitivity vs a windowless hallway with 0.0) have fundamentally different sun-dimming needs, and the home-level control made that impossible to express without replumbing per-area exposure around the global. Moved to `RHYTHM_SETTINGS` in `glozone.py`: added `brightness_sensitivity` to the set (and removed it from `GLOBAL_SETTINGS`), with default `1.0` in `get_zone_config`'s defaults block. Pipeline resolution via `get_effective_config_for_area` already overlays per-zone RHYTHM_SETTINGS over globals into the flat `Config` dict, so `Config.from_dict()` now picks up the zone-specific sensitivity automatically — no new Config field needed. `primitives.py` area-status endpoint switched from `glozone.get_config().get("brightness_sensitivity", 5.0)` to `glozone.get_zone_config_for_area(area_id).get("brightness_sensitivity", 1.0)` (and updated two call sites to reuse the already-fetched `rhythm_cfg` where available). One-shot inheritance added at the top of `load_config` (runs BEFORE the generic RHYTHM_SETTINGS-to-first-zone migration so the value lands in every zone, not just the first): read any lingering top-level `brightness_sensitivity`, `setdefault` it into every zone, let the normal migration loop strip it from top level. Idempotent on subsequent loads (`get` returns None when key is absent, block no-ops). `webserver.py` zone-states endpoint at `:1670` now includes `brightness_sensitivity` in each zone's payload so tune.html per-zone/per-area brightness previews pick up their own zone's sensitivity — previously read off `tuneData.brightness_sensitivity` (the global). **Home-level Sun multiplier card fully removed from tune.html**: dropped the card HTML template (~17 lines), removed the global sensitivity slider + change event filter entry, removed the `sensitivityStep` tracking across `captureTuneSnapshot` / `isTuneDirty` / `saveAllTuneChanges` / `cancelAllTuneChanges`, removed the snap-and-save-on-load block for `brightness_sensitivity`, and replaced `toggleSensitivityBody` / `getSunMultiplier` / `fmtSunMultiplier` / `updateSunMultiplierCard` with a simplified `updateSunInfoPanel` that retains only the sun info panel logic (angle / conditions / intensity) — then renamed all callers via sed. Added a `zoneSensitivity(zn)` helper that reads `zoneStates?.[zn]?.brightness_sensitivity ?? 1.0`; per-zone rendering in `renderTune` / `rebuildTuneLightValues` / `buildLightsSection` / sort callback all read through it. **Zone-level control added to rhythm-design.html Brightness card body** (chosen over a standalone top-level card — sensitivity is semantically a brightness modifier, and nesting it inside the card whose graph already shows its effect keeps the cognitive load tight). Added `.tune-control-row` + `.tune-slider-row` pair mirroring the existing `color_sensitivity` control in the Color card: label "Sun sensitivity", 0–8 integer range using the 9-step `SENSITIVITY_STEPS` array (None / Minimal / Low / Medium / Moderate / Standard / High / Strong / Maximum → multipliers 0.00 / 0.10 / 0.25 / 0.50 / 0.75 / 1.00 / 1.25 / 1.50 / 2.00). Wired into `BRIGHTNESS_FIELDS` for dirty detection, cancel revert (via existing `cancelBrightnessChanges` → `revertFields`), and save (`saveZoneSettings` payload). Impact text uses the `updateOffsetDisplays` path (already called on every input). `reset-brightness-sensitivity` uses the standard `tune-control-reset` + `data-default="5"` pattern so it auto-joins the loaded-value capture + dirty-tracking loops in DOMContentLoaded. **CSS rules for the now-dead Sun multiplier card (`.tune-sensitivity-card/body/math/chevron/header/title/section-label/slider-row`) left in place** — cleanup deferred because `.tune-sensitivity-slider` is shared with `.ct-sensitivity-slider` via a combined selector and disentangling that is out-of-scope churn. Behavioral impact: users with a non-default global `brightness_sensitivity` find that value automatically seeded into every zone on first load after upgrade; each zone is then independently adjustable from its own rhythm page. Users who never touched the global get `1.0` across all zones (unchanged from prior default-after-standardization behavior).

## 1.2.150
- **Sleep card restructured to match Auto card's day-bubble pattern + reveal-on-tap sliders across rhythm/area-details** — second pass of the rhythm/area-details convergence plan. Three coordinated changes. (1) **Sleep card Primary/Secondary labels dropped, day-indicators promoted from under the slider into the left side of the control row.** Old structure had each time block as `.tune-control-row` (label "Time"/"1 - Primary"/"2 - Secondary" + time impact) followed by `.tune-slider-row` (slider + `.day-indicators` below it). That pushed the day-bubbles under the slider handle, made "Primary"/"Secondary" carry a hierarchy implication that doesn't actually exist (both are peers — alt is just "the other days"), and meant the day-indicator row was only reachable after scrolling past the slider. New structure: `.day-indicators` moved into `.tune-control-row > .tune-control-left` so the M–Su buttons sit to the left of the time impact, always visible regardless of slider state. Primary/alt blocks wrap in `.reveal-group`, slider drops into a nested `.tune-slider-row` that collapses by default. When no alt exists (`.sleep-time-group.no-alt`) the second block hides via existing CSS; when the user deselects a day, the alt block auto-appears as before — no label change needed because there are no labels anymore. Dropped the `#wake-primary-label` / `#wake-alt-label` / `#bed-primary-label` / `#bed-alt-label` element IDs and the `updateSleepSummary` lines that toggled their text between "Time"/"1 - Primary"/"2 - Secondary". (2) **Reveal-on-tap pattern added to all rhythm-page Sleep card sliders** — wake time, bed time, brightness, speed on both blocks. Each `.tune-control-row` + `.tune-slider-row` pair is wrapped in `.reveal-group`; CSS collapses the slider row to `max-height: 0; opacity: 0` with a 0.25s transition unless the group carries `.is-revealing`. A single document-level click handler `initAutoHideSliders()` reads `e.target.closest('.reveal-group')` and swaps the `is-revealing` class to the tapped group, collapsing all others. Clicking outside any group collapses everything. Scope explicitly excludes color temp (too much information density — the gradient + min/max needs to stay fully visible) and brightness min/max (pair-symmetry with color temp min/max). Tune card sliders also excluded — those are cross-home comparison controls where the slider itself is the information. (3) **Same reveal-on-tap applied to Auto On/Off Fade sliders in area.html** — the Fade row previously showed slider + value permanently; now the slider collapses to `width: 0; opacity: 0` while `.auto-sched-fade-val` (the "5 min" readout) stays visible, so users see what the setting is without the control hogging horizontal space. Tapping anywhere on the row expands the slider. Implemented via `.auto-fade-row` class + `flex: 0 0 0 / pointer-events: none` on the collapsed state, `flex: 1 1 auto` on `.is-revealing`. Same `initAutoHideSliders()` helper added to area.html's DOMContentLoaded init after `initAutoOuterState`. Also folded rhythm-design.html into the v1.2.149 tokenization sweep (71 font-size declarations → 8 font tokens, completing the miss from last ship). Behavioral notes: day-indicators stay fully interactive in the collapsed state — tap a day-bubble to toggle without opening the slider; tap anywhere else on the row to reveal. Phase-range clamp (`updateWakeBedSliderConstraints`) unaffected — element IDs `#wake-time` and `#bed-time` preserved, constraint updates still fire on pattern change.

## 1.2.149
- **Typography tokens introduced, ~40 ad-hoc font sizes collapsed to 8 design tokens** — first pass of the broader rhythm/area-details UI convergence work (see plan for v1.2.150 Sleep card + v1.2.151 brightness_sensitivity relocation). The two page stylesheets (`area.html` + `tune.html`) had accumulated ~40 distinct `rem` font-sizes: common tiers like 0.85rem and 0.8rem appeared dozens of times while one-offs like 0.48rem, 0.52rem, 0.54rem, 0.56rem, 0.58rem, 0.62rem, 0.68rem, 0.72rem, 0.78rem, 0.82rem, 0.88rem, 1.05rem, 1.15rem, 1.2rem, 1.4rem, 1.8rem each appeared once or twice — most drift was uncoordinated tuning over many ships with no semantic rationale. Defined eight tokens in `:root` of both files: `--font-hero: 1.4rem`, `--font-display: 1.1rem`, `--font-card-title: 0.95rem`, `--font-value: 0.85rem`, `--font-body: 0.78rem`, `--font-muted: 0.7rem`, `--font-caps: 0.65rem`, `--font-micro: 0.55rem`. Swept all 209 font-size declarations (119 in area.html, 90 in tune.html) — both CSS rules and inline `style=""` attributes — to `var(--font-*)` per the nearest-token mapping (1.8→hero, 1.2/1.15→display, 1.0→card-title, 0.9/0.88/0.82→value, 0.8/0.75/0.72→body, 0.68→muted, 0.62/0.6→caps, 0.58/0.56/0.54/0.52/0.48→micro). Aggressive consolidation chosen over preserving every existing value because the sub-0.05rem differences were not design decisions — nobody was going to defend 0.82 vs 0.85 vs 0.88 as three distinct semantic tiers. Expect some minor visual shifts (the outdoor panel hero number shrinks from 1.8rem to 1.4rem, inline day-pill text grows from 0.48→0.55, uppercase micro headers tighten from 0.58-0.62 toward 0.55-0.65 bands). Zero behavioral change — this is a cosmetic foundation pass. Next two ships (Sleep card convergence, brightness_sensitivity relocation) will consume these tokens directly instead of minting new ad-hoc values. Left three px-based font-sizes alone (`.tune-card: 13px` base, `.tune-col-header: 11px`, one `10px` inline Plotly hover hint) — those are outside the rem scale and tokenizing them can wait.

## 1.2.148
- **Auto sub-section body fades when its toggle is off** — disabled On/Off sub-section previously looked identical to an enabled one, with the only cue being the toggle position itself. Users opening a busy Auto card with only one side on had to scan every row to infer which block was active. Added `.auto-sched-card--sub.is-disabled > .auto-sched-body { opacity: 0.5 }` with a 0.2s transition, paired with a helper `updateAutoSubCardEnabledUI(type)` that toggles the `is-disabled` class on `#auto-{on,off}-card` based on the checkbox state. Called from `onAutoToggleChanged` (live) and from the post-settings-load path (initial render). Header + toggle stay full strength so the enable affordance is always visually reachable; inputs in the body remain interactive so users can pre-configure before flipping the toggle on. Chosen over re-introducing per-sub-section expand/collapse (which would have brought back the is-open state the v1.2.137 merge consolidated into a single outer card) — fade is stateless and doesn't add collapse machinery.
- **Override link moved to sub-header, clear vs set unified into one element** — Override lived in a dedicated body row (`#auto-{on,off}-override-row` at `area.html:1296,1385`) labeled "Override" with a "set" link, plus a separate tiny "clear override" link stacked under the resolved-time in the sub-header right column. Two separate DOM elements for the same concept, and the body row was eating a whole field-row worth of vertical space even when empty. Collapsed into a single `#auto-{on,off}-override-link` in the header right column that flips text between `set override` and `clear override` based on state, with onclick re-assigned in `updateAutoOverrideIndicator` (opens popup vs calls `clearAutoOverride`). Dropped both body rows and the now-unused `.auto-sched-override-link` CSS class. To preserve the "modified" visual signal that the old "clear override" text provided: resolved-time `#auto-{on,off}-next` now gets a `.has-override` class when active, tinting it brand orange `rgba(254,172,96,0.95)` via new `.auto-sched-next.has-override` rule. Kept the full word "override" in the link text (at 0.65rem, same size as the old clear link) rather than shortening to just "set"/"clear" — the word disambiguates the action at-a-glance without costing vertical space since the link lives in unused horizontal space next to the time. Added a small `_autoOverrideState` cache so callers that don't know hasOverride (toggle flips at `onAutoToggleChanged`, card expand/collapse at `toggleAutoSchedule`) read the last-known value instead of falsely reverting to "set override" until the next settings fetch — the old code had the same pre-existing gap but it was masked because the clear link defaulted to hidden.
- **Tune section: Cancel now resets slider track fill AND re-renders chart; graph responds to Sun-exposure slider in real time** — three related fixes to the area-details Tune card. (1) `cancelBrightnessChanges` at `area.html:4482` was setting `lumenSlider.value` / `solarSlider.value` back to snapshot without calling `updateSliderFill` on them, so the `--fill-pct` CSS custom property (which drives the left-whitish / right-greyish track gradient via `linear-gradient(to right, var(--track-fill) var(--fill-pct), var(--track-empty) var(--fill-pct))`) stayed at the dragged position — handle snapped back but the color-split didn't. Added `updateSliderFill` calls for both sliders after the value reset. (2) Same function didn't re-render the chart, so canceling a drag left the Adjust graph showing the unsaved slider values. Added `renderMiniChartForArea(selectedArea.area_id)` at the end. Reset-per-slider links (`#tune-reset-lumen`, `#tune-reset-solar`) already had both calls; this brings the main Cancel button to parity. (3) Room balance slider already affected the chart in real time via `areaState.area_factor` flowing into `calcMiniBrightness` (multiplies the curve). Sun exposure didn't, because the chart's sun-dimming derives from `sunTimes.sunBrightFactorNow` — a single backend-computed scalar tied to the saved exposure. Added a client-side projection: since backend formula is `sbf = max(0, 1 − exposure × intensity × sensitivity)`, we recover `intensity × sensitivity = (1 − backend_sbf) / saved_exposure` from the last backend reading, then reapply with live exposure → `live_sbf`. Stored on `areaState.live_sbf` and read first in `renderMiniChart`'s sbfNow sourcing (`state.live_sbf ?? areaLive.sun_bright_factor ?? sunTimes.sunBrightFactorNow ?? 1.0`). Only runs when saved exposure > 0 and slider has moved off its saved position (edge case: saved exposure = 0 means we can't recover the intensity product — chart stays at no-dimming until save reveals the true value; acceptable since in this case the user hasn't configured sun dimming at all, so the preview showing the curve-without-dimming is the correct "nothing's changing yet" read). Polling pauses during slider drag via `sliderInteracting`, so the projected live_sbf doesn't get stomped by fresh backend fetches until the user releases.

## 1.2.147
- **Override row restored on Auto sub-sections** — the "Override" row (the `set` link that opens the per-trigger override popup) stopped rendering for both Auto On and Auto Off. Code was all intact — HTML rows at `area.html:1296` (`auto-on-override-row`) and `:1385` (`auto-off-override-row`), popup CSS `.auto-override-popover` at 728–742, handlers `openAutoOverridePopup` at 6156 and `clearAutoOverride` at 6302. The visibility guard in `updateAutoOverrideIndicator` gated display on `bodyVisible = document.getElementById('auto-' + type + '-card')?.classList.contains('is-open')`, reading `is-open` off the sub-card. That check made sense when each sub-section had its own expand/collapse (pre-1.2.137), but v1.2.137/138 merged On+Off into a single outer `auto-outer-card` and the sub-cards stopped toggling `is-open` — so `bodyVisible` has been permanently `false` since then, unconditionally hiding both override rows. Dropped the `bodyVisible` term from the display guard — the row now shows whenever `enabled && !hasOverride`, which inherits visibility naturally from the outer Auto card's collapse state (when outer is collapsed the whole body is hidden by its parent `max-height: 0`; when open, the sub-card bodies render; no additional check needed).

## 1.2.146
- **Moon crescent geometry fixed — vertically symmetric now** — v1.2.145's mask approach (outer `cx=11 cy=12 r=9` + cutout `cx=16 cy=11 r=8`) had the two centers at different `cy` values, which meant the cutout's vertical extent (y=3–19) stopped short of the outer disc's bottom (y=3–21). Result: the cutout only carved the TOP-right of the outer disc, leaving a thin wedge at top and the full 6-unit-high bottom cap of the outer disc intact below y=19. Visually that reads as "top half of a crescent got clipped" because the shape below the clip line is a full fat disc-bottom instead of the tapered second half of a crescent. Moved both circles to `cy=12` (outer `cx=10 cy=12 r=9`, cutout `cx=15 cy=12 r=9`), same radius so intersections land at `(12.5, 3.35)` and `(12.5, 20.65)` — the horns are now vertically symmetric about y=12 and the crescent has the classic mirror-symmetric C shape. Dropped the 1-unit tilt from v1.2.145; tilt is a cosmetic choice that was fighting with the asymmetric-geometry bug and masking it.

## 1.2.145
- **Moon SVG switched from evenodd-fill path to mask-based crescent** — the v1.2.142 path (`M 12 2 A 10 10 0 1 1 12.01 2 Z M 15 5 A 7 7 0 1 1 15.01 5 Z` with `fill-rule: evenodd`) was mathematically well-defined (non-degenerate arcs via the 0.01-unit close-offset, inner disc fully contained in outer) but rendered as a pinched/clipped-looking shape in Plotly's SVG-as-image embedding at the small size the chart uses (~40px). Replaced with a mask composite: a solid `<circle cx="11" cy="12" r="9">` filled with the moon tone, masked by `<mask id="cresmask">` containing a white full-viewBox rect minus a black `<circle cx="16" cy="11" r="8">`. The mask's black disc carves the bite out of the bright disc cleanly — no path-arc interpretation involved, which is the rendering path that was tripping. Added a 1-unit vertical offset between outer and inner centers (y=12 vs y=11) so the crescent tilts slightly, reading as a classic "🌙" shape rather than a symmetric horizontal C.
- **Card rhythm fixed on area-details page (Controls↔Auto no longer double-gapped)** — the flex container `#auto-sched-section { gap: 8px }` holds `chart-card` → `tune-controls-card` → `auto-outer-card`. `tune-controls-card` carries `.tune-card` which globally sets `margin-bottom: 8px` (intended for the Tune↔Lights pair inside `#area-tune-section`, which is a regular block container with no flex gap). Inside the flex section, flex-gap and child margin stack additively (flex gap is a floor, not a replacement), so Controls↔Auto rendered at 16px while the other card pairs rendered at 8px — the screenshot showed a visibly generous break between Controls and Auto while Adjust↔Controls, Auto↔Tune, and Tune↔Lights were all tight. Added a scoped override `#auto-sched-section .tune-card { margin-bottom: 0 }` so the flex gap is the sole spacer in that section; unchanged behavior for `tune-brightness-card` and `tune-lights-card` in `#area-tune-section` (they still use the block margin-bottom since they have no flex gap to rely on).

## 1.2.144
- **Motion-sensor control detail: sensitivity row hidden when device doesn't expose the cluster** — the sensitivity control was shown for every ZHA motion sensor, populated via `/api/controls/{device_id}/zha-settings` which searches the HA entity registry for a `select.*sensitivity*` or `number.*sensitivity*` sibling. When no such entity exists (Third Reality 3RMS16BZ is the triggering case — it only exposes `number.*_detection_interval`, not a sensitivity cluster attribute), the frontend previously fell into an `else` branch that rendered `<option value="">Not available</option>` in the select — a dead dropdown showing empty text. Changed that branch to hide the whole `#sensitivity-row` instead. Hue sensors still get the brief "Loading..." → options flow on open because the render gate at `control.html:2748` unconditionally sets `display: flex` and calls `loadZhaSettings` every time the detail page opens — so if the device starts reporting sensitivity later, the UI picks it up next open. The `is_zha === false` short-circuit branch (non-ZHA integration) already hid the row and is unchanged.

## 1.2.143
- **Third Reality 3RMS16BZ motion sensor added to allowlist** — single-entry addition to `MOTION_SENSOR_MODELS` in `addon/switches.py`: manufacturer key `third reality` (substring-matches HA's reported `Third Reality, Inc`), model key `3RMS16BZ`, display name `Third Reality Motion`. Sensor emits standard binary_sensor `on`/`off` transitions (verified from HA activity log: `detected motion` → `cleared (no motion detected)` with 15–60s clear delay) — no ZHA event path required. Auto-discovery picks up the motion entity by `device_class: motion` / `_motion` entity-id pattern. Sibling `number.*_detection_interval` (user-adjustable clear-delay), `sensor.*_battery`, `update.*_firmware` entities are HA-native and need no addon-side handling.

## 1.2.142
- **Moon crescent actually renders now** — v1.2.141 switched the sunset marker from a `🌙` emoji annotation to a Plotly `images[]` SVG path `M15 4 A 8 8 0 1 0 15 20 A 6 6 0 1 1 15 4 Z` which is the textbook "two arcs of different radius sharing endpoints" crescent shape. Problem: the chord from (15,4) to (15,20) is exactly 16 long, which equals the outer arc's diameter (2 × r=8). When chord length equals diameter the arc is a perfect semicircle and both the large-arc flag AND sweep flag are ambiguous — SVG spec says rendering is implementation-defined. In practice Plotly's SVG rasterizer silently drops the path → invisible moon. Replaced with a two-subpath evenodd-fill path that uses full-circle arcs (`M 12 2 A 10 10 0 1 1 12.01 2 Z M 15 5 A 7 7 0 1 1 15.01 5 Z`) — the 0.01-unit offset on the close point keeps each arc non-degenerate (chord < 2r) so the arc command is unambiguous. Outer disc cx=12 r=10, inner disc cx=15 r=7 (fully contained within outer), evenodd fill carves the inner out → classic crescent opening to the right, same size + y position as the sun.
- **"bulbs" label dropped from chart** — the Adjust chart annotated two curves: the solid filled gradient ("bulbs" — what lights actually output after sun-bright dimming) and the dotted line ("sun exposure" — the pre-dimming circadian target). The bulb curve is the main graph — it's what the sliders control, what the NOW dot sits on, what determines the filled gradient — labeling it was noise. Only the dotted reference line needed naming. Removed the `bulbs` annotation push in `renderMiniChart` and dropped the `divBulbY` local that only fed it. `sun exposure` annotation unchanged.
- **Day-of-week buttons vertically centered against time input** — inside `.auto-sched-days-time` (flex row, `align-items: center`), each `.auto-sched-day-col` was a 2-row flex column: `<button>` on top, empty `<span class="auto-sched-day-time">` below. That span had explicit `height: 0.75rem; line-height: 0.75rem` — even empty it was ~12px of height, making the col taller than the time input. Flex centering aligned col-center with input-center, which parked the button ~7px above the input's vertical midpoint. The span was legacy: one write path (`showResolvedAutoTime`) only ever clears it to `''`, never populates. Added `.auto-sched-day-time:empty { display: none }` — removes the 12px from the col, col becomes button-height only, flex centering now lands the button exactly on the input's midline. Safe because the only write path is `sp.textContent = ''` which leaves the span matching `:empty`; if a future feature populates per-day times again, the rule self-disables.

## 1.2.141
- **2-step gate widened for off→on** — two behavioral changes to the 2-step (color-pre-send at 1% → delay → brightness ramp) that close holes the prior CT-delta + brightness-threshold gates left open. (1) **Unknown prev CT forces 2-step instead of skipping**: `main.py` gate at ~line 3867 previously skipped 2-step when `prev_kelvin is None` and lights were already on (the rationale being "lights are on, no off→on flash risk"). But prev_kelvin is in-memory — after an addon restart it's always None even for on-lights — so we were silently falling back to single-shot dispatches at potentially-wrong CT. Now treated as "can't verify color safety, force 2-step." Matching change in `primitives.py` batch-dispatch at ~line 4305: the `last_ct is not None and ...` check flipped to `last_ct is None or ...` so unknown CT also triggers the batch 2-step path. (2) **Brightness threshold dropped for off→on**: previously off→on skipped 2-step when target bri < `two_step_bri_threshold` (default 15%). That meant turning lights on to e.g. 5% or 10% skipped the 2-step entirely and came in at whatever CT the bulb last had cached — which is the exact flash scenario 2-step exists to prevent. Phase 1 is always 1% brightness regardless of target, so there's no visual cost to 2-stepping a low-target turn-on — the only "cost" is the delay the user was going to wait through anyway. Removed the `if filtered_bri < bri_delta_threshold: continue` skip in `main.py` off→on branch and the equivalent `if bri >= bri_delta_threshold:` guard in the `primitives.py` batch off→on branch. Already-on brightness-delta gate preserved (those stay threshold-gated — no color-flash risk, just ramp smoothness).
- **NOW hover chip matches CCT** — the blue tile on hover-over-the-NOW-dot (Plotly default `hoverlabel` inheriting the marker's cyan fill `rgba(140,210,255,0.95)`) was off-brand vs. the curve trace which already carries a CCT-tinted hoverlabel (bg = `cctToRGB(k)` at 0.92 alpha, border at 0.65, readable text color). Added the same `hoverlabel` block to the NOW dot trace in `area.html` so hovering the dot gets a warm-orange tile at 2200K / cool-blue at 6500K — same color the NOW pill itself uses.
- **Sun icon — face removed** — the v1.2.140 smiling-sun SVG (circle + 8 rays + two eye dots + Q-curve smile) dropped the face: just circle + 8 rays now. Same viewBox / fill / position — simpler read at the small size the chart renders it.
- **Moon rendered as SVG image matching sun geometry** — sunset marker was a Plotly `annotations[].text: '🌙'` emoji at `y: 0.99, font size 14, yanchor: top`; sunrise was a Plotly `images[]` SVG at `y: 1.05, sizex: 1.0, sizey: 0.14, yanchor: top`. Two different render primitives → different effective heights + vertical positions. Moon now rendered as an SVG image (`svgSunset`: crescent path `M15 4 A 8 8 0 1 0 15 20 A 6 6 0 1 1 15 4 Z` filled `rgb(230,225,195)`) with identical `y / sizex / sizey / xanchor / yanchor` to the sun so both hover at the same baseline.
- **Custom schedule: "Schedule 2" label dropped; remove becomes inline ×** — when custom mode added a 2nd schedule, the group rendered a mini-header `.auto-sched-custom-header` with "Schedule 2" label (`.auto-sched-custom-label`, uppercase muted) and a right-side "remove" underlined link on its own row. Restructured: header gone, remove collapsed to a single `&times;` link at `font-size 1rem` inside the schedule 2's `.auto-sched-days-time` flex row (rightmost element, sibling to days + time input). Classes retired: `.auto-sched-custom-header`, `.auto-sched-custom-label`. `.auto-sched-remove-link` restyled: no underline, `font-size` 0.7→1rem, `padding 0 4px`, `flex-shrink: 0`. JS untouched — `showAutoSchedule2` / `removeAutoSchedule2` still just toggle display on `#auto-{type}-sched-2` and the "+ add schedule" link.
- **Consistent vertical rhythm in custom schedule block** — radios row had `margin-bottom: 10px`, schedule 1 days-time row `margin-bottom: 4px`, schedule 2 wrapper `margin-top: 10px + margin-bottom: 4px` — cramped between radios and schedule 1, generous between schedule 1 and schedule 2. Standardized to 10px everywhere: `.auto-sched-days-time { margin-bottom: 10px }` (was 4); `.auto-sched-custom-group { margin-top: 0; margin-bottom: 0 }` (was 10/4) with `.auto-sched-custom-group .auto-sched-days-time { margin-bottom: 0 }` to avoid doubling at the bottom edge. Result: 10px gap radios→sched1, 10px sched1→sched2, 10px sched2→add-schedule-link when shown.
- **Auto Off header time now shows when auto-on has never fired** — `_compute_next_auto_off_with_untouched` in `webserver.py` returned `None` whenever `auto_off_only_untouched` was enabled AND `_auto_fired[area_id]['auto_on']` was empty (the in-memory dict is cleared on addon restart and is also empty for any area whose auto-on hasn't yet fired today — common case: auto-on is scheduled for 7pm, user checks the UI at 2pm). The `None` propagated to the header "Off" row, blanking the time. The "untouched since auto-on" guard only makes sense when there's an auto-on baseline to compare against — if auto-on has never fired, there's no baseline, so the guard has nothing to check. Changed the early-return to pass through the scheduled result (`return result` instead of `return None`) in that branch. Still suppresses auto-off when auto-on has fired AND the user has touched since, which is the actual case the guard is defending against.

## 1.2.140
- **Polish pass on v1.2.139 UI** — ten targeted tweaks after landing the Lights/Tune split. (1) Chart: daily (shifted-state) wake/bed vertical lines lost their `dash: 'dot'` styling — now solid-but-muted (`rgba(92,179,255,0.28)` / `rgba(255,230,128,0.28)` at width 1.25). They were colliding visually with the natural-light target line which also uses `dash: 'dot'` — two dotted lines with the same dash pattern but different semantics. Keeping the muted alpha preserves the "ghost of the default schedule" reading; solid distinguishes it from the target. (2) Auto Off "If" checkbox label `"Skip if manually touched since last Auto On"` → `"lights not touched since Auto On"` — positive framing, reads as a precondition rather than a negation of a negation. (3) Schedule 2 inline header: `.auto-sched-custom-header` dropped `justify-content: space-between` (now just `gap: 10px`) so "remove" sits adjacent to "Schedule 2" instead of being flung to the far right of the container. "remove" text dropped the `−` prefix — just the word, cleaner. (4) Home-page area-card bed/wake pill: removed the `(±H:MM)` delta hint from `getPhaseMidpoint` in `areas.html`. When the area midpoint matches its zone default, the pill is suppressed entirely (existing behavior); when it differs, we now show just `Bed 10:30p` without the offset in parens. The offset hint was overkill for the compact pill — kept intact on the Auto On/Off merged header where the delta is actionable. (5) Card reorder: tune section now reads Adjust → Controls → Auto → Tune → Lights (was Adjust → Auto → Tune → Lights → Controls). Controls moves from position 5 to position 2 because Controls is a small lookup list (counts + feedback target) that reads best adjacent to Adjust, while Tune/Lights are deeper configuration. Structurally moved `tune-controls-card` out of `area-tune-section` and inserted between `chart-card` and `auto-outer-card` in `auto-sched-section`. (6) Lights card collapsed header now shows count: new `.tune-lights-count` span (auto-margin-left, tabular-nums, muted) mirrors the `#tune-controls-count` pattern — shows sortedLights.length; hidden when card is open via `.tune-lights-card.is-open .tune-lights-count { opacity: 0; }`. (7) "Feedback light:" dropdown moved from Controls body to top of Lights body. It's a per-light selector, so it belongs adjacent to the light list, not the controls list. Simplified `controlsBody.innerHTML = controlsListHtml` (no divider, no fbhtml appended). (8) Tune "Sun exposure" slider word label rebalanced: `Strong 0.90` left side now renders with `.tune-solar-main` (font-size 0.78rem, weight 600, full --text color); right-side `peak sun ↓ 18%` now `.tune-solar-peak` (font-size 0.68rem, --muted2 color). Main label reads as the primary state, peak sun is secondary context. (9) Hand-drawn sunrise SVG (horizontal line + half-disc for "horizon + rising sun") replaced with a smiling-sun face — circle + 8 rays + two eye dots + Q-curve smile, viewBox 0 0 24 24. Visually friendlier and matches the "Sunrise ✨" tone rather than the literal "sun clearing the horizon" diagram. Bumped `sizex` 0.9 → 1.0 and `sizey` 0.16 → 0.14, moved `y` 1.02 → 1.05 so the now-square icon sits cleanly above the curve. (10) Custom mode day pills + time input now share one row (`.auto-sched-days-time` flex wrapper) instead of stacking. Day buttons shrink to 19×19px with 0.48rem font and 1.25px border inside the wrapper; time input is `.auto-sched-time-input--inline` (padding 3px 6px, font 0.78rem, max-width 108px, `flex-shrink: 0`). Added `::-webkit-datetime-edit-ampm-field { text-transform: lowercase; font-size: 0.68rem; }` to lowercase the AM/PM to "am"/"pm" and shrink that field (single-letter "a"/"p" isn't possible on native `<input type="time">` since the field content is browser-controlled, but lowercase + smaller font claws back visible width). Schedule 1's time-1 input lives inside the `.auto-sched-days-time` wrapper, hidden via `style="display:none;"` by default and shown via `setAutoSourceUI` when `source === 'custom'`; Schedule 2's time-2 is always visible (Schedule 2 only exists in custom mode). HTML restructured for both Auto On and Auto Off; time-1 input moved out of the `auto-sched-row` in `auto-{on,off}-custom-controls` (which now holds only the Schedule 2 group + "+ add schedule" link).

## 1.2.139
- **Area-details Lights/Tune split + Adjust header live readout** — the old "Lights" card (internally `tune-brightness-card`) was overloaded: it owned the Tuning-zone sliders (Sun exposure, Room balance), the Activity breakdown (Boost, Dimming, Fade, User override), *and* the per-light list, all collapsed behind a single header. Split into two peer cards and added a compact live readout on the Adjust card header. **(1) Adjust card header gets right-side `78% · 2910K` display** — new `.adjust-outer-next` span inside `#chart-card`'s header, populated in the same update loop that drives `#slider-hero-brightness` / `#slider-hero-color` (reads `areaState.actual_brightness` / `effectiveCCT` — same server-truth source from v1.2.135). Kelvin number colored inline via `cctToRGB(kDisp)` (shared.js) so 2200K shows warm orange, 4000K off-white, 6500K cool blue — mirrors the slider thumb border color. Dot (U+00B7) separator in muted2. Hidden when card open (same `.is-open` rule as `.auto-outer-next` from v1.2.137), since expanded card shows the full sliders. **(2) `tune-brightness-card` renamed "Lights" → "Tune", body rebuilt as math-equation waterfall** — removed the `.tune-hero-block` (18px "Area Brightness" value + breadcrumb `[base]% curve · [Δ]% adjustments` with inner collapse), removed the `.tune-zone-label` "Tuning"/"Activity" subheaders, removed `tune-adj-details` inner collapse, removed the `tune-activity-empty` "None active" placeholder, removed hide-zero-rows logic in `updateActivityVisibility` (now a no-op — every row shows even at 0%). New layout is a 4-col grid `1.5em 1fr auto auto` (operator, label, reset link, value) rendered as: `Curve 80%` (no operator), `+ Sun exposure +0%` [slider], `+ Room balance +2%` [slider], `+ User brightened −10%`, `+ Boost +0%`, `+ Dimming +0%`, `+ Auto-on fade +0%`, divider, `= Area Brightness 72%`. `formatImpact` updated to use Unicode minus (U+2212) for negative values. Sliders sit in `.tune-wf-slider` rows directly beneath their parent row, padded 52px left to align under the label column. Reset links (`tune-reset-solar`, `tune-reset-lumen`) moved from `.tune-control-reset` class to `.tune-wf-reset` — same behavior (opacity 0 → 0.6 when `.is-dirty`), new class for the grid-cell placement. **(3) Per-light list extracted to its own "Lights" card** — the previously-hidden `tune-lights-card` element (was `display:none`) now gets rendered: new `.tune-lights-header` with chevron + "Lights" title, `.tune-lights-body` contains the per-light accordion (name / purpose / impact / final columns, sort headers, impact breakdowns). The `.tune-individual-toggle` wrapper + `#tune-individual-body` inner collapse were dropped — card-level expand/collapse replaces them. Persistence keys split: `tune_collapsed` (new, was `tune_details_expanded`) and `lights_collapsed` (new, was `tune_lights_expanded`) — both follow the "`true` = collapsed" convention from `chart_collapsed` / `auto_collapsed`. Deep-link: `?focus=tune` added to `handleDeepLink` (opens tune card, scrolls, `focus-flash`); generalized `.focus-flash` rule now applies to `.tune-card` as well as `.auto-sched-card--sub`. `?focus=lights` intentionally omitted (no home-row hit surface for it). **(4) Page order reshuffled** — was Adjust → Auto → Tune (with lights inline) → Controls; now Adjust → Auto → Tune → Lights → Controls. Controls card moved after Lights to match the "view/configure" reading order (lights are primary state, controls are secondary configuration). **(5) Cleanups** — `initChartCardState` generalized to collapse on any `_pageFocus` value other than `chart` (previously was an explicit allowlist of `auto_on`/`auto_off`/`controls` — now automatically adapts to new focus targets like `tune`). Dead code paths for `tune-lights-inline` (ID) removed from `sortLightsList` and the column-sort handler attach block.

## 1.2.138
- **Auto card polish pass** — cleanups from the 1.2.137 screenshot review. (a) Sub-section titles "Auto On" / "Auto Off" → "On" / "Off" — the outer card is already "Auto", so re-saying it was noise. (b) Merged header next-trigger display now hidden when outer is expanded (`.auto-sched-card--auto.is-open .auto-outer-next { display: none; }`) — the sub-section resolved-time to the right of each toggle (`9:00a Sat`) already carries the information, so the compact merged form was duplicating it. (c) Field rows inside sub-sections indented 28px from the left (`.auto-sched-card--sub .auto-sched-field { padding-left: 28px; }`) so Light/Time/Fade/If labels sit under — not flush with — the "On"/"Off" titles, creating a visual parent-child hierarchy. (d) Removed the `Conditions` header on Auto Off — the single "If" row below doesn't need a category label, and killing it claims ~30px of vertical real estate. (e) Removed the per-section days summary (`"2 days"`, `"Every day"`, `"Weekdays"`, `"Weekends"`) that rendered above the day pill row — weirdly formatted, redundant with the pill state, and eats a line. Delete removed the HTML div; the `updateAutoDaysSummary` function early-returns on missing element so all its callers remain harmless.
- **Schedule 2 reorder + inline remove link** — custom mode with "+ add schedule" showed schedule 1 as `[days row] → [time input]` but schedule 2 as `[time input] → [days row]`, inconsistent ordering. Reordered schedule 2 to match schedule 1 (days first, then time). Also moved the "− remove schedule 2" link from its own line below the days to a new inline header row `.auto-sched-custom-header` (`display: flex; justify-content: space-between`): label `Schedule 2` left-aligned, `− remove` link right-aligned — reclaims a line of vertical space and makes the action adjacent to its target.
- **Offset stepper compaction** — when `Sunrise` or `Sunset` is selected, the `[−]  [value]  [+]` row stretched awkwardly with `[−]` and `[+]` flung to opposite edges of the container because `.auto-sched-offset-val` had `min-width: 7.5em` (legacy from the "5 min before" / "5 min after" string widths). Reduced to `3.5em` to match the new `±Hm` / `±H:MM` format widths. Separately, `formatOffset(0)` now returns the literal `'0'` instead of empty string, so the stepper's middle slot reads `[−]  0  [+]` when at zero — a grounded center element instead of blank whitespace. Merged header still treats offset=0 as empty via its own guard in `formatMergedAutoSide` (`s.offset === 0 ? '' : ...`), so `Sunset` without offset stays bare, not `Sunset 0`.
- **Auto On trigger renamed: "Trigger" → "If", pill labels shortened** — parallels the new "If" label on Auto Off ("Skip if manually touched..."), making both sub-sections have the same conditional vocabulary. Pill text: `Always` / `Skip if brighter` / `Skip if on` → `Always` / `Dimmer` / `Off`. Data-mode values (`always` / `skip_brighter` / `skip_on`) unchanged — backend reads the same payload, only the button face changed. Reads more concisely in the row and lines up with the `If` column width.
- **Outer Auto body max-height raised 3000 → 6000px** — the 1.2.137 screenshot showed Auto Off clipping below its offset stepper (Fade slider, If row, Override, Save/Cancel bar all below the cut). Both sub-sections fully expanded can exceed 3000px on mobile viewports once custom mode, schedule 2, and dirty action bars are all rendered. 6000px is comfortably above any realistic combined height; CSS `max-height` transition still animates cleanly since it's a finite value.

## 1.2.137
- **Area-details: Auto On and Auto Off merged into a single "Auto" card with a compact combined header** — previously the area-details page had two sibling sub-cards inside `.auto-sched-bonded` (Auto On, Auto Off), each independently collapsible with its own `toggleAutoBody(type)`. Headers showed source-word form when collapsed (`Sunset -10m`) and resolved absolute time when expanded (`6:19p`). This ate vertical real estate (two header bands, two chevrons) and the old client-side `computeNextAutoTime()` next-trigger string was verbose (`5:00p tomorrow (Fri)`, `5:00p Sun (Apr 26)`). Restructured into one outer card `#auto-outer-card` (new `.auto-sched-card--auto` variant, `max-height: 3000px` when open to fit both subsections) wrapping the existing bonded panel; inner subs lost their individual collapse (CSS override `max-height: none; opacity: 1; overflow: visible` on `.auto-sched-card--sub > .auto-sched-body`) and their headers are now static (`.auto-sched-header--static`, no chevron). Outer header right-side is a new `.auto-outer-next` container rendering a merged next-trigger summary: `On Sunset +30m • Off 5p Fri` — each side a tappable anchor `a[data-auto-hit]` that calls `focusAutoSub(type)`.
- **Format rules for the merged header**: (a) `formatAutoTimeCompact(t)` strips `:00` only, so `5:00p` → `5p` but `5:05p` stays (matches home page `formatAutoSchedulePill` exactly). (b) `formatOffset(min)` returns empty string for 0, `+30m`/`−45m` for sub-hour, `+2:30`/`−1:15` hours:minutes for ≥60m (replaces the literal `'on time'` and the verbose `150 min after` form). (c) `formatAutoDaySuffix(nxt)` uses the server-provided `offset`/`day_abbr`/`date_short` fields: bare within 24h, day abbr 2-6 days out, date short 7+ days — same bucket logic as home-page algorithm. (d) Sun-based triggers use the word form (`Sunset +30m`) always (even when offset <60m, unlike home page which drops offsets <60m because horizontal space is tighter there); clock-based triggers use absolute time. (e) When a side is disabled: greyed-out `On —` / `Off —`; when both disabled: collapsed to single `Off` pill.
- **Dead-code removal**: `computeNextAutoTime()` (the 14-day forward walk that duplicated server-side next-trigger computation) deleted along with its callers in `onAutoFieldChanged`. Client now relies on `fetchNextAutoSchedule(type)` → `_cachedNextAuto[type]` for all next-trigger display. `updateAutoHeaderText` simplified: sub-card headers always show resolved `nxt.time + nxt.day` (no more collapsed/expanded branching since inner subs don't collapse).
- **Deep-link + hit-zone flow unified**: New `focusAutoSub(type)` opens outer Auto, scrolls target sub with `scrollIntoView({block: 'start'})` (changed from `block: 'center'` so the lower `auto-off-card` lands fully in view when targeted — center was cutting the bottom off on shorter viewports), and flashes the `focus-flash` outline (upgraded from background-tint-only to `background + inset 2px box-shadow` in orange `rgba(254,172,96,0.85)` for stronger signal). Same function services both the merged-header hit zones (tapping "On…" or "Off…" in the outer header) and the `?focus=auto_on`/`?focus=auto_off` deep link arriving from the home-page area-row auto-schedule pill. `handleDeepLink()` pared down accordingly; the ad-hoc outer-border-flash was replaced by the sub-card flash alone.
- **Persistence keys consolidated**: Retired `auto_on_collapsed` and `auto_off_collapsed` localStorage keys (two-level collapse is gone). New single key `auto_collapsed` tracks outer Auto card state. `initAutoOuterState()` mirrors `initChartCardState()`: deep-link to `auto_on`/`auto_off` forces outer open; deep-link elsewhere (`controls`, or any `?focus=` / `?from=`) forces closed; no-deep-link arrival restores from localStorage. During a `_pageFocus` session `_persistCards` is already `false`, so neither outer nor inner state writes to localStorage — matches the same "deep-link is transient" rule already used by `chart_collapsed` and the tune cards.

## 1.2.136
- **Home-row slider drag feedback — ghost thumb + inline target % + track-fill band** — the home-page area-row sliders commit on release (bandwidth optimization: lights don't respond until pointerup), so mid-drag the user had zero quantitative feedback — just a pill moving on a track. Added three complementary affordances that appear on pointerdown and clear on pointerup/cancel: **(a) Ghost thumb** — a 1.5px faint outlined duplicate of the pill anchored at the drag-start X position, stays put while the solid thumb follows the finger. Familiar from Figma/Photoshop; gives visual anchoring for the delta. **(b) Fill-drag band** — a 6px semi-transparent white rail stretched between ghost and live thumb, auto-swapping left/width so it works in both drag directions. Reinforces direction (brightening vs dimming) and magnitude at a glance. **(c) Inline target %** — a `.row-drag-value` span in `.row-middle-top` (right of the area name, same vertical band as the name, *above* the slider track — so it doesn't compress track width). Shows the live integer brightness during drag, hidden otherwise. **Reset chip hidden during drag** — `.mismatch-dot-area` is suppressed under `.area-row.slider-dragging` so the inline % can use the horizontal space (reset isn't tappable mid-drag anyway; it reappears on release if the area is still dirty). All three affordances are driven by `track.classList.add('dragging')` + `row.classList.add('slider-dragging')` on pointerdown, cleared on pointerup/pointercancel via `clearDragAffordances()`. Ghost position anchored once from `thumb.style.left` at the start of drag; never recomputed until release.

## 1.2.135
- **NOW chip on Adjust chart now reads from the same source as the Bright/Color slider headers and the Lights section** — previously `markerBri` and `markerCCT` were re-derived client-side via `calcMiniBrightness` + `calcBulbBrightnessAt` / `calcMiniColor`. After a brightness or color drag landed, the NOW pill would disagree with the slider for ~30s — showing 73% while the slider showed 25%, or 3743K while the slider showed 1700K — then "self-correct" but still sit ~2% off (e.g. slider 26%, NOW 28%). Two root causes, both sidestepped by pointing the chip at the server-truth fields `areaLive.actual_brightness` and `areaLive.api_kelvin` (which are exactly what the slider-header labels and the Lights card read): **(a) clock-precision race** — server writes `brightness_override_set_at` / `color_override_set_at` using second-precision wall clock (e.g. `18.80833`) in `primitives.py:1071`, while client's `currentHour` in `area.html:2623` uses minute-floored precision (`18.80`), so the `h48 >= setAt48` guard in `calcMiniBrightness:1720` / `calcMiniColor:1812` fails for the NOW sample even though curve samples 6 min later succeed. The cliff appears in the curve but the NOW marker text is still on the pre-override side. **(b) accounting mismatch** — `set_position(brightness)` in `primitives.py:1064` stores `override = target_actual − state.get_last_sent_brightness(area_id)` (delta from *post-everything* last-sent value, which already includes area_factor, sun_bright compensation, and any existing override folded in), whereas client's render computes `room = logistic × area_factor + stored_override` (starting from *pre-everything* pure circadian). The two baselines diverge by ~2% on steep descend segments. Fix: in `renderMiniChart`, after the existing `calcMini*`-based `markerBri`/`markerCCT` defaults (kept as cold-start fallback), overwrite with `areaLive.actual_brightness` / `areaLive.api_kelvin` whenever those fields are finite. `markerOverride` (drag preview) still applies last, so live-drag feedback is unaffected. Curve render still uses the client-side pipeline — the ~2% accounting drift remains visible in the curve shape but not in the NOW chip, which is what matters for "what are the lights doing right now."

## 1.2.134
- **Adjust-card curve reshapes live on brightness/color slider drag** — prior to this the brightness/color slider drag only moved the NOW pill/dot; the curve itself stayed in its pre-drag shape, so the user had to guess what the lights would actually look like post-release. Now `previewSlider` (brightness and color branches) derives a *new* override = `previewValue − pureCurveAtNow` (where "pure" = the logistic × area_factor at current hour with any existing override explicitly nulled out), and injects it into a cloned `areaState` as `{brightness|color}_override` + `{...}_override_set_at: currentHour` before handing to `renderMiniChart`. The existing `calcMiniBrightness`/`calcMiniColor` decay logic (linear taper from set-time forward to the next phase boundary; two phase sizes per day) then renders the curve exactly as it will behave once the drag lands — rising or dipping at NOW by the full override delta and tapering to pure circadian by the next Wake/Bed edge. Pattern matches the existing phase-drag branch's "inject preview state, reuse render math" approach; no new render code path, no new decay math.
- **Row "red dot" → round reset chip on Home page** — the 10px red dot that appeared when an area had been nudged off its rhythm zone (step/freeze/override) was a weak affordance: it reads as a status indicator, not a button. Replaced with a 22px round dark chip (`rgba(0,0,0,0.55)` bg, white ↺ glyph, hover darkens to 0.75) — same visual family as the existing zone-header reset button and the power button, but intentionally sized smaller than the 36px power button to create a primary/secondary hierarchy within the row. Visibility logic unchanged (still gated on `isAreaDirty`), click handler unchanged (still `rowAction(..., 'glo_down')`). The 22×22 footprint natively meets touch-target spec so no `::after` hit-region hack is needed. Dark chip stays legible across the full warm→cool row background palette that the CT spectrum produces.

## 1.2.133
- **Plateau fallback on hero step arrows** — v1.2.132 wired `[◀]`/`[▶]` to `step_up`/`step_down`, which correctly preserved server-side `cancel_fade` + `mark_user_action` (so "auto-off untouched" still counts the hero press as a touch, and in-progress fades get interrupted). But `step_up`/`step_down` are brightness-vector primitives: they compute `target_bri = current_bri ± step_size` and bounce at `[min_bri, max_bri]`. On the plateau (e.g. 2pm with bed=10pm, current_bri already at 100%), the step is a no-op because the curve at current time can't go higher — even though the slider has room to push bed further out. Fix: backend returns `at_limit: true` in the `/api/area/action` response when `step_up`/`step_down` returns `None` or `"sun_dimming_limit"`; frontend `chartHeroStep` detects this and falls through to `executeSetPhaseTime(current ± step_fallback_minutes / 60)`. Best of both: curve-aware step in the body of the curve, time-based nudge on the plateau. Phase-boundary clamp still applies (`phaseMin+0.01`, `phaseMax-0.01`).
- **New config: `step_fallback_minutes`** (default 30) — settings page "Step increments" row now has a second numeric input after the existing "steps" field: `[10] steps  [30] minutes`. Added to `RHYTHM_SETTINGS` and `int_params` alongside `max_dim_steps`. Tooltip updated. Fallback used by the hero step arrows only (switches untouched) — keeps the tactile "at max/min" bounce for hardware presses while letting the UI keep moving the handle.
- **Sunrise emoji replaced with a custom SVG** — `🌅` had a busy landscape/photo-style frame (semicircle + mountains + rays) that read as cluttered. Swapped for an inline SVG: a solid yellow half-disc (`rgb(244,201,107)`, r=5) sitting on a thin gray horizon line (`rgb(180,180,180)`, 1.2px). 24×14 viewbox, ~14px render — same visual weight as the moon glyph at sunset. Rendered via Plotly `layout.images` with URL-encoded `data:image/svg+xml`, same plumbing we used before (reintroduced `images` array back to the layout).
- **Hero time label updates live during chart drag** — previously `phaseCtx.currentTargetTime` was read from server-side `areaStatus.adjusted_wake_time` / `adjusted_bed_time`, which doesn't update until drag release. Now `updateChartHero` uses `_chartDrag.dragHour` when `_chartDrag.active`, so the "5:24a" text follows the drag in real time, matching the phase-slider hero's existing live behavior. Hero x-position already used `dragHour` for the same reason; label just hadn't been wired up.
- **`step_down` now returns its result from `handle_service_event`** (parity with `step_up`) — needed so the webserver can inspect the result and set the `at_limit` flag. Zero behavioral change for existing callers that ignore the return value.

## 1.2.132
- **Hero cluster moved inside the chart** — previously the Wake/Bed label, time, and step arrows lived in a reserved 56px band below `#mini-chart` on the page's gray background, with a visible gap between the wake line end and the hero. Now the chart div grows from 190px → 220px and `margin.b` expands 56 → 86 so the hero sits inside the chart's own bottom margin, just under the wake/bed line end (~10px gap) and well clear of the x-tick label row (~23px below). `#chart-shell` no longer reserves padding; the hero uses `bottom: 6px` of the shell. Visually, the hero now reads as part of the chart rather than an appendage below it.
- **Hero `[◀]` / `[▶]` now call `step_up` / `step_down`** — v1.2.131 used a hand-rolled `step_hours = 0.40 / |slope|` feeding `executeSetPhaseTime`, which bypassed the server-side step logic (step-size config, bounce-at-limit, `sun_dimming_limit` hint, fade cancellation, user-action marking). Now wired to `executeAction('step_up'|'step_down')` with phase-aware direction mapping: in wake phase `[◀]` = earlier = brighter now = `step_up`, in bed phase `[◀]` = earlier = dimmer now = `step_down`. Server handles everything else. `chartHeroStepHours` helper deleted. Boundary suppression kept as a simple `currentTargetPct ≤ 3` / `≥ 97` check (still needed for curve-shape edge cases near the v1.2.128 narrowed-boundary).
- **Wake/Bed label and time now phase-colored** — `#5cb3ff` (wake blue) and `#ffe680` (bed gold), matching the phase line colors in the chart. Step arrows and reset button stay neutral. Visually tethers the hero to whichever handle it's annotating.
- **Sunrise/sunset icons swapped from lucide SVG to unicode emoji** — `🌅` at sunrise and `🌙` at sunset, via Plotly `annotations` with `text` (replacing the old `layout.images` with URL-encoded `data:image/svg+xml`). The SVGs read as "sun with up-arrow / sun with down-arrow" which was visually noisy; emoji sunrise-over-horizon + moon reads cleaner and needs no stroke/fill tuning. `images` array and its layout slot removed.

## 1.2.131
- **"Curve" card renamed to "Adjust"** — the card's job is adjusting today's lights, not displaying a curve. The chart is still there as the primary affordance.
- **Phase slider row removed** — the on-chart drag handle has proven to be a strong-enough affordance on its own. Replaced with a two-line hero cluster tethered below the plot at the active handle's x-position: line 1 is the phase label (`Wake` / `Bed`) with a reset button that only appears when shifted; line 2 is `[◀]  <time>  [▶]` for stepping the target in brightness-vector-sized increments (`step_hours = 0.40 / |slope|`, matching "one step along the curve" at current time — smaller jumps for steep phases, larger for shallow). Hero clamps horizontally to the plot edges, and the direction button suppresses (`disabled`, faded) when stepping would cross the v1.2.128 narrowed phase boundary. `ResizeObserver` on `#mini-chart` re-aligns the overlay when the chart resizes (Plotly's `responsive: true` redraws the plot but doesn't re-fire our layout logic).
- **Weather label removed from chart** — the "Sunny / Cloudy" chip in the chart's top-right cluttered the layout and was frequently wrong (showed Cloudy on clear days). The conditions multiplier still feeds into the circadian math; only the visible chip is gone.
- **Small wake/bed annotations below the plot removed** — redundant with the hero cluster and the on-plot handle/dot. Keeps the plot's bottom breathing room clean.
- **Delta visualization replaces the `(+30m)` text**: when the handle is shifted off the daily target, the plot now shows a faint phase-colored band between the daily (dotted) and adjusted (solid) vertical lines. The daily line is drawn in a muted version of its phase color (`rgba(92,179,255,0.28)` for wake, `rgba(255,230,128,0.28)` for bed) instead of neutral gray so the two lines read as "same thing, shifted" rather than "gray ghost vs colored line". Hover label on the active handle no longer includes the `(+30m)` delta string — the band carries that meaning visually.
- **Sunrise/sunset glyphs replaced with inline SVG icons** — `☀` and `☾` read as "sun" and "moon" rather than "rise" and "set." Now lucide-style sunrise (sun with up-arrow over horizon) and sunset (sun with down-arrow over horizon) via `layout.images` with URL-encoded `data:image/svg+xml` sources. Invisible scatter markers preserve the hover tooltips (`sunrise · 6:42a` / `sunset · 7:14p`).
- **"natural light" chart annotation renamed to "sun exposure"**; **"Solar exposure" label in the tune section renamed to "Sun exposure"** — terminology is now consistent across the chart and the tune panel.
- **Solar exposure / Room balance tune sliders now preview in the chart live** (brought forward from uncommitted staging): dragging either slider calls `renderMiniChartForArea` with `tuneState` overrides applied to `areaState.sun_exposure` / `area_factor` / `brightness_sensitivity` during the mini-chart render, so the curve reshapes under the cursor instead of only updating on release. Reset buttons also re-render. Parity with how Bright/Color previews already worked.

## 1.2.130
- **Chart drag now respects the v1.2.128 narrowed phase bounds** (previously only the phase slider did). Chart-drag clamp (`_chartGeom.phaseMin/Max`) now runs through `computePhaseSafeOffset` the same way the slider does, so dragging the chart handle can no longer reach a target whose shifted mid would escape the phase window and trigger the downstream `% 24` wrap. Both UI inputs to wake/bed targeting are now consistent.
- **Phase slider hour-tick suppression relaxed for the daily wake/bed marker**: v1.2.125 hid any hour tick within ±12% of the daily-marker x to prevent label overlap, but the ticks live at `top: 0` and the daily marker at `bottom: 0` of the 28px tick row — they occupy different vertical bands and don't actually collide. Suppression now only applies to the NOW marker (which sits in the top band alongside hour ticks).
- **Chart hover tooltip simplified and anchored to the bulb curve**: previously the invisible hover trace was anchored to the natural-light (combined) curve with a four-field label (`time · bulbs X% · natural Y% · ZK`). Now it's anchored to the bulb curve (`y: bulbPct`) with a three-field label (`time · X% · YK`) — what the user is pointing at and what the bulbs actually output. The dotted natural-light line keeps `hoverinfo: 'skip'`, so it reads as a decorative "pre-sun-dimming target shape" without inviting interaction.
- **NOW dot + opposite-phase dot added to the chart**: previously only the active-phase handle and (when shifted) the daily marker had on-curve dots. Now every anchor the user cares about has a visible, hoverable callout: active handle (existing, 16px filled colored), daily wake/bed (existing, 7px hollow white, only when shifted), **opposite-phase dot** (new, 7px hollow in that phase's muted color — e.g. faint gold bed dot while cursor is in wake phase), and **NOW dot** (new, 8px cyan-filled on the bulb curve at current time, hover: `now · <time> · <X>% · <YK>`). Ties the dot, cursor line, and NOW pill visually into one anchor.

## 1.2.129
- **NOW tick on phase slider**: phase slider tick row now shows a cyan "NOW" label at the current-time position, so users see where they are on the phase timeline relative to the daily wake/bed marker and the slider handle. Any hour tick within ±12% of NOW is suppressed to prevent label collisions (same rule already used for the daily marker). Computed from `phaseCtx.currentHour` normalized into the `[phaseMin, phaseMax]` window; skipped if outside the narrowed slider range (rare edge case — only possible when the v1.2.128 boundary carves out a very aggressive margin). Kept as plain text (no triangle) to avoid competing visually with the gold daily-marker triangle below.
- **Graph ↔ phase slider live-sync**: previously the two inputs only cross-updated on pointer release — dragging the slider changed the gradient/hero/thumb but left the curve unchanged; dragging the chart handle reshaped the curve and updated brightness/color heroes but left the slider thumb and phase hero frozen. Now both directions update live:
  - *Slider → chart*: `previewSlider` in phase mode now calls `renderMiniChart` with a shallow-copied `areaState` whose `brightness_mid`/`color_mid` are overridden to the preview's shifted midpoint, and passes `adjustedTimes` so the wake/bed vertical line tracks the drag.
  - *Chart → slider*: `renderMiniChartForArea`'s `isDragActive` block now also maps `_chartDrag.dragHour` into the narrowed `phaseCtx` bounds, calls `applyOneSlider` on the phase track (skipped if it's itself being dragged), and updates `slider-hero-phase`.
  - The chart-drag clamp (`_chartDrag.phaseMin/Max`) still uses the **raw** phase window, so chart drag can reach a target that's outside the v1.2.128-narrowed slider range; in that case the slider thumb clamps to the narrowed edge while the chart handle continues past. This is the remaining path that can still trip the `% 24` wrap — flagged in the `project_phase_mid_wrap_audit.md` memo.

## 1.2.128
- **Phase slider now narrows its range dynamically so the shifted midpoint stays inside the phase window** — fixes the 1.2.125-reported bug where setting bed=12:48p (cursor just past descend_start with `bed_brightness ≠ 50%`) rendered the curve as if bed were ~2a. Root cause: `compute_shifted_midpoint` uses the inverse-logistic `mid = target + log((1-ratio)/ratio) / slopeSigned`. When target is close to the phase boundary and brightness ≠ 50%, the `log` term pushes the mid *outside* `[phaseMin, phaseMax]`; downstream `% 24` in `primitives.py` wraps it into the wrong day, and the curve evaluates against the wrong phase. Fix is UI-side (no phase-logic edits in `primitives.py`/`brain.py`/`main.py`): new `computePhaseSafeOffset(cfg, cursorInAscend)` computes the exact log-term shift magnitude from current `bed_brightness`/`wake_brightness`, `bed_speed`/`wake_speed`, and `min_brightness`/`max_brightness`; `buildPhaseCtx` narrows `phaseMin = phaseMinRaw + minOffset`, `phaseMax = phaseMaxRaw - maxOffset` (+15min margin), falling back to raw bounds if extreme brightness + shallow slope would invert the window. Net: you can no longer drag the phase slider to a target whose shifted mid would escape the phase window. Speed is load-bearing — shallower slope → larger required offset. 50% brightness yields zero offset (log term = 0), matching the "no shift needed" intuition. The `% 24` wrap in `primitives.py:1187` and its readers remain flagged for a future cleanup pass (documented in memory).

## 1.2.127
- **NOW pill and sun/moon glyphs now render at distinctly different heights**: 1.2.125 moved pill to `y=1.18` and sun/moon to `y=1.06`, which looked fine on paper (12% of plot height apart) — but the chart is only 190px tall with `margin.t=38` and `margin.b=56`, leaving a plot area of ~96px. 12% of 96px = 11.5px center-to-center, and pill/glyph heights are ~20px/~14px, so they visually overlapped. The root cause was using paper-relative y for both: any small plot collapses the gap. Fix: moved sun/moon **inside** the plot area at `y=0.90` (above the natural-light plateau at ~0.68, below the plot top) and pushed pill to `y=1.26` (in the top margin). Now pill lives in margin, glyphs live in plot's upper breathing room — separation is absolute, not proportional. Cursor line extended to `y1=1.18` to reach the pill's bottom. `margin.t 38 → 36` as small additional trim.

## 1.2.126
- **Renamed "default bed/wake" to "daily bed/wake"** on the phase slider tick-row marker and on the curve's unshifted-handle hover tooltip. "Default" was ambiguous (could be read as factory-default, or as default-for-this-zone); "daily" makes it clear this is the day's scheduled target, distinct from the override the user drags with the slider handle.

## 1.2.125
- **NOW pill lifted, margin trimmed, sun/moon pulled in**: previous 1.2.124 values (pill `y=1.35`, sun/moon `y=1.15`, `margin.t=56`) put the pill near the top canvas edge but left the sun/moon floating in the middle of the upper dead space, making everything read as "one crowded cluster above the chart." Now pill `y=1.18`, sun/moon `y=1.06`, `margin.t=56→38` — pill sits cleanly above the glyphs with a tight, intentional gap, and the chart itself reclaims ~18px of vertical real estate.
- **Cursor line now stops at the bulb dot (no longer reaches the x-axis)**: the dashed vertical previously ran `y=0 → y=1.28`, which meant it visually "passed through" the colored bulb curve and continued down to the axis ticks. Now it runs from `y = cursorBulbY/110 + 0.04` up to `y=1.12` — only in the margin area, connecting the NOW pill to the dot on the curve. Dash pattern changed from the default `'dash'` (~8px segments) to a tighter `'3px,3px'` so the short line reads as decorative stitching rather than a heavy divider.
- **Phase slider: ticks moved next to slider, marker dropped below, overlap hidden**: feedback was threefold — (a) "default bed/wake" label was anonymously labeled "bed"/"wake" (ambiguous since the slider handle itself represents the user's current bed/wake override, so "bed" as a tick-row label read as duplicate/confusing), (b) the label sat on top of tick labels when default time coincided with a rendered tick (`bed 10p` stacked behind tick `10p`), and (c) ticks felt far from the slider. Renamed to `default wake X` / `default bed X`. Swapped in-container positions: ticks now at `top: 0` (right under the slider), marker moved to `bottom: 0` with the triangle flipped to point up (`▲` via `border-bottom`) so it still visually indicates slider position. Any tick within ±12% of the marker's x is suppressed to remove the label collision.
- **KNOWN ISSUE (not fixed this version)**: setting bed time far into the future phase (e.g. 12:48p when current time is also ~12:48p and cursor has *just* crossed into descend) causes the brightness curve to render as if bed were ~2a rather than 12:48p. Root cause appears to be in `state.brightness_mid` computation or `liftMidpointToPhase` on the descend side; flagged for explicit review before touching phase logic.

## 1.2.124
- **Curve card now animates open/close smoothly**: headline-variant cards used `max-height: none` when open, and `none ↔ 0` is a discrete CSS transition (not interpolatable). The body slammed shut/open while the chevron transition looked fine on its own — the net effect read as "immediate." Changed to `max-height: 1600px` so the height animates like every other card (the chart + controls comfortably fit inside 1600px).
- **NOW pill moved up, sun/moon always visible**: previously the pill sat at `y=1.20` right on top of the ☀/☾ glyphs (`y=1.15`), so we hid the glyph whenever the cursor was within ~1.75h of sunrise/sunset. Now the pill sits at `y=1.35` with the cursor line extending to `y=1.28`, and the top margin grew `40 → 56px` to accommodate — the pill sits clearly above the glyph row, so the sun/moon always render (removed the overlap-skip logic). Also addresses a secondary concern that the pill's old position made it look visually tied to the wake slider below.
- **Phase slider tick row tightened**: `.hslider-ticks` height `28 → 20px`, margin-top `6 → 4px`. The 28px container (added in 1.2.122 to house both the default-time marker and the tick labels) introduced a larger-than-necessary gap between the slider and its "wake"/"bed" label + time ticks. Shrunk to the minimum that still fits the triangle + label + bottom-aligned tick text.

## 1.2.123
- **Chevrons now animate in both directions**: opening animated fine; closing skipped straight to the collapsed state because the base CSS had no explicit `transform`, only `transform: rotate(90deg)` when `.is-open`. Transitioning between computed `none` and `rotate(90deg)` is not reliably interpolated by browsers (the spec allows it but many engines treat `none ↔ rotate(Xdeg)` as a discrete change). Added explicit `transform: rotate(0deg)` to the base of every chevron class (`.auto-sched-chevron`, `.tune-lights-chevron`, `.tune-brightness-chevron`, `.tune-adj-chevron-inline`, `.tune-individual-chevron-el`, `.zone-chevron` on `areas.html` + `tune.html`) so both open and close animate smoothly. The Curve card was the most visible symptom — it starts `is-open`, so the first user interaction is always a close, which was the direction that silently skipped animation.

## 1.2.122
- **NOW pill updates live when dragging brightness / color sliders**: previously the pill's `%`/`K` values only refreshed on the periodic (~1-minute) poll, so dragging the brightness or color slider changed the track gradient and the slider's own value label but left the chart's NOW chip stale until the next tick. `previewSlider` now calls `renderMiniChart` with a `markerOverride = { bri, cct }` so the pill reflects the drag position in real time. Added an optional `markerOverride` parameter to `renderMiniChart` so callers can pass live preview values without touching `areaState`.
- **NOW pill no longer covers the ☀/☾ glyphs when cursor is near sunrise/sunset**: the pill's tinted background fully occludes the sun/moon symbol whenever they fall within the pill's horizontal span. Now we skip rendering the glyph when `|sunriseX/sunsetX − cursor| < 1.75h`, which removes the overlap cleanly without reintroducing dead space above the chart.
- **Phase slider's default-time marker is now `{triangle above, label below}` instead of `{label above, triangle below}`**: feedback was the label rendered "on top of the slider" and should sit "below the little down arrow." Expanded `.hslider-ticks` from 12→28px and moved tick labels to `bottom: 0` so the marker (now `::before` for the ↓ triangle + text content) drops into the freed space at the top of the tick area, directly under the slider. Slider itself is not pushed down because the extra tick-row height only lives on the phase slider (the only one with `hslider-ticks`).
- **Chevron transition durations normalized to 0.25s**: two chevron classes (`.tune-adj-chevron-inline`, `.tune-individual-chevron-el`) were at 0.2s while the other five were at 0.25s. Now all card/toggle chevrons animate at the same speed. Also dropped the unnecessary parent-scoped selector on `.tune-individual-chevron-el` so the transition applies wherever the element is rendered.

## 1.2.121
- **Further tightened dead space above the curve**: `margin.t 50 → 40`, NOW pill `y 1.25 → 1.20`, cursor line `y1 1.20 → 1.14`. Sun/moon glyphs raised `y 1.07 → 1.15` so the slightly-cramped layout keeps clearance between the pill and the ☀/☾ glyphs.
- **Curve card chevron now on the left** — matches Auto On / Auto Off / Controls cards. Previous layout had the Curve chevron pinned to the right via `margin-left:auto`, which was the only card that did that.
- **Reset button now adjacent to the value** on brightness/color/phase sliders. Removed `margin-left: auto` from `.hslider-reset` so the ↺ sits immediately after the value instead of floating to the far right edge of the row.
- **Default-time indicator is now a visible label, not a hover tooltip**: the small gold triangle on the phase slider used a `title` attribute + `cursor: help` so you had to hover to discover "default wake 7a". Replaced with a compact visible label (e.g. `wake 7a` / `bed 11p`) above the triangle — no hover required.

## 1.2.120
- **Slider thumbs no longer flattened on top/bottom**: the 18px circular thumb was being clipped by the 8px track's box because `.slider-track` carried `filter: saturate(0.55)` — filter creates a rendering surface sized to the element, which effectively clips overflowing children. On hover the filter became `saturate(1)` (identity), which browsers optimize as "no filter," removing the clip — exactly why the thumb looked correct only when hovered. Moved the track's background + filter onto a new `.slider-track-bg` child div; the thumb is now a sibling outside the filtered box and renders in full at all times.
- **Reclaim wasted space above the curve**: `margin.t 84 → 50` and NOW pill `y 1.45 → 1.25` (cursor line `y1 1.40 → 1.20`). The raised pill left ~40px of dead black space above the curve; the new values keep the pill clearly above the plot without the wasted headroom.
- **Wake/bed labels no longer overlap x-axis tick labels**: the shrunken plot area (from the previous over-tall `margin.t`) caused `y=-0.33` to render only ~20px below the plot, right on top of the time-tick row. Added `yshift: -12` to both wake and bed annotations so they sit cleanly below tick labels regardless of plot height, and bumped `margin.b 44 → 56` to give the shifted labels room.

## 1.2.119
- **Revert 1.2.118 2-step gate change**: the previous version expanded off→on 2-step to ignore the CT delta check. That was the wrong call — our tracked `prev_kelvin` is the authoritative record of what the bulb was last commanded to, and small deltas really are small. Forcing 2-step in that case only slowed down turn-on without benefit. Reverted to the prior gate: 2-step only when `abs(new_kelvin − prev_kelvin) >= two_step_ct_threshold`.

## 1.2.118
- **Area-card power button readable on warm cards**: active-state `.row-controls-left .row-btn` was a solid accent circle — invisible against the amber card shading in evening/warm zones. Switched to a translucent dark chip (`rgba(0,0,0,0.4)` fill, `rgba(0,0,0,0.3)` border) with the accent color preserved on the ⏻ glyph. Reads as a proper button over any card hue, warm or cool.
- **Fix: off→on motion events now always 2-step (no "old-color flash" artifact)**: the 2-step gate in `main.py` skipped entirely when `|new_kelvin − prev_kelvin| < two_step_ct_threshold` — *even for lights coming up from off*. In practice, a cold-power-on bulb may flash its stale internal color (whatever CT it held earlier in the day) before applying the newly-commanded value, regardless of what we last sent. User-observed symptom: motion triggers lights that briefly come up at a daytime CT, then shift to the warm evening target. The small-CT-delta skip now only applies to already-on lights; off→on always proceeds to 2-step (subject to the brightness threshold).

## 1.2.117
- **Cursor dashed line now reaches the NOW pill**: line's y-reference was `y` (data coords) so it stopped at the top of the plot area, leaving a visible gap between the line and the pill floating in the top margin. Changed to `yref: 'paper'` with `y1: 1.40`, so the line extends through the margin straight up into the pill's underside. Line + dot + pill now read as one linked NOW indicator.
- **NOW pill raised further**: `y 1.32 → 1.45`, `margin.t 68 → 84`. Earlier positioning left the pill visually adjacent to the ☾/☀ glyphs and the bed label; moving it higher separates it clearly and affirms its role as an "above-plot header" for the cursor.
- **Slider thumb no longer clipped by header**: `.hslider-row` gap `4px → 10px`. The 18px thumb protrudes 5px above the 8px track; the old 4px gap left the thumb's top half underneath the label/value text row. 10px gives the thumb clear air above the track.
- **Fix: curve no longer flips when bed set to late hours (e.g. 1:10a)**: the v1.2.116 fix for early-bed (before descend_start) inadvertently broke late-bed by anchoring the wide descend phase at `phaseStart` instead of `phaseCenter` — so `bed=1:10a` clamped to noon instead of wrapping to 25:10. Reverted `liftMidpointToPhase` to phase-center anchoring (correct for late-bed wrap). Moved the early-bed fix to its proper layer: in `calcMiniBrightness`, the shifted bed midpoint now clamps to `[tDescend + 0.01, tDescend + 24 − 0.01]` instead of `% 24` wrapping, preventing the shift-induced midpoint from re-wrapping to the following day.

## 1.2.116
- **Slider thumbs no longer clipped**: thumb sized from 22px → 18px (border 2px → 1.5px) and tick row `margin-top: 2px → 8px`. Thumbs now sit clear of tick labels on all three sliders.
- **NOW pill connected to its cursor line**: the dashed vertical at the current time was neutral gray, reading as a plot gridline. Now tinted with the pill's CCT/brightness color (`colorWithAlpha(cctToRGB(markerCCT), 0.7)`), so the line + chip + on-curve dot read as one linked NOW indicator. Frozen state uses the cool blue tone instead.
- **NOW pill raised above moon/sun glyphs**: pill y `1.22 → 1.32`, layout `margin.t 56 → 68`. Prevents the pill from bumping into the ☀/☾ glyphs at times when cursor sits near sunrise or sunset.
- **Curve card now collapsible**: the Curve header was static. Added a chevron + click handler (reusing the existing `toggleChartCard` / `initChartCardState` pair). When a deep link targets Auto-On or Auto-Off (`?focus=auto_on|auto_off|controls`), the Curve collapses automatically so the target card stays near the top of the viewport. Persists open/closed state in `localStorage.chart_collapsed`.
- **Default bed/wake marker more prominent**: the ▾ triangle above the slider track grew `5→7px` tall, gained gold tint (`rgba(255, 215, 120, 0.95)`) and a drop-shadow. Was blend-into-the-track subtle; now reads as a proper landmark.
- **Fix: curve no longer flips when bed_time falls before descend_start**: when a user dragged bed to ~12:40p or earlier (with default `descend_start` at noon/6p), `liftMidpointToPhase` wrapped the shifted midpoint forward 24h, producing a sigmoid centered next morning — the curve showed "bright the whole phase". `liftMidpointToPhase` now branches on phase span: the 24h-wide descend phase anchors at `phaseStart` instead of `phaseCenter`, so early-bed midpoints clamp to `phaseStart + margin` rather than jumping to the following day.

## 1.2.115
- **Graph overhaul — split context to top, controls to bottom**:
  - **Sunrise/sunset move above the plot as ☀/☾ glyphs**: previously sat in a crowded bottom band alongside wake/bed + the Now pill. Now tier-1 above the curve carries passive environmental context (sun position), and tier-1 below the curve is reserved for the things the user *tunes* (wake, bed). Dotted vertical ticks for rise/set removed — the glyphs are anchored at the right x.
  - **Now pill moves above the plot with `NOW` prefix**: was below the x-axis, colliding with wake/bed/sunset labels whenever current time was near any of them. New position above the plot with a `NOW   time · bri% · K` layout. The pill still uses header shading (`tintColorByBrightness` + `readableTextColor`). Freeze state prefix becomes `FROZEN`.
  - **Now dot on the curve itself**: added a small filled circle at `(cursorHour, bulbPct[cursorHour])` so the header's brightness/CCT reading ties to its spot on the curve. Dot fill matches the pill (and header). Non-interactive — the bed/wake handle stays the only draggable marker.
  - **Inactive-phase mute softened**: overlay alpha 0.32 → 0.24. Still recedes the inactive half, but ascend curve reads better when descend is active.
  - **Y-axis ticks reduced to 50/100**: was 0/25/50/75/100 on a 190px-tall chart — too granular for the peak-vs-midpoint story it needs to tell.
  - **X-axis trailing `3a` duplicate removed**: 3a→3a wrapped to the same label. Last tick dropped (loop `i <= 8` → `i < 8`).
  - **`Sunny` / `Cloudy` chip now gated on daylight**: if current time is before sunrise or after sunset, the chip is hidden. No weather story after dark, regardless of area's solar_exposure setting.
  - **Chart margins rebalanced**: top 16 → 56 (room for glyphs + Now pill), bottom 85 → 44 (only wake/bed below now).
- **Bright/Color/Bed sliders visually recede when idle**:
  - **Track thinned from 12px → 8px** (thumb stays 22px): the thumb continues to read as the interactive element; the track becomes a scale, not a lit panel.
  - **Idle saturation 55%, full on hover/drag**: CSS `filter: saturate(0.55)` on `.slider-track` transitions to `saturate(1)` on `:hover` and `.dragging`. The color slider in particular stops dominating the card when not being used.
- **Bed/Wake slider: edge tick + default marker**:
  - **Edge tick at phase boundary**: the hour-based ticks stopped at the last whole hour inside the window (e.g. 12a for a 3a-anchored bed window), leaving the max shift (3a) unmarked. Added an explicit edge tick at `phaseMax` with a muted weight, so the user sees how far the thumb can travel.
  - **Default marker**: small ▾ triangle above the track at the user's configured default wake/bed time. Title-hover reveals the default time. Gives the chart handle's ±delta hover a visual partner on the slider.

## 1.2.114
- **Chart hand cursor now scoped to the drag handle**: Plotly's drag layer applied a hand (`cursor: pointer`) across the entire chart by default, suggesting the whole chart was interactive when in fact only the wake/bed midpoint is draggable. Overrode Plotly's drag-layer cursor to `default`, and added a JS pointer-move handler that toggles `#mini-chart.handle-hover` when the pointer is within 18px of the active midpoint — that class switches the cursor to `grab`, and `dragging` switches to `grabbing`. Non-drag areas now show the plain cursor.

## 1.2.113
- **Area detail polish bundle, round 3**: Three carry-overs from the v1.2.112 screenshot review.
  - **Now pill now matches the header exactly**: The under-cursor pill was tinted via `cctToRGB + colorWithAlpha` (translucent overlay on the chart bg), while the header state bar uses `tintColorByBrightness(cctToRGB(kelvin), brightness)` as a solid fill — so at matching CCT/brightness the two read as different colors. Switched the pill to the same `tintColorByBrightness` approach with a solid bg, `readableTextColor` for the text, and the raw CCT-tint at 0.55 alpha as the border. Header and pill now share one shading formula.
  - **Inactive phase of the graph itself is now muted (not just the labels)**: Previously only the inactive phase's wake/bed line + text labels were dimmed; the curve area of the inactive half still read at full intensity. Added a `rgba(8,10,14,0.32)` rect at `layer: 'above'` spanning the inactive phase window (ascend-range when descend is active, descend-range when ascend is active), so the inactive half visually recedes behind the active half's curve. The existing active-half colored wash (blue/amber at 0.045 alpha) is kept.
  - **Time ticks on the BED / WAKE horizontal slider**: The phase slider at the bottom of the Adjust cluster had no hour markers — the user could see a thumb at 60% but had to guess that 60% meant "around 4p". Added a `.hslider-ticks` row below the track with hour labels spanning the phase window (4h intervals for wide spans, 2h for narrow). Ticks are rebuilt every render from the live `phaseCtx.phaseMin/phaseMax`, so they track adjusted wake/bed times and the ascend/descend switch at midday.

## 1.2.112
- **Area detail polish bundle, round 2**: Follow-ups after reviewing v1.2.111 live.
  - **"On" view-pill no longer reads as a power button**: The home-page `On` filter pill (active state) was orange-filled (`background: var(--accent)`) — same chrome as the row power button, so the natural instinct was "tap to turn off everything." Switched the active state to border-only with orange text, matching the `RHYTHM ZONE` chip's border-only style. Reads as a filter, not an action.
  - **Now-pill tinted with current state**: The under-cursor `time · bri% · K` pill was neutral grey. Now its border + bg are tinted with the current CCT color (`cctToRGB(markerCCT)`) and the alpha scales with brightness (border `0.32 → 0.77`, bg `0.18 → 0.40`). At a glance the pill matches the header — same color, same intensity. Frozen state still uses the cool blue tint to remain visually distinct.
  - **`91%` → `91% curve` (space restored)**: The Lights breadcrumb showed `91%curve` because the literal text node `" curve"` after the `<span>` lost its leading whitespace inside the `display: flex` container (anonymous flex items strip leading whitespace). Replaced with `&nbsp;curve` so the space is preserved.
  - **Per-light impact: `?` cursor → `ⓘ` tap-toggle**: The `cursor: help` + native `title` tooltip on `.tune-light-impact` was invisible on mobile and unfamiliar on desktop. Replaced with an inline `ⓘ` glyph that toggles a breakdown sub-row showing `Purpose ↑N% · CT ↓N%` directly under the row. Works on tap (mobile) and click (desktop), refreshes when the underlying values change, and auto-closes when impact returns to zero.
  - **Active phase line is the bold one (not always wake)**: Previously `wake` was always solid+bold and `bed` was always thinner — even when descend was the active phase. Line weight now switches based on `cursorInAscendGeom`: the active-phase line gets `width: 2.5` + 0.78 alpha, the inactive line gets `width: 1.25` + 0.32 alpha and is capped at the curve y so it doesn't overshoot above the bulb line. Wake/bed text labels under the chart get the same treatment (active full color, inactive 0.45 alpha).
  - **Faint phase wash on the active half**: A very subtle colored rect (`0.045` alpha, blue for ascend / amber for descend) fills the active half of the chart at `layer: 'below'`, so the active phase reads as the foregrounded zone. Faint enough to not compete with the curve.
  - **`RHYTHM ZONE` chip slightly less recessed**: Bumped opacity from 0.55 → 0.72. Was readable but felt almost ghosted next to the area name; now reads as definitely-present-but-secondary.
  - **`MODE` / `ADJUST` labels stay legible on tinted backgrounds**: The toolbar group labels were `color: var(--muted); opacity: 0.55` — fine on the dark panel bg, washed out when the area-state bg is tinted with current CCT. Switched to `rgba(255,255,255,0.78)` + bold + a subtle `text-shadow: 0 1px 2px rgba(0,0,0,0.45)` to hold contrast across both states.
  - **Wake/bed handle hover: time + delta from default**: The drag handle's hover text was `drag to shift wake`. Now: `wake · 7:30a (+30m)<br>drag to shift` — the time is on the thumb, ±delta from the saved default is shown when shifted, and a faint hollow ring marker is added at the original midpoint position so the user can see where "home" is.
  - **Bright/Color override no longer leaks across phase boundary**: The decay-projection gate in `calcMiniBrightness` and `calcMiniColor` only checked the upper bound (`h48 < expiresAt`). For an override set in descend, `expiresAt = tAscend + 24`, which exceeds every hour in the day — so the override was applied across the ascend half too, making the chart show the other phase shifted. Added a lower-bound check (`h48 >= setAt48`) so an override only applies from when it was set forward, within the active phase. Ascend-set overrides happened to work because their `expiresAt = tDescend` already excluded descend hours; this fix makes the gating symmetric.

## 1.2.111
- **Area detail polish bundle**: Deep-link fix + chart overhaul + toolbar labels + Lights card affordance.
  - **Focused deep-link expands target without persisting**: Tapping Auto On / Auto Off from the home page (`?focus=auto_on` or `?focus=auto_off`) now force-expands the target card every time, even if it was collapsed before. The expansion is NOT written to `localStorage` so later visits still respect the user's saved preference. Fix covers both the `toggleAutoBody` write path and the race where `loadAutoScheduleSettings` could close the card after `handleDeepLink` opened it.
  - **Chart anchor always at ascend start**: Reverted the v1.2.102 phase-switching. The x-axis now always starts at `ascend_start` regardless of current phase, so the day reads left-to-right from morning inflection.
  - **Wake/bed drag handle on the curve**: The draggable blue/amber handle is interpolated onto the bulb curve at its midpoint x, instead of floating at y=100. Reads as "pick this point on the curve" — the curve itself is the track.
  - **Dropped floating "now" circle**: The colored header and the new info pill already carry current state. One fewer circle on the chart, less visual noise.
  - **Now info pill**: Replaced the two-line "now / time" label under the cursor with a compact pill `{time} · {bri%} · {K}` with a subtle bg and border. "frozen · " prefix when frozen.
  - **Conditions chip (top-right)**: Derived from `conditionMultiplier` — `Sunny` at ≥0.85, `Cloudy` below. Warm amber border for sunny, cool blue-gray for cloudy.
  - **Line hierarchy**: Wake = solid bold blue (width 2.5), Bed = solid thinner amber (width 1.5) — were both dotted and equal-weight. Now (cursor) line = dashed + muted. Sunrise/sunset stays dotted short + faint. Reads as a clear visual order: primary (wake/bed) > secondary (now) > tertiary (sun).
  - **Page header**: Dropped the "Area:" prefix. Replaced the tiny "rhythm zone" text label with a bordered `RHYTHM ZONE` chip matching the home page style.
  - **Toolbar split with labels**: Added tiny `MODE` and `ADJUST` labels above the left (circadian/power/freeze/boost) and right (full-send/glo-up/glo-down/glo-reset) button clusters. Makes the two clusters read as distinct groups — state-visible toggles vs one-shot actions.
  - **Lights card — full-row tap band + tighter spacing**: The adjustments disclosure is no longer a tiny chevron at the end of the breadcrumb. The whole breadcrumb row is now a tappable band with hover bg and the chevron pinned to the right. Tightened `.tune-hero-block` padding-top from 12 → 4 to close the gap between "Lights" header and "Area Brightness" hero.

## 1.2.110
- **Off-row schedule pill readability**: Off rows previously carried a blanket `opacity: 0.75` on `.row-off-summary`, which compounded with the row's muted text color to render the upcoming-auto pill barely readable — but that's exactly the info a user wants on an off area ("when will this turn on?"). Removed the parent opacity. The `Off` label keeps a scoped 0.55 opacity (it's a state cue, not actionable), and the schedule pill now uses `color: var(--text)` so it punches through clearly.

## 1.2.109
- **Sunrise/Sunset label on home schedule pill**: When the next auto on/off fires on a sunrise/sunset trigger and the schedule is within the ~24h window (no day/date tag shown), the absolute time is replaced with `Sunrise` or `Sunset`. Example: `▲ 7:55p · 10h` → `▲ Sunset · 10h`. Semantic label wins when the user just wants to know "when" in sun-relative terms; the exact fire time is still one tap away in area detail, and the relative tip (`· 22m` / `· 10h`) covers precision as the trigger approaches.
  - **Offsets**: hidden for sub-hour offsets (the label is "sunset-ish" — precision available via the relative tip or area detail). At ≥60 min, the hour-rounded offset is appended: `Sunset +2h`. Keeps the chip compact but signals large shifts.
  - **Beyond 24h**: the schedule pill continues to show the absolute time + day (`8:02p May1 · 10d`). "Sunset May1" would require almanac lookup for a future date and the absolute time is more informative there.
  - **Override/custom**: untouched. If there's an active time-override or a custom (non-sun) schedule, the absolute time is preserved.
  - Backend (`_compute_next_auto_time`) now emits `source` and `sun_offset_min` on the `next_auto_on` / `next_auto_off` payload when the firing comes from the sunrise/sunset rule (not from an override-time or custom schedule). The frontend uses these to decide whether to swap in the label.

## 1.2.108
- **Phase offset hint: compact + recede**: The `(+N)` offset hint next to an area's Wake/Bed time is less crammed on row 3.
  - Shrunk to `font-size: 0.85em` with `opacity: 0.55`, matching the treatment of the relative-time tip on the next-auto pill. Reads as secondary info instead of competing with the Wake/Bed time itself.
  - Large offsets (≥60 min) now render as `H:MM` instead of raw minutes: `(+166)` → `(+2:46)`. Same character count, easier to parse as a duration. Sub-hour offsets stay as `(+25)` / `(−25)` for compactness.

## 1.2.107
- **Home page polish round 2**: Follow-ups after reviewing v1.2.106 live.
  - **Red dot becomes the reset button**: The per-row `↺` reset button is gone. The red mismatch dot (which was already a dirty-state indicator) is now a tap target — 10px dot with a 32×32 invisible hit area, 10px gap from the area name, cursor pointer, hover ring, and tooltip "Reset to rhythm zone". Kills the duplication with the red dot and means row 3 no longer reflows when a row goes dirty/clean.
  - **Zone header matches area width**: Removed `margin-left: 32px` from `.zone-content` so zone header and its area cards share the same left edge. Zone header border-radius updated from `8px 8px 0 8px` to `8px 8px 0 0` for a clean seam.
  - **Desktop width cap on zone-group**: Added `max-width: 720px` on `.zone-group` at ≥768px, so the row cluster (slider + right controls) stays tight on wide monitors instead of leaving a big gap right of the slider.
  - **Naked chevron next to zone name**: Moved the zone expand/collapse chevron out of the right control cluster and inline with the zone name. Stripped the bordered-button chrome; it's now a plain `›` with a muted color and opacity-on-hover. Fixes the visual collision with the row step-down (`∨`) button on area cards.
  - **`RHYTHM ZONE` chip**: Renamed the small `ZONE` chip under the zone wake/bed time to `RHYTHM ZONE` for clarity (short "Zone" read ambiguously next to area names).
  - **Direct `Organize` link**: Replaced the toolbar `⋮` dropdown with a direct `Organize` link. Dropped the `Refresh` menu item — the page already auto-refreshes on an interval. Cleaned up dropdown CSS + `toggleToolbarMenu` + outside-click close handler.

## 1.2.106
- **Home page polish bundle**: Ten coordinated tweaks to the areas/zones list.
  - **Zone chevron moved inline**: The expand/collapse chevron on zone headers no longer floats on the left as a dark circle — it's now a bordered 28×28 button inside the right-side control cluster, so it doesn't look orphaned when the zone renders with `no-tint` (all-off) background. When a zone header has no power button (no on-areas), a hidden placeholder keeps the control cluster balanced.
  - **ZONE chip**: A small uppercase `ZONE` pill renders next to the zone name so zone headers read as a distinct row type at a glance, independent of indentation or tint.
  - **Phase-midpoint delta hint**: Area Wake/Bed labels show a muted `(+28)` / `(−15)` offset versus the zone default, so you can see "this area is 28 min ahead of the zone" without opening detail.
  - **Compact off-row layout**: When an area is off, row collapses to a 2-line summary (`Off` + next-auto schedule) instead of rendering the full slider + step cluster. Saves vertical space in `Off` groups. `data-area-schedule` is preserved so the tick loop still updates the right-side next-auto pill.
  - **Dirty-only reset + inline step buttons**: Extracted `isAreaDirty(area)` helper driving both the red mismatch dot and the reset-↺ button's visibility (hidden via `.is-hidden` when clean). Step ▲/▼ are now laid out horizontally alongside the reset instead of stacked.
  - **Power button visual weight**: Power icon reduced from a heavy filled rectangle to a circular button — transparent when off, amber-filled (`var(--accent)`) when the area is on.
  - **Relative-time hint on schedule pill**: Next-auto pill now appends a muted relative offset (`· 22m` / `· 11h` / `· 2d`) after the absolute time, so you can estimate "how soon" without arithmetic.
  - **`On` filter pill**: View-toggle renamed from `on · off` to `On`, restyled as a rounded pill that fills amber when active — stronger affordance that you're in the on-only filtered view.
  - **Home title promoted**: Home name at top of the page renders at 1.45rem / weight 700 / full-text color (was 1.1rem / 500 / muted), so the page has a clearer hero.
  - **Desktop slider width cap**: Slider track capped at `max-width: 480px` above 768px, so a wide monitor doesn't stretch the slider across the whole viewport.

## 1.2.105
- **Conditions header polish**: Removed the `border-top` divider above the new `Conditions` mini-header — inside the bonded Auto On + Auto Off shell, the divider fragmented one half of the panel. Added 14px left padding so the `CONDITIONS` label aligns with the other field labels (Light / Time / Fade / Trigger / If) instead of sitting flush to the card edge.

## 1.2.104
- **Adjustments label spacing**: Brightness-card hero reads `0% adjustments` again (was `0%adjustments`). The parent `.tune-adj-target` is `display: inline-flex`, which collapses literal whitespace between children; added a `gap: 4px` and split "adjustments" into its own span.
- **Auto card tweaks** (area detail → Auto On / Auto Off):
  - Relative-day labels: `tom (Tue)` → `tomorrow (Tue)` in the next-fire hero.
  - Label column widened from 4.5em to 5.5em so `Trigger` / `Override` align flush with `Light` / `Time` / `Fade`.
  - Offset stepper reads directionally: `5 min before` / `on time` / `5 min after` instead of `-5 min` / `0 min` / `+5 min`.
  - Days summary text (`Every day` / `Weekdays` / `Weekends` / `N days`) renders above the day pills whenever a single schedule claims the row; hidden in two-schedule Custom mode where distribution matters.
  - Fade value ("5 min") now reads as a clear hero (0.85rem, weight 600, solid text color) rather than muted at 0.78rem.
  - Trigger switched from a bare `<select>` to a pill group (`Always` / `Skip if brighter` / `Skip if on`), matching the Light pill pattern. Backed by a hidden input so save/load code didn't need to change shape.
  - Untouched row rephrased: `Only if not touched since auto on` → `Skip if manually touched since last Auto On`, grouped under a new `Conditions` mini-header with label `If`.

## 1.2.103
- **Brightness-card height cap bump**: Raised `.tune-brightness-body` max-height from 500px to 2000px when expanded, so the Individual sub-section shows all lights regardless of area size. Symptom was a 5-light area rendering only 4 rows: backend and DOM both had all 5, but the parent card's `overflow: hidden` was clipping the 5th below the 500px fold.

## 1.2.102
- **Phase-anchored to current phase**: The area-detail chart's x-axis now starts at whichever phase is currently active (`ascend_start` during the wake-to-bed stretch, `descend_start` during the bed-to-wake stretch), so the active phase is always on the left of the chart. Previously the anchor was always `ascend_start`, which pushed `now` to the right half of the chart during evening hours.
- **Inline purpose picker**: Clicking a light's purpose name in the Lights card now opens the purpose picker directly, instead of first expanding the row. Removed the separate trigger button, breakdown line, and meta line that used to live in the expanded row.
- **Per-row "Now" column**: The picker's header gained a `Now` column showing what each purpose would deliver for *this specific light at the current curve position* (e.g. `23%`). Replaces the hover-preview footer, which resized the dropdown width as you scrolled. Dropdown width is now fixed at 320px.
- **Impact tooltip**: The per-light `impact` cell now shows a tooltip when impact is non-zero (dotted underline + help cursor), listing both `Purpose ↑X%` and `CT ↑Y%` contributions consistently, regardless of which factor is zero.

## 1.2.101
- **Purpose picker tabular + preview**: The per-light purpose picker now lays out options as aligned columns (Purpose / Dim / Bright / Off) with a header row, instead of a sentence per row. Selected row gets a `●` marker. A live preview footer shows what the hovered purpose would do to *this specific light* — e.g. `Accent → Kitchen counter would go to 23% (46% area · −50% at curve pos)` — so you can compare options without doing the math. Reserved a disabled `+ New purpose…` slot at the bottom as a future affordance.
- **Phase-anchored curve chart**: The area-detail chart now starts its x-axis at `ascend_start` (typically 3a) and spans 24 hours forward, so **wake is always on the left and bed is always on the right**. The bed handle no longer wraps around midnight — dragging to the right edge of the chart now directly targets the late-night hours. All event markers (wake, bed, sunrise, sunset, cursor) shift into the same window; the `now` cursor moves left-to-right across the day.

## 1.2.100
- **Bonded Auto panel**: Auto On and Auto Off now share a single outer shell (one border, one rounded corner) with a thin divider between. Each sub-section retains its own toggle + collapsible body, so deep-links to `?focus=auto_on` or `?focus=auto_off` still open exactly one side. Focus highlight flashes both the bonded border and the target sub-card's background so it's obvious which side was deep-linked to.

## 1.2.99
- **Bed slider wrap fix**: After release, bed slider no longer jumps to far-left when the target time sits across midnight. `buildPhaseCtx` now wraps the adjusted time into the phase window `[phaseMin, phaseMax]` directly instead of checking against `tAscend`.
- **Phase gradient accuracy**: Phase slider gradient now computes bri/color via direct logistic from the raw shifted midpoint, bypassing `calcMiniBrightness` / `calcMiniColor` whose `liftMidpointToPhase` wraps painted the wrong tone near the edges (e.g., bed at noon with low `bed_brightness` rendered white instead of near-black).

## 1.2.98
- **Horizontal slider stack**: Curve card's vertical Bright + Color sliders replaced with three horizontal rows: **Bright**, **Color**, and **Wake|Bed** (label swaps with phase). Each row has a header (label + hero value + reset ↺) and a gradient track. Reset buttons appear only when there's something to reset: clearing `brightness_override`, `color_override`, or `brightness_mid`/`color_mid` respectively.
- **Phase slider semantics**: The new wake/bed slider represents the **user-facing target time** (e.g., "10p bedtime") — internally converted to the shifted sigmoid midpoint so that at the target time brightness equals `wake_brightness` / `bed_brightness`. Gradient samples 10 points across the phase window and previews what the bulbs would look like **right now** if wake/bed were set to each candidate.
- **`set_phase_time` backend action**: Replaces the short-lived `set_midpoint` action. Accepts target time (user-facing) and calls `compute_shifted_midpoint` internally. Chart drag and phase slider both route through this — drag release now lands exactly on the user-facing time, regardless of `wake_brightness` / `bed_brightness` shift.
- **Per-slider reset actions**: New `reset_brightness_override`, `reset_color_override`, `reset_phase` primitives. Each clears the relevant fields and re-applies lights.

## 1.2.97
- **Drag-release fix**: Chart handle now sends the dragged midpoint directly via new `set_midpoint` backend action (primitives.set_midpoint → area_state). Old path routed through `set_position` which lost precision near the asymptote and was distorted by `bed_brightness` / `wake_brightness` shifts (symptom: dragging bed rightward snapped to ~now-time on release). Release now lands exactly where the user let go.
- **Natural-light curve masking**: Muted dotted curve now only renders at hours where `natural - bulbs ≥ 1%`, so it disappears before sunrise and after sunset (and anywhere else the two coincide) instead of drawing a flat segment along the bulb curve.

## 1.2.96
- **Draggable phase handle on chart**: A colored circle at the top of the active-phase midpoint line can now be dragged (wake during ascend, blue; bed during descend, yellow). Live preview: graph re-renders during drag, Bright% / Color% hero labels update to reflect the new midpoint. On release, the corresponding curve-space position is sent via `set_position` (step mode). Drag is clamped to the active phase window; the inactive line stays locked. Original wake/bed dotted lines remain visible so the delta from the configured time reads at a glance.

## 1.2.95
- **Dual-curve chart: bulbs vs. natural light**: Colorful gradient curve now represents actual bulb output (after sun dimming). A muted dotted line shows the room's natural-light target; the two merge at night when sun isn't dimming anything. Peak-of-divergence labels "natural light" and "bulbs" anchor meaning; hover shows both values (e.g., `bulbs 47% · natural 82%`).
- **Projection math**: Per-hour sun angle uses `getSunElevationAtHour` calibrated to the area's current `sun_bright_factor` anchor. Honors `sun_saturation` + `sun_saturation_ramp` (linear/squared) settings. Backend now exposes these three fields in `/api/area-status`.

## 1.2.94
- **Curve card headline (Phase A)**: Curve card is now always-open — no chevron, no toggle. Graph sits on top, Bright + Color sliders pulled inside the card body directly beneath it. The standalone Circadian slider is gone; circadian-on/off still uses the Enable overlay over the slider row.

## 1.2.93
- **Bigger Adjustments touch target**: Whole "↓N% adjustments ›" group is now one tap target with mobile-friendly padding, not just the chevron glyph.
- **Directional sort arrow**: Sort indicator now shows ↑ or ↓ based on current direction (was the bidirectional ↕, which rendered as a tofu box on some fonts).
- **Default sort = Purpose**: Per-light table opens sorted by Purpose, with name as tiebreak — keeps lights of the same purpose grouped and alphabetized within.

## 1.2.92
- **Inline Adjustments disclosure**: Chevron moved to end of the hero breadcrumb (`91% curve · ↓45% adjustments ›`). Defaults closed; click expands Tuning + Activity rows below. Removed the redundant "Adjustments" header row and the left rule.
- **Arrow notation in breadcrumb**: Adjustments value now reads `↓N%` / `↑N%` for consistency with per-light rows. Stays as `0%` (not `—`) when net is zero so the chevron remains anchored.
- **Individual collapsible header**: New peer-level "Individual" toggle with leading chevron sits above the per-light table. Defaults open; clicking collapses the table.
- **Open/close state**: Both new toggles persist via the existing `_persistCards` pattern (read/write localStorage only when arriving from home; deep-link entries use hard-coded defaults).

## 1.2.91
- **Single Impact column**: Per-light Purpose-impact and CT-impact merged into one Impact value. Drilldown breakdown ("Purpose ↓N% · CT ↑N%") shows in the row's expanded view.
- **Adjustments chevron beside label**: Chevron now sits immediately left of "Adjustments" so the disclosure affordance is obvious.
- **Lights table separated from Adjustments**: Tuning/Activity zones now visually nested inside Adjustments (left rule); per-light table sits below its own divider as a sibling block.
- **Zone-label spacing aligned**: TUNING and ACTIVITY now have matching gap to their first child.
- **Bigger active-sort arrow**: ↕ enlarged so it reads as an arrow rather than two dots.

## 1.2.90
- **Lights card redesign**: Renamed "Brightness" to "Lights". Hero shows Area Brightness up top with a `curve · adjustments` breadcrumb, so the big number's provenance is one glance away.
- **Adjustments split into Tuning / Activity zones**: Tuning holds the user-set sliders (Solar exposure, Room balance); Activity holds transient effects (User brightened, Boost, Dimming, Auto-on fade). Zero-value activity rows collapse automatically with a "None active" placeholder when the zone is quiet.
- **Per-light row cleanup**: Impact and CT deltas render as `↑N%` / `↓N%` (0 becomes `—`). Purpose now reads as a pill instead of a dotted-underline link. Column headers unified to small-caps gray; the orange arrow is reserved for the active sort.

## 1.2.89
- **Sensor impact labels**: Per-scope tokens joined with `+` — e.g. "On + 1m boost", "5m + Alert". Clearer multi-reach representation.
- **Control detail deep-link**: Navigating from area detail pre-expands reach cards containing that area, highlights the source area chip. Back button returns to area detail with Controls card open and scrolled into view.
- **Controls list sorting**: Switches first (solo before non-solo), then motion/camera/contact (alert-only last). Paused and disabled sink to bottom.
- **Card state persistence**: All area detail cards (chart, brightness, controls, lights, auto on/off) save expand/collapse to localStorage when arriving from home page. Focused entry points (tune, control detail, deep links) force only the target card open, keep rest collapsed, and don't write to localStorage.
- **Batch group sync fix**: Per-area group sync no longer deletes batch groups — prevents unnecessary delete+recreate cycle on restart.

## 1.2.87
- **Switch reach labels**: Switch impact now shows per-reach area context — "Solo", "+ Kitchen", "Solo | Kitchen +2" — using feedback primary area when restrict-to-primary is enabled.

## 1.2.86
- **Area detail controls list**: Controls card now shows all controls that reach the area — name, category icon, and a compact impact label (e.g. "On · 5m · Boost"). Click navigates to control detail with back-to-area support. Count shown in collapsed header.

## 1.2.83
- **Camera as separate control type**: Cameras now show as "Camera" with a camera icon in the controls list, distinct from "Motion" sensors. Backend handling unchanged (same data model and event processing).
- **Fix deep-link auto card header**: When deep-linking to auto on/off from home page, the expanded card now correctly shows the resolved time instead of the source label.
- **Home page & area detail UI polish**: Bigger area/zone names, bed/wake, and schedule times. Reduced card padding to offset. Collapsible chart card. Auto card header shows source (Sunrise/Sunset ±offset) when collapsed, resolved time when expanded. Schedule text inherits row color (no pill background). Clickable auto schedule deep-links to area detail.

## 1.2.55
- **Batch groups from all controls**: `get_all_unique_reaches()` now includes multi-area scopes from motion sensors and contact sensors, not just switches.
- **Wire motion/contact event handlers for batch dispatch**: Multi-area motion and contact events now use batch groups when available. `lights_on`, `motion_on_off`, and `motion_on_only` accept `send_command=False` for deferred batch delivery.

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
