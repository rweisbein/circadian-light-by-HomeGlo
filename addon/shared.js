/**
 * Shared utility functions for Circadian Light UI.
 * Used by areas.html, glo-designer.html, and other pages.
 */

/**
 * Convert color temperature (Kelvin) to RGB.
 * Perceptual color mapping for UI display (not physics-based).
 * 500K = red, ~1300K = orange, ~1900K = yellow, 2600K = warm white, 4000K = white, 6500K = cool blue
 *
 * @param {number} kelvin - Color temperature in Kelvin (500-10000)
 * @returns {string} RGB string like "rgb(255,230,200)"
 */
function cctToRGB(kelvin) {
  let k = Math.max(500, Math.min(10000, kelvin));
  let r, g, b;

  if (k <= 700) {
    // Pure red range: 500K → 700K
    r = 255; g = 0; b = 0;
  } else if (k <= 1000) {
    // Red to deep orange: 700K → 1000K
    const t = (k - 700) / 300;
    r = 255; g = 100 * t; b = 20 * t;
  } else if (k <= 1600) {
    // Deep orange range: 1000K → 1600K
    const t = (k - 1000) / 600;
    r = 255; g = 100 + 60 * t; b = 20 + 20 * t;
  } else if (k <= 2200) {
    // Orange to yellow: 1600K → 2200K
    const t = (k - 1600) / 600;
    r = 255; g = 160 + 60 * t; b = 40 + 40 * t;
  } else if (k <= 3000) {
    // Yellow to off-white: 2200K → 3000K
    const t = (k - 2200) / 800;
    r = 255; g = 220 + 25 * t; b = 80 + 140 * t;
  } else if (k <= 4000) {
    // Off-white to white: 3000K → 4000K
    const t = (k - 3000) / 1000;
    r = 255; g = 245 + 10 * t; b = 220 + 35 * t;
  } else {
    // Cool range: 4000K → 6500K+ (light blue)
    const t = Math.min(1, (k - 4000) / 2500);
    r = 255 - 70 * t; g = 255 - 25 * t; b = 255;
  }

  r = Math.max(0, Math.min(255, Math.round(r)));
  g = Math.max(0, Math.min(255, Math.round(g)));
  b = Math.max(0, Math.min(255, Math.round(b)));
  return `rgb(${r},${g},${b})`;
}

/**
 * Add alpha channel to an RGB color string.
 * @param {string} rgb - RGB string like "rgb(255,230,200)"
 * @param {number} alpha - Alpha value 0-1
 * @returns {string} RGBA string like "rgba(255,230,200,0.5)"
 */
function colorWithAlpha(rgb, alpha) {
  const match = rgb.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
  if (match) {
    return `rgba(${match[1]},${match[2]},${match[3]},${alpha})`;
  }
  return rgb;
}

/**
 * Tint/dim a color based on brightness level.
 * Blends toward a dark warm tone instead of black to preserve warm hues.
 * @param {string} rgbStr - RGB string like "rgb(255,230,200)"
 * @param {number} brightness - Brightness percentage 0-100
 * @returns {string} Tinted RGB string
 */
function tintColorByBrightness(rgbStr, brightness) {
  const match = rgbStr.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
  if (!match) return rgbStr;
  const fraction = Math.max(0, Math.min(1, brightness / 100));
  // Floor at 0.50 so low-brightness chips/pills/cards never fade into the dark
  // page bg — the brightness signal still varies (0.50 → 1.00 is a clear range)
  // but the lower half is clipped where it became unreadable on dark surfaces.
  const f = 0.50 + 0.50 * fraction;
  const [sr, sg, sb] = [Number(match[1]), Number(match[2]), Number(match[3])];
  // Blend toward dark warm brown (40,25,10) instead of black to keep warm hues
  const r = Math.round(40 * (1 - f) + sr * f);
  const g = Math.round(25 * (1 - f) + sg * f);
  const b = Math.round(10 * (1 - f) + sb * f);
  return `rgb(${r},${g},${b})`;
}

/**
 * Initialize responsive nav overflow menu.
 * When nav links don't fit, overflow items collapse behind a "..." button with a dropdown.
 */
function initNavOverflow() {
  const nav = document.querySelector('.nav');
  const linksContainer = document.querySelector('.nav-links');
  const moreBtn = document.querySelector('.nav-more');
  const overflow = document.querySelector('.nav-overflow');
  if (!nav || !linksContainer || !moreBtn || !overflow) return;

  function update() {
    // Reset: show all links, hide overflow
    const links = Array.from(linksContainer.querySelectorAll('.nav-link'));
    links.forEach(l => l.style.visibility = '');
    overflow.innerHTML = '';
    moreBtn.style.display = 'none';
    overflow.classList.remove('open');

    // Check if links overflow their container
    if (linksContainer.scrollWidth <= linksContainer.clientWidth) return;

    // Show the more button
    moreBtn.style.display = 'block';

    // Find which links are clipped (their right edge exceeds container right)
    const containerRight = linksContainer.getBoundingClientRect().right;
    for (const link of links) {
      if (link.getBoundingClientRect().right > containerRight + 1) {
        link.style.visibility = 'hidden';
        const item = document.createElement('a');
        item.href = link.href;
        item.className = 'nav-overflow-item';
        if (link.classList.contains('active')) item.classList.add('active');
        // Use title attribute for icon-only links (Settings gear), otherwise textContent
        item.textContent = link.title || link.textContent.trim();
        overflow.appendChild(item);
      }
    }

    // If nothing actually overflowed into dropdown, hide button
    if (overflow.children.length === 0) {
      moreBtn.style.display = 'none';
    }
  }

  // Toggle dropdown on click
  moreBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    overflow.classList.toggle('open');
  });

  // Close on outside click
  document.addEventListener('click', () => {
    overflow.classList.remove('open');
  });

  // Re-check on resize
  new ResizeObserver(update).observe(nav);

  // Initial check
  update();
}

