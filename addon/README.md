# Circadian Light by HomeGlo

Circadian Light honors your circadian rhythm by intuitively adapting smart lights' color and brightness to your daily pattern.

## What It Does

Circadian Light automatically adjusts your home's lighting throughout the day — warm and dim in the evening, bright and cool during the day — following a natural curve you design. It works across ZigBee (ZHA), Z-Wave, WiFi, and Matter lights.

## Key Features

### Rhythm Designer
Design your lighting curve with an interactive visual editor:
- Drag handles to set color temperature and brightness ranges
- Configure wake and bed times with per-day scheduling and alternate times
- Warm Night caps color temperature after sunset
- Cool Day adjusts color based on outdoor light intensity
- Live Design mode previews changes on real lights in real time

### Tune
Fine-tune brightness per area across your home:
- Per-area brightness sliders grouped by zone
- Per-light filter adjustments (accent, task, ambient)
- Natural light sensitivity control

### Controls
Manage physical switches and buttons:
- Map ZHA switch buttons to actions (on, off, step up/down, boost)
- Per-switch configuration with area assignment

### Magic Moments
Create whole-home lighting presets:
- One-tap scenes that apply across all areas
- Per-area exceptions for flexible control

### Area Management
Organize lights into zones:
- Group areas into rhythm zones that share a lighting curve
- Custom area ordering
- Per-area boost controls for temporary brightness

## Installation

1. In Home Assistant, go to **Settings > Add-ons > Add-on Store**
2. Click the three-dot menu > **Repositories**
3. Add: `https://github.com/rweisbein/circadian-light-by-HomeGlo`
4. Find "Circadian Light by HomeGlo" and click **Install**
5. Enable **Show in sidebar** for quick access

## Configuration

The add-on option `manage_integration` (enabled by default) keeps the Circadian Light custom integration deployed in Home Assistant, providing service primitives for automations and switch control.

All lighting configuration is managed through the built-in web UI — no YAML editing required.

## Support

For issues or feature requests: [GitHub Issues](https://github.com/rweisbein/circadian-light-by-HomeGlo/issues)
