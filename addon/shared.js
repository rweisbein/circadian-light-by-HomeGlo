/**
 * Shared utility functions for Circadian Light UI.
 * Used by home.html, glo-designer.html, and other pages.
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