document.addEventListener('DOMContentLoaded', initNavOverflow);

async function initChannelBadge() {
  let channel = 'main';
  try {
    const resp = await fetch('./api/channel');
    if (resp.ok) {
      const data = await resp.json();
      channel = (data && data.channel) || 'main';
    }
  } catch (err) {
    return;
  }
  if (channel !== 'dev' && channel !== 'beta') return;

  const label = channel.toUpperCase();
  if (document.title && !document.title.startsWith(`[${label}]`)) {
    document.title = `[${label}] ${document.title}`;
  }
}

document.addEventListener('DOMContentLoaded', initChannelBadge);

/**
 * Get readable text color (black or white) for a background color.
 * @param {string} bgColor - Background color as rgb/rgba or hex
 * @returns {string} "#000" or "#fff"
 */
function readableTextColor(bgColor) {
  let r, g, b;

  // Try rgb/rgba format
  const rgbMatch = bgColor.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
  if (rgbMatch) {
    r = parseInt(rgbMatch[1]);
    g = parseInt(rgbMatch[2]);
    b = parseInt(rgbMatch[3]);
  } else {
    // Try hex format (#rgb or #rrggbb)
    const hexMatch = bgColor.match(/^#([0-9a-f]{3,6})$/i);
    if (hexMatch) {
      let hex = hexMatch[1];
      if (hex.length === 3) {
        hex = hex[0] + hex[0] + hex[1] + hex[1] + hex[2] + hex[2];
      }
      r = parseInt(hex.substring(0, 2), 16);
      g = parseInt(hex.substring(2, 4), 16);
      b = parseInt(hex.substring(4, 6), 16);
    } else {
      return '#fff'; // Default to white text
    }
  }

  // Calculate perceived brightness (ITU-R BT.709)
  const brightness = (r * 0.299 + g * 0.587 + b * 0.114);
  return brightness > 150 ? '#000' : '#fff';
}

// =============================================================================
// Area Picker Component
// =============================================================================

/**
 * Open an area picker modal for selecting areas.
 * Returns a Promise that resolves with selected area IDs, or null if cancelled.
 *
 * @param {Object} options - Configuration options
 * @param {string} options.title - Modal title (default: "Select Areas")
 * @param {string[]} options.selected - Array of already-selected area IDs (will be disabled)
 * @param {boolean} options.multi - Allow multi-select (default: true)
 * @param {Function} options.onConfirm - Optional callback with array of selected area IDs
 * @param {Function} options.onCancel - Optional callback when cancelled
 * @returns {Promise<string[]|null>} Selected area IDs or null if cancelled
 */
async function openAreaPicker(options = {}) {
  const {
    title = 'Select Areas',
    selected = [],
    multi = true,
    onConfirm,
    onCancel
  } = options;

  // Return a Promise that resolves when user confirms or cancels
  return new Promise(async (resolve) => {

  // Fetch zones and HA areas
  let zones = {};
  let haAreaIds = null;
  try {
    const [gzResp, haResp] = await Promise.all([
      fetch('./api/glozones'),
      fetch('./api/areas')
    ]);
    if (gzResp.ok) {
      const data = await gzResp.json();
      zones = data.zones || {};
    }
    if (haResp.ok) {
      const haAreas = await haResp.json();
      haAreaIds = new Set(haAreas.map(a => a.area_id));
    }
  } catch (err) {
    console.error('Failed to fetch zones:', err);
    resolve(null);
    return;
  }

  // Filter out stale areas (in config but removed from HA)
  if (haAreaIds) {
    for (const [zoneName, zoneData] of Object.entries(zones)) {
      if (zoneData.areas) {
        zoneData.areas = zoneData.areas.filter(area => {
          const areaId = typeof area === 'object' ? (area.id || area.area_id) : area;
          return haAreaIds.has(areaId);
        });
      }
    }
  }

  // Track sort preference (persisted in localStorage)
  let sortMode = localStorage.getItem('areaPicker_sort') || 'custom';

  // Track search filter
  let searchFilter = '';

  // Create modal HTML
  const overlay = document.createElement('div');
  overlay.className = 'area-picker-overlay';
  overlay.innerHTML = `
    <div class="area-picker-modal">
      <div class="area-picker-header">
        <h3>${title}</h3>
        <input type="text" class="area-picker-search" placeholder="Search areas..." autocomplete="off">
        <div class="area-picker-sort">
          <span class="sort-option ${sortMode === 'custom' ? 'active' : ''}" data-sort="custom">Your order</span>
          <span class="sort-separator">|</span>
          <span class="sort-option ${sortMode === 'az' ? 'active' : ''}" data-sort="az">A-Z</span>
        </div>
      </div>
      <div class="area-picker-list"></div>
      <div class="area-picker-footer">
        <button class="btn btn-cancel" id="area-picker-cancel">Cancel</button>
        <button class="btn btn-primary" id="area-picker-confirm">${multi ? 'Add Selected' : 'Select'}</button>
      </div>
    </div>
  `;

  // Add styles if not already present
  if (!document.getElementById('area-picker-styles')) {
    const styles = document.createElement('style');
    styles.id = 'area-picker-styles';
    styles.textContent = `
      .area-picker-overlay {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(0, 0, 0, 0.7);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 300;
        animation: fadeIn 0.15s ease-out;
      }
      @keyframes fadeIn {
        from { opacity: 0; }
        to { opacity: 1; }
      }
      .area-picker-modal {
        background: var(--card, #1a1a1a);
        border: 1px solid var(--line, #333);
        border-radius: 12px;
        width: 90%;
        max-width: 400px;
        max-height: 80vh;
        display: flex;
        flex-direction: column;
        animation: slideUp 0.2s ease-out;
      }
      @keyframes slideUp {
        from { transform: translateY(20px); opacity: 0; }
        to { transform: translateY(0); opacity: 1; }
      }
      .area-picker-header {
        padding: 16px 20px;
        border-bottom: 1px solid var(--line, #333);
      }
      .area-picker-header h3 {
        margin: 0 0 12px 0;
        font-size: 1.1rem;
        color: var(--text, #fff);
      }
      .area-picker-search {
        width: 100%;
        padding: 10px 12px;
        margin-bottom: 12px;
        background: var(--bg, #000);
        border: 1px solid var(--line, #333);
        border-radius: 6px;
        color: var(--text, #fff);
        font-size: 0.9rem;
        outline: none;
        transition: border-color 0.15s;
      }
      .area-picker-search:focus {
        border-color: var(--accent, #feac60);
      }
      .area-picker-search::placeholder {
        color: var(--muted, #888);
      }
      .area-picker-sort {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 0.85rem;
      }
      .sort-option {
        color: var(--muted, #888);
        cursor: pointer;
        padding: 4px 8px;
        border-radius: 4px;
        transition: all 0.15s;
      }
      .sort-option:hover {
        color: var(--text, #fff);
        background: var(--panel, #252525);
      }
      .sort-option.active {
        color: var(--accent, #feac60);
        background: rgba(254, 172, 96, 0.15);
      }
      .sort-separator {
        color: var(--line, #333);
      }
      .area-picker-list {
        flex: 1;
        overflow-y: auto;
        padding: 8px 0;
        min-height: 200px;
        max-height: 400px;
      }
      .area-picker-zone {
        padding: 8px 20px 4px;
        font-size: 0.75rem;
        font-weight: 600;
        color: var(--muted, #888);
        text-transform: uppercase;
        letter-spacing: 0.5px;
      }
      .area-picker-item {
        display: flex;
        align-items: center;
        padding: 10px 20px;
        cursor: pointer;
        transition: background 0.1s;
      }
      .area-picker-item:hover {
        background: var(--panel, #252525);
      }
      .area-picker-item.disabled {
        opacity: 0.4;
        cursor: not-allowed;
      }
      .area-picker-item.disabled:hover {
        background: transparent;
      }
      .area-picker-checkbox {
        width: 18px;
        height: 18px;
        border: 2px solid var(--line, #444);
        border-radius: 4px;
        margin-right: 12px;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
        transition: all 0.15s;
      }
      .area-picker-item.selected .area-picker-checkbox {
        background: var(--accent, #feac60);
        border-color: var(--accent, #feac60);
      }
      .area-picker-item.selected .area-picker-checkbox::after {
        content: '✓';
        color: #000;
        font-size: 12px;
        font-weight: bold;
      }
      .area-picker-name {
        flex: 1;
        font-size: 0.95rem;
        color: var(--text, #fff);
      }
      .area-picker-no-results {
        padding: 24px 20px;
        text-align: center;
        color: var(--muted, #888);
        font-size: 0.9rem;
        font-style: italic;
      }
      .area-picker-footer {
        padding: 16px 20px;
        border-top: 1px solid var(--line, #333);
        display: flex;
        justify-content: flex-end;
        gap: 12px;
      }
      .area-picker-footer .btn {
        padding: 8px 16px;
        border-radius: 6px;
        font-size: 0.9rem;
        cursor: pointer;
        border: none;
        transition: all 0.15s;
      }
      .area-picker-footer .btn-cancel {
        background: var(--panel, #252525);
        color: var(--text, #fff);
      }
      .area-picker-footer .btn-cancel:hover {
        background: var(--line, #333);
      }
      .area-picker-footer .btn-primary {
        background: var(--accent, #feac60);
        color: #000;
      }
      .area-picker-footer .btn-primary:hover {
        filter: brightness(1.1);
      }
    `;
    document.head.appendChild(styles);
  }

  document.body.appendChild(overlay);

  // Track selected items
  const newSelections = new Set();

  // Render the area list
  function renderList() {
    const listEl = overlay.querySelector('.area-picker-list');
    listEl.innerHTML = '';

    const searchLower = searchFilter.toLowerCase().trim();

    // Convert zones to array
    const zoneEntries = Object.entries(zones);

    let hasResults = false;

    // A-Z mode: flatten all areas into one sorted list (no zone headers)
    if (sortMode === 'az') {
      let allAreas = [];
      for (const [, zoneData] of zoneEntries) {
        for (const area of (zoneData.areas || [])) {
          allAreas.push(area);
        }
      }
      // Filter by search
      if (searchLower) {
        allAreas = allAreas.filter(area => {
          const areaName = (typeof area === 'object' ? (area.name || area.id) : area) || '';
          return areaName.toLowerCase().includes(searchLower);
        });
      }
      // Sort alphabetically
      allAreas.sort((a, b) => {
        const nameA = (typeof a === 'object' ? a.name : a) || '';
        const nameB = (typeof b === 'object' ? b.name : b) || '';
        return nameA.localeCompare(nameB);
      });
      hasResults = allAreas.length > 0;
      for (const area of allAreas) {
        appendAreaItem(area);
      }
    } else {
      // Custom mode: group by zone with headers
      for (const [zoneName, zoneData] of zoneEntries) {
        const areas = zoneData.areas || [];
        if (areas.length === 0) continue;

        // Filter areas by search
        let filteredAreas = areas;
        if (searchLower) {
          filteredAreas = areas.filter(area => {
            const areaName = (typeof area === 'object' ? (area.name || area.id) : area) || '';
            return areaName.toLowerCase().includes(searchLower);
          });
        }
        if (filteredAreas.length === 0) continue;

        hasResults = true;

        // Zone header
        const zoneHeader = document.createElement('div');
        zoneHeader.className = 'area-picker-zone';
        zoneHeader.textContent = zoneName;
        listEl.appendChild(zoneHeader);

        // Area items
        for (const area of filteredAreas) {
          appendAreaItem(area);
        }
      }
    }

    function appendAreaItem(area) {
      const areaId = typeof area === 'object' ? area.id : area;
      const areaName = typeof area === 'object' ? (area.name || area.id) : area;
      const isDisabled = selected.includes(areaId);
      const isSelected = newSelections.has(areaId);

      const item = document.createElement('div');
      item.className = 'area-picker-item';
      if (isDisabled) item.classList.add('disabled');
      if (isSelected) item.classList.add('selected');
      item.dataset.areaId = areaId;

      item.innerHTML = `
        <div class="area-picker-checkbox"></div>
        <span class="area-picker-name">${areaName}</span>
      `;

      if (!isDisabled) {
        item.addEventListener('click', () => {
          if (multi) {
            if (newSelections.has(areaId)) {
              newSelections.delete(areaId);
              item.classList.remove('selected');
            } else {
              newSelections.add(areaId);
              item.classList.add('selected');
            }
          } else {
            // Single select - clear others
            newSelections.clear();
            newSelections.add(areaId);
            listEl.querySelectorAll('.area-picker-item.selected').forEach(el => {
              el.classList.remove('selected');
            });
            item.classList.add('selected');
          }
        });
      }

      listEl.appendChild(item);
    }

    // Show "no results" if search yielded nothing
    if (!hasResults && searchLower) {
      const noResults = document.createElement('div');
      noResults.className = 'area-picker-no-results';
      noResults.textContent = 'No areas match your search';
      listEl.appendChild(noResults);
    }
  }

  // Handle search input
  const searchInput = overlay.querySelector('.area-picker-search');
  searchInput.addEventListener('input', (e) => {
    searchFilter = e.target.value;
    renderList();
  });

  // Handle sort toggle
  overlay.querySelectorAll('.sort-option').forEach(opt => {
    opt.addEventListener('click', () => {
      sortMode = opt.dataset.sort;
      localStorage.setItem('areaPicker_sort', sortMode);
      overlay.querySelectorAll('.sort-option').forEach(o => o.classList.remove('active'));
      opt.classList.add('active');
      renderList();
    });
  });

  // Handle cancel
  const closeModal = (result) => {
    overlay.remove();
    document.removeEventListener('keydown', handleKeydown);
    resolve(result);
  };

  overlay.querySelector('#area-picker-cancel').addEventListener('click', () => {
    if (onCancel) onCancel();
    closeModal(null);
  });

  // Click outside to close
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) {
      if (onCancel) onCancel();
      closeModal(null);
    }
  });

  // Handle confirm
  overlay.querySelector('#area-picker-confirm').addEventListener('click', () => {
    const selectedIds = Array.from(newSelections);
    if (onConfirm) onConfirm(selectedIds);
    closeModal(selectedIds);
  });

  // Escape key to close
  const handleKeydown = (e) => {
    if (e.key === 'Escape') {
      if (onCancel) onCancel();
      closeModal(null);
    }
  };
  document.addEventListener('keydown', handleKeydown);

  // Initial render
  renderList();

  }); // end Promise
}

