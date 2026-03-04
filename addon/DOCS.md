# Documentation

## Configuration Options

### manage_integration
Automatically install and update the Circadian Light custom integration inside Home Assistant. This provides service primitives (`circadian_light_on`, `circadian_light_off`, `step_up`, `step_down`, etc.) for use in automations and switch control.

## Getting Started

1. Start the add-on and enable **Show in sidebar**
2. Open Circadian Light from the sidebar
3. Create a rhythm zone and assign areas to it
4. Configure your lighting curve in the Rhythm Designer
5. Enable Circadian Light for each area from the area detail page

## Pages

### Home
Manage rhythm zones and areas. Create zones, assign areas, and reorder them.

### Tune
Fine-tune brightness per area. Adjust per-light filters and natural light sensitivity.

### Controls
Configure physical switches. Map ZHA button presses to Circadian Light actions.

### Magic Moments
Create whole-home lighting presets with per-area exceptions.

### Settings
Configure location, timezone, and integration options.

## Rhythm Designer

Access the Rhythm Designer by tapping a zone on the Home page. Design your lighting curve with:

- **Sleep card**: Set wake/bed times with per-day scheduling and alternate times. Configure brightness and transition speed for each.
- **Color temperature card**: Set warmest/coolest range with interactive gradient. Enable Warm Night (caps color after sunset) and Cool Day (adjusts for outdoor light).
- **Brightness card**: Set dimmest/brightest range with interactive gradient.
- **Live Design**: Toggle to preview curve changes on real lights in real time.
- **Date slider**: Scrub through the year to see how sunrise/sunset affects your curve.

## Multi-Protocol Support

Circadian Light controls any Home Assistant light entity:
- **ZigBee (ZHA)**: Automatic group management for efficient control
- **Z-Wave**: Standard light control
- **WiFi**: Works with any WiFi-connected light
- **Matter**: Full support for Matter lights

## Support

For issues or feature requests: [GitHub Issues](https://github.com/rweisbein/circadian-light-by-HomeGlo/issues)
