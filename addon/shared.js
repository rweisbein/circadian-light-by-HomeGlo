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
 * At 0% brightness, color is dimmed to 25% intensity.
 * At 100% brightness, color is full intensity.
 * @param {string} rgbStr - RGB string like "rgb(255,230,200)"
 * @param {number} brightness - Brightness percentage 0-100
 * @returns {string} Tinted RGB string
 */
function tintColorByBrightness(rgbStr, brightness) {
  const match = rgbStr.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
  if (!match) return rgbStr;
  const fraction = Math.max(0, Math.min(1, brightness / 100));
  const dimFactor = 0.25 + 0.75 * fraction;
  const [r, g, b] = [match[1], match[2], match[3]].map(v => Math.round(Number(v) * dimFactor));
  return `rgb(${r},${g},${b})`;
}

/**
 * Initialize the nav bar solar display.
 * Fetches sunrise/sunset from /api/sun_times and populates #nav-rise and #nav-set.
 */
function initNavSolar() {
  function formatNavHour(h) {
    if (h === undefined || h === null || !Number.isFinite(h)) return '--';
    const h24 = ((h % 24) + 24) % 24;
    let hr = Math.floor(h24);
    let min = Math.round((h24 - hr) * 60);
    if (min === 60) { min = 0; hr = (hr + 1) % 24; }
    const suffix = hr < 12 ? 'a' : 'p';
    const hr12 = hr === 0 ? 12 : (hr > 12 ? hr - 12 : hr);
    return min === 0 ? `${hr12}${suffix}` : `${hr12}:${min.toString().padStart(2, '0')}${suffix}`;
  }

  fetch('./api/sun_times')
    .then(r => r.ok ? r.json() : null)
    .then(data => {
      if (!data) return;
      const riseEl = document.getElementById('nav-rise');
      const setEl = document.getElementById('nav-set');
      if (riseEl) riseEl.textContent = '\u2191 ' + formatNavHour(data.sunrise_hour);
      if (setEl) setEl.textContent = '\u2193 ' + formatNavHour(data.sunset_hour);
      // Show the container once loaded
      const container = document.getElementById('nav-solar');
      if (container) container.style.opacity = '1';
    })
    .catch(() => {});
}

document.addEventListener('DOMContentLoaded', initNavSolar);

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

  // Fetch zones and areas
  let zones = {};
  try {
    const resp = await fetch('./api/glozones');
    if (resp.ok) {
      const data = await resp.json();
      zones = data.zones || {};
    }
  } catch (err) {
    console.error('Failed to fetch zones:', err);
    resolve(null);
    return;
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

    // Convert zones to array for sorting
    let zoneEntries = Object.entries(zones);

    // Sort zones: default first, then by name or custom order
    if (sortMode === 'az') {
      zoneEntries.sort((a, b) => a[0].localeCompare(b[0]));
    }
    // 'custom' mode uses the order from the API (user's order)

    let hasResults = false;

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

      // Sort areas within zone
      let sortedAreas = [...filteredAreas];
      if (sortMode === 'az') {
        sortedAreas.sort((a, b) => {
          const nameA = (typeof a === 'object' ? a.name : a) || '';
          const nameB = (typeof b === 'object' ? b.name : b) || '';
          return nameA.localeCompare(nameB);
        });
      }

      // Area items
      for (const area of sortedAreas) {
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