// =============================================================================
// Duration picker — shared between sky-clarity override (settings) and control
// pause (controls list). Six options: 5 min / 1 hour / 4 hours / Day / Week /
// Forever. Pause uses all six; sky clarity uses all six.
// =============================================================================

const DURATION_OPTIONS = [
  { value: '5',       label: '5 min',  minutes: 5 },
  { value: '60',      label: '1 hour', minutes: 60 },
  { value: '240',     label: '4 hours', minutes: 240 },
  { value: '1440',    label: 'Day',    minutes: 1440 },
  { value: '10080',   label: 'Week',   minutes: 10080 },
  { value: 'forever', label: 'Forever', minutes: null },
];

const DURATION_DEFAULT = '240';  // 4 hours — common case for both flows.

// Resolve a picker value to actual minutes, or null for "forever" (no expiry).
function durationValueToMinutes(value) {
  if (value === 'forever' || value == null) return null;
  const n = parseInt(value, 10);
  return Number.isFinite(n) ? n : null;
}

// Compact single-unit countdown display — drops smaller units once a
// larger one is meaningful (3h instead of "3h 15m"; minutes don't matter
// at that scale, same with hours vs days). Returns 'forever' for null
// (matches the duration picker's "Forever" option for consistency
// between the picker and active-state countdown displays).
// Examples with default suffix='left': "25m left", "3h left", "5d left".
// Pass suffix='' for unsuffixed form when the caller wraps with its own
// prefix (e.g., "unpause in 3h").
function formatDurationRemaining(minutes, suffix) {
  if (minutes === null || minutes === undefined) return 'forever';
  if (suffix === undefined) suffix = 'left';
  const m = Math.max(0, Math.round(minutes));
  let unit;
  if (m < 60) unit = m + 'm';
  else {
    const h = Math.round(m / 60);
    if (h < 24) unit = h + 'h';
    else {
      const d = Math.round(h / 24);
      if (d < 7) unit = d + 'd';
      else unit = Math.round(d / 7) + 'w';
    }
  }
  return suffix ? unit + ' ' + suffix : unit;
}

