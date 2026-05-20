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
// Duration picker — shared across pause-control, freeze, boost, power-off.
// Preset list comes from the HomeGlo Lab `duration_picker_presets` setting
// (CSV of minutes + "forever"); a default list applies when unset.
// =============================================================================

const DEFAULT_DURATION_PRESETS = '5,60,240,1440,10080,forever';
const DURATION_DEFAULT = '240';  // 4 hours — common case across pickers.

// Format a minute count into the picker label ("5 min", "1 hour", "Day").
function formatDurationLabel(m) {
  if (m === 1440) return 'Day';
  if (m === 10080) return 'Week';
  if (m < 60) return m + ' min';
  if (m % 60 === 0) {
    const h = m / 60;
    return h === 1 ? '1 hour' : h + ' hours';
  }
  return m + ' min';
}

// Build a single { value, label, minutes } option from a raw preset token.
// Returns null for invalid tokens (silently dropped).
function _makeDurationOption(token) {
  const t = String(token).trim();
  if (!t) return null;
  if (t === 'forever') return { value: 'forever', label: 'Forever', minutes: null };
  const m = parseInt(t, 10);
  if (!Number.isFinite(m) || m <= 0) return null;
  return { value: String(m), label: formatDurationLabel(m), minutes: m };
}

// Resolve the active preset list from config (or fall back to default).
// Returned array is always non-empty; if config parses to nothing, defaults
// are used so pickers always have at least one row to render.
function getDurationOptions() {
  const csv = (typeof window !== 'undefined' && window.cachedConfig)
    ? window.cachedConfig.duration_picker_presets : null;
  const raw = (typeof csv === 'string' && csv.trim()) ? csv : DEFAULT_DURATION_PRESETS;
  const opts = raw.split(',').map(_makeDurationOption).filter(Boolean);
  return opts.length ? opts : DEFAULT_DURATION_PRESETS.split(',').map(_makeDurationOption).filter(Boolean);
}

// Resolve a config minute-count to a picker `value` string. Snaps to an
// existing option when possible; otherwise returns the fallback.
function _resolveDefaultDuration(key, fallback) {
  try {
    const cfg = (typeof window !== 'undefined' && window.cachedConfig) ? window.cachedConfig : {};
    const m = cfg[key];
    if (m == null) return fallback;
    if (m === 0 || m === 'forever') return 'forever';
    const str = String(m);
    return getDurationOptions().find(o => o.value === str) ? str : fallback;
  } catch (_) {
    return fallback;
  }
}

// Per-context default duration helpers — all return a picker `value` string.
function getDefaultPauseDurationValue() { return _resolveDefaultDuration('default_pause_duration_minutes', DURATION_DEFAULT); }
function getDefaultFreezeDurationValue() { return _resolveDefaultDuration('default_freeze_duration_minutes', '60'); }
function getDefaultBoostDurationValue() { return _resolveDefaultDuration('default_boost_duration_minutes', '5'); }
function getDefaultPowerOffDurationValue() { return _resolveDefaultDuration('default_power_off_duration_minutes', 'forever'); }

// Default boost intensity %, falling back to the existing boost_default setting.
function getDefaultBoostIntensity() {
  const cfg = (typeof window !== 'undefined' && window.cachedConfig) ? window.cachedConfig : {};
  const v = cfg.boost_default;
  if (typeof v === 'number' && v > 0 && v <= 100) return v;
  return 30;
}

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
    ? getDurationOptions().filter(o => o.value !== 'forever')
    : getDurationOptions();
  return opts
    .map(o => `<option value="${o.value}"${o.value === selectedValue ? ' selected' : ''}>${o.label}</option>`)
    .join('');
}