// Build the <option> markup for a duration <select>. Pass excludeForever to
// hide the "Forever" option (kept for future flexibility — not currently
// used anywhere, both pickers now include Forever).
function buildDurationOptions(selectedValue, excludeForever) {
  const opts = excludeForever
    ? DURATION_OPTIONS.filter(o => o.value !== 'forever')
    : DURATION_OPTIONS;
  return opts
    .map(o => `<option value="${o.value}"${o.value === selectedValue ? ' selected' : ''}>${o.label}</option>`)
    .join('');
}

// =============================================================================
// Pulse dot — small white dot indicating recent control activity. Opacity
// fades linearly from 1 to 0 over a configured window (default 6 hours).
// Same color throughout — only brightness/decay reads as the signal.
// Used on area-details Controls card and (future) main controls list.
// =============================================================================

// Returns 0..1 opacity. lastTouchedSeconds is epoch seconds; null/undefined
// means "never touched". windowHours over which the dot decays to invisible.
function pulseOpacity(lastTouchedSeconds, windowHours) {
  if (!lastTouchedSeconds || !windowHours || windowHours <= 0) return 0;
  const nowSec = Date.now() / 1000;
  const elapsedH = Math.max(0, (nowSec - lastTouchedSeconds) / 3600);
  if (elapsedH >= windowHours) return 0;
  return 1 - (elapsedH / windowHours);
}

// Build the pulse-dot HTML. Returns empty string if invisible (so callers can
// render an empty slot for layout stability — see ctrl-fresh-dot-slot etc.).
function buildPulseDot(lastTouchedSeconds, windowHours) {
  const op = pulseOpacity(lastTouchedSeconds, windowHours);
  if (op <= 0) return '';
  return '<span class="pulse-dot" style="opacity: ' + op.toFixed(2) + ';" aria-hidden="true"></span>';
}

// =============================================================================
// Grouping divider — header that splits a list into named buckets with an
// optional count. See `.group-divider` in shared.css. Use anywhere a list
// has named subdivisions: in/reach on area-filtered views, scheduled/permanent
// on the PAUSED control view, etc. Pass count=null to omit the parenthetical.
// =============================================================================
// HomeGlo Lab: how long card-state localStorage persists before
// resetting to defaults. Pages with collapsible cards (area, control,
// rhythm-design) read this at init time — synchronous via the
// localStorage shadow that settings.html writes whenever the Lab
// value changes. Default 15 min.
const _CARD_FRESHNESS_LS_KEY = 'homeglo_card_freshness_min';
function cardFreshnessMs() {
  const raw = localStorage.getItem(_CARD_FRESHNESS_LS_KEY);
  const m = raw == null ? NaN : parseInt(raw, 10);
  return Number.isFinite(m) && m > 0 ? m * 60 * 1000 : 15 * 60 * 1000;
}