// =============================================================================
// Inline duration popover — shared between switches (pause), area-details
// (freeze / boost / power-off sub-lines), and any future caller. Anchors to
// an element, calls back with the chosen `value` ('5' | '60' | ... | 'forever').
// =============================================================================
let _durationPopoverEl = null;
function showDurationPicker(anchorEl, currentVal, onPick) {
  hideDurationPicker();
  const opts = getDurationOptions();
  const pop = document.createElement('div');
  pop.className = 'pause-dur-popover';
  pop.innerHTML = opts.map(o =>
    '<button class="pause-dur-opt' + (o.value === currentVal ? ' active' : '')
      + '" data-val="' + o.value + '">' + o.label + '</button>'
  ).join('');
  document.body.appendChild(pop);
  const r = anchorEl.getBoundingClientRect();
  const vw = window.innerWidth;
  pop.style.top = (r.bottom + 4) + 'px';
  const popW = pop.offsetWidth || 130;
  let left = r.left + r.width / 2 - popW / 2;
  if (left + popW + 8 > vw) left = vw - popW - 8;
  if (left < 8) left = 8;
  pop.style.left = left + 'px';
  pop.addEventListener('click', (e) => {
    const opt = e.target.closest('[data-val]');
    if (opt) {
      try { onPick(opt.dataset.val); } catch (err) { console.error(err); }
      hideDurationPicker();
    }
  });
  // Defer outside-click handler so the click that opened the popover doesn't
  // immediately close it.
  setTimeout(() => {
    document.addEventListener('click', _onDurationPickerOutside);
  }, 0);
  _durationPopoverEl = pop;
}
function hideDurationPicker() {
  if (_durationPopoverEl) {
    _durationPopoverEl.remove();
    _durationPopoverEl = null;
  }
  document.removeEventListener('click', _onDurationPickerOutside);
}
function _onDurationPickerOutside(e) {
  if (_durationPopoverEl && !_durationPopoverEl.contains(e.target)) hideDurationPicker();
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
// "Recent" controls (touched within the recentTouchedWindowMs Lab window —
// default 5 min) get an extra `is-recent` class for the glow + breathing
// animation defined in shared.css. The `animation-delay: -X.Xs` per element
// is computed against absolute time mod animation period, so all dots stay
// in phase across page renders (no flash on re-render).
function buildPulseDot(lastTouchedSeconds, windowHours) {
  const op = pulseOpacity(lastTouchedSeconds, windowHours);
  if (op <= 0) return '';
  const recent = isRecentlyTouched(lastTouchedSeconds);
  const cls = recent ? 'pulse-dot is-recent' : 'pulse-dot';
  // Animation period (seconds) — must match shared.css `pulse-breathe`
  // duration. Sync via absolute-time-derived delay so re-renders pick up
  // the same phase.
  const periodSec = 4;
  const delay = recent
    ? ' animation-delay: -' + ((Date.now() / 1000) % periodSec).toFixed(2) + 's;'
    : '';
  return '<span class="' + cls + '" style="opacity: ' + op.toFixed(2) + ';' + delay + '" aria-hidden="true"></span>';
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

// HomeGlo Lab: how recently a control must have been touched to get
// the "very recent" emphasis (glow + breathing animation on the pulse
// dot). Default 5 min. Same localStorage-shadow pattern.
const _RECENT_WINDOW_LS_KEY = 'homeglo_recent_window_min';
function recentTouchedWindowMs() {
  const raw = localStorage.getItem(_RECENT_WINDOW_LS_KEY);
  const m = raw == null ? NaN : parseInt(raw, 10);
  return Number.isFinite(m) && m > 0 ? m * 60 * 1000 : 5 * 60 * 1000;
}

// True when a control's lastTouched timestamp falls within the recent
// window. Used to add an `is-recent` class on pulse dots for the
// glow + breathing emphasis.
function isRecentlyTouched(lastTouchedSeconds) {
  if (!lastTouchedSeconds) return false;
  const ageMs = Date.now() - lastTouchedSeconds * 1000;
  return ageMs >= 0 && ageMs <= recentTouchedWindowMs();
}

// Compact "when last used" label. Multi-line HTML for the 1-9d range
// (adds time on a second line); single line otherwise.
//   Today  : "8:05p"
//   1-9 d  : "3d" + "8:05p"   (two lines)
//   10-99d : "23d"
//   100+ d : "5/4"
// Returns '' when timestamp is missing.
function formatCompactDateHtml(ts) {
  if (!ts) return '';
  const t = new Date(ts);
  if (isNaN(t.getTime())) return '';
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const tDay = new Date(t.getFullYear(), t.getMonth(), t.getDate());
  const dayDiff = Math.floor((today.getTime() - tDay.getTime()) / 86400000);
  const timeStr = (() => {
    let h = t.getHours();
    const m = t.getMinutes();
    const ap = h >= 12 ? 'p' : 'a';
    h = h % 12 || 12;
    return h + ':' + (m < 10 ? '0' + m : m) + ap;
  })();
  if (dayDiff <= 0) {
    return '<span class="ctrl-card-date-line">' + timeStr + '</span>';
  }
  if (dayDiff < 10) {
    return '<span class="ctrl-card-date-line">' + dayDiff + 'd</span>'
      + '<span class="ctrl-card-date-line ctrl-card-date-sub">' + timeStr + '</span>';
  }
  if (dayDiff < 100) {
    return '<span class="ctrl-card-date-line">' + dayDiff + 'd</span>';
  }
  return '<span class="ctrl-card-date-line">' + (t.getMonth() + 1) + '/' + t.getDate() + '</span>';
}

// Legacy single-string variant kept in case any caller still uses it.
function formatCompactDate(ts) {
  if (!ts) return '';
  const t = new Date(ts);
  if (isNaN(t.getTime())) return '';
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const tDay = new Date(t.getFullYear(), t.getMonth(), t.getDate());
  const dayDiff = Math.floor((today.getTime() - tDay.getTime()) / 86400000);
  if (dayDiff <= 0) {
    let h = t.getHours();
    const m = t.getMinutes();
    const ap = h >= 12 ? 'p' : 'a';
    h = h % 12 || 12;
    return h + ':' + (m < 10 ? '0' + m : m) + ap;
  }
  if (dayDiff < 10) return dayDiff + 'd';
  if (dayDiff < 100) return dayDiff + 'd';
  return (t.getMonth() + 1) + '/' + t.getDate();
}

function buildGroupDivider(title, count, descriptor, opts) {
  opts = opts || {};
  const countSpan = (count == null)
    ? ''
    : '<span class="group-divider-count">(' + count + ')</span>';
  // Descriptor renders without parens — muted lighter color carries the
  // "this is secondary info" cue; double-marking with parens AND lighter
  // text was overkill (especially since the count already uses parens).
  // Order: title → count → descriptor. Reads as "what / how many /
  // what window" left-to-right.
  const descSpan = descriptor
    ? '<span class="group-divider-descriptor">' + descriptor + '</span>'
    : '';
  // Optional collapsible variant: caller provides a bucketKey, we add
  // a chevron + cursor-pointer + `is-collapsible` class. Click handler
  // lives in the consuming page (toggles the matching `.ctrl-bucket-body`
  // by data-bucket-key + persists state).
  if (opts.bucketKey) {
    const initiallyCollapsed = !!opts.collapsed;
    return '<div class="group-divider is-collapsible'
      + (initiallyCollapsed ? ' is-collapsed' : '')
      + '" data-bucket-key="' + opts.bucketKey + '">'
      + '<span class="group-divider-chevron">&rsaquo;</span>'
      + '<span class="group-divider-title">' + title + '</span>'
      + countSpan
      + descSpan
      + '</div>';
  }
  return '<div class="group-divider">'
    + '<span class="group-divider-title">' + title + '</span>'
    + countSpan
    + descSpan
    + '</div>';
}

// Map a control's last-action timestamp to a recency bucket key. Calendar-
// day boundaries (in user's local timezone) so a control used at 11pm
// yesterday lands in 'yesterday' (not 'today' via rolling 24h).
function controlsTimeBucket(ts) {
  if (!ts) return 'never';
  const t = new Date(ts);
  if (isNaN(t.getTime())) return 'never';
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const tDay = new Date(t.getFullYear(), t.getMonth(), t.getDate());
  const dayDiff = Math.floor((today.getTime() - tDay.getTime()) / 86400000);
  if (dayDiff <= 0) return 'today';
  if (dayDiff === 1) return 'yesterday';
  if (dayDiff <= 7) return 'pastweek';
  if (dayDiff <= 30) return 'pastmonth';
  if (dayDiff <= 365) return 'pastyear';
  return 'prior';
}

// Ordered list of recency buckets with display label + optional descriptor
// (parenthetical reminder of what days each bucket covers, since "past
// week" implicitly excludes today/yesterday). Pages iterate this in order
// to render only populated buckets.
const CONTROLS_TIME_BUCKETS = [
  { key: 'today',     label: 'Today',      descriptor: null },
  { key: 'yesterday', label: 'Yesterday',  descriptor: null },
  { key: 'pastweek',  label: 'Past week',  descriptor: '2–7 days ago' },
  { key: 'pastmonth', label: 'Past month', descriptor: '8–30 days ago' },
  { key: 'pastyear',  label: 'Past year',  descriptor: '1–12 months ago' },
  { key: 'prior',     label: 'Prior',      descriptor: null },
  { key: 'never',     label: 'Never used', descriptor: null },
];

// Group-collapse state factory — pages (switches, activity, etc.) call
// `createBucketState('<page>_bucket')` to get a shared API for tracking
// collapsed group dividers in localStorage. Includes a freshness reset so
// the next visit after `cardFreshnessMs()` of inactivity returns to the
// default (all expanded). Different pages use different prefixes to avoid
// key collisions (e.g. 'ctrl_bucket' vs 'activity_bucket').
function createBucketState(keyPrefix) {
  const tsKey = keyPrefix + '_ts';
  const itemKey = (k) => keyPrefix + '_' + k + '_collapsed';
  return {
    maybeResetIfStale() {
      const ts = parseInt(localStorage.getItem(tsKey) || '0', 10);
      if (!ts || Date.now() - ts > (typeof cardFreshnessMs === 'function' ? cardFreshnessMs() : 15 * 60 * 1000)) {
        Object.keys(localStorage).forEach(k => {
          if (k.startsWith(keyPrefix + '_') && k !== tsKey) localStorage.removeItem(k);
        });
        localStorage.setItem(tsKey, String(Date.now()));
      }
    },
    isCollapsed(key) {
      return localStorage.getItem(itemKey(key)) === 'true';
    },
    toggle(key) {
      const cur = this.isCollapsed(key);
      if (cur) localStorage.removeItem(itemKey(key));
      else localStorage.setItem(itemKey(key), 'true');
      localStorage.setItem(tsKey, String(Date.now()));
    },
  };
}

// Battery percentage bucketing for the BATTERY view on the controls
// list. Critical / Low / Medium / Good — answers "how many devices
// need new batteries?" at a glance. Within-bucket sort matches the
// view's existing "lowest first" rule.
const CONTROLS_BATTERY_BUCKETS = [
  { key: 'critical', label: 'Critical', descriptor: '0–10%',  max: 10 },
  { key: 'low',      label: 'Low',      descriptor: '11–25%', max: 25 },
  { key: 'medium',   label: 'Medium',   descriptor: '26–50%', max: 50 },
  { key: 'good',     label: 'Good',     descriptor: '51–100%', max: 100 },
];

function controlsBatteryBucket(value) {
  if (value == null) return null;
  for (const b of CONTROLS_BATTERY_BUCKETS) {
    if (value <= b.max) return b.key;
  }
  return 'good';  // safety net for >100 weirdness
}

// =============================================================================
// Button-row multiplier collapse — shared by the cheatsheet (/switches in
// cheatsheet view) and the area-details Buttons card. If a button's 1× action
// is one of the multi-press base families (step_up, step_down, bright_up,
// bright_down, color_up, color_down) and a higher-press row is literally that
// same id with `_N` appended (e.g. 1× = bright_up, 2× = bright_up_2), the
// higher row is redundant noise — collapse it. Each press level evaluates
// against the 1× id independently, so non-matching levels still render.
// =============================================================================
const _COLLAPSIBLE_MULTIPLIER_BASES = [
  'step_up', 'step_down',
  'bright_up', 'bright_down',
  'color_up', 'color_down',
];
const _MULTIPLIER_PRESS_N = {
  double_press: 2,
  triple_press: 3,
  quadruple_press: 4,
  quintuple_press: 5,
};
function _normalizeActionId(v) {
  if (v && typeof v === 'object') return v.action;
  return v;
}
function shortPressBaseActionId(mapping, btn) {
  if (!mapping) return null;
  return _normalizeActionId(mapping[btn + '_short_release'] || mapping[btn + '_press']) || null;
}
function isRedundantMultiplierRow(baseId, actionType, currentId) {
  if (!baseId || !currentId) return false;
  const n = _MULTIPLIER_PRESS_N[actionType];
  if (!n) return false;
  if (!_COLLAPSIBLE_MULTIPLIER_BASES.includes(baseId)) return false;
  return currentId === baseId + '_' + n;
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

// Format an area list. Sort: home-area-order (areaOrder map) first,
// then alphabetical for areas not in that map, then `(+N)` overflow at
// 6 names. Filter area (if set) is HL-wrapped wherever it lands —
// position not pinned, so every row shows areas in the same canonical
// order regardless of filter (eyes build muscle memory).
function controlSummaryFormatAreasList(areaIds, allAreas, opts) {
  opts = opts || {};
  if (!areaIds || !areaIds.length) return '';
  const filterAreaId = opts.filterAreaId || null;
  const areaOrder = opts.areaOrder || null;
  const sortKey = (id) => {
    if (areaOrder && id in areaOrder) return [0, areaOrder[id], ''];
    return [1, 0, controlSummaryAreaName(id, allAreas).toLowerCase()];
  };
  const sorted = [...areaIds].sort((a, b) => {
    const ka = sortKey(a), kb = sortKey(b);
    if (ka[0] !== kb[0]) return ka[0] - kb[0];
    if (ka[1] !== kb[1]) return ka[1] - kb[1];
    if (ka[2] < kb[2]) return -1;
    if (ka[2] > kb[2]) return 1;
    return 0;
  });
  const CAP = 6;
  const visible = sorted.slice(0, CAP);
  const overflow = sorted.length - CAP;
  const parts = visible.map(id => {
    const name = controlSummaryAreaName(id, allAreas);
    return (filterAreaId && id === filterAreaId)
      ? '<span class="hl">' + name + '</span>'
      : name;
  });
  let result = parts.join(', ');
  if (overflow > 0) result += ' (+' + overflow + ')';
  return result;
}

function controlSummaryFormatSensorModeName(mode) {
  if (mode === 'on_off') return 'Turn on with timer';
  if (mode === 'on_only' || mode === 'on') return 'Turn on';
  if (mode === 'alert') return 'Alert';
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

// Render one summary line: "<label>: <areas>". Label is in default text
// (prominent); area list is muted. Empty areas render as "—".
function _ctrlSummaryLine(label, areasHtml) {
  return '<div class="summary-line">'
    + '<span>' + label + ':</span>'
    + ' <span class="areas">' + (areasHtml || '&mdash;') + '</span>'
    + '</div>';
}

// Sensor — render one summary-line per non-empty mode group, in canonical
// order (on, on/off, alert — `on` is higher-priority signal: stays on
// while presence detected; `on/off` adds a timer; `alert` is passive).
// Each line's area list is sorted in canonical home-area order (via
// opts.areaOrder), with the filter area HL-wrapped wherever it falls.
function _ctrlSummaryRenderSensor(scopes, allAreas, filterAreaId, areaOrder) {
  const groups = _ctrlSummaryGroupSensorScopes(scopes);
  const order = ['on', 'on_off', 'alert'];
  const lines = [];
  const opts = { filterAreaId: filterAreaId, areaOrder: areaOrder };
  const renderGroup = (mode) => {
    const areasHtml = controlSummaryFormatAreasList(Array.from(groups[mode]), allAreas, opts);
    lines.push(_ctrlSummaryLine(controlSummaryFormatSensorModeName(mode), areasHtml));
  };
  for (const mode of order) {
    if (groups[mode] && groups[mode].size > 0) renderGroup(mode);
  }
  for (const mode in groups) {
    if (!order.includes(mode) && groups[mode].size > 0) renderGroup(mode);
  }
  return lines.join('');
}

// Switch — render one summary-line per scope ("1: areas", "2: areas").
// Bare ordinal (no "reach" prefix) — bucket header conveys the reach
// context when filtered, and repetition across multi-scope rows hurt
// readability more than it helped. Always show the ordinal even for
// single-scope switches: keeps every switch row visually consistent
// (scopes are always numbered, regardless of how many there are).
function _ctrlSummaryRenderSwitch(scopes, allAreas, filterAreaId, deviceAreaId, areaOrder) {
  if (!scopes || !scopes.length) return '';
  const opts = { filterAreaId: filterAreaId, areaOrder: areaOrder };
  return scopes.map((s, idx) => {
    const areasHtml = controlSummaryFormatAreasList(s.areas || [], allAreas, opts);
    return _ctrlSummaryLine(String(idx + 1), areasHtml);
  }).join('');
}

// Top-level dispatcher. opts = { allAreas, filterAreaId, deviceAreaId, areaOrder }.
// Returns multi-line HTML (concatenated `<div class="summary-line">…</div>`).
// Caller wraps with `<div class="ctrl-card-summary">…</div>`.
function controlSummary(c, opts) {
  opts = opts || {};
  const scopes = c.scopes || [];
  if (!scopes.length) return '';
  const allAreas = opts.allAreas || [];
  const filterAreaId = opts.filterAreaId || null;
  const deviceAreaId = opts.deviceAreaId || c.area_id || null;
  const areaOrder = opts.areaOrder || null;
  if (c.category === 'switch') {
    return _ctrlSummaryRenderSwitch(scopes, allAreas, filterAreaId, deviceAreaId, areaOrder);
  }
  return _ctrlSummaryRenderSensor(scopes, allAreas, filterAreaId, areaOrder);
}

// Bucket controls when filtering by a specific area. Returns five
// arrays splitting switches and sensors into separate categories
// (different concepts: switch press vs presence trigger).
//
//   Switch:   scope 0 hits the area               → switchDirect
//             scope 1+ hits the area, scope 0 doesn't → switchIndirect
//             lives here, no scope reaches it     → doesntReach
//   Sensor*:  any non-alert scope hits the area   → presence
//             alert scope hits the area, no non-alert does → alerts
//             lives here, no scope reaches it     → doesntReach
//
// Each control appears in exactly one bucket. Sensor with BOTH
// on/on_off AND alert scopes hitting the filter lands in `presence`
// (presence wins precedence over alerts).
function bucketControlsForArea(controls, filterAreaId, currentAreaName) {
  const switchDirect = [];
  const switchIndirect = [];
  const presence = [];
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
      if (smallest === 0) switchDirect.push(c);
      else if (smallest > 0) switchIndirect.push(c);
      else if (livesHere(c)) doesntReach.push(c);
    } else {
      const hasPresence = scopes.some(s =>
        (s.mode === 'on' || s.mode === 'on_only' || s.mode === 'on_off')
        && (s.areas || []).includes(filterAreaId));
      const hasAlert = scopes.some(s =>
        s.mode === 'alert' && (s.areas || []).includes(filterAreaId));
      if (hasPresence) presence.push(c);
      else if (hasAlert) alerts.push(c);
      else if (livesHere(c)) doesntReach.push(c);
    }
  }
  return { switchDirect, switchIndirect, presence, alerts, doesntReach };
}

// Summary for the "Doesn't reach <area>" bucket. Switches use the standard
// (no-filter) form. Sensors use the standard sensor form, but with an
// alert-only fallback: if any non-alert mode has areas, alert lines are
// hidden (the user cares about what the device does, alerts secondary);
// if only alert scopes have any areas, alert lines do render.
function controlSummaryDoesntReach(c, allAreas, areaOrder) {
  if (c.category === 'switch') {
    return controlSummary(c, { allAreas: allAreas, deviceAreaId: c.area_id, areaOrder: areaOrder });
  }
  const groups = _ctrlSummaryGroupSensorScopes(c.scopes || []);
  const hasNonAlert = (groups.on_off && groups.on_off.size > 0)
    || (groups.on && groups.on.size > 0);
  const filtered = (c.scopes || []).filter(s => {
    if (!s.mode || s.mode === 'disabled') return false;
    if (s.mode === 'alert' && hasNonAlert) return false;
    return true;
  });
  return _ctrlSummaryRenderSensor(filtered, allAreas, null, areaOrder);
}

// =============================================================================
// Control list item — unified renderer used by /switches (renderControls)
// and area-details (renderAreaControlsBody). Both pages used to ship their
// own renderer and they drifted (compact date stamp, setup/stale/low-batt/
// magic badges, paused time-remaining were missing from area-details).
// One implementation now, with per-page wiring via opts.
// =============================================================================

// Category labels — short human form for the icon's title attribute.
function formatCategory(category) {
  const labels = {
    'switch': 'Switch',
    'motion_sensor': 'Motion',
    'camera': 'Camera',
    'contact_sensor': 'Contact',
    'unknown': 'Unknown'
  };
  return labels[category] || category || '—';
}

// Category icons — single 18px set used by both control-list pages.
// (Was previously duplicated at 18px in switches.html and 16px in area.html;
// merged to 18px since both contexts can accommodate it and visual
// consistency outweighs the 2px savings on the area-details card.)
function categoryIcon(category) {
  const size = 18;
  const icons = {
    'switch': `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="7" y="2" width="10" height="20" rx="3"/><circle cx="12" cy="8" r="1.5" fill="currentColor" stroke="none"/><circle cx="12" cy="13" r="1.5" fill="currentColor" stroke="none"/><line x1="10" y1="18" x2="14" y2="18"/></svg>`,
    'motion_sensor': `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M8 18 A8 8 0 0 1 8 6"/><path d="M5 20 A12 12 0 0 1 5 4"/><circle cx="14" cy="12" r="3" fill="currentColor" stroke="none" opacity="0.6"/><path d="M17 9 A5 5 0 0 1 17 15"/><path d="M20 7 A8 8 0 0 1 20 17"/></svg>`,
    'contact_sensor': `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="6" width="8" height="12" rx="2"/><rect x="14" y="6" width="8" height="12" rx="2"/><line x1="10" y1="11" x2="14" y2="11" stroke-dasharray="2 2"/><line x1="10" y1="13" x2="14" y2="13" stroke-dasharray="2 2"/></svg>`,
    'camera': `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>`,
  };
  return icons[category] || '—';
}

// Render one control as a list-item row. Same DOM/CSS contract on both
// pages — the only per-page variation is via `opts`.
//
// opts:
//   view              'all' | 'paused' | 'batteries' | 'setup'   (default 'all')
//   doesntReach       bool — switches the summary to the "doesn't reach" form
//   allAreas          area registry array (for summary)
//   filterAreaId      area_id to highlight in the summary, or null
//   areaOrder         { area_id -> index } map for canonical sort
//   pulseWindowHours  pulse-dot fade window (default 6)
//   isPauseFlipped    fn(c) -> bool — paused-view "flipped from snapshot" marker
//   pendingPauseDurations  per-control next-pause duration overrides ({ id: value })
//   makeClickAttr     fn(c) -> string — onclick attribute (e.g. "onCardRowClick(event, 'id')"
//                     or "window.location.href='/control/id?from=area&id=x'")
function renderControlListItem(c, opts) {
  opts = opts || {};
  const view = opts.view || 'all';
  const doesntReach = !!opts.doesntReach;
  const allAreas = opts.allAreas || [];
  const filterAreaId = opts.filterAreaId || null;
  const areaOrder = opts.areaOrder || {};
  const pulseWindowHours = opts.pulseWindowHours || 6;
  const isPauseFlipped = typeof opts.isPauseFlipped === 'function' ? opts.isPauseFlipped : () => false;
  const pendingPauseDurations = opts.pendingPauseDurations || {};
  const makeClickAttr = typeof opts.makeClickAttr === 'function' ? opts.makeClickAttr : () => '';

  const lastTouchedSec = (c.last_action && c.last_action.timestamp)
    ? new Date(c.last_action.timestamp).getTime() / 1000
    : null;
  const pulseHtml = buildPulseDot(lastTouchedSec, pulseWindowHours);
  const icon = categoryIcon(c.category);

  // Title-row badges: paused (+ time left), setup, stale, low-battery, magic icon.
  const badges = [];
  if (c.inactive) {
    let pausedLbl = 'paused';
    const iu = c.inactive_until;
    if (iu && iu !== 'forever') {
      const remMs = new Date(iu) - Date.now();
      if (remMs > 0) pausedLbl = 'paused ' + formatDurationRemaining(remMs / 60000, '');
    }
    badges.push('<span class="ctrl-badge ctrl-badge-paused">' + pausedLbl + '</span>');
  }
  else if (c.status === 'not_configured') badges.push('<span class="ctrl-badge ctrl-badge-setup">setup</span>');
  else if (c.stale) badges.push('<span class="ctrl-badge ctrl-badge-stale">stale</span>');
  if (c.battery && c.battery.value != null && c.battery.value < 10) {
    badges.push('<span class="ctrl-card-lowbatt" title="Low battery">&#9679;</span>');
  }
  if (c.magic_buttons && Object.keys(c.magic_buttons).length > 0) {
    badges.push('<span class="ctrl-card-magic" title="Has magic button assignments">&#10038;</span>');
  }

  // View-specific right-side primary field.
  let primaryHtml = '';
  if (view === 'batteries') {
    const batt = c.battery && c.battery.value;
    if (batt != null) {
      const cls = batt < 10 ? 'ctrl-card-pri ctrl-card-pri-danger'
        : batt < 25 ? 'ctrl-card-pri ctrl-card-pri-warn'
        : batt < 50 ? 'ctrl-card-pri ctrl-card-pri-caution'
        : 'ctrl-card-pri';
      primaryHtml = '<span class="' + cls + '">' + batt + '%</span>';
    } else {
      primaryHtml = '<span class="ctrl-card-pri-muted">&mdash;</span>';
    }
  } else if (view === 'paused') {
    // Slide toggle + clickable duration label. Routed via the page-local
    // handlePauseToggleClick / handlePauseDurClick handlers (only wired
    // up on /switches today; area-details doesn't enter paused view).
    const isPaused = !!c.inactive;
    const toggleTitle = isPaused ? 'Resume' : 'Pause';
    const safeId = c.id.replace(/'/g, "\\'");
    let durLabel;
    if (isPaused) {
      if (!c.inactive_until || c.inactive_until === 'forever') {
        durLabel = 'forever';
      } else {
        const remMs = new Date(c.inactive_until) - Date.now();
        durLabel = remMs > 0 ? formatDurationRemaining(remMs / 60000, '') : 'expired';
      }
    } else {
      const perCard = pendingPauseDurations[c.id];
      const val = perCard || getDefaultPauseDurationValue();
      const opt = getDurationOptions().find(o => o.value === val);
      durLabel = opt ? opt.label.replace(' ', '') : '4hr';
    }
    primaryHtml = '<div class="ctrl-pause-action" data-pause-card="' + safeId + '">'
      + '<button class="ctrl-pause-switch" data-pause-action="toggle" role="switch" aria-pressed="'
      + (isPaused ? 'true' : 'false') + '" title="' + toggleTitle + '"></button>'
      + '<span class="ctrl-pause-dur" data-pause-action="dur" role="button" tabindex="0">' + durLabel + '</span>'
      + '</div>';
  } else {
    // ALL & SETUP: just the area name (or muted "Unassigned" if none).
    const areaNameStr = c.area_name || 'Unassigned';
    const areaCls = c.area_name ? 'ctrl-card-pri' : 'ctrl-card-pri-muted';
    primaryHtml = '<span class="' + areaCls + '">' + areaNameStr + '</span>';
  }

  let rowClass = c.stale ? 'ctrl-card-row is-stale' : 'ctrl-card-row';
  if (view === 'paused' && isPauseFlipped(c)) rowClass += ' is-flipped';

  // "What this controls" summary.
  const summaryHtml = doesntReach
    ? controlSummaryDoesntReach(c, allAreas, areaOrder)
    : controlSummary(c, {
        allAreas: allAreas,
        filterAreaId: filterAreaId,
        deviceAreaId: c.area_id,
        areaOrder: areaOrder,
      });
  const summaryLine = summaryHtml
    ? '<div class="ctrl-card-summary">' + summaryHtml + '</div>'
    : '';

  // Compact "when last used" stamp — sits BELOW the pulse dot in column 1.
  const dateInnerHtml = c.last_action && c.last_action.timestamp
    ? formatCompactDateHtml(c.last_action.timestamp)
    : '';
  const dateHtml = dateInnerHtml
    ? '<span class="ctrl-card-date" title="Last activity">' + dateInnerHtml + '</span>'
    : '';

  const clickAttr = makeClickAttr(c);
  const onclickPart = clickAttr ? ' onclick="' + clickAttr + '"' : '';

  return ''
    + '<div class="' + rowClass + '"' + onclickPart + '>'
    +   '<div class="ctrl-card-pulse">' + pulseHtml + dateHtml + '</div>'
    +   '<div class="ctrl-card-icon" title="' + formatCategory(c.category) + '">' + icon + '</div>'
    +   '<div class="ctrl-card-title">'
    +     '<span class="ctrl-card-title-text">' + c.name + '</span>'
    +     badges.join(' ')
    +   '</div>'
    +   primaryHtml
    +   summaryLine
    + '</div>';
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

// =============================================================================
// SunIntensity — shared popover component.
//
// Drop-in attach: SunIntensity.attach(triggerEl, popoverEl) wires a click
// handler that fetches /api/outdoor-status, renders the breakdown
// (sun angle × sky clarity = intensity), and exposes the override picker
// (condition + duration + Set / clear).
//
// Markup contract:
//   The trigger must contain a child with `[data-sun-icon]` and another with
//   `[data-sun-pct]` for the icon glow + % readout. The popover is positioned
//   with `position: fixed` at runtime so it isn't clipped by overflow:hidden
//   on any ancestor.
//
// Returns a controller: { refresh, close, isOpen, detach }.
//
// ----- Polling -----
// A module-scope poll timer fires `refresh()` on the most-recently-attached
// controller every `pollIntervalSeconds` seconds (default 60). It survives
// re-attaches (timer is module-scope, not per-controller) so dynamic hosts
// like the home toolbar can re-attach freely without resetting the clock.
//
// ----- Usage patterns -----
//
// (A) STATIC HOST (area-details, settings, rhythm-design): the trigger lives
// in static page markup and isn't re-rendered. Attach once on page load.
//
//     SunIntensity.attach(
//       document.getElementById('chart-sun-info'),
//       document.getElementById('chart-sun-popover'),
//       { pollIntervalSeconds: cachedConfig?.outdoor_refresh_interval || 60 }
//     );
//
// (B) DYNAMIC HOST (areas.html — toolbar re-renders every ~3s): cache the
// payload at module scope, pass `initialData` on every re-attach to skip the
// fetch. Detach the previous instance to clear listeners. The polling timer
// continues to run independently and refreshes the latest controller.
//
//     let _cachedOutdoorData = null;
//     let _ctrl = null;
//
//     function attachSunIntensity() {
//       if (_ctrl) _ctrl.detach();
//       _ctrl = SunIntensity.attach(triggerEl, popoverEl, {
//         initialData: _cachedOutdoorData,          // skips initial fetch
//         pollIntervalSeconds: cachedConfig?.outdoor_refresh_interval || 60,
//         onData: (data, pct) => { _cachedOutdoorData = data; },
//       });
//     }
//
// `cachedConfig.outdoor_refresh_interval` is the HomeGlo Lab setting that
// controls the cadence (10–600 sec, default 60).
// =============================================================================
window.SunIntensity = (function () {
  // Module-scope polling state — survives re-attaches on dynamic hosts.
  let _activeController = null;
  let _pollTimer = null;
  let _pollMs = 0;

  function _setPollInterval(ms) {
    if (ms === _pollMs && _pollTimer) return;
    if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
    _pollMs = ms;
    if (ms > 0) {
      _pollTimer = setInterval(() => {
        if (_activeController) _activeController.refresh();
      }, ms);
    }
  }

  const OVERRIDE_CONDITIONS = [
    { value: 'sunny',         label: 'Sunny',         groupKey: 'sunny' },
    { value: 'partlycloudy',  label: 'Partly cloudy', groupKey: 'mixed' },
    { value: 'cloudy',        label: 'Cloudy',        groupKey: 'cloudy' },
    { value: 'rainy',         label: 'Rainy',         groupKey: 'rainy' },
    { value: 'snowy',         label: 'Snowy',         groupKey: 'snowy' },
    { value: 'fog',           label: 'Fog',           groupKey: 'fog' },
    { value: 'pouring',       label: 'Pouring',       groupKey: 'pouring' },
    { value: 'lightning',     label: 'Storm',         groupKey: 'lightning' },
  ];

  function buildClarityIcon(d) {
    if (!d) return '☀️';
    const isOverride = d.source === 'override' && d.override && d.override.condition;
    const cond = (isOverride ? d.override.condition : (d.weather_condition || '')).toLowerCase();
    const cloudCover = isOverride ? 0 : (d.weather_cloud_cover ?? 0);
    if (cond.includes('lightning') || cond.includes('storm')) return '⛈️';
    if (cond.includes('pour')) return '🌧️';
    if (cond.includes('rain')) return '🌦️';
    if (cond.includes('snow')) return '❄️';
    if (cond.includes('fog') || cond.includes('mist')) return '🌫️';
    if (cond.includes('partlycloudy') || cond.includes('partly')) return '⛅';
    if (cond.includes('cloudy') || cloudCover > 70) return '☁️';
    return '☀️';
  }

  function pickDefaultOverrideCondition(data) {
    const cond = (data && data.weather_condition || '').toLowerCase();
    if (cond.includes('lightning') || cond.includes('storm')) return 'lightning';
    if (cond.includes('pour') || cond.includes('hail')) return 'pouring';
    if (cond.includes('rain')) return 'rainy';
    if (cond.includes('snow')) return 'snowy';
    if (cond.includes('fog') || cond.includes('mist')) return 'fog';
    if (cond.includes('partlycloudy') || cond.includes('partly')) return 'partlycloudy';
    if (cond.includes('cloudy')) return 'cloudy';
    return 'sunny';
  }

  function attach(triggerEl, popoverEl, options = {}) {
    if (!triggerEl || !popoverEl) return null;
    let _lastData = null;
    let _pickerOpen = false;

    function isOpen() { return !popoverEl.hidden; }

    function paintTriggerIcon(pct) {
      const iconEl = triggerEl.querySelector('[data-sun-icon]');
      const pctEl = triggerEl.querySelector('[data-sun-pct]');
      if (pctEl) pctEl.textContent = pct + '%';
      if (!iconEl) return;
      const t = Math.max(0, Math.min(100, pct)) / 100;
      // Color stays distinctly yellow at all intensities — at 0% the old
      // rgb(120,100,60) muddied into brown and blended into warm CCT
      // headers. Glow size + saturation scale with t so intensity still
      // reads, and a constant dark outer text-shadow keeps the glyph
      // legible on warm/amber backgrounds.
      const r = Math.round(235 + (255 - 235) * t);
      const g = Math.round(185 + (215 - 185) * t);
      const b = Math.round(60  + (90  - 60 ) * t);
      iconEl.style.color = `rgb(${r}, ${g}, ${b})`;
      iconEl.style.textShadow = [
        `0 0 ${5 + t * 10}px rgba(${r},${g},${b},${0.45 + t * 0.45})`,
        `0 0 1px rgba(0,0,0,1)`,
        `0 0 3px rgba(0,0,0,0.7)`,
      ].join(', ');
    }

    async function refresh() {
      try {
        const res = await fetch('./api/outdoor-status');
        if (!res.ok) return;
        const data = await res.json();
        _lastData = data;
        const pct = Math.max(0, Math.min(100, Math.round((data.outdoor_normalized ?? 0) * 100)));
        paintTriggerIcon(pct);
        if (typeof options.onData === 'function') options.onData(data, pct);
        if (!popoverEl.hidden) render(data);
      } catch (e) { /* leave previous values */ }
    }

    function render(data) {
      const src = data.source || 'none';
      const isActive = !!data.override;
      const anglePct = Math.round((data.angle_factor ?? 0) * 100);
      const outdoorPct = Math.round((data.outdoor_normalized ?? 0) * 100);
      let condPct;
      if (isActive && (data.angle_factor ?? 0) > 0) {
        condPct = Math.round((data.outdoor_normalized / data.angle_factor) * 100);
      } else {
        condPct = Math.round((data.condition_multiplier ?? 1) * 100);
      }
      let condWord = '';
      if (isActive && data.override) {
        condWord = data.override.condition.replace(/_/g, ' ');
      } else if (src === 'weather' && data.weather_condition) {
        condWord = data.weather_condition.replace(/-/g, ' ');
      }

      let rows = '';
      rows += `
        <span class="ocp-op"></span>
        <span class="ocp-label">Sun position</span>
        <span class="ocp-num">${anglePct}%</span>
        <span class="ocp-extras"></span>
      `;
      if (src === 'weather' || src === 'angle' || src === 'override') {
        // Icon alone is enough — the word version overflows the popover when
        // the override picker section is open. Tooltip carries the word.
        const condLine = `<span class="ocp-extras-line"><span class="ocp-cond-icon" title="${condWord || ''}">${buildClarityIcon(data)}</span></span>`;
        let metaLine = '';
        if (isActive) {
          const remaining = formatDurationRemaining(data.override.expires_in_minutes);
          metaLine = `<span class="ocp-extras-line ocp-extras-meta">
            <span class="ocp-tag-override">override</span>
            <span>&middot; ${remaining}</span>
            <button type="button" class="ocp-link-btn" data-act="clear" title="Clear override">clear</button>
          </span>`;
        } else if (!_pickerOpen) {
          metaLine = `<span class="ocp-extras-line ocp-extras-meta">
            <button type="button" class="ocp-link-btn" data-act="toggle-picker">override</button>
          </span>`;
        }
        rows += `
          <span class="ocp-op">&#xd7;</span>
          <span class="ocp-label">Sky clarity</span>
          <span class="ocp-num">${condPct}%</span>
          <span class="ocp-extras">${condLine}${metaLine}</span>
        `;
      }
      rows += `<span class="ocp-pad"></span><div class="ocp-divider"></div><span class="ocp-pad"></span>`;
      rows += `
        <span class="ocp-op"></span>
        <span class="ocp-label ocp-label-total">Sun intensity</span>
        <span class="ocp-num ocp-num-total">${outdoorPct}%</span>
        <span class="ocp-extras"></span>
      `;
      if (!isActive && _pickerOpen) {
        const defaultCond = pickDefaultOverrideCondition(data);
        const groupMap = {};
        (data.weather_groups || []).forEach(g => { groupMap[g.key] = g.multiplier; });
        const condOpts = OVERRIDE_CONDITIONS
          .map(c => {
            const mult = groupMap[c.groupKey];
            const pctSuffix = mult != null ? ' ' + Math.round(mult * 100) + '%' : '';
            return `<option value="${c.value}"${c.value === defaultCond ? ' selected' : ''}>${c.label}${pctSuffix}</option>`;
          })
          .join('');
        rows += `<div class="ocp-section-divider"></div>`;
        rows += `
          <div class="ocp-override">
            <div class="ocp-override-section-header">
              <span class="ocp-override-section-title">Sky clarity override</span>
              <button type="button" class="ocp-link-btn" data-act="toggle-picker">cancel</button>
            </div>
            <div class="ocp-override-controls">
              <select data-act="cond">${condOpts}</select>
              <select data-act="dur">${buildDurationOptions(DURATION_DEFAULT)}</select>
              <button type="button" data-act="set">Set</button>
            </div>
          </div>
        `;
      }
      popoverEl.innerHTML = rows;

      // Wire override handlers (re-attach each render — innerHTML wipes them).
      popoverEl.querySelectorAll('[data-act]').forEach(el => {
        const act = el.dataset.act;
        if (act === 'toggle-picker') {
          el.addEventListener('click', (e) => {
            e.stopPropagation();
            const wasOpen = _pickerOpen;
            _pickerOpen = !_pickerOpen;
            if (_lastData) render(_lastData);
            position();
            if (!wasOpen) {
              const condSel = popoverEl.querySelector('[data-act="cond"]');
              if (condSel) {
                condSel.focus();
                if (typeof condSel.showPicker === 'function') {
                  try { condSel.showPicker(); } catch (_) { /* ignore */ }
                }
              }
            }
          });
        } else if (act === 'set') {
          el.addEventListener('click', async (e) => {
            e.stopPropagation();
            const condition = popoverEl.querySelector('[data-act="cond"]').value;
            const durRaw = popoverEl.querySelector('[data-act="dur"]').value;
            const duration_minutes = durationValueToMinutes(durRaw);
            el.disabled = true;
            el.textContent = 'Setting...';
            try {
              await fetch('./api/outdoor-override', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ condition, duration_minutes }),
              });
              _pickerOpen = false;
              await refresh();
            } catch (err) { console.warn('override set failed:', err); }
            finally { el.disabled = false; }
          });
        } else if (act === 'clear') {
          el.addEventListener('click', async (e) => {
            e.stopPropagation();
            el.disabled = true;
            el.textContent = 'clearing...';
            try {
              await fetch('./api/outdoor-override', { method: 'DELETE' });
              await refresh();
            } catch (err) { console.warn('override clear failed:', err); }
            finally { el.disabled = false; }
          });
        }
      });
    }

    function position() {
      if (popoverEl.hidden) return;
      const r = triggerEl.getBoundingClientRect();
      popoverEl.style.position = 'fixed';
      popoverEl.style.top = (r.bottom + 6) + 'px';
      popoverEl.style.left = r.left + 'px';
      const popW = popoverEl.offsetWidth;
      const vw = window.innerWidth;
      if (r.left + popW + 12 > vw) {
        popoverEl.style.left = Math.max(8, vw - popW - 12) + 'px';
      }
    }

    function toggle(force) {
      const next = force != null ? force : popoverEl.hidden;
      popoverEl.hidden = !next;
      triggerEl.setAttribute('aria-expanded', next ? 'true' : 'false');
      if (next) {
        if (_lastData) render(_lastData);
        position();
        // Always fetch fresh data when opening so the popover doesn't show stale numbers.
        refresh();
      } else {
        _pickerOpen = false;
      }
      if (typeof options.onToggle === 'function') options.onToggle(next);
    }

    const triggerHandler = (e) => { e.stopPropagation(); toggle(); };
    const docHandler = (e) => {
      if (popoverEl.contains(e.target) || triggerEl.contains(e.target)) return;
      if (!popoverEl.hidden) toggle(false);
    };
    triggerEl.addEventListener('click', triggerHandler);
    document.addEventListener('click', docHandler);

    const controller = {
      refresh,
      close: () => toggle(false),
      isOpen,
      detach: () => {
        triggerEl.removeEventListener('click', triggerHandler);
        document.removeEventListener('click', docHandler);
        if (_activeController === controller) _activeController = null;
      },
    };

    // If the host provides cached data from a previous attach, use it and
    // skip the initial fetch — the module-scope poll timer (below) handles
    // true-source freshness. Otherwise, do an initial fetch on attach.
    if (options.initialData) {
      _lastData = options.initialData;
      const pct = Math.max(0, Math.min(100, Math.round((options.initialData.outdoor_normalized ?? 0) * 100)));
      paintTriggerIcon(pct);
      if (typeof options.onData === 'function') options.onData(options.initialData, pct);
    } else {
      refresh();
    }

    // Register as active controller and (re)start the shared poll timer.
    _activeController = controller;
    const pollSec = options.pollIntervalSeconds;
    const pollMs = (typeof pollSec === 'number' && pollSec >= 10 && pollSec <= 600)
      ? pollSec * 1000
      : 60000;  // default 60s; overridden by cachedConfig.outdoor_refresh_interval at the host
    _setPollInterval(pollMs);

    return controller;
  }

  return { attach };
})();

// =============================================================================
// Activity / History rendering — shared across the per-area Activity card
// (area.html) and the all-rooms Activity page (activity.html). Pure rendering
// helpers; callers pass any lookup maps they need so this module stays
// dependency-free from any specific page's state.
// =============================================================================

// User-facing action labels. Keep in sync with primitives.history.record's
// `action` enum.
const HIST_ACTION_LABEL = {
  'restart': 'Addon started',
  'turn_on': 'Turn on',
  'turn_off': 'Turn off',
  'brightness': 'Brightness',
  'color': 'Color',
  'phase': 'Phase',
  'freeze': 'Freeze',
  'unfreeze': 'Unfreeze',
  'freeze_duration_changed': 'Freeze duration',
  'boost': 'Boost',
  'boost_end': 'Boost ended',
  'circadian_on': 'Circadian on',
  'circadian_off': 'Circadian off',
  'auto_off_set': 'Off-timer set',
  'auto_off_cleared': 'Off-timer cleared',
  'glo_down': 'Reset (zone defaults)',
  'glo_up': 'Push to zone',
  'glo_reset': 'Reset (rhythm)',
  'full_send': 'Full send',
  'reset_brightness_override': 'Reset brightness',
  'reset_color_override': 'Reset color',
  'reset_phase': 'Reset phase',
};

// Source kind → display word. Entity follows after a colon when known.
const HIST_SOURCE_LABEL = {
  'switch': 'Switch',
  'motion': 'Motion',
  'contact': 'Contact',
  'app': 'App',
  'auto_schedule': 'Schedule',
  'timer': 'Timer',
  'service_call': 'Service',
  'system': 'System',
};

// Format an absolute timestamp into a compact relative-or-absolute string.
//   Today        → "3:42p"
//   Yesterday    → "Yesterday 3:42p"
//   This year    → "Mon 5/12 3:42p"
//   Older        → "5/12/26 3:42p"
// Verbose timestamp formatter — kept for callers who want a single-line
// human-readable string (e.g. tooltips). The history list renderer uses
// formatCompactDateHtml instead to mirror the Controls list's compact
// 2-line stack ("3d" / "8:05p").
function formatHistoryTs(ts) {
  const d = new Date(ts * 1000);
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  const yest = new Date(now); yest.setDate(yest.getDate() - 1);
  const isYesterday = d.toDateString() === yest.toDateString();
  const sameYear = d.getFullYear() === now.getFullYear();
  let h = d.getHours(), m = d.getMinutes();
  const suffix = h >= 12 ? 'p' : 'a';
  const hr12 = ((h + 11) % 12) + 1;
  const mins = m === 0 ? '' : ':' + (m < 10 ? '0' + m : m);
  const time = hr12 + mins + suffix;
  if (sameDay) return time;
  if (isYesterday) return 'Yesterday ' + time;
  const mo = d.getMonth() + 1;
  const day = d.getDate();
  if (sameYear) {
    const days = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
    return days[d.getDay()] + ' ' + mo + '/' + day + ' ' + time;
  }
  const yr2 = String(d.getFullYear() % 100).padStart(2, '0');
  return mo + '/' + day + '/' + yr2 + ' ' + time;
}

// "Xm ago" compact relative time — used by the Activity card subtitle and
// anywhere else we want freshness-at-a-glance.
function formatRelativeAgo(ts) {
  if (!ts) return '';
  const diff = Date.now() / 1000 - ts;
  if (diff < 0) return '';
  if (diff < 30) return 'just now';
  if (diff < 60) return Math.floor(diff) + 's ago';
  const m = Math.floor(diff / 60);
  if (m < 60) return m + 'm ago';
  const h = Math.floor(m / 60);
  if (h < 24) return h + 'h ago';
  const d = Math.floor(h / 24);
  if (d < 7) return d + 'd ago';
  return Math.floor(d / 7) + 'w ago';
}

// Compute the addon's mount base path from the current URL. Uses the
// server-injected `window.circadianData.pageName` to know which segment to
// strip off the end of `window.location.pathname`. Returns a path string
// (no trailing slash) that can be prefixed with `/<page>` to navigate to
// any sibling page on the same addon — works under HA ingress prefixes
// and direct port access alike, and avoids the fragile "./<page>" relative
// resolution that breaks on `/zone/X`-shaped URLs.
//
// Examples:
//   pathname=/switches,                              page=switches  → ""
//   pathname=/api/hassio_ingress/<tok>/switches,    page=switches  → "/api/hassio_ingress/<tok>"
//   pathname=/zone/X (rhythm-design, page=rhythm-design)            → "/zone/X" (no match; safe fallback)
function getAddonBase() {
  const cd = (typeof window !== 'undefined' && window.circadianData) || {};
  const pageName = cd.pageName || '';
  const path = (window.location.pathname || '').replace(/\/+$/, '');
  if (pageName) {
    const re = new RegExp('/' + pageName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '$');
    if (re.test(path)) return path.replace(re, '');
  }
  return path;
}

// Navigate to a sibling page within the addon (e.g. navToAddonPage('activity')).
function navToAddonPage(pageSegment) {
  const base = getAddonBase();
  window.location.href = base + '/' + pageSegment;
}

// Build a {control_identifier: friendly_name} map from a controls list.
// Keys by BOTH `id` and `device_id` so the lookup works whether the entry
// stored an HA entity_id (motion / contact) or an IEEE (switch).
function buildControlNameLookup(controls) {
  const map = {};
  for (const c of (controls || [])) {
    if (c.id) map[c.id] = c.name || c.id;
    if (c.device_id) map[c.device_id] = c.name || c.device_id;
  }
  return map;
}

// "Switch: Living Hue Dimmer" / "Motion: Master Motion" / "Timer".
// Lookup miss (re-paired device, removed entity, renamed) renders as
// "<word> (unavailable)" — covers all three causes neutrally.
// Kept for any external caller; the new list renderer uses
// formatHistoryDevice + getSourceKindIcon instead.
function formatHistorySource(entry, controlNames) {
  const word = HIST_SOURCE_LABEL[entry.source_kind] || entry.source_kind;
  if (!entry.source_entity) return word;
  const name = controlNames && controlNames[entry.source_entity];
  if (name) return word + ': ' + name;
  return word + ' (unavailable)';
}

// Just the device name (e.g. "Master Motion") — no "Motion:" prefix.
// Empty string when the entry has no source_entity (App, Timer, System).
// "(unavailable)" when the entity exists but isn't in the controls map
// (re-paired, removed, renamed). The icon column carries the source-kind
// semantics so we no longer prefix the device with the kind word.
function formatHistoryDevice(entry, controlNames) {
  if (!entry.source_entity) return '';
  const name = controlNames && controlNames[entry.source_entity];
  if (name) return name;
  return '(unavailable)';
}

// Source-kind icon vocabulary. Switch/motion/contact/camera are visually
// consistent with the Controls page icons (switches.html getControlIcon).
// App / timer / auto_schedule / service_call / system are new for the
// activity-list rendering.
const _HIST_ICON_SVG = {
  switch: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="7" y="2" width="10" height="20" rx="3"/><circle cx="12" cy="8" r="1.5" fill="currentColor" stroke="none"/><circle cx="12" cy="13" r="1.5" fill="currentColor" stroke="none"/><line x1="10" y1="18" x2="14" y2="18"/></svg>',
  motion: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M8 18 A8 8 0 0 1 8 6"/><path d="M5 20 A12 12 0 0 1 5 4"/><circle cx="14" cy="12" r="3" fill="currentColor" stroke="none" opacity="0.6"/><path d="M17 9 A5 5 0 0 1 17 15"/><path d="M20 7 A8 8 0 0 1 20 17"/></svg>',
  contact: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="6" width="8" height="12" rx="2"/><rect x="14" y="6" width="8" height="12" rx="2"/><line x1="10" y1="11" x2="14" y2="11" stroke-dasharray="2 2"/><line x1="10" y1="13" x2="14" y2="13" stroke-dasharray="2 2"/></svg>',
  camera: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>',
  // App: phone/tap — a smartphone outline with a tap dot.
  app: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="2" width="14" height="20" rx="2.5"/><circle cx="12" cy="18" r="1" fill="currentColor" stroke="none"/></svg>',
  // Timer: clock with hands.
  timer: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="13" r="8"/><polyline points="12 9 12 13 15 15"/><line x1="9" y1="2" x2="15" y2="2"/></svg>',
  // Auto schedule: calendar with header tabs.
  auto_schedule: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="17" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="16" y1="2" x2="16" y2="6"/></svg>',
  // Service call: API/server rack with status dots.
  service_call: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="6" rx="1"/><rect x="3" y="14" width="18" height="6" rx="1"/><line x1="7" y1="7" x2="7.01" y2="7"/><line x1="7" y1="17" x2="7.01" y2="17"/></svg>',
  // System: simple gear/sun — center circle + 8 spokes.
  system: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M22 12h-3M5 12H2M19.07 4.93l-2.12 2.12M7.05 16.95l-2.12 2.12M19.07 19.07l-2.12-2.12M7.05 7.05L4.93 4.93"/></svg>',
};

function getSourceKindIcon(kind) {
  return _HIST_ICON_SVG[kind] || _HIST_ICON_SVG.system;
}

// Details cell content. Empty for binary actions; populated for value-bearing
// actions (brightness/color/phase delta, duration, intensity, etc.).
function formatHistoryDetails(entry) {
  const parts = [];
  if (entry.action === 'brightness') {
    if (entry.from_value != null && entry.to_value != null) {
      parts.push(Math.round(entry.from_value) + '% → ' + Math.round(entry.to_value) + '%');
    } else if (entry.brightness != null) {
      parts.push(entry.brightness + '%');
    }
  } else if (entry.action === 'color') {
    if (entry.from_value != null && entry.to_value != null) {
      parts.push(Math.round(entry.from_value) + 'K → ' + Math.round(entry.to_value) + 'K');
    } else if (entry.kelvin != null) {
      parts.push(entry.kelvin + 'K');
    }
  } else if (entry.action === 'phase') {
    if (entry.to_value != null) parts.push('pos ' + Math.round(entry.to_value));
  } else if (entry.action === 'freeze' || entry.action === 'boost' || entry.action === 'auto_off_set') {
    if (entry.duration_minutes != null) {
      parts.push(formatDurationRemaining(entry.duration_minutes, ''));
    } else if (entry.action !== 'auto_off_set') {
      parts.push('forever');
    }
    if (entry.action === 'boost' && entry.intensity != null) {
      parts.push('+' + entry.intensity + '%');
    }
  } else if (entry.action === 'freeze_duration_changed') {
    // None duration → "indefinite" (user cleared the auto-expire).
    if (entry.duration_minutes != null) {
      parts.push(formatDurationRemaining(entry.duration_minutes, ''));
    } else {
      parts.push('indefinite');
    }
  } else if (entry.action === 'turn_on' || entry.action === 'turn_off') {
    const bri = entry.brightness, ke = entry.kelvin;
    const bits = [];
    if (bri != null) bits.push(bri + '%');
    if (ke != null) bits.push(ke + 'K');
    if (bits.length) parts.push(bits.join(', '));
    if (entry.is_2step) parts.push('2-step');
  } else if (entry.brightness != null || entry.kelvin != null) {
    // Reset / glo_* / circadian_on/off → show landing state context.
    const bits = [];
    if (entry.brightness != null) bits.push(entry.brightness + '%');
    if (entry.kelvin != null) bits.push(entry.kelvin + 'K');
    if (bits.length) parts.push(bits.join(', '));
  }
  if (entry.is_zone_action) parts.push('(zone-wide)');
  return parts.join(' · ');
}

// Render a list of history entries as stacked card-style rows.
//
// Layout per row:
//   [source-kind icon] [optional: area · ] [action]      [time]
//                      [device · details · ...]            <- omitted when empty
//
// The icon column carries the source-kind semantics (Switch/Motion/App/
// Timer/etc.) — we no longer prefix the device with a "Kind: " label.
// Title attribute on the icon surfaces the kind name on hover (desktop).
//
// opts:
//   showArea     — include the area name on the top row (Activity page; default false)
//   areaNames    — { area_id: friendly_name } map (required when showArea)
//   controlNames — { id|device_id: name } map for device attribution
//   scrollable   — wrap the list in a fixed-height scroll container
//   maxHeight    — CSS height for the scroll container (e.g. "70vh", "400px")
//   emptyMessage — text shown when entries is empty
function renderHistoryList(entries, opts) {
  opts = opts || {};
  if (!entries || !entries.length) {
    const msg = opts.emptyMessage || 'No activity yet — recording starts when the addon last restarts.';
    return '<div class="tune-history-empty">' + msg + '</div>';
  }
  const showArea = !!opts.showArea;
  const areaNames = opts.areaNames || {};
  const controlNames = opts.controlNames || {};
  const esc = (s) => String(s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));

  const rows = entries.map(e => {
    // Compact 2-line date/time stack (matches Controls list — today is
    // single-line "8:05p"; 1-9d is "Xd" / "8:05p"; older is "Xd" alone or
    // "M/D"). Hover title surfaces the verbose form for new users.
    const tsHtml = formatCompactDateHtml(e.ts * 1000);
    const tsTitle = formatHistoryTs(e.ts);
    const action = HIST_ACTION_LABEL[e.action] || e.action;
    const device = formatHistoryDevice(e, controlNames);
    const details = formatHistoryDetails(e);
    const kindLabel = HIST_SOURCE_LABEL[e.source_kind] || e.source_kind;
    const icon = getSourceKindIcon(e.source_kind);

    // Headline cell (row 1, col 3): optional [area · ] action.
    let headline = '';
    if (showArea) {
      const aName = e.area_id ? (areaNames[e.area_id] || e.area_id) : '';
      if (aName) {
        headline += '<span class="hist-area">' + esc(aName) + '</span>'
                  + '<span class="hist-sep">·</span>';
      }
    }
    headline += esc(action);

    // Sub cell (row 2, col 3): device · details, joined by middot. Omitted
    // entirely when both are empty (e.g. a System "restart" marker) so the
    // row collapses to a single visual line.
    const subParts = [];
    if (device) subParts.push(esc(device));
    if (details) subParts.push(esc(details));
    const subLine = subParts.join(' <span class="hist-sep">·</span> ');

    // 3-column grid: time | icon | content. Time + icon span both rows so
    // they read as "when" / "what kind" anchors next to a self-contained
    // content block. Matches the Controls list layout pattern.
    return '<div class="hist-row">'
      + '<div class="hist-time" title="' + esc(tsTitle) + '">' + tsHtml + '</div>'
      + '<div class="hist-icon" title="' + esc(kindLabel) + '">' + icon + '</div>'
      + '<div class="hist-headline">' + headline + '</div>'
      + (subLine ? '<div class="hist-sub">' + subLine + '</div>' : '')
      + '</div>';
  }).join('');

  const list = '<div class="hist-list">' + rows + '</div>';

  if (opts.scrollable) {
    const h = opts.maxHeight || '60vh';
    return '<div class="tune-history-scroll" style="max-height:' + h + ';overflow-y:auto;">' + list + '</div>';
  }
  return list;
}

// Backward-compat alias — `renderHistoryTable` is now a misnomer (we render
// a list of cards, not a table) but the old name was used by two call sites.
// Keep it pointing at the new implementation.
const renderHistoryTable = renderHistoryList;