function buildGroupDivider(title, count) {
  const countSpan = (count == null)
    ? ''
    : '<span class="group-divider-count">(' + count + ')</span>';
  return '<div class="group-divider">'
    + '<span class="group-divider-title">' + title + '</span>'
    + countSpan
    + '</div>';
}

// =============================================================================
// Control summary — "what this control does", scopes-driven. Shared between
// the controls list page (/switches) and the area-details Controls card. The
// page passes its `allAreas` registry plus optional `filterAreaId` (when
// scoped to one area) and `deviceAreaId` (the control's home area, used for
// switch reach prioritization).
// =============================================================================

function controlSummaryAreaName(areaId, allAreas) {
  const a = (allAreas || []).find(x => x.area_id === areaId);
  return a ? a.name : areaId;
}

// Format a list of area_ids alphabetically: 1-3 names spelled, (+N) for rest.
function controlSummaryFormatAreasList(areaIds, allAreas) {
  if (!areaIds || !areaIds.length) return '';
  const names = areaIds.map(id => controlSummaryAreaName(id, allAreas));
  const sorted = [...names].sort((a, b) => a.localeCompare(b));
  if (sorted.length <= 3) return sorted.join(', ');
  return sorted.slice(0, 3).join(', ') + ' (+' + (sorted.length - 3) + ')';
}

// Format a list of area_ids with priority ordering: filter area first
// (if set), then device's home area (if different and present), then
// the rest sorted alphabetically. Up to 3 names spelled, (+N) for rest.
// Critical for the cap to land correctly — without prioritization the
// filter area can fall past the 3-name cap into "(+N)" purgatory and
// disappear from the visible row.
function controlSummaryFormatAreasListPrioritized(areaIds, allAreas, deviceAreaId, filterAreaId) {
  if (!areaIds || !areaIds.length) return '';
  const remaining = [...areaIds];
  const ordered = [];
  const take = (id) => {
    const idx = remaining.indexOf(id);
    if (idx >= 0) {
      ordered.push(id);
      remaining.splice(idx, 1);
    }
  };
  if (filterAreaId) take(filterAreaId);
  if (deviceAreaId && deviceAreaId !== filterAreaId) take(deviceAreaId);
  remaining.sort((a, b) =>
    controlSummaryAreaName(a, allAreas).localeCompare(controlSummaryAreaName(b, allAreas))
  );
  ordered.push(...remaining);
  const names = ordered.map(id => controlSummaryAreaName(id, allAreas));
  if (names.length <= 3) return names.join(', ');
  return names.slice(0, 3).join(', ') + ' (+' + (names.length - 3) + ')';
}

function controlSummaryFormatSensorModeName(mode) {
  if (mode === 'on_off') return 'on/off';
  if (mode === 'on_only' || mode === 'on') return 'on';
  if (mode === 'alert') return 'alert';
  return mode;
}

// Group sensor scopes by mode → { mode: Set<areaId>, ... }. on_only is
// normalized to 'on' so the rendered label is consistent.
function _ctrlSummaryGroupSensorScopes(scopes) {
  const groups = {};
  for (const s of scopes || []) {
    if (!s.mode || s.mode === 'disabled') continue;
    const key = (s.mode === 'on_only') ? 'on' : s.mode;
    if (!groups[key]) groups[key] = new Set();
    for (const a of (s.areas || [])) groups[key].add(a);
  }
  return groups;
}

// Render one mode group: "<primary>mode</primary> <areas>area-list</areas>".
// When filterAreaId is set (area-filtered context), the filter area is
// pinned to the front of the area list so it can't fall past the 3-name
// cap and disappear into "(+N)".
function _ctrlSummaryRenderSensorGroup(mode, areaSet, allAreas, filterAreaId) {
  const modeLabel = controlSummaryFormatSensorModeName(mode);
  const arr = Array.from(areaSet);
  const areasHtml = filterAreaId
    ? controlSummaryFormatAreasListPrioritized(arr, allAreas, null, filterAreaId)
    : controlSummaryFormatAreasList(arr, allAreas);
  return '<span class="primary">' + modeLabel + '</span>'
    + (areasHtml ? ' <span class="areas">' + areasHtml + '</span>' : '');
}

// Render a set of sensor scopes as "<group> · <group> · ..." with the
// muted middle-dot separator wrapped in .areas so it visually belongs
// with the muted area lists, not the prominent mode names.
function _ctrlSummaryJoinSensorGroups(scopes, allAreas, filterAreaId) {
  const groups = _ctrlSummaryGroupSensorScopes(scopes);
  const order = ['on_off', 'on', 'alert'];
  const segs = [];
  for (const mode of order) {
    if (!groups[mode] || groups[mode].size === 0) continue;
    segs.push(_ctrlSummaryRenderSensorGroup(mode, groups[mode], allAreas, filterAreaId));
  }
  for (const mode in groups) {
    if (!order.includes(mode) && groups[mode].size > 0) {
      segs.push(_ctrlSummaryRenderSensorGroup(mode, groups[mode], allAreas, filterAreaId));
    }
  }
  if (!segs.length) return '';
  return segs.join(' <span class="areas">·</span> ');
}

// Switch — no area filter. Reach 1 areas in primary; "+N reaches" suffix
// in secondary (small + muted) when more scopes exist.
function controlSummarySwitchAllScopes(scopes, allAreas, deviceAreaId) {
  const primary = scopes[0];
  if (!primary) return '';
  const areas = controlSummaryFormatAreasListPrioritized(primary.areas || [], allAreas, deviceAreaId, null);
  const moreReaches = scopes.length - 1;
  let html = '<span class="primary">' + (areas || '&mdash;') + '</span>';
  if (moreReaches > 0) {
    html += ' <span class="secondary">+' + moreReaches + ' reach' + (moreReaches !== 1 ? 'es' : '') + '</span>';
  }
  return html;
}

// Format a list of reach indices as "reach N", "reach N & M",
// "reach A, B & C".
function _ctrlSummaryJoinReachLabels(labels) {
  if (labels.length === 1) return labels[0];
  if (labels.length === 2) return labels[0] + ' & ' + labels[1];
  return labels.slice(0, -1).join(', ') + ' & ' + labels[labels.length - 1];
}

// Switch — area filter active. Two cases:
//   Reach 1 matches the filter → primary reach 1 areas, plus a muted
//     secondary suffix listing additional matching reaches by number
//     (no partner counts; reach 1's areas already convey the partners).
//   Reach 1 doesn't match (Indirect bucket) → all-muted summary, with
//     partner counts for each matching reach since reach 1's prominent
//     content isn't there to imply them.
function controlSummarySwitchAreaFiltered(scopes, filterAreaId, allAreas, deviceAreaId) {
  const matching = [];
  scopes.forEach((s, idx) => {
    if ((s.areas || []).includes(filterAreaId)) matching.push(idx);
  });
  if (!matching.length) return '';
  if (matching[0] === 0) {
    const reach1Areas = scopes[0].areas || [];
    const areasFormatted = controlSummaryFormatAreasListPrioritized(reach1Areas, allAreas, deviceAreaId, filterAreaId);
    let html = '<span class="primary">' + (areasFormatted || '&mdash;') + '</span>';
    const others = matching.slice(1);
    if (others.length > 0) {
      const labels = others.map(i => 'reach ' + (i + 1));
      html += ' <span class="secondary">+ ' + _ctrlSummaryJoinReachLabels(labels) + '</span>';
    }
    return html;
  }
  // Indirect: all matching reaches with partner counts, all muted same-size
  const segs = matching.map(i => {
    const partners = (scopes[i].areas || []).filter(a => a !== filterAreaId).length;
    return partners > 0 ? 'reach ' + (i + 1) + ' (+' + partners + ')' : 'reach ' + (i + 1);
  });
  return '<span class="areas">' + _ctrlSummaryJoinReachLabels(segs) + '</span>';
}

function controlSummarySensorAllScopes(scopes, allAreas) {
  return _ctrlSummaryJoinSensorGroups(scopes || [], allAreas);
}

function controlSummarySensorAreaFiltered(scopes, filterAreaId, allAreas) {
  const matching = (scopes || []).filter(s =>
    s.mode && s.mode !== 'disabled' && (s.areas || []).includes(filterAreaId)
  );
  return _ctrlSummaryJoinSensorGroups(matching, allAreas, filterAreaId);
}

// Top-level dispatcher. opts = { allAreas, filterAreaId, deviceAreaId }.
// Returns the inner HTML for the summary line (excluding the leading glyph
// — callers wrap with `<div class="ctrl-card-summary"><span class="lead">→</span>...</div>`).
function controlSummary(c, opts) {
  opts = opts || {};
  const scopes = c.scopes || [];
  if (!scopes.length) return '';
  const allAreas = opts.allAreas || [];
  const filterAreaId = opts.filterAreaId || null;
  const deviceAreaId = opts.deviceAreaId || c.area_id || null;
  if (c.category === 'switch') {
    return filterAreaId
      ? controlSummarySwitchAreaFiltered(scopes, filterAreaId, allAreas, deviceAreaId)
      : controlSummarySwitchAllScopes(scopes, allAreas, deviceAreaId);
  }
  return filterAreaId
    ? controlSummarySensorAreaFiltered(scopes, filterAreaId, allAreas)
    : controlSummarySensorAllScopes(scopes, allAreas);
}

// Bucket controls when filtering by a specific area. Returns four
// arrays — bucketing rules differ between switches (reach-index based)
// and sensors/cameras/contact (mode based; reach index is irrelevant).
//
//   Switch:   scope 0 hits the area              → direct
//             scope 1+ hits the area, scope 0 doesn't → indirect
//             lives here, no scope reaches it    → doesntReach
//   Sensor*:  any non-alert scope hits the area  → direct
//             alert scope hits the area, no non-alert does → alerts
//             lives here, no scope reaches it    → doesntReach
//
// Each control appears in exactly one bucket. Precedence inside each
// type: direct > indirect/alerts > doesntReach.
function bucketControlsForArea(controls, filterAreaId, currentAreaName) {
  const direct = [];
  const indirect = [];
  const alerts = [];
  const doesntReach = [];
  const livesHere = (c) => currentAreaName != null
    ? c.area_name === currentAreaName
    : c.area_id === filterAreaId;
  for (const c of controls) {
    const scopes = c.scopes || [];
    if (c.category === 'switch') {
      let smallest = -1;
      scopes.forEach(function (s, idx) {
        if ((s.areas || []).includes(filterAreaId) && smallest === -1) smallest = idx;
      });
      if (smallest === 0) direct.push(c);
      else if (smallest > 0) indirect.push(c);
      else if (livesHere(c)) doesntReach.push(c);
    } else {
      const hasDirect = scopes.some(s =>
        (s.mode === 'on' || s.mode === 'on_only' || s.mode === 'on_off')
        && (s.areas || []).includes(filterAreaId));
      const hasAlert = scopes.some(s =>
        s.mode === 'alert' && (s.areas || []).includes(filterAreaId));
      if (hasDirect) direct.push(c);
      else if (hasAlert) alerts.push(c);
      else if (livesHere(c)) doesntReach.push(c);
    }
  }
  return { direct, indirect, alerts, doesntReach };
}

// Summary line for the "Doesn't reach <area>" bucket. Switches use the
// standard non-area-filtered form (their reach-list is naturally an
// area enumeration). Sensors use the mode-prominent form, but with an
// alert-only fallback: if any non-alert scopes have areas, only those
// render (alert info hidden); if only alert scopes have areas, those
// render. Same prominence rules (mode in primary, areas in muted).
function controlSummaryDoesntReach(c, allAreas) {
  if (c.category === 'switch') {
    return controlSummary(c, { allAreas: allAreas, deviceAreaId: c.area_id });
  }
  const groups = _ctrlSummaryGroupSensorScopes(c.scopes || []);
  const hasNonAlert = (groups.on_off && groups.on_off.size > 0)
    || (groups.on && groups.on.size > 0);
  const filtered = (c.scopes || []).filter(s => {
    if (!s.mode || s.mode === 'disabled') return false;
    if (s.mode === 'alert' && hasNonAlert) return false;
    return true;
  });
  return _ctrlSummaryJoinSensorGroups(filtered, allAreas);
}

// =============================================================================
// View segments bar — shared mode-picker component used on the home page,
// controls list, and cheatsheet. Each consuming page mounts it via this
// function with its own views array + onSelect callback. The component
// manages its own collapsed/expanded state internally.
//
// IMPORTANT: call this exactly ONCE per page load. To update the active
// value later, call the returned handle's setActive(value) method —
// don't re-call setupViewSegments. Re-mounting would stack additional
// document click handlers (one per call), and stale handlers fighting
// over state caused the "pill jumps to All before I click" bug.
//
// Options:
//   containerId: id of an existing <div class="view-segments"> in the DOM
//   views:       [{ value, label }, ...] in display order
//   active:      value of the currently-active view
//   onSelect:    (value) => void — called when user picks a non-active view
//
// Returns: { setActive(value) } handle for updating the active view.
// =============================================================================
function setupViewSegments(opts) {
  const container = document.getElementById(opts.containerId);
  if (!container) return null;
  let expanded = false;
  let active = opts.active;

  function render() {
    const activeView = opts.views.find(v => v.value === active) || opts.views[0];
    container.classList.toggle('is-expanded', expanded);
    container.innerHTML =
      '<button class="view-segment active" data-view="' + activeView.value + '">' + activeView.label + '</button>'
      + '<div class="view-segments-popover">'
      + opts.views.map(v => {
          const cls = v.value === active ? 'view-segment active' : 'view-segment';
          return '<button class="' + cls + '" data-view="' + v.value + '">' + v.label + '</button>';
        }).join('')
      + '</div>';
  }

  render();

  // Click handling: outside-click collapses; bar-pill toggles expanded;
  // active-in-popover collapses (no switch); inactive-in-popover triggers
  // onSelect. The handler reads `active` from the closure each call, so
  // updating active via setActive() does NOT need to re-bind.
  document.addEventListener('click', function (e) {
    const seg = e.target.closest && e.target.closest('.view-segment');
    const segContainer = e.target.closest && e.target.closest('#' + opts.containerId);
    if (!segContainer && expanded) {
      expanded = false;
      render();
      return;
    }
    if (!seg || !segContainer) return;
    const isActive = seg.classList.contains('active');
    if (!expanded) {
      expanded = true;
      render();
      return;
    }
    if (isActive) {
      expanded = false;
      render();
      return;
    }
    expanded = false;
    if (opts.onSelect) opts.onSelect(seg.dataset.view);
  });

  return {
    setActive: function (v) {
      active = v;
      expanded = false;
      render();
    },
  };
}
