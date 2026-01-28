#!/usr/bin/env python3
"""Web server for Home Assistant ingress - Light Designer interface."""

import asyncio
import json
import logging
import math
import os
from typing import Any, Dict, List, Optional
from aiohttp import web, ClientSession
from aiohttp.web import Request, Response
import websockets
import aiofiles
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from astral import LocationInfo
from astral.sun import sun

import state
import switches
import glozone
import glozone_state
from brain import (
    CircadianLight,
    Config,
    AreaState,
    DEFAULT_MAX_DIM_STEPS,
    calculate_dimming_step,
    get_circadian_lighting,
    get_current_hour,
    ACTIVITY_PRESETS,
    apply_activity_preset,
    get_preset_names,
    calculate_sun_times,
)

logger = logging.getLogger(__name__)


def calculate_step_sequence(current_hour: float, action: str, max_steps: int, config: dict) -> list:
    """Calculate a sequence of step positions for visualization.

    Args:
        current_hour: Current clock time (0-24)
        action: 'brighten' or 'dim'
        max_steps: Maximum number of steps to calculate
        config: Configuration dict with curve parameters

    Returns:
        List of dicts with hour, brightness, kelvin, rgb for each step
    """
    steps = []

    # Get location from config
    latitude = config.get('latitude')
    longitude = config.get('longitude')
    timezone = config.get('timezone')

    if not latitude or not longitude or not timezone:
        logger.error("Missing location data in config")
        return steps

    # Use the current date but calculate proper solar times
    try:
        tzinfo = ZoneInfo(timezone)
    except:
        tzinfo = ZoneInfo('UTC')

    today = datetime.now(tzinfo).date()
    loc = LocationInfo(latitude=latitude, longitude=longitude, timezone=tzinfo)
    solar_events = sun(loc.observer, date=today, tzinfo=tzinfo)
    solar_noon = solar_events["noon"]
    solar_midnight = solar_events["noon"] - timedelta(hours=12)

    # Convert clock hour (0-24) to actual datetime
    # current_hour is now clock time (0 = midnight, 12 = noon, etc.)
    base_time = datetime.now(tzinfo).replace(hour=0, minute=0, second=0, microsecond=0)
    adjusted_time = base_time + timedelta(hours=current_hour)

    try:
        for step_num in range(max_steps):
            if step_num == 0:
                # First "step" is the current position
                lighting_values = get_circadian_lighting(
                    latitude=config.get('latitude'),
                    longitude=config.get('longitude'),
                    timezone=config.get('timezone'),
                    current_time=adjusted_time,
                    config=config
                )
                steps.append({
                    'hour': current_hour,
                    'brightness': lighting_values['brightness'],
                    'kelvin': lighting_values['kelvin'],
                    'rgb': lighting_values.get('rgb', [255, 255, 255])
                })
            else:
                # Calculate the next step
                result = calculate_dimming_step(
                    current_time=adjusted_time,
                    action=action,
                    latitude=config.get('latitude'),
                    longitude=config.get('longitude'),
                    timezone=config.get('timezone'),
                    max_steps=max_steps,
                    min_color_temp=config.get('min_color_temp', 500),
                    max_color_temp=config.get('max_color_temp', 6500),
                    min_brightness=config.get('min_brightness', 1),
                    max_brightness=config.get('max_brightness', 100),
                    config=config
                )

                # Check if we've reached a boundary (no change)
                if abs(result['time_offset_minutes']) < 0.1:
                    break

                # Apply the time offset
                adjusted_time += timedelta(minutes=result['time_offset_minutes'])

                # Convert back to clock hour (0-24 scale)
                new_hour = adjusted_time.hour + adjusted_time.minute / 60.0

                steps.append({
                    'hour': new_hour,
                    'brightness': result['brightness'],
                    'kelvin': result['kelvin'],
                    'rgb': result.get('rgb', [255, 255, 255])
                })

                # Update for next iteration
                current_hour = new_hour

    except Exception as e:
        logger.error(f"Error calculating step sequence: {e}")
        logger.error(f"Config: {config}")
        logger.error(f"Current hour: {current_hour}, action: {action}, max_steps: {max_steps}")
        # Return at least the first step if possible
        if not steps:
            try:
                # Try to get just the current position without stepping
                lighting_values = get_circadian_lighting(
                    latitude=config.get('latitude'),
                    longitude=config.get('longitude'),
                    timezone=config.get('timezone'),
                    current_time=adjusted_time,
                    config=config
                )
                steps.append({
                    'hour': current_hour,
                    'brightness': lighting_values['brightness'],
                    'kelvin': lighting_values['kelvin'],
                    'rgb': lighting_values.get('rgb', [255, 255, 255])
                })
            except Exception as e2:
                logger.error(f"Error getting current position: {e2}")

    return steps


def generate_curve_data(config: dict) -> dict:
    """Generate complete curve data for visualization.

    Args:
        config: Configuration dict with curve parameters and location

    Returns:
        Dict containing curve arrays, solar times, and segments
    """
    try:
        # Get location from config
        latitude = config.get('latitude', 35.0)
        longitude = config.get('longitude', -78.6)
        timezone = config.get('timezone', 'US/Eastern')
        month = config.get('month', 6)  # Test month for UI

        # Create timezone info
        try:
            tzinfo = ZoneInfo(timezone)
        except:
            tzinfo = ZoneInfo('UTC')

        # Use current date but for the specified test month
        today = datetime.now(tzinfo).replace(month=month, day=15)  # Mid-month for consistency
        loc = LocationInfo(latitude=latitude, longitude=longitude, timezone=tzinfo)
        solar_events = sun(loc.observer, date=today.date(), tzinfo=tzinfo)

        solar_noon = solar_events["noon"]
        solar_midnight = solar_events["noon"] - timedelta(hours=12)

        # Use the get_circadian_lighting function to get values at each time point
        # We'll call it for each sample point

        # Sample at 0.1 hour intervals (matching JavaScript)
        sample_step = 0.1
        hours = []
        brightness_values = []
        cct_values = []
        rgb_values = []
        sun_power_values = []

        # Morning segment (solar midnight to solar noon)
        morning_hours = []
        morning_brightness = []
        morning_cct = []

        # Evening segment (solar noon to solar midnight)
        evening_hours = []
        evening_brightness = []
        evening_cct = []

        # Sample the full 24-hour curve using actual clock time
        # Start from midnight of today and sample every 0.1 hours
        base_time = datetime.now(tzinfo).replace(hour=0, minute=0, second=0, microsecond=0)

        for i in range(int(24 / sample_step)):
            current_time = base_time + timedelta(hours=i * sample_step)

            # Calculate hour of day (0-24 scale) for plotting
            clock_hour = current_time.hour + current_time.minute / 60.0

            # Get circadian lighting values using the main function
            lighting_values = get_circadian_lighting(
                latitude=latitude,
                longitude=longitude,
                timezone=timezone,
                current_time=current_time,
                min_color_temp=config.get('min_color_temp', 500),
                max_color_temp=config.get('max_color_temp', 6500),
                min_brightness=config.get('min_brightness', 1),
                max_brightness=config.get('max_brightness', 100),
                config=config
            )

            brightness = lighting_values['brightness']
            cct = lighting_values['kelvin']
            rgb = lighting_values.get('rgb', [255, 255, 255])

            # Calculate sun power (simple approximation based on time)
            # This is just for visualization - using a simple sine wave approximation
            hour_of_day = current_time.hour + current_time.minute / 60
            if 6 <= hour_of_day <= 18:  # Daytime hours
                sun_power = max(0, 300 * math.sin(math.pi * (hour_of_day - 6) / 12))
            else:
                sun_power = 0

            # Add to main arrays
            hours.append(clock_hour)
            brightness_values.append(brightness)
            cct_values.append(cct)
            rgb_values.append(list(rgb))
            sun_power_values.append(sun_power)

            # Add to appropriate segment (split at solar noon, not clock noon)
            # Convert solar noon to clock time for proper segmentation
            solar_noon_clock = solar_noon.hour + solar_noon.minute / 60.0
            if clock_hour < solar_noon_clock:
                morning_hours.append(clock_hour)
                morning_brightness.append(brightness)
                morning_cct.append(cct)
            else:
                evening_hours.append(clock_hour)
                evening_brightness.append(brightness)
                evening_cct.append(cct)

            # Move to next sample point
            current_time += timedelta(hours=sample_step)

        # Convert solar times to clock hours (0-24 scale)
        solar_noon_hour = solar_noon.hour + solar_noon.minute / 60.0
        solar_midnight_hour = (solar_noon_hour + 12) % 24

        # Calculate sunrise/sunset if available
        sunrise_hour = None
        sunset_hour = None
        try:
            if 'sunrise' in solar_events and solar_events['sunrise']:
                sunrise_hour = solar_events['sunrise'].hour + solar_events['sunrise'].minute / 60.0

            if 'sunset' in solar_events and solar_events['sunset']:
                sunset_hour = solar_events['sunset'].hour + solar_events['sunset'].minute / 60.0
        except:
            pass

        return {
            'hours': hours,
            'bris': brightness_values,
            'ccts': cct_values,
            'sunPower': sun_power_values,
            'morn': {
                'hours': morning_hours,
                'bris': morning_brightness,
                'ccts': morning_cct
            },
            'eve': {
                'hours': evening_hours,
                'bris': evening_brightness,
                'ccts': evening_cct
            },
            'solar': {
                'sunrise': sunrise_hour,
                'sunset': sunset_hour,
                'solarNoon': solar_noon_hour,
                'solarMidnight': solar_midnight_hour
            }
        }

    except Exception as e:
        logger.error(f"Error generating curve data: {e}")
        # Return minimal valid structure on error
        return {
            'hours': [0, 12, 24],
            'bris': [1, 100, 1],
            'ccts': [500, 6500, 500],
            'sunPower': [0, 300, 0],
            'morn': {'hours': [0, 12], 'bris': [1, 100], 'ccts': [500, 6500]},
            'eve': {'hours': [12, 24], 'bris': [100, 1], 'ccts': [6500, 500]},
            'solar': {'sunrise': 6, 'sunset': 18, 'solarNoon': 12, 'solarMidnight': 0}
        }


class LightDesignerServer:
    """Web server for the Light Designer ingress interface."""
    
    def __init__(self, port: int = 8099):
        self.port = port
        self.app = web.Application()
        self.setup_routes()

        # Detect environment and set appropriate paths
        # Prefer /config/circadian-light (visible in HA config folder, included in backups)
        # Fall back to /data for backward compatibility, then local .data for dev
        if os.path.exists("/config"):
            # Running in Home Assistant - use config folder (visible and backed up)
            self.data_dir = "/config/circadian-light"
            os.makedirs(self.data_dir, exist_ok=True)
            # Migrate from old /data location if needed
            self._migrate_data_location_sync()
        elif os.path.exists("/data"):
            # Fallback to /data if /config not available
            self.data_dir = "/data"
        else:
            # Running in development - use local .data directory
            self.data_dir = os.path.join(os.path.dirname(__file__), ".data")
            os.makedirs(self.data_dir, exist_ok=True)
            logger.info(f"Development mode: using {self.data_dir} for configuration storage")

        # Set file paths based on data directory
        self.options_file = os.path.join(self.data_dir, "options.json")
        self.designer_file = os.path.join(self.data_dir, "designer_config.json")

        # Live Design capability cache (one area at a time)
        # Populated when Live Design is enabled for an area
        self.live_design_area: str = None  # Currently active Live Design area
        self.live_design_color_lights: list = []  # Color-capable lights in area
        self.live_design_ct_lights: list = []  # CT-only lights in area
        self.live_design_saved_states: dict = {}  # Saved light states to restore when ending

        # Initialize switches module (loads from switches_config.json)
        switches.init()

    def _migrate_data_location_sync(self):
        """Migrate config files from /data to /config/circadian-light if they exist."""
        old_data_dir = "/data"
        if not os.path.exists(old_data_dir):
            return

        files_to_migrate = ["designer_config.json", "options.json"]
        for filename in files_to_migrate:
            old_path = os.path.join(old_data_dir, filename)
            new_path = os.path.join(self.data_dir, filename)

            # Only migrate if old file exists and new file doesn't
            if os.path.exists(old_path) and not os.path.exists(new_path):
                try:
                    import shutil
                    shutil.copy2(old_path, new_path)
                    logger.info(f"Migrated {filename} from {old_data_dir} to {self.data_dir}")
                except Exception as e:
                    logger.warning(f"Failed to migrate {filename}: {e}")

    def setup_routes(self):
        """Set up web routes."""
        # API routes - must handle all ingress prefixes
        self.app.router.add_route('GET', '/{path:.*}/api/config', self.get_config)
        self.app.router.add_route('POST', '/{path:.*}/api/config', self.save_config)
        self.app.router.add_route('GET', '/{path:.*}/api/steps', self.get_step_sequences)
        self.app.router.add_route('GET', '/{path:.*}/api/curve', self.get_curve_data)
        self.app.router.add_route('GET', '/{path:.*}/api/time', self.get_time)
        self.app.router.add_route('GET', '/{path:.*}/api/zone-states', self.get_zone_states)
        self.app.router.add_route('GET', '/{path:.*}/api/presets', self.get_presets)
        self.app.router.add_route('GET', '/{path:.*}/api/sun_times', self.get_sun_times)
        self.app.router.add_route('GET', '/{path:.*}/health', self.health_check)
        self.app.router.add_route('GET', '/{path:.*}/api/areas', self.get_areas)
        self.app.router.add_route('POST', '/{path:.*}/api/apply-light', self.apply_light)
        self.app.router.add_route('POST', '/{path:.*}/api/circadian-mode', self.set_circadian_mode)

        # Direct API routes (for non-ingress access)
        self.app.router.add_get('/api/config', self.get_config)
        self.app.router.add_post('/api/config', self.save_config)
        self.app.router.add_get('/api/steps', self.get_step_sequences)
        self.app.router.add_get('/api/curve', self.get_curve_data)
        self.app.router.add_get('/api/time', self.get_time)
        self.app.router.add_get('/api/zone-states', self.get_zone_states)
        self.app.router.add_get('/api/presets', self.get_presets)
        self.app.router.add_get('/api/sun_times', self.get_sun_times)
        self.app.router.add_get('/health', self.health_check)

        # Live Design API routes
        self.app.router.add_get('/api/areas', self.get_areas)
        self.app.router.add_route('GET', '/{path:.*}/api/area-status', self.get_area_status)
        self.app.router.add_get('/api/area-status', self.get_area_status)
        self.app.router.add_route('GET', '/{path:.*}/api/area-settings/{area_id}', self.get_area_settings)
        self.app.router.add_route('POST', '/{path:.*}/api/area-settings/{area_id}', self.save_area_settings)
        self.app.router.add_get('/api/area-settings/{area_id}', self.get_area_settings)
        self.app.router.add_post('/api/area-settings/{area_id}', self.save_area_settings)
        self.app.router.add_post('/api/apply-light', self.apply_light)
        self.app.router.add_post('/api/circadian-mode', self.set_circadian_mode)

        # GloZone API routes - Circadian Presets CRUD
        self.app.router.add_route('GET', '/{path:.*}/api/circadian-presets', self.get_circadian_presets)
        self.app.router.add_route('POST', '/{path:.*}/api/circadian-presets', self.create_circadian_preset)
        self.app.router.add_route('PUT', '/{path:.*}/api/circadian-presets/{name}', self.update_circadian_preset)
        self.app.router.add_route('DELETE', '/{path:.*}/api/circadian-presets/{name}', self.delete_circadian_preset)
        self.app.router.add_get('/api/circadian-presets', self.get_circadian_presets)
        self.app.router.add_post('/api/circadian-presets', self.create_circadian_preset)
        self.app.router.add_put('/api/circadian-presets/{name}', self.update_circadian_preset)
        self.app.router.add_delete('/api/circadian-presets/{name}', self.delete_circadian_preset)

        # GloZone API routes - Zones CRUD
        self.app.router.add_route('GET', '/{path:.*}/api/glozones', self.get_glozones)
        self.app.router.add_route('POST', '/{path:.*}/api/glozones', self.create_glozone)
        self.app.router.add_route('PUT', '/{path:.*}/api/glozones/{name}', self.update_glozone)
        self.app.router.add_route('DELETE', '/{path:.*}/api/glozones/{name}', self.delete_glozone)
        self.app.router.add_route('POST', '/{path:.*}/api/glozones/{name}/areas', self.add_area_to_zone)
        self.app.router.add_route('DELETE', '/{path:.*}/api/glozones/{name}/areas/{area_id}', self.remove_area_from_zone)
        self.app.router.add_get('/api/glozones', self.get_glozones)
        self.app.router.add_post('/api/glozones', self.create_glozone)
        self.app.router.add_put('/api/glozones/{name}', self.update_glozone)
        self.app.router.add_delete('/api/glozones/{name}', self.delete_glozone)
        self.app.router.add_post('/api/glozones/{name}/areas', self.add_area_to_zone)
        self.app.router.add_delete('/api/glozones/{name}/areas/{area_id}', self.remove_area_from_zone)

        # GloZone API routes - Actions
        self.app.router.add_route('POST', '/{path:.*}/api/glozone/glo-up', self.handle_glo_up)
        self.app.router.add_route('POST', '/{path:.*}/api/glozone/glo-down', self.handle_glo_down)
        self.app.router.add_route('POST', '/{path:.*}/api/glozone/glo-reset', self.handle_glo_reset)
        self.app.router.add_post('/api/glozone/glo-up', self.handle_glo_up)
        self.app.router.add_post('/api/glozone/glo-down', self.handle_glo_down)
        self.app.router.add_post('/api/glozone/glo-reset', self.handle_glo_reset)

        # Area action API route
        self.app.router.add_route('POST', '/{path:.*}/api/area/action', self.handle_area_action)
        self.app.router.add_post('/api/area/action', self.handle_area_action)

        # Controls API routes (new unified endpoint)
        self.app.router.add_route('GET', '/{path:.*}/api/controls', self.get_controls)
        self.app.router.add_route('POST', '/{path:.*}/api/controls/{control_id}/configure', self.configure_control)
        self.app.router.add_route('DELETE', '/{path:.*}/api/controls/{control_id}/configure', self.remove_control_config)
        self.app.router.add_get('/api/controls', self.get_controls)
        self.app.router.add_post('/api/controls/{control_id}/configure', self.configure_control)
        self.app.router.add_delete('/api/controls/{control_id}/configure', self.remove_control_config)

        # Legacy switches API routes (keeping for backwards compat)
        self.app.router.add_route('GET', '/{path:.*}/api/switches', self.get_switches)
        self.app.router.add_route('POST', '/{path:.*}/api/switches', self.create_switch)
        self.app.router.add_route('PUT', '/{path:.*}/api/switches/{switch_id}', self.update_switch)
        self.app.router.add_route('DELETE', '/{path:.*}/api/switches/{switch_id}', self.delete_switch)
        self.app.router.add_route('GET', '/{path:.*}/api/switch-types', self.get_switch_types)
        self.app.router.add_get('/api/switches', self.get_switches)
        self.app.router.add_post('/api/switches', self.create_switch)
        self.app.router.add_put('/api/switches/{switch_id}', self.update_switch)
        self.app.router.add_delete('/api/switches/{switch_id}', self.delete_switch)
        self.app.router.add_get('/api/switch-types', self.get_switch_types)

        # Page routes - specific pages first, then catch-all
        # With ingress path prefix
        self.app.router.add_route('GET', '/{path:.*}/switches', self.serve_switches)
        self.app.router.add_route('GET', '/{path:.*}/zones', self.serve_zones)
        self.app.router.add_route('GET', '/{path:.*}/glo/{glo_name}', self.serve_glo_designer)
        self.app.router.add_route('GET', '/{path:.*}/glo', self.serve_glo_designer)
        self.app.router.add_route('GET', '/{path:.*}/settings', self.serve_settings)
        self.app.router.add_route('GET', '/{path:.*}/', self.serve_home)
        # Without ingress path prefix
        self.app.router.add_get('/glo/{glo_name}', self.serve_glo_designer)
        self.app.router.add_get('/glo', self.serve_glo_designer)
        self.app.router.add_get('/zones', self.serve_zones)
        self.app.router.add_get('/settings', self.serve_settings)
        self.app.router.add_get('/', self.serve_home)
        # Legacy routes
        self.app.router.add_get('/designer', self.serve_home)
        self.app.router.add_get('/areas', self.serve_home)
        self.app.router.add_route('GET', '/{path:.*}/areas', self.serve_home)

    async def serve_page(self, page_name: str, extra_data: dict = None) -> Response:
        """Generic page serving function."""
        try:
            config = await self.load_config()

            html_path = Path(__file__).parent / f"{page_name}.html"
            if not html_path.exists():
                logger.error(f"Page not found: {page_name}.html")
                return web.Response(text=f"Page not found: {page_name}", status=404)

            async with aiofiles.open(html_path, 'r') as f:
                html_content = await f.read()

            # Inline shared.js content (avoids routing issues with ingress paths)
            shared_js_path = Path(__file__).parent / "shared.js"
            if shared_js_path.exists():
                async with aiofiles.open(shared_js_path, 'r') as f:
                    shared_js_content = await f.read()
                # Replace external script reference with inline script (simple string replace)
                inline_script = f'<script>\n{shared_js_content}\n</script>'
                original_len = len(html_content)
                # Try multiple possible formats
                for pattern in ['<script src="./shared.js"></script>',
                               '<script src="shared.js"></script>',
                               "<script src='./shared.js'></script>",
                               "<script src='shared.js'></script>"]:
                    if pattern in html_content:
                        html_content = html_content.replace(pattern, inline_script)
                        break

            # Build injected data
            inject_data = {"config": config}
            if extra_data:
                inject_data.update(extra_data)

            config_script = f"""
            <script>
            window.circadianData = {json.dumps(inject_data)};
            </script>
            """

            html_content = html_content.replace('</body>', f'{config_script}</body>')

            return web.Response(
                text=html_content,
                content_type='text/html',
                headers={
                    'Cache-Control': 'no-cache, no-store, must-revalidate',
                    'Pragma': 'no-cache',
                    'Expires': '0'
                }
            )
        except Exception as e:
            logger.error(f"Error serving {page_name} page: {e}")
            return web.Response(text=f"Error: {str(e)}", status=500)

    async def serve_home(self, request: Request) -> Response:
        """Serve the Home page (areas)."""
        return await self.serve_page("areas")

    async def serve_zones(self, request: Request) -> Response:
        """Serve the Control Zones page."""
        return await self.serve_page("home")

    async def serve_glo_designer(self, request: Request) -> Response:
        """Serve the Glo Designer page."""
        glo_name = request.match_info.get("glo_name")
        return await self.serve_page("glo-designer", {"selectedGlo": glo_name})

    async def serve_settings(self, request: Request) -> Response:
        """Serve the Settings page."""
        return await self.serve_page("settings")

    async def serve_areas(self, request: Request) -> Response:
        """Legacy: redirect to home (areas is now the home page)."""
        return await self.serve_page("areas")

    async def get_config(self, request: Request) -> Response:
        """Get current curve configuration."""
        try:
            config = await self.load_config()
            return web.json_response(config)
        except Exception as e:
            logger.error(f"Error getting config: {e}")
            return web.json_response({"error": str(e)}, status=500)
    
    async def save_config(self, request: Request) -> Response:
        """Save curve configuration.

        Handles both legacy flat config and new GloZone format.
        - Flat preset settings are merged into the active preset
        - circadian_presets and glozones are merged at their level
        - Global settings are merged at top level
        """
        try:
            data = await request.json()
            logger.info(f"[SaveConfig] Incoming data keys: {list(data.keys())}")
            logger.info(f"[SaveConfig] Incoming glozones: {data.get('glozones', 'NOT PRESENT')}")

            # Load existing raw config (GloZone format)
            config = await self.load_raw_config()
            logger.info(f"[SaveConfig] Loaded raw config glozones: {list(config.get('glozones', {}).keys())}")

            # Separate incoming data into categories
            incoming_presets = data.pop("circadian_presets", None)
            incoming_glozones = data.pop("glozones", None)
            logger.info(f"[SaveConfig] After pop - incoming_glozones: {incoming_glozones}")

            # Handle incoming preset and glozone structures
            if incoming_presets:
                config["circadian_presets"].update(incoming_presets)

            if incoming_glozones:
                logger.info(f"[SaveConfig] Updating glozones with: {list(incoming_glozones.keys())}")
                config["glozones"].update(incoming_glozones)

            # Remaining data could be flat preset settings or global settings
            preset_updates = {}
            global_updates = {}

            for key, value in data.items():
                if key in self.PRESET_SETTINGS:
                    preset_updates[key] = value
                elif key in self.GLOBAL_SETTINGS:
                    global_updates[key] = value
                # Ignore unknown keys

            # Apply preset updates to the first preset (active preset)
            if preset_updates and config.get("circadian_presets"):
                first_preset_name = list(config["circadian_presets"].keys())[0]
                config["circadian_presets"][first_preset_name].update(preset_updates)
                logger.debug(f"Updated preset '{first_preset_name}' with: {list(preset_updates.keys())}")

            # Apply global updates to top level
            config.update(global_updates)

            # Log what we're about to save
            logger.info(f"[SaveConfig] Final glozones to save: {list(config.get('glozones', {}).keys())}")
            for zn, zc in config.get('glozones', {}).items():
                areas = zc.get('areas', [])
                logger.info(f"[SaveConfig]   Zone '{zn}': {len(areas)} areas, preset={zc.get('preset')}")

            # Save the raw config (GloZone format)
            await self.save_config_to_file(config)

            # Update glozone module with new config
            glozone.set_config(config)

            # Trigger refresh of enabled areas by firing an event
            # main.py listens for this event and signals the periodic updater
            refreshed = False
            _, ws_url, token = self._get_ha_api_config()
            if ws_url and token:
                refreshed = await self._fire_event_via_websocket(
                    ws_url, token, 'circadian_light_refresh', {}
                )
                if refreshed:
                    logger.info("Fired circadian_light_refresh event after config save")
                else:
                    logger.warning("Failed to fire circadian_light_refresh event")

            # Return effective config for backward compatibility
            effective_config = self._get_effective_config(config)
            return web.json_response({"status": "success", "config": effective_config, "refreshed": refreshed})
        except Exception as e:
            logger.error(f"Error saving config: {e}")
            return web.json_response({"error": str(e)}, status=500)
    
    async def health_check(self, request: Request) -> Response:
        """Health check endpoint."""
        return web.json_response({"status": "healthy"})

    async def get_presets(self, request: Request) -> Response:
        """Get available activity presets."""
        try:
            presets = {}
            for name in get_preset_names():
                preset = ACTIVITY_PRESETS.get(name, {})
                presets[name] = {
                    "wake_time": preset.get("wake_time", 6.0),
                    "bed_time": preset.get("bed_time", 22.0),
                    "ascend_start": preset.get("ascend_start", 3.0),
                    "descend_start": preset.get("descend_start", 12.0),
                }
            return web.json_response({
                "presets": presets,
                "names": get_preset_names()
            })
        except Exception as e:
            logger.error(f"Error getting presets: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def get_sun_times(self, request: Request) -> Response:
        """Get sun times for a specific date (for date slider preview)."""
        try:
            # Get parameters from query
            date_str = request.query.get('date')
            lat = float(request.query.get('latitude', 35.0))
            lon = float(request.query.get('longitude', -78.6))

            if not date_str:
                # Default to today
                date_str = datetime.now().strftime('%Y-%m-%d')

            # Calculate sun times using brain.py function
            sun_times = calculate_sun_times(lat, lon, date_str)

            # Helper to convert ISO string to hour
            def iso_to_hour(iso_str, default):
                if not iso_str:
                    return default
                try:
                    dt = datetime.fromisoformat(iso_str)
                    return dt.hour + dt.minute / 60.0 + dt.second / 3600.0
                except:
                    return default

            sunrise_hour = iso_to_hour(sun_times.get("sunrise"), 6.0)
            sunset_hour = iso_to_hour(sun_times.get("sunset"), 18.0)
            noon_hour = iso_to_hour(sun_times.get("noon"), 12.0)
            midnight_hour = (noon_hour + 12.0) % 24.0

            return web.json_response({
                "date": date_str,
                "latitude": lat,
                "longitude": lon,
                # ISO strings for display
                "sunrise": sun_times.get("sunrise"),
                "sunset": sun_times.get("sunset"),
                "solar_noon": sun_times.get("noon"),
                "solar_midnight": None,
                # Hour values for calculations
                "sunrise_hour": sunrise_hour,
                "sunset_hour": sunset_hour,
                "noon_hour": noon_hour,
                "midnight_hour": midnight_hour,
            })
        except Exception as e:
            logger.error(f"Error getting sun times: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def get_time(self, request: Request) -> Response:
        """Get current server time in Home Assistant timezone."""
        try:
            from datetime import datetime
            from zoneinfo import ZoneInfo
            from brain import get_circadian_lighting

            # Get location from environment variables (set by main.py)
            latitude = float(os.getenv("HASS_LATITUDE", "35.0"))
            longitude = float(os.getenv("HASS_LONGITUDE", "-78.6"))
            timezone = os.getenv("HASS_TIME_ZONE", "US/Eastern")

            # Get current time in HA timezone
            try:
                tzinfo = ZoneInfo(timezone)
            except:
                tzinfo = None

            now = datetime.now(tzinfo)

            # Calculate current hour (0-24 scale)
            current_hour = now.hour + now.minute / 60.0

            # Load current configuration to use same parameters as UI
            config = await self.load_config()

            # Get current circadian lighting values for comparison using same config as UI
            lighting_values = get_circadian_lighting(
                latitude=latitude,
                longitude=longitude,
                timezone=timezone,
                current_time=now,
                min_color_temp=config.get('min_color_temp', 500),
                max_color_temp=config.get('max_color_temp', 6500),
                min_brightness=config.get('min_brightness', 1),
                max_brightness=config.get('max_brightness', 100),
                config=config
            )

            return web.json_response({
                "current_time": now.isoformat(),
                "current_hour": current_hour,
                "timezone": timezone,
                "latitude": latitude,
                "longitude": longitude,
                "lighting": {
                    "brightness": lighting_values.get('brightness', 0),
                    "kelvin": lighting_values.get('kelvin', 0),
                    "solar_position": lighting_values.get('solar_position', 0)
                }
            })

        except Exception as e:
            logger.error(f"Error getting time info: {e}")
            return web.json_response(
                {"error": f"Failed to get time info: {e}"},
                status=500
            )

    async def get_zone_states(self, request: Request) -> Response:
        """Get current circadian values for each Glo Zone.

        Returns brightness and kelvin for each zone, accounting for:
        - The zone's Glo preset configuration
        - The zone's runtime state (brightness_mid, color_mid, frozen_at from GloUp/GloDown)
        - Solar rules (warm_night, cool_day) based on actual sun times

        This is per-zone, not per-preset, because two zones can share the same
        Glo but have different runtime states.
        """
        try:
            from zoneinfo import ZoneInfo
            from brain import CircadianLight, Config, AreaState, SunTimes, calculate_sun_times

            # Get location from environment
            latitude = float(os.getenv("HASS_LATITUDE", "35.0"))
            longitude = float(os.getenv("HASS_LONGITUDE", "-78.6"))
            timezone = os.getenv("HASS_TIME_ZONE", "US/Eastern")

            try:
                tzinfo = ZoneInfo(timezone)
            except:
                tzinfo = None

            now = datetime.now(tzinfo)
            hour = now.hour + now.minute / 60 + now.second / 3600

            # Calculate sun times for solar rules
            sun_times = SunTimes()  # defaults
            try:
                date_str = now.strftime('%Y-%m-%d')
                sun_dict = calculate_sun_times(latitude, longitude, date_str)

                def iso_to_hour(iso_str, default):
                    if not iso_str:
                        return default
                    try:
                        dt = datetime.fromisoformat(iso_str)
                        # Convert to local timezone if available
                        if tzinfo and dt.tzinfo:
                            dt = dt.astimezone(tzinfo)
                        return dt.hour + dt.minute / 60.0 + dt.second / 3600.0
                    except:
                        return default

                sun_times = SunTimes(
                    sunrise=iso_to_hour(sun_dict.get("sunrise"), 6.0),
                    sunset=iso_to_hour(sun_dict.get("sunset"), 18.0),
                    solar_noon=iso_to_hour(sun_dict.get("noon"), 12.0),
                    solar_mid=(iso_to_hour(sun_dict.get("noon"), 12.0) + 12.0) % 24.0,
                )
            except Exception as e:
                logger.debug(f"[ZoneStates] Error calculating sun times: {e}")

            # Get zones and presets from glozone module (consistent with area-status)
            zones = glozone.get_glozones()

            logger.info(f"[ZoneStates] Found {len(zones)} zones: {list(zones.keys())}")

            zone_states = {}
            for zone_name, zone_config in zones.items():
                # Get the preset (Glo) for this zone using glozone module
                preset_name = zone_config.get("preset", "Glo 1")
                preset_config = glozone.get_preset_config(preset_name)
                logger.info(f"[ZoneStates] Zone '{zone_name}' preset_config keys: {list(preset_config.keys())}")
                logger.info(f"[ZoneStates] Zone '{zone_name}' preset min/max bri: {preset_config.get('min_brightness')}/{preset_config.get('max_brightness')}")

                # Get zone runtime state (from GloUp/GloDown adjustments)
                runtime_state = glozone_state.get_zone_state(zone_name)
                logger.info(f"[ZoneStates] Zone '{zone_name}' runtime_state: {runtime_state}")

                # Build Config from preset using from_dict (handles all fields with defaults)
                brain_config = Config.from_dict(preset_config)
                logger.info(f"[ZoneStates] Zone '{zone_name}' brain_config: wake={brain_config.wake_time}, bed={brain_config.bed_time}, min_bri={brain_config.min_brightness}, max_bri={brain_config.max_brightness}, warm_night={brain_config.warm_night_enabled}")

                # Build AreaState from zone runtime state
                area_state = AreaState(
                    is_circadian=True,
                    is_on=True,
                    brightness_mid=runtime_state.get('brightness_mid'),
                    color_mid=runtime_state.get('color_mid'),
                    frozen_at=runtime_state.get('frozen_at'),
                )
                logger.info(f"[ZoneStates] Zone '{zone_name}' area_state: brightness_mid={area_state.brightness_mid}, color_mid={area_state.color_mid}, frozen_at={area_state.frozen_at}")

                # Calculate lighting values - use frozen_at if set, otherwise current time
                calc_hour = area_state.frozen_at if area_state.frozen_at is not None else hour
                result = CircadianLight.calculate_lighting(calc_hour, brain_config, area_state, sun_times=sun_times)

                zone_states[zone_name] = {
                    "brightness": result.brightness,
                    "kelvin": result.color_temp,
                    "preset": preset_name,
                    "runtime_state": runtime_state,
                }
                logger.info(f"[ZoneStates] Zone '{zone_name}': {result.brightness}% {result.color_temp}K at hour {calc_hour:.2f} (preset: {preset_name}, sun_times: sunrise={sun_times.sunrise:.2f}, sunset={sun_times.sunset:.2f})")

            logger.info(f"[ZoneStates] Returning {len(zone_states)} zone states")
            return web.json_response({"zone_states": zone_states})

        except Exception as e:
            logger.error(f"Error getting zone states: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)

    def apply_query_overrides(self, config: dict, query) -> dict:
        """Apply UI query parameters to a config dict for live previews."""
        # Float parameters (ascend/descend model)
        float_params = [
            'min_color_temp', 'max_color_temp',
            'min_brightness', 'max_brightness',
            'ascend_start', 'descend_start',
            'wake_time', 'bed_time',
            'latitude', 'longitude',
            'warm_night_target', 'warm_night_fade',
            'warm_night_start', 'warm_night_end',
            'cool_day_target', 'cool_day_fade',
            'cool_day_start', 'cool_day_end',
        ]

        # Integer parameters
        int_params = [
            'month', 'wake_speed', 'bed_speed', 'max_dim_steps'
        ]

        for param_name in float_params:
            if param_name in query:
                raw_value = query[param_name]
                try:
                    config[param_name] = float(raw_value)
                except (ValueError, TypeError):
                    logger.warning(f"Invalid value for {param_name}: {raw_value}")

        for param_name in int_params:
            if param_name in query:
                raw_value = query[param_name]
                try:
                    config[param_name] = int(float(raw_value))
                except (ValueError, TypeError):
                    logger.warning(f"Invalid value for {param_name}: {raw_value}")

        # Boolean parameters
        bool_params = [
            'warm_night_enabled', 'cool_day_enabled', 'use_ha_location'
        ]
        for param_name in bool_params:
            if param_name in query:
                config[param_name] = query[param_name].lower() in ('true', '1', 'yes', 'on')

        # String parameters
        string_params = [
            'activity_preset', 'warm_night_mode', 'cool_day_mode', 'timezone'
        ]
        for param_name in string_params:
            if param_name in query:
                config[param_name] = query[param_name]

        return config

    async def get_step_sequences(self, request: Request) -> Response:
        """Calculate step sequences for visualization."""
        try:
            # Get parameters from query string
            current_hour = float(request.query.get('hour', 12.0))
            max_steps = int(request.query.get('max_steps', 10))

            # Load current configuration
            config = await self.load_config()

            # Apply overrides from UI for live preview
            config = self.apply_query_overrides(config, request.query)

            # Calculate step sequences in both directions
            step_up_sequence = calculate_step_sequence(current_hour, 'brighten', max_steps, config)
            step_down_sequence = calculate_step_sequence(current_hour, 'dim', max_steps, config)

            return web.json_response({
                "step_up": {"steps": step_up_sequence},
                "step_down": {"steps": step_down_sequence}
            })

        except Exception as e:
            logger.error(f"Error calculating step sequences: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def get_curve_data(self, request: Request) -> Response:
        """Generate and return curve data for visualization."""
        try:
            # Load base configuration (includes server location data)
            config = await self.load_config()

            # Override with UI parameters from query string
            config = self.apply_query_overrides(config, request.query)

            # Generate curve data using the merged configuration
            curve_data = generate_curve_data(config)

            return web.json_response(curve_data)

        except Exception as e:
            logger.error(f"Error generating curve data: {e}")
            return web.json_response({"error": str(e)}, status=500)

    # Settings that are per-preset (not global)
    PRESET_SETTINGS = {
        "color_mode", "min_color_temp", "max_color_temp",
        "min_brightness", "max_brightness",
        "ascend_start", "descend_start", "wake_time", "bed_time",
        "wake_speed", "bed_speed",
        "warm_night_enabled", "warm_night_mode", "warm_night_target",
        "warm_night_start", "warm_night_end", "warm_night_fade",
        "cool_day_enabled", "cool_day_mode", "cool_day_target",
        "cool_day_start", "cool_day_end", "cool_day_fade",
        "activity_preset", "max_dim_steps",
    }

    # Settings that are global (not per-preset)
    GLOBAL_SETTINGS = {
        "latitude", "longitude", "timezone", "use_ha_location", "month",
        "turn_on_transition",  # Transition time in tenths of seconds for turn-on operations
        "turn_off_transition",  # Transition time in tenths of seconds for turn-off operations
        "two_step_delay",  # Delay between two-step phases in tenths of seconds (default 3 = 300ms)
        "multi_click_enabled",  # Enable multi-click detection for Hue Hub switches
        "multi_click_speed",  # Multi-click window in tenths of seconds
        "circadian_refresh",  # How often to refresh circadian lighting (seconds)
        "sync_refresh_multiplier",  # Multiplier for sync refresh interval (default 5x circadian refresh)
        "motion_warning_time",  # Seconds before motion timer expires to trigger warning dim
        "motion_warning_blink_threshold",  # Brightness % below which warning blinks instead of dims
        "freeze_off_rise",  # Transition time in tenths of seconds for unfreeze rise (default 10 = 1.0s)
        "limit_warning_speed",  # Transition time in tenths of seconds for limit bounce animation (default 3 = 0.3s)
        "warning_intensity",  # Base depth of limit warning dip/flash (1-10, default 5)
        "warning_scaling",  # How much depth increases near the limit (1-10, default 5)
        "boost_default",  # Default boost percentage (10-100, default 30)
        "controls_ui",  # Controls page UI preferences (sort, filter)
        "areas_ui",  # Areas page UI preferences (sort, filter)
        "area_settings",  # Per-area settings (motion_function, motion_duration)
    }

    def _migrate_to_glozone_format(self, config: dict) -> dict:
        """Migrate old flat config to new GloZone format.

        Old format: flat dict with all settings
        New format: {
            circadian_presets: {"Glo 1": {...preset settings...}},
            glozones: {"Unassigned": {preset: "Glo 1", areas: []}},
            ...global settings...
        }

        Args:
            config: The loaded config dict

        Returns:
            Migrated config dict
        """
        # Check if already migrated
        if "circadian_presets" in config and "glozones" in config:
            logger.debug("Config already in GloZone format")
            return config

        logger.info("Migrating config to GloZone format...")

        # Extract preset settings from flat config
        preset_config = {}
        for key in self.PRESET_SETTINGS:
            if key in config:
                preset_config[key] = config[key]

        # Extract global settings
        global_config = {}
        for key in self.GLOBAL_SETTINGS:
            if key in config:
                global_config[key] = config[key]

        # Build new config structure
        new_config = {
            "circadian_presets": {
                glozone.DEFAULT_PRESET: preset_config
            },
            "glozones": {
                glozone.INITIAL_ZONE_NAME: {
                    "preset": glozone.DEFAULT_PRESET,
                    "areas": [],
                    "is_default": True
                }
            },
        }

        # Add global settings
        new_config.update(global_config)

        logger.info(f"Migration complete: created preset '{glozone.DEFAULT_PRESET}' "
                    f"and zone '{glozone.INITIAL_ZONE_NAME}' (default)")

        return new_config

    def _get_effective_config(self, config: dict) -> dict:
        """Get effective config by merging preset settings with global settings.

        For backward compatibility with code that expects flat config,
        this merges the first preset's settings into the top level.

        Args:
            config: The GloZone-format config

        Returns:
            Flat config dict with all settings merged
        """
        result = {}

        # Start with global settings
        for key in self.GLOBAL_SETTINGS:
            if key in config:
                result[key] = config[key]

        # Get the first preset's settings (or default preset)
        presets = config.get("circadian_presets", {})
        if presets:
            # Use first preset for backward compatibility
            first_preset_name = list(presets.keys())[0]
            first_preset = presets[first_preset_name]
            result.update(first_preset)

        # Keep the new structure available
        result["circadian_presets"] = config.get("circadian_presets", {})
        result["glozones"] = config.get("glozones", {})

        return result

    async def load_config(self) -> dict:
        """Load configuration, merging HA options with designer overrides.

        Order of precedence (later wins):
          defaults -> options.json -> designer_config.json

        Automatically migrates old flat config to new GloZone format.
        """
        # Defaults using new ascend/descend model
        config: dict = {
            # Color range
            "color_mode": "kelvin",
            "min_color_temp": 500,
            "max_color_temp": 6500,

            # Brightness range
            "min_brightness": 1,
            "max_brightness": 100,

            # Ascend/Descend timing (hours 0-24)
            "ascend_start": 3.0,
            "descend_start": 12.0,
            "wake_time": 6.0,
            "bed_time": 22.0,

            # Speed (1-10 scale)
            "wake_speed": 8,
            "bed_speed": 6,

            # Warm at night rule
            "warm_night_enabled": False,
            "warm_night_mode": "all",  # "all", "sunrise", "sunset"
            "warm_night_target": 2700,
            "warm_night_start": -60,  # minutes offset from sunset (negative = before)
            "warm_night_end": 60,     # minutes offset from sunrise (positive = after)
            "warm_night_fade": 60,    # fade duration in minutes

            # Cool during day rule
            "cool_day_enabled": False,
            "cool_day_mode": "all",
            "cool_day_target": 6500,
            "cool_day_start": 0,
            "cool_day_end": 0,
            "cool_day_fade": 60,

            # Activity preset
            "activity_preset": "adult",

            # Location (default to HA, allow override)
            "latitude": 35.0,
            "longitude": -78.6,
            "timezone": "US/Eastern",
            "use_ha_location": True,

            # Dimming steps
            "max_dim_steps": DEFAULT_MAX_DIM_STEPS,

            # UI preview settings
            "month": 6,

            # Advanced timing settings (tenths of seconds unless noted)
            "turn_on_transition": 3,
            "turn_off_transition": 3,
            "two_step_delay": 3,
            "multi_click_enabled": True,
            "multi_click_speed": 2,
            "circadian_refresh": 30,  # seconds
            "sync_refresh_multiplier": 5,  # multiplier of circadian refresh

            # Motion warning settings
            "motion_warning_time": 0,  # seconds (0 = disabled)
            "motion_warning_blink_threshold": 15,  # percent brightness

            # Visual feedback settings
            "freeze_off_rise": 10,  # tenths of seconds (1.0s)
            "limit_warning_speed": 3,  # tenths of seconds (0.3s)
            "warning_intensity": 3,  # 1-10
            "warning_scaling": 1,  # 1-10
        }

        # Merge supervisor-managed options.json (if present)
        try:
            if os.path.exists(self.options_file):
                async with aiofiles.open(self.options_file, 'r') as f:
                    content = await f.read()
                    opts = json.loads(content)
                    if isinstance(opts, dict):
                        config.update(opts)
        except Exception as e:
            logger.warning(f"Error loading {self.options_file}: {e}")

        # Merge user-saved designer config (persists across restarts)
        try:
            if os.path.exists(self.designer_file):
                async with aiofiles.open(self.designer_file, 'r') as f:
                    content = await f.read()
                    overrides = json.loads(content)
                    if isinstance(overrides, dict):
                        config.update(overrides)
        except Exception as e:
            logger.warning(f"Error loading {self.designer_file}: {e}")

        # Migrate to GloZone format if needed
        config = self._migrate_to_glozone_format(config)

        # Ensure top-level preset settings are merged INTO the preset
        # This handles cases where config was partially migrated
        if "circadian_presets" in config and config["circadian_presets"]:
            first_preset_name = list(config["circadian_presets"].keys())[0]
            first_preset = config["circadian_presets"][first_preset_name]
            for key in list(config.keys()):
                if key in self.PRESET_SETTINGS:
                    if key not in first_preset:
                        first_preset[key] = config[key]
                    del config[key]

        # Update glozone module with current config
        glozone.set_config(config)

        # Return effective config (flat format for backward compatibility)
        return self._get_effective_config(config)

    async def load_raw_config(self) -> dict:
        """Load raw configuration without flattening.

        Returns the GloZone-format config with circadian_presets and glozones.
        Used internally for save operations.
        """
        # Start with defaults
        config: dict = {
            "color_mode": "kelvin",
            "min_color_temp": 500,
            "max_color_temp": 6500,
            "min_brightness": 1,
            "max_brightness": 100,
            "ascend_start": 3.0,
            "descend_start": 12.0,
            "wake_time": 6.0,
            "bed_time": 22.0,
            "wake_speed": 8,
            "bed_speed": 6,
            "warm_night_enabled": False,
            "warm_night_mode": "all",
            "warm_night_target": 2700,
            "warm_night_start": -60,
            "warm_night_end": 60,
            "warm_night_fade": 60,
            "cool_day_enabled": False,
            "cool_day_mode": "all",
            "cool_day_target": 6500,
            "cool_day_start": 0,
            "cool_day_end": 0,
            "cool_day_fade": 60,
            "activity_preset": "adult",
            "latitude": 35.0,
            "longitude": -78.6,
            "timezone": "US/Eastern",
            "use_ha_location": True,
            "max_dim_steps": DEFAULT_MAX_DIM_STEPS,
            "month": 6,
            # Advanced timing settings (tenths of seconds unless noted)
            "turn_on_transition": 3,
            "turn_off_transition": 3,
            "two_step_delay": 3,
            "multi_click_enabled": True,
            "multi_click_speed": 2,
            "circadian_refresh": 30,  # seconds
            "sync_refresh_multiplier": 5,  # multiplier of circadian refresh
            # Motion warning settings
            "motion_warning_time": 0,  # seconds (0 = disabled)
            "motion_warning_blink_threshold": 15,  # percent brightness
            # Visual feedback settings
            "freeze_off_rise": 10,  # tenths of seconds (1.0s)
            "limit_warning_speed": 3,  # tenths of seconds (0.3s)
            "warning_intensity": 3,  # 1-10
            "warning_scaling": 1,  # 1-10
        }

        # Merge options.json
        try:
            if os.path.exists(self.options_file):
                async with aiofiles.open(self.options_file, 'r') as f:
                    content = await f.read()
                    opts = json.loads(content)
                    if isinstance(opts, dict):
                        config.update(opts)
        except Exception as e:
            logger.warning(f"Error loading {self.options_file}: {e}")

        # Merge designer_config.json
        designer_loaded = False
        try:
            if os.path.exists(self.designer_file):
                async with aiofiles.open(self.designer_file, 'r') as f:
                    content = await f.read()
                    overrides = json.loads(content)
                    if isinstance(overrides, dict):
                        config.update(overrides)
                        designer_loaded = True
            else:
                # File doesn't exist yet - that's OK for fresh installs
                designer_loaded = True
        except json.JSONDecodeError as e:
            # Try to repair corrupted JSON (e.g., "Extra data" from duplicate writes)
            logger.warning(f"JSON error in {self.designer_file}: {e}")
            if "Extra data" in str(e) and os.path.exists(self.designer_file):
                logger.info("Attempting to repair corrupted designer_config.json...")
                try:
                    repaired = await self._repair_json_file(self.designer_file)
                    if repaired and isinstance(repaired, dict):
                        config.update(repaired)
                        designer_loaded = True
                        logger.info("Successfully repaired and loaded designer_config.json")
                except Exception as repair_err:
                    logger.error(f"Failed to repair {self.designer_file}: {repair_err}")
        except Exception as e:
            logger.error(f"CRITICAL: Failed to load {self.designer_file}: {e}")
            # Mark as not loaded to prevent accidental overwrites
            designer_loaded = False

        # Track load status to prevent saving incomplete data
        config["_designer_loaded"] = designer_loaded
        if not designer_loaded:
            logger.error("Designer config load failed - saves will be blocked to prevent data loss")

        # Migrate to GloZone format if needed
        config = self._migrate_to_glozone_format(config)

        # Ensure top-level preset settings are merged INTO the preset before removing them
        # This handles cases where config was partially migrated (has circadian_presets structure
        # but settings are still at top level)
        if "circadian_presets" in config and config["circadian_presets"]:
            first_preset_name = list(config["circadian_presets"].keys())[0]
            first_preset = config["circadian_presets"][first_preset_name]

            # Copy any top-level preset settings into the preset (if not already there)
            for key in list(config.keys()):
                if key in self.PRESET_SETTINGS:
                    if key not in first_preset:
                        first_preset[key] = config[key]
                        logger.debug(f"Migrated top-level key '{key}' into preset '{first_preset_name}'")
                    del config[key]

        return config

    async def _repair_json_file(self, filepath: str):
        """Attempt to repair a corrupted JSON file with duplicate content.

        When a JSON file has "Extra data" error, it usually means the file
        was written multiple times without truncating. This extracts the
        first valid JSON object and rewrites the file.

        Args:
            filepath: Path to the corrupted JSON file

        Returns:
            The repaired dict, or None if repair failed
        """
        try:
            async with aiofiles.open(filepath, 'r') as f:
                content = await f.read()

            # Use JSONDecoder to extract just the first valid JSON object
            decoder = json.JSONDecoder()
            repaired_data, end_idx = decoder.raw_decode(content)

            if isinstance(repaired_data, dict):
                # Backup the corrupted file
                backup_path = filepath + ".corrupted"
                async with aiofiles.open(backup_path, 'w') as f:
                    await f.write(content)
                logger.info(f"Backed up corrupted file to {backup_path}")

                # Write the repaired JSON
                async with aiofiles.open(filepath, 'w') as f:
                    await f.write(json.dumps(repaired_data, indent=2))
                logger.info(f"Repaired {filepath} (extracted {end_idx} of {len(content)} chars)")

                return repaired_data
            else:
                logger.warning(f"Repaired JSON is not a dict: {type(repaired_data)}")
                return None
        except Exception as e:
            logger.error(f"Failed to repair JSON file {filepath}: {e}")
            return None

    async def save_config_to_file(self, config: dict):
        """Save designer configuration to persistent file distinct from options.json.

        Will refuse to save if the config was not successfully loaded, to prevent
        accidental data loss from overwriting good data with incomplete data.
        """
        # Safety check: don't save if we failed to load the config properly
        if not config.get("_designer_loaded", True):
            logger.error("REFUSING TO SAVE: config was not loaded successfully - would cause data loss")
            raise RuntimeError("Cannot save config: original file was not loaded successfully")

        try:
            # Remove internal tracking flag before saving
            save_config = {k: v for k, v in config.items() if not k.startswith("_")}
            async with aiofiles.open(self.designer_file, 'w') as f:
                await f.write(json.dumps(save_config, indent=2))
            logger.info(f"Configuration saved to {self.designer_file}")
        except Exception as e:
            logger.error(f"Error saving config to file: {e}")
            raise

    # -------------------------------------------------------------------------
    # Live Design API endpoints
    # -------------------------------------------------------------------------

    def _get_ha_api_config(self) -> tuple:
        """Get Home Assistant API URL and token from environment.

        Returns:
            Tuple of (rest_url, ws_url, token) or (None, None, None) if not available.
        """
        token = os.environ.get('HA_TOKEN')
        if not token:
            return None, None, None

        # Check for explicit URLs first (set by run script in addon mode)
        rest_url = os.environ.get('HA_REST_URL')
        ws_url = os.environ.get('HA_WEBSOCKET_URL')

        if rest_url and ws_url:
            return rest_url, ws_url, token

        # Fall back to constructing URLs from host/port
        host = os.environ.get('HA_HOST')
        port = os.environ.get('HA_PORT', '8123')
        use_ssl = os.environ.get('HA_USE_SSL', 'false').lower() == 'true'

        if host:
            http_protocol = 'https' if use_ssl else 'http'
            ws_protocol = 'wss' if use_ssl else 'ws'
            rest_url = f"{http_protocol}://{host}:{port}/api"
            ws_url = f"{ws_protocol}://{host}:{port}/api/websocket"
            return rest_url, ws_url, token

        return None, None, None

    async def _fetch_area_light_capabilities(self, ws_url: str, token: str, area_id: str) -> tuple:
        """Fetch light capabilities for an area via WebSocket.

        Queries HA for lights in the specified area and determines which support
        color modes (xy/rgb/hs) vs CT-only.

        Args:
            ws_url: WebSocket URL
            token: HA auth token
            area_id: Area to fetch lights for

        Returns:
            Tuple of (color_lights, ct_lights) - lists of entity_ids
        """
        color_lights = []
        ct_lights = []

        try:
            async with websockets.connect(ws_url) as ws:
                # Authenticate
                msg = json.loads(await ws.recv())
                if msg.get('type') != 'auth_required':
                    logger.error(f"[Live Design] Unexpected WS message: {msg}")
                    return [], []

                await ws.send(json.dumps({'type': 'auth', 'access_token': token}))
                msg = json.loads(await ws.recv())
                if msg.get('type') != 'auth_ok':
                    logger.error(f"[Live Design] WS auth failed: {msg}")
                    return [], []

                # Fetch device registry (for device -> area mapping)
                await ws.send(json.dumps({'id': 1, 'type': 'config/device_registry/list'}))
                device_msg = json.loads(await ws.recv())
                device_areas = {}
                if device_msg.get('success') and device_msg.get('result'):
                    for device in device_msg['result']:
                        device_id = device.get('id')
                        dev_area = device.get('area_id')
                        if device_id and dev_area:
                            device_areas[device_id] = dev_area

                # Fetch entity registry (for entity -> area/device mapping)
                await ws.send(json.dumps({'id': 2, 'type': 'config/entity_registry/list'}))
                entity_msg = json.loads(await ws.recv())
                if not entity_msg.get('success') or not entity_msg.get('result'):
                    logger.error(f"[Live Design] Failed to get entities: {entity_msg}")
                    return [], []

                # Find light entities in this area
                area_light_entities = []
                for entity in entity_msg['result']:
                    entity_id = entity.get('entity_id', '')
                    if not entity_id.startswith('light.'):
                        continue

                    # Check if entity is in our area (directly or via device)
                    entity_area = entity.get('area_id')
                    if not entity_area:
                        device_id = entity.get('device_id')
                        if device_id:
                            entity_area = device_areas.get(device_id)

                    if entity_area == area_id:
                        area_light_entities.append(entity_id)

                if not area_light_entities:
                    logger.info(f"[Live Design] No lights found in area {area_id}")
                    return [], []

                # Fetch states to get supported_color_modes
                await ws.send(json.dumps({'id': 3, 'type': 'get_states'}))
                states_msg = json.loads(await ws.recv())
                if not states_msg.get('success') or not states_msg.get('result'):
                    logger.error(f"[Live Design] Failed to get states: {states_msg}")
                    return [], []

                # Build lookup of entity_id -> state
                state_lookup = {s.get('entity_id'): s for s in states_msg['result']}

                # Classify lights by color capability
                for entity_id in area_light_entities:
                    state = state_lookup.get(entity_id, {})
                    attrs = state.get('attributes', {})
                    modes = set(attrs.get('supported_color_modes', []))

                    # Check if light supports any color mode (xy, rgb, hs)
                    if 'xy' in modes or 'rgb' in modes or 'hs' in modes:
                        color_lights.append(entity_id)
                    else:
                        ct_lights.append(entity_id)

                logger.info(f"[Live Design] Area {area_id}: {len(color_lights)} color lights, {len(ct_lights)} CT-only lights")
                return color_lights, ct_lights

        except Exception as e:
            logger.error(f"[Live Design] Error fetching light capabilities: {e}", exc_info=True)
            return [], []

    async def _call_service_via_websocket(self, ws_url: str, token: str, domain: str, service: str, service_data: dict = None) -> bool:
        """Call a Home Assistant service via WebSocket API.

        Args:
            ws_url: WebSocket URL (e.g., ws://supervisor/core/api/websocket)
            token: Home Assistant auth token
            domain: Service domain (e.g., 'circadian')
            service: Service name (e.g., 'refresh')
            service_data: Optional service data dict

        Returns:
            True if service call succeeded, False otherwise
        """
        try:
            async with websockets.connect(ws_url) as ws:
                # Wait for auth_required message
                msg = json.loads(await ws.recv())
                if msg.get('type') != 'auth_required':
                    logger.error(f"[WS Service] Unexpected message: {msg}")
                    return False

                # Send auth
                await ws.send(json.dumps({
                    'type': 'auth',
                    'access_token': token
                }))

                # Wait for auth response
                msg = json.loads(await ws.recv())
                if msg.get('type') != 'auth_ok':
                    logger.error(f"[WS Service] Auth failed: {msg}")
                    return False

                # Call the service
                call_msg = {
                    'id': 1,
                    'type': 'call_service',
                    'domain': domain,
                    'service': service,
                }
                if service_data:
                    call_msg['service_data'] = service_data

                await ws.send(json.dumps(call_msg))

                # Wait for result (with timeout)
                try:
                    result = await asyncio.wait_for(ws.recv(), timeout=5.0)
                    result_msg = json.loads(result)
                    # The result may just acknowledge the call was received
                    # For circadian.refresh, main.py handles it via event subscription
                    logger.info(f"[WS Service] {domain}.{service} call result: {result_msg.get('type')}")
                    return True
                except asyncio.TimeoutError:
                    # Service call was sent, assume it worked
                    logger.info(f"[WS Service] {domain}.{service} call sent (no response)")
                    return True

        except Exception as e:
            logger.warning(f"[WS Service] Error calling {domain}.{service}: {e}")
            return False

    async def _fire_event_via_websocket(self, ws_url: str, token: str, event_type: str, event_data: dict = None) -> bool:
        """Fire a Home Assistant event via WebSocket API.

        Args:
            ws_url: WebSocket URL (e.g., ws://supervisor/core/api/websocket)
            token: Home Assistant auth token
            event_type: Event type to fire (e.g., 'circadian_light_refresh')
            event_data: Optional event data dict

        Returns:
            True if event was fired, False otherwise
        """
        try:
            async with websockets.connect(ws_url) as ws:
                # Wait for auth_required message
                msg = json.loads(await ws.recv())
                if msg.get('type') != 'auth_required':
                    logger.error(f"[WS Event] Unexpected message: {msg}")
                    return False

                # Send auth
                await ws.send(json.dumps({
                    'type': 'auth',
                    'access_token': token
                }))

                # Wait for auth response
                msg = json.loads(await ws.recv())
                if msg.get('type') != 'auth_ok':
                    logger.error(f"[WS Event] Auth failed: {msg}")
                    return False

                # Fire the event
                fire_msg = {
                    'id': 1,
                    'type': 'fire_event',
                    'event_type': event_type,
                }
                if event_data:
                    fire_msg['event_data'] = event_data

                await ws.send(json.dumps(fire_msg))

                # Wait for result (with timeout)
                try:
                    result = await asyncio.wait_for(ws.recv(), timeout=5.0)
                    result_msg = json.loads(result)
                    logger.info(f"[WS Event] {event_type} fire result: {result_msg.get('type')}")
                    return result_msg.get('type') == 'result' and result_msg.get('success', False)
                except asyncio.TimeoutError:
                    # Event was sent, assume it worked
                    logger.info(f"[WS Event] {event_type} event sent (no response)")
                    return True

        except Exception as e:
            logger.warning(f"[WS Event] Error firing {event_type}: {e}")
            return False

    async def _fetch_light_states(self, ws_url: str, token: str, entity_ids: list) -> dict:
        """Fetch current states of lights for later restoration.

        Args:
            ws_url: WebSocket URL
            token: Home Assistant auth token
            entity_ids: List of light entity IDs

        Returns:
            Dict mapping entity_id to state dict with brightness, color_temp, etc.
        """
        if not entity_ids:
            return {}

        saved_states = {}
        try:
            async with websockets.connect(ws_url) as ws:
                # Auth
                msg = json.loads(await ws.recv())
                if msg.get('type') != 'auth_required':
                    return {}
                await ws.send(json.dumps({'type': 'auth', 'access_token': token}))
                msg = json.loads(await ws.recv())
                if msg.get('type') != 'auth_ok':
                    return {}

                # Get states
                await ws.send(json.dumps({'id': 1, 'type': 'get_states'}))
                result = json.loads(await ws.recv())

                if result.get('type') == 'result' and result.get('success'):
                    states = result.get('result', [])
                    for state_obj in states:
                        entity_id = state_obj.get('entity_id')
                        if entity_id in entity_ids:
                            attrs = state_obj.get('attributes', {})
                            saved_states[entity_id] = {
                                'state': state_obj.get('state'),
                                'brightness': attrs.get('brightness'),
                                'color_temp_kelvin': attrs.get('color_temp_kelvin'),
                                'color_temp': attrs.get('color_temp'),  # Mireds
                                'xy_color': attrs.get('xy_color'),
                                'rgb_color': attrs.get('rgb_color'),
                                'color_mode': attrs.get('color_mode'),
                            }

                logger.info(f"[Live Design] Saved states for {len(saved_states)} lights")
                return saved_states

        except Exception as e:
            logger.error(f"[Live Design] Error fetching light states: {e}")
            return {}

    async def _turn_off_lights(self, ws_url: str, token: str, entity_ids: list, transition: float = 2) -> bool:
        """Turn off lights with a transition.

        Args:
            ws_url: WebSocket URL
            token: Home Assistant auth token
            entity_ids: List of light entity IDs
            transition: Transition time in seconds

        Returns:
            True if successful
        """
        if not entity_ids:
            return True

        try:
            async with websockets.connect(ws_url) as ws:
                # Auth
                msg = json.loads(await ws.recv())
                if msg.get('type') != 'auth_required':
                    return False
                await ws.send(json.dumps({'type': 'auth', 'access_token': token}))
                msg = json.loads(await ws.recv())
                if msg.get('type') != 'auth_ok':
                    return False

                # Turn off all lights with transition
                await ws.send(json.dumps({
                    'id': 1,
                    'type': 'call_service',
                    'domain': 'light',
                    'service': 'turn_off',
                    'service_data': {'entity_id': entity_ids, 'transition': transition}
                }))

                # Wait for transition to complete
                await asyncio.sleep(transition + 0.5)
                logger.info(f"[Live Design] Turned off {len(entity_ids)} lights with {transition}s transition")
                return True

        except Exception as e:
            logger.error(f"[Live Design] Error turning off lights: {e}")
            return False

    async def _restore_light_states(self, ws_url: str, token: str, saved_states: dict, transition: float = 2) -> bool:
        """Restore previously saved light states.

        Args:
            ws_url: WebSocket URL
            token: Home Assistant auth token
            saved_states: Dict from _fetch_light_states
            transition: Transition time in seconds

        Returns:
            True if restoration succeeded
        """
        if not saved_states:
            return True

        try:
            async with websockets.connect(ws_url) as ws:
                # Auth
                msg = json.loads(await ws.recv())
                if msg.get('type') != 'auth_required':
                    return False
                await ws.send(json.dumps({'type': 'auth', 'access_token': token}))
                msg = json.loads(await ws.recv())
                if msg.get('type') != 'auth_ok':
                    return False

                msg_id = 1
                for entity_id, state_data in saved_states.items():
                    if state_data.get('state') == 'off':
                        # Light was off - turn it off with transition
                        msg_id += 1
                        await ws.send(json.dumps({
                            'id': msg_id,
                            'type': 'call_service',
                            'domain': 'light',
                            'service': 'turn_off',
                            'service_data': {'entity_id': entity_id, 'transition': transition}
                        }))
                    else:
                        # Light was on - restore its settings
                        service_data = {'entity_id': entity_id, 'transition': transition}

                        brightness = state_data.get('brightness')
                        if brightness is not None:
                            service_data['brightness'] = brightness

                        # Restore color based on what mode it was in
                        color_mode = state_data.get('color_mode')
                        if color_mode == 'xy' and state_data.get('xy_color'):
                            service_data['xy_color'] = state_data['xy_color']
                        elif color_mode == 'color_temp' and state_data.get('color_temp_kelvin'):
                            service_data['color_temp_kelvin'] = state_data['color_temp_kelvin']
                        elif state_data.get('color_temp_kelvin'):
                            service_data['color_temp_kelvin'] = state_data['color_temp_kelvin']

                        msg_id += 1
                        await ws.send(json.dumps({
                            'id': msg_id,
                            'type': 'call_service',
                            'domain': 'light',
                            'service': 'turn_on',
                            'service_data': service_data
                        }))

                # Wait for transition to complete
                await asyncio.sleep(transition + 0.5)
                logger.info(f"[Live Design] Restored {len(saved_states)} light states with {transition}s transition")
                return True

        except Exception as e:
            logger.error(f"[Live Design] Error restoring light states: {e}")
            return False

    async def _fetch_areas_via_websocket(self, ws_url: str, token: str) -> list:
        """Fetch areas that have lights from Home Assistant via WebSocket API.

        Args:
            ws_url: WebSocket URL (e.g., ws://supervisor/core/api/websocket)
            token: Home Assistant auth token

        Returns:
            List of area dicts with area_id and name (only areas with lights)
        """
        logger.info(f"[Live Design] Connecting to WebSocket: {ws_url}")
        try:
            async with websockets.connect(ws_url) as ws:
                # Wait for auth_required message
                msg = json.loads(await ws.recv())
                logger.info(f"[Live Design] WS received: {msg.get('type')}")
                if msg.get('type') != 'auth_required':
                    logger.error(f"[Live Design] Unexpected WS message: {msg}")
                    return []

                # Send auth
                await ws.send(json.dumps({
                    'type': 'auth',
                    'access_token': token
                }))
                logger.info("[Live Design] Sent auth")

                # Wait for auth response
                msg = json.loads(await ws.recv())
                logger.info(f"[Live Design] Auth response: {msg.get('type')}")
                if msg.get('type') != 'auth_ok':
                    logger.error(f"[Live Design] WS auth failed: {msg}")
                    return []

                # Request area registry
                await ws.send(json.dumps({
                    'id': 1,
                    'type': 'config/area_registry/list'
                }))
                logger.info("[Live Design] Requested area registry")

                # Get area response
                area_msg = json.loads(await ws.recv())
                if not area_msg.get('success') or not area_msg.get('result'):
                    logger.error(f"[Live Design] Failed to get areas: {area_msg}")
                    return []

                all_areas = {a['area_id']: a['name'] for a in area_msg['result']}
                logger.info(f"[Live Design] Found {len(all_areas)} total areas")

                # Request device registry (lights often get area from device)
                await ws.send(json.dumps({
                    'id': 2,
                    'type': 'config/device_registry/list'
                }))
                logger.info("[Live Design] Requested device registry")

                # Get device response
                device_msg = json.loads(await ws.recv())
                device_areas = {}
                if device_msg.get('success') and device_msg.get('result'):
                    for device in device_msg['result']:
                        device_id = device.get('id')
                        area_id = device.get('area_id')
                        if device_id and area_id:
                            device_areas[device_id] = area_id
                logger.info(f"[Live Design] Found {len(device_areas)} devices with areas")

                # Request entity registry to find light entities
                await ws.send(json.dumps({
                    'id': 3,
                    'type': 'config/entity_registry/list'
                }))
                logger.info("[Live Design] Requested entity registry")

                # Get entity response
                entity_msg = json.loads(await ws.recv())
                if not entity_msg.get('success') or not entity_msg.get('result'):
                    logger.error(f"[Live Design] Failed to get entities: {entity_msg}")
                    # Fall back to returning all areas
                    areas = [{'area_id': k, 'name': v} for k, v in all_areas.items()]
                    areas.sort(key=lambda x: x['name'].lower())
                    return areas

                # Find area_ids that have at least one light entity
                # Check both direct entity area and area via device
                areas_with_lights = set()
                for entity in entity_msg['result']:
                    entity_id = entity.get('entity_id', '')
                    if not entity_id.startswith('light.'):
                        continue
                    # Check direct area assignment
                    area_id = entity.get('area_id')
                    if area_id:
                        areas_with_lights.add(area_id)
                    # Check area via device
                    device_id = entity.get('device_id')
                    if device_id and device_id in device_areas:
                        areas_with_lights.add(device_areas[device_id])

                logger.info(f"[Live Design] Found {len(areas_with_lights)} areas with lights")

                # Return only areas that have lights
                areas = [
                    {'area_id': area_id, 'name': all_areas[area_id]}
                    for area_id in areas_with_lights
                    if area_id in all_areas
                ]
                areas.sort(key=lambda x: x['name'].lower())
                logger.info(f"[Live Design] Returning {len(areas)} areas with lights")
                return areas

        except Exception as e:
            logger.error(f"[Live Design] WebSocket error: {e}", exc_info=True)
            return []

    async def get_areas(self, request: Request) -> Response:
        """Fetch areas from Home Assistant area registry."""
        rest_url, ws_url, token = self._get_ha_api_config()

        logger.info(f"[Live Design] get_areas called - ws_url={ws_url}, has_token={bool(token)}")

        if not token:
            logger.warning("[Live Design] No HA token configured")
            return web.json_response(
                {'error': 'Home Assistant API not configured'},
                status=503
            )

        if not ws_url:
            logger.warning("[Live Design] No WebSocket URL configured")
            return web.json_response(
                {'error': 'WebSocket URL not configured'},
                status=503
            )

        try:
            areas = await self._fetch_areas_via_websocket(ws_url, token)
            logger.info(f"[Live Design] Returning {len(areas)} areas to client")
            return web.json_response(areas)
        except Exception as e:
            logger.error(f"[Live Design] Error fetching areas: {e}")
            return web.json_response(
                {'error': str(e)},
                status=500
            )

    async def get_area_status(self, request: Request) -> Response:
        """Get status for all areas using Circadian Light state (no HA polling).

        Uses in-memory state from state.py and glozone_state.py, and calculates
        brightness from the circadian curve. This matches what lights are set to
        after each 30-second update cycle.

        Returns a dict mapping area_id to status:
        {
            "area_id": {
                "is_circadian": true/false (Circadian Light controls this area),
                "is_on": true/false (target light power state),
                "brightness": 0-100 (calculated from circadian curve),
                "frozen": true/false (whether zone is frozen),
                "zone_name": "Zone Name" or null
            }
        }
        """
        try:
            from brain import SunTimes, calculate_sun_times

            # Load config to get glozone mappings and presets
            config = await self.load_config()
            glozones = config.get('glozones', {})
            presets = config.get('circadian_presets', {})

            # Reload state from disk (main.py runs in separate process and writes state there)
            state.init()

            # Get current hour for calculations
            current_hour = get_current_hour()

            # Calculate sun times for solar rules
            latitude = float(os.getenv("HASS_LATITUDE", "35.0"))
            longitude = float(os.getenv("HASS_LONGITUDE", "-78.6"))
            sun_times = SunTimes()  # defaults
            try:
                from zoneinfo import ZoneInfo
                timezone = os.getenv("HASS_TIME_ZONE", "US/Eastern")
                try:
                    tzinfo = ZoneInfo(timezone)
                except:
                    tzinfo = None
                now = datetime.now(tzinfo)
                date_str = now.strftime('%Y-%m-%d')
                sun_dict = calculate_sun_times(latitude, longitude, date_str)

                def iso_to_hour(iso_str, default):
                    if not iso_str:
                        return default
                    try:
                        dt = datetime.fromisoformat(iso_str)
                        # Convert to local timezone if available
                        if tzinfo and dt.tzinfo:
                            dt = dt.astimezone(tzinfo)
                        return dt.hour + dt.minute / 60.0 + dt.second / 3600.0
                    except:
                        return default

                sun_times = SunTimes(
                    sunrise=iso_to_hour(sun_dict.get("sunrise"), 6.0),
                    sunset=iso_to_hour(sun_dict.get("sunset"), 18.0),
                    solar_noon=iso_to_hour(sun_dict.get("noon"), 12.0),
                    solar_mid=(iso_to_hour(sun_dict.get("noon"), 12.0) + 12.0) % 24.0,
                )
            except Exception as e:
                logger.debug(f"[AreaStatus] Error calculating sun times: {e}")

            # Build response for each area in zones (including Unassigned)
            area_status = {}
            for zone_name, zone_data in glozones.items():
                # Add status for each area in this zone
                for area in zone_data.get('areas', []):
                    # Areas can be stored as {id, name} or just string
                    area_id = area.get('id') if isinstance(area, dict) else area

                    # Get area's state (includes brightness_mid, color_mid, frozen_at)
                    area_state_dict = state.get_area(area_id)
                    area_state = AreaState.from_dict(area_state_dict)

                    # Get effective config for this area (zone's preset merged with global config)
                    config_dict = glozone.get_effective_config_for_area(area_id)
                    area_config = Config.from_dict(config_dict)

                    # Use area's frozen_at if set, otherwise current time
                    calc_hour = area_state.frozen_at if area_state.frozen_at is not None else current_hour

                    # Calculate using area's actual state (which has brightness_mid, color_mid)
                    brightness = 50
                    kelvin = 4000
                    try:
                        result = CircadianLight.calculate_lighting(calc_hour, area_config, area_state, sun_times=sun_times)
                        brightness = result.brightness
                        kelvin = result.color_temp
                    except Exception as e:
                        logger.warning(f"Error calculating lighting for area {area_id}: {e}")

                    # Check if area is boosted and add boost brightness
                    is_boosted = state.is_boosted(area_id)
                    if is_boosted:
                        boost_state = state.get_boost_state(area_id)
                        boost_amount = boost_state.get('boost_brightness') or 0
                        brightness = min(100, brightness + boost_amount)

                    area_status[area_id] = {
                        'is_circadian': area_state.is_circadian,
                        'is_on': area_state.is_on,
                        'brightness': brightness,
                        'kelvin': kelvin,
                        'frozen': area_state.frozen_at is not None,
                        'boosted': is_boosted,
                        'zone_name': zone_name if zone_name != 'Unassigned' else None,
                        # Raw state model
                        'brightness_mid': area_state.brightness_mid,
                        'color_mid': area_state.color_mid,
                        'color_override': area_state.color_override,
                        'frozen_at': area_state.frozen_at,
                    }

            return web.json_response(area_status)

        except Exception as e:
            logger.error(f"[Area Status] Error: {e}", exc_info=True)
            return web.json_response({'error': str(e)}, status=500)

    async def get_area_settings(self, request: Request) -> Response:
        """Get settings for a specific area.

        Returns motion_function, motion_duration for the area.
        """
        area_id = request.match_info.get('area_id')
        if not area_id:
            return web.json_response({'error': 'area_id required'}, status=400)

        try:
            config = await self.load_config()
            area_settings = config.get('area_settings', {})
            settings = area_settings.get(area_id, {
                'motion_function': 'disabled',
                'motion_duration': 60
            })
            return web.json_response(settings)

        except Exception as e:
            logger.error(f"[Area Settings] Error getting settings for {area_id}: {e}")
            return web.json_response({'error': str(e)}, status=500)

    async def save_area_settings(self, request: Request) -> Response:
        """Save settings for a specific area.

        Expects JSON body with motion_function and/or motion_duration.
        """
        area_id = request.match_info.get('area_id')
        if not area_id:
            return web.json_response({'error': 'area_id required'}, status=400)

        try:
            data = await request.json()

            # Validate motion_function if provided
            valid_functions = ['disabled', 'boost', 'on_off', 'on_only']
            if 'motion_function' in data and data['motion_function'] not in valid_functions:
                return web.json_response({
                    'error': f"Invalid motion_function. Must be one of: {valid_functions}"
                }, status=400)

            # Load current config
            config = await self.load_config()

            # Initialize area_settings if not present
            if 'area_settings' not in config:
                config['area_settings'] = {}

            # Initialize this area's settings if not present
            if area_id not in config['area_settings']:
                config['area_settings'][area_id] = {
                    'motion_function': 'disabled',
                    'motion_duration': 60
                }

            # Update with provided values
            if 'motion_function' in data:
                config['area_settings'][area_id]['motion_function'] = data['motion_function']
            if 'motion_duration' in data:
                config['area_settings'][area_id]['motion_duration'] = int(data['motion_duration'])

            # Save config
            await self.save_config_to_file(config)

            logger.info(f"[Area Settings] Saved settings for {area_id}: {config['area_settings'][area_id]}")
            return web.json_response({'success': True, 'settings': config['area_settings'][area_id]})

        except Exception as e:
            logger.error(f"[Area Settings] Error saving settings for {area_id}: {e}")
            return web.json_response({'error': str(e)}, status=500)

    async def apply_light(self, request: Request) -> Response:
        """Apply brightness and color temperature to lights in an area.

        Uses cached light capabilities to send appropriate commands:
        - Color-capable lights: xy_color for full color range
        - CT-only lights: color_temp_kelvin (clamped to 2000K minimum)
        """
        rest_url, ws_url, token = self._get_ha_api_config()

        if not rest_url or not token:
            logger.warning("Home Assistant API not configured for Live Design")
            return web.json_response(
                {'error': 'Home Assistant API not configured'},
                status=503
            )

        try:
            data = await request.json()
            area_id = data.get('area_id')
            brightness = data.get('brightness')
            color_temp = data.get('color_temp')
            transition = data.get('transition', 0.3)  # Default 0.3s for smooth updates

            if not area_id:
                return web.json_response(
                    {'error': 'area_id is required'},
                    status=400
                )

            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json',
            }

            # Check if we have cached capabilities for this area
            if self.live_design_area == area_id and (self.live_design_color_lights or self.live_design_ct_lights):
                # Use capability-based splitting
                async with ClientSession() as session:
                    tasks = []

                    # Color-capable lights: use xy_color
                    if self.live_design_color_lights:
                        color_data = {
                            'entity_id': self.live_design_color_lights,
                            'transition': transition,
                        }
                        if brightness is not None:
                            color_data['brightness_pct'] = int(brightness)
                        if color_temp is not None:
                            xy = CircadianLight.color_temperature_to_xy(int(color_temp))
                            color_data['xy_color'] = list(xy)

                        tasks.append(session.post(
                            f'{rest_url}/services/light/turn_on',
                            headers=headers,
                            json=color_data
                        ))

                    # CT-only lights: use color_temp_kelvin
                    if self.live_design_ct_lights:
                        ct_data = {
                            'entity_id': self.live_design_ct_lights,
                            'transition': transition,
                        }
                        if brightness is not None:
                            ct_data['brightness_pct'] = int(brightness)
                        if color_temp is not None:
                            ct_data['color_temp_kelvin'] = max(2000, int(color_temp))

                        tasks.append(session.post(
                            f'{rest_url}/services/light/turn_on',
                            headers=headers,
                            json=ct_data
                        ))

                    # Execute all requests concurrently
                    if tasks:
                        responses = await asyncio.gather(*tasks)
                        for resp in responses:
                            if resp.status not in (200, 201):
                                logger.error(f"Failed to apply light: {resp.status}")

                logger.info(
                    f"Live Design: Applied {brightness}% / {color_temp}K to area {area_id} "
                    f"({len(self.live_design_color_lights)} color, {len(self.live_design_ct_lights)} CT)"
                )
                return web.json_response({'status': 'ok'})

            else:
                # Fallback: no cached capabilities, use area-based with XY
                service_data = {
                    'area_id': area_id,
                    'transition': transition,
                }

                if brightness is not None:
                    service_data['brightness_pct'] = int(brightness)

                if color_temp is not None:
                    xy = CircadianLight.color_temperature_to_xy(int(color_temp))
                    service_data['xy_color'] = list(xy)

                async with ClientSession() as session:
                    async with session.post(
                        f'{rest_url}/services/light/turn_on',
                        headers=headers,
                        json=service_data
                    ) as resp:
                        if resp.status not in (200, 201):
                            logger.error(f"Failed to apply light: {resp.status}")
                            return web.json_response(
                                {'error': f'HA API returned {resp.status}'},
                                status=resp.status
                            )

                logger.info(
                    f"Live Design (fallback): Applied {brightness}% / {color_temp}K to area {area_id}"
                )
                return web.json_response({'status': 'ok'})
        except json.JSONDecodeError:
            return web.json_response(
                {'error': 'Invalid JSON'},
                status=400
            )
        except Exception as e:
            logger.error(f"Error applying light: {e}")
            return web.json_response(
                {'error': str(e)},
                status=500
            )

    async def set_circadian_mode(self, request: Request) -> Response:
        """Enable or disable Circadian mode for an area.

        Used by Live Design to pause automatic updates while designing.
        When circadian mode is disabled (is_circadian=False), Live Design becomes active
        and we fetch light capabilities for that area, save current light states,
        and notify main.py to skip this area in periodic updates.
        """
        try:
            data = await request.json()
            area_id = data.get('area_id')
            # Support both 'is_circadian' (new) and 'enabled' (legacy) field names
            is_circadian = data.get('is_circadian', data.get('enabled', True))

            if not area_id:
                return web.json_response(
                    {'error': 'area_id is required'},
                    status=400
                )

            state.set_is_circadian(area_id, is_circadian)

            rest_url, ws_url, token = self._get_ha_api_config()

            if not is_circadian:
                # Live Design is starting - fetch light capabilities for this area
                if ws_url and token:
                    color_lights, ct_lights = await self._fetch_area_light_capabilities(ws_url, token, area_id)
                    self.live_design_area = area_id
                    self.live_design_color_lights = color_lights
                    self.live_design_ct_lights = ct_lights

                    # Save current light states for restoration later
                    all_lights = color_lights + ct_lights
                    self.live_design_saved_states = await self._fetch_light_states(ws_url, token, all_lights)
                    logger.info(f"[Live Design] Started for area {area_id}: {len(color_lights)} color, {len(ct_lights)} CT-only, saved {len(self.live_design_saved_states)} states")

                    # Visual feedback: fade to off over 2 seconds
                    await self._turn_off_lights(ws_url, token, all_lights, transition=2)

                    # Notify main.py to skip this area in periodic updates
                    await self._fire_event_via_websocket(
                        ws_url, token, 'circadian_light_live_design',
                        {'area_id': area_id, 'active': True}
                    )
                else:
                    logger.warning("[Live Design] Cannot fetch capabilities - no HA API config")
                    self.live_design_area = area_id
                    self.live_design_color_lights = []
                    self.live_design_ct_lights = []
                    self.live_design_saved_states = {}
            else:
                # Live Design is ending - restore saved states and clear cache
                if self.live_design_area == area_id:
                    logger.info(f"[Live Design] Ended for area {area_id}")

                    all_lights = self.live_design_color_lights + self.live_design_ct_lights

                    # Visual feedback: fade to off over 2 seconds, then restore with 2s transition
                    if all_lights and ws_url and token:
                        await self._turn_off_lights(ws_url, token, all_lights, transition=2)

                    # Restore saved light states with 2s transition
                    if self.live_design_saved_states and ws_url and token:
                        await self._restore_light_states(ws_url, token, self.live_design_saved_states, transition=2)
                        logger.info(f"[Live Design] Restored {len(self.live_design_saved_states)} light states")

                    # Notify main.py that Live Design ended
                    if ws_url and token:
                        await self._fire_event_via_websocket(
                            ws_url, token, 'circadian_light_live_design',
                            {'area_id': area_id, 'active': False}
                        )

                    self.live_design_area = None
                    self.live_design_color_lights = []
                    self.live_design_ct_lights = []
                    self.live_design_saved_states = {}

            logger.info(f"[Live Design] Circadian mode {'enabled' if is_circadian else 'disabled'} for area {area_id}")

            return web.json_response({'status': 'ok', 'is_circadian': is_circadian})
        except json.JSONDecodeError:
            return web.json_response(
                {'error': 'Invalid JSON'},
                status=400
            )
        except Exception as e:
            logger.error(f"Error setting circadian mode: {e}")
            return web.json_response(
                {'error': str(e)},
                status=500
            )

    # -------------------------------------------------------------------------
    # GloZone API - Circadian Presets CRUD
    # -------------------------------------------------------------------------

    async def get_circadian_presets(self, request: Request) -> Response:
        """Get all circadian presets."""
        try:
            config = await self.load_raw_config()
            presets = config.get("circadian_presets", {})
            return web.json_response({"presets": presets})
        except Exception as e:
            logger.error(f"Error getting circadian presets: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def create_circadian_preset(self, request: Request) -> Response:
        """Create a new circadian preset."""
        try:
            data = await request.json()
            name = data.get("name")
            settings = data.get("settings", {})

            if not name:
                return web.json_response({"error": "name is required"}, status=400)

            config = await self.load_raw_config()

            if name in config.get("circadian_presets", {}):
                return web.json_response({"error": f"Preset '{name}' already exists"}, status=409)

            # Create the preset with provided settings (or empty)
            config.setdefault("circadian_presets", {})[name] = settings

            await self.save_config_to_file(config)
            glozone.set_config(config)

            logger.info(f"Created circadian preset: {name}")
            return web.json_response({"status": "created", "name": name})
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)
        except Exception as e:
            logger.error(f"Error creating preset: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def update_circadian_preset(self, request: Request) -> Response:
        """Update a circadian preset (settings or rename)."""
        try:
            name = request.match_info.get("name")
            data = await request.json()

            config = await self.load_raw_config()

            if name not in config.get("circadian_presets", {}):
                return web.json_response({"error": f"Glo '{name}' not found"}, status=404)

            # Handle rename if "name" field is provided
            new_name = data.pop("name", None)
            if new_name and new_name != name:
                if name == glozone.DEFAULT_PRESET:
                    return web.json_response(
                        {"error": f"Cannot rename default Glo '{name}'"},
                        status=400
                    )
                if new_name in config.get("circadian_presets", {}):
                    return web.json_response(
                        {"error": f"Glo '{new_name}' already exists"},
                        status=400
                    )
                # Rename the preset
                config["circadian_presets"][new_name] = config["circadian_presets"].pop(name)
                # Update all zones using this preset
                for zone_name, zone_data in config.get("glozones", {}).items():
                    if zone_data.get("preset") == name:
                        zone_data["preset"] = new_name
                logger.info(f"Renamed circadian preset: {name} -> {new_name}")
                name = new_name

            # Update the preset settings if any remain
            if data:
                config["circadian_presets"][name].update(data)

            await self.save_config_to_file(config)
            glozone.set_config(config)

            # Fire refresh event to notify main.py to reload config
            _, ws_url, token = self._get_ha_api_config()
            if ws_url and token:
                await self._fire_event_via_websocket(ws_url, token, 'circadian_light_refresh', {})
                logger.info("Fired circadian_light_refresh event after preset update")

            logger.info(f"Updated circadian preset: {name}")
            return web.json_response({"status": "updated", "name": name})
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)
        except Exception as e:
            logger.error(f"Error updating preset: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def delete_circadian_preset(self, request: Request) -> Response:
        """Delete a circadian preset."""
        try:
            name = request.match_info.get("name")

            if name == glozone.DEFAULT_PRESET:
                return web.json_response(
                    {"error": f"Cannot delete default preset '{name}'"},
                    status=400
                )

            config = await self.load_raw_config()

            if name not in config.get("circadian_presets", {}):
                return web.json_response({"error": f"Preset '{name}' not found"}, status=404)

            # Check if any zones use this preset
            zones_using = [
                zn for zn, zc in config.get("glozones", {}).items()
                if zc.get("preset") == name
            ]
            if zones_using:
                # Switch those zones to default preset
                for zone_name in zones_using:
                    config["glozones"][zone_name]["preset"] = glozone.DEFAULT_PRESET
                logger.info(f"Switched {len(zones_using)} zones to default preset")

            del config["circadian_presets"][name]

            await self.save_config_to_file(config)
            glozone.set_config(config)

            logger.info(f"Deleted circadian preset: {name}")
            return web.json_response({"status": "deleted", "name": name})
        except Exception as e:
            logger.error(f"Error deleting preset: {e}")
            return web.json_response({"error": str(e)}, status=500)

    # -------------------------------------------------------------------------
    # GloZone API - Zones CRUD
    # -------------------------------------------------------------------------

    async def get_glozones(self, request: Request) -> Response:
        """Get all GloZones with their areas and runtime state."""
        try:
            config = await self.load_raw_config()
            zones = config.get("glozones", {})

            # Auto-migrate: add unassigned HA areas to default zone
            await self._migrate_unassigned_areas_to_default(config)
            zones = config.get("glozones", {})

            # Enrich with runtime state
            result = {}
            for zone_name, zone_config in zones.items():
                runtime = glozone_state.get_zone_state(zone_name)
                result[zone_name] = {
                    "preset": zone_config.get("preset"),
                    "areas": zone_config.get("areas", []),
                    "runtime": runtime,
                    "is_default": zone_config.get("is_default", False),
                }

            return web.json_response({"zones": result})
        except Exception as e:
            logger.error(f"Error getting glozones: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def _migrate_unassigned_areas_to_default(self, config: dict) -> None:
        """One-time migration: add any HA areas not in any zone to the default zone.

        This only runs once per installation, tracked by 'areas_migrated_v1' flag.
        """
        try:
            # Check if migration already ran (one-time only)
            if config.get("areas_migrated_v1"):
                return

            # Get HA connection info
            rest_url, ws_url, token = self._get_ha_api_config()
            if not token or not ws_url:
                return

            # Fetch all areas from HA
            ha_areas = await self._fetch_areas_via_websocket(ws_url, token)
            if not ha_areas:
                return

            # Ensure glozones dict exists
            if "glozones" not in config:
                config["glozones"] = {}
            zones = config["glozones"]

            # Safety check: if no zones exist but we expected some, don't proceed
            # This prevents wiping out zones if load_raw_config failed to read them
            if not zones:
                logger.warning("No zones found - skipping migration to avoid data loss")
                return

            # Get all area IDs currently in zones
            assigned_area_ids = set()
            for zone_config in zones.values():
                for area in zone_config.get("areas", []):
                    area_id = area.get("id") if isinstance(area, dict) else area
                    assigned_area_ids.add(area_id)

            # Find the default zone
            default_zone_name = next(
                (name for name, zc in zones.items() if zc.get("is_default")),
                next(iter(zones.keys()), None)
            )
            if not default_zone_name:
                logger.warning("No default zone found - skipping migration")
                return

            # Add unassigned areas to default zone
            unassigned = [a for a in ha_areas if a.get("area_id") not in assigned_area_ids]

            if unassigned:
                logger.info(f"Migrating {len(unassigned)} unassigned areas to default zone '{default_zone_name}'")
                for area in unassigned:
                    zones[default_zone_name].setdefault("areas", []).append({
                        "id": area["area_id"],
                        "name": area.get("name", area["area_id"])
                    })

            # Mark migration as complete (even if no areas to migrate)
            config["areas_migrated_v1"] = True

            # Save the updated config
            await self.save_config_to_file(config)
            glozone.set_config(config)
            logger.info(f"Area migration complete - migrated {len(unassigned)} areas")

        except Exception as e:
            logger.warning(f"Could not migrate unassigned areas: {e}")

    async def create_glozone(self, request: Request) -> Response:
        """Create a new GloZone."""
        try:
            data = await request.json()
            name = data.get("name")
            preset = data.get("preset", glozone.DEFAULT_PRESET)

            if not name:
                return web.json_response({"error": "name is required"}, status=400)

            config = await self.load_raw_config()

            if name in config.get("glozones", {}):
                return web.json_response({"error": f"Zone '{name}' already exists"}, status=409)

            # Validate preset exists
            if preset not in config.get("circadian_presets", {}):
                return web.json_response(
                    {"error": f"Preset '{preset}' not found"},
                    status=400
                )

            # Create the zone
            config.setdefault("glozones", {})[name] = {
                "preset": preset,
                "areas": []
            }

            await self.save_config_to_file(config)
            glozone.set_config(config)

            logger.info(f"Created GloZone: {name} with preset {preset}")
            return web.json_response({"status": "created", "name": name})
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)
        except Exception as e:
            logger.error(f"Error creating zone: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def update_glozone(self, request: Request) -> Response:
        """Update a GloZone (preset, areas, rename, or set as default)."""
        try:
            name = request.match_info.get("name")
            data = await request.json()

            config = await self.load_raw_config()

            if name not in config.get("glozones", {}):
                return web.json_response({"error": f"Glo Zone '{name}' not found"}, status=404)

            # Handle rename if "name" field is provided
            new_name = data.pop("name", None)
            if new_name and new_name != name:
                if new_name in config.get("glozones", {}):
                    return web.json_response(
                        {"error": f"Glo Zone '{new_name}' already exists"},
                        status=400
                    )
                # Rename the zone (preserve is_default status)
                config["glozones"][new_name] = config["glozones"].pop(name)
                logger.info(f"Renamed GloZone: {name} -> {new_name}")
                name = new_name

            # Update preset if provided
            if "preset" in data:
                preset = data["preset"]
                if preset not in config.get("circadian_presets", {}):
                    return web.json_response(
                        {"error": f"Glo '{preset}' not found"},
                        status=400
                    )
                config["glozones"][name]["preset"] = preset

            # Update areas if provided (replaces entire list)
            if "areas" in data:
                config["glozones"][name]["areas"] = data["areas"]

            # Handle is_default - setting this zone as the default
            if data.get("is_default"):
                # Clear is_default from all zones, set on this one
                for zn, zc in config["glozones"].items():
                    zc["is_default"] = (zn == name)
                logger.info(f"Set '{name}' as default zone")

            await self.save_config_to_file(config)
            glozone.set_config(config)

            logger.info(f"Updated GloZone: {name}")
            return web.json_response({"status": "updated", "name": name})
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)
        except Exception as e:
            logger.error(f"Error updating zone: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def delete_glozone(self, request: Request) -> Response:
        """Delete a GloZone (moves areas to default zone)."""
        try:
            name = request.match_info.get("name")

            config = await self.load_raw_config()
            zones = config.get("glozones", {})

            if name not in zones:
                return web.json_response({"error": f"Zone '{name}' not found"}, status=404)

            # Cannot delete the last zone
            if len(zones) <= 1:
                return web.json_response(
                    {"error": "Cannot delete the last zone"},
                    status=400
                )

            # If deleting the default zone, make another zone the default first
            is_default = zones[name].get("is_default", False)
            if is_default:
                # Find another zone to make default
                other_zone = next((zn for zn in zones.keys() if zn != name), None)
                if other_zone:
                    zones[other_zone]["is_default"] = True
                    logger.info(f"Transferred default status to '{other_zone}'")

            # Find the new default zone to move areas to
            default_zone = next(
                (zn for zn, zc in zones.items() if zc.get("is_default") and zn != name),
                next((zn for zn in zones.keys() if zn != name), None)
            )

            # Move areas to default zone
            areas = zones[name].get("areas", [])
            if areas and default_zone:
                zones[default_zone].setdefault("areas", []).extend(areas)
                logger.info(f"Moved {len(areas)} areas to '{default_zone}'")

            del config["glozones"][name]

            # Reset zone runtime state
            glozone_state.reset_zone_state(name)

            await self.save_config_to_file(config)
            glozone.set_config(config)

            logger.info(f"Deleted GloZone: {name}")
            return web.json_response({"status": "deleted", "name": name})
        except Exception as e:
            logger.error(f"Error deleting zone: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def add_area_to_zone(self, request: Request) -> Response:
        """Add an area to a GloZone (removes from any other zone first)."""
        try:
            zone_name = request.match_info.get("name")
            data = await request.json()
            area_id = data.get("area_id")
            area_name = data.get("area_name", area_id)  # Optional friendly name

            if not area_id:
                return web.json_response({"error": "area_id is required"}, status=400)

            config = await self.load_raw_config()

            if zone_name not in config.get("glozones", {}):
                return web.json_response({"error": f"Zone '{zone_name}' not found"}, status=404)

            # Find current zone for this area (if any)
            current_zone = None
            for zn, zc in config.get("glozones", {}).items():
                for a in zc.get("areas", []):
                    aid = a.get("id") if isinstance(a, dict) else a
                    if aid == area_id:
                        current_zone = zn
                        break

            # Remove area from any existing zone
            for zn, zc in config.get("glozones", {}).items():
                zc["areas"] = [
                    a for a in zc.get("areas", [])
                    if (isinstance(a, dict) and a.get("id") != area_id) or
                       (isinstance(a, str) and a != area_id)
                ]

            # Add to target zone
            config["glozones"][zone_name]["areas"].append({
                "id": area_id,
                "name": area_name
            })

            await self.save_config_to_file(config)
            glozone.set_config(config)

            # Reset area state if moving to a different zone (new Glo config)
            if current_zone and current_zone != zone_name:
                state.update_area(area_id, {
                    "frozen_at": None,
                    "brightness_mid": None,
                    "color_mid": None,
                })
                logger.info(f"Reset state for area {area_id} (moved from {current_zone} to {zone_name})")

            logger.info(f"Added area {area_id} to zone {zone_name}")
            return web.json_response({"status": "added", "area_id": area_id, "zone": zone_name})
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)
        except Exception as e:
            logger.error(f"Error adding area to zone: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def remove_area_from_zone(self, request: Request) -> Response:
        """Remove an area from a GloZone (moves to default zone)."""
        try:
            zone_name = request.match_info.get("name")
            area_id = request.match_info.get("area_id")

            config = await self.load_raw_config()
            zones = config.get("glozones", {})

            if zone_name not in zones:
                return web.json_response({"error": f"Zone '{zone_name}' not found"}, status=404)

            # Find the default zone
            default_zone = next(
                (zn for zn, zc in zones.items() if zc.get("is_default")),
                next(iter(zones.keys()), None)
            )

            # Can't remove from default zone (areas must always be in a zone)
            if zone_name == default_zone:
                return web.json_response(
                    {"error": "Cannot remove area from default zone. Move it to another zone instead."},
                    status=400
                )

            # Find and remove the area
            areas = zones[zone_name].get("areas", [])
            area_entry = None
            new_areas = []
            for a in areas:
                if (isinstance(a, dict) and a.get("id") == area_id) or (isinstance(a, str) and a == area_id):
                    area_entry = a
                else:
                    new_areas.append(a)

            if area_entry is None:
                return web.json_response(
                    {"error": f"Area '{area_id}' not found in zone '{zone_name}'"},
                    status=404
                )

            config["glozones"][zone_name]["areas"] = new_areas

            # Add to default zone
            if default_zone:
                zones[default_zone].setdefault("areas", []).append(area_entry)

            await self.save_config_to_file(config)
            glozone.set_config(config)

            logger.info(f"Removed area {area_id} from zone {zone_name}, moved to {default_zone}")
            return web.json_response({"status": "removed", "area_id": area_id})
        except Exception as e:
            logger.error(f"Error removing area from zone: {e}")
            return web.json_response({"error": str(e)}, status=500)

    # -------------------------------------------------------------------------
    # GloZone API - Actions (glo_up, glo_down, glo_reset)
    # -------------------------------------------------------------------------

    async def handle_glo_up(self, request: Request) -> Response:
        """Handle glo_up action - push area state to zone, propagate to all areas.

        This fires an event that main.py listens for to execute the primitive.
        """
        try:
            data = await request.json()
            area_id = data.get("area_id")

            if not area_id:
                return web.json_response({"error": "area_id is required"}, status=400)

            # Fire event for main.py to handle
            _, ws_url, token = self._get_ha_api_config()
            if ws_url and token:
                success = await self._fire_event_via_websocket(
                    ws_url, token, 'circadian_light_service_event',
                    {'service': 'glo_up', 'area_id': area_id}
                )
                if success:
                    logger.info(f"Fired glo_up event for area {area_id}")
                    return web.json_response({"status": "ok", "action": "glo_up", "area_id": area_id})
                else:
                    return web.json_response({"error": "Failed to fire event"}, status=500)
            else:
                return web.json_response({"error": "HA API not configured"}, status=503)

        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)
        except Exception as e:
            logger.error(f"Error handling glo_up: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def handle_glo_down(self, request: Request) -> Response:
        """Handle glo_down action - pull zone state to area.

        This fires an event that main.py listens for to execute the primitive.
        """
        try:
            data = await request.json()
            area_id = data.get("area_id")

            if not area_id:
                return web.json_response({"error": "area_id is required"}, status=400)

            # Fire event for main.py to handle
            _, ws_url, token = self._get_ha_api_config()
            if ws_url and token:
                success = await self._fire_event_via_websocket(
                    ws_url, token, 'circadian_light_service_event',
                    {'service': 'glo_down', 'area_id': area_id}
                )
                if success:
                    logger.info(f"Fired glo_down event for area {area_id}")
                    return web.json_response({"status": "ok", "action": "glo_down", "area_id": area_id})
                else:
                    return web.json_response({"error": "Failed to fire event"}, status=500)
            else:
                return web.json_response({"error": "HA API not configured"}, status=503)

        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)
        except Exception as e:
            logger.error(f"Error handling glo_down: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def handle_glo_reset(self, request: Request) -> Response:
        """Handle glo_reset action - reset zone and all member areas.

        This fires an event that main.py listens for to execute the primitive.
        """
        try:
            data = await request.json()
            area_id = data.get("area_id")

            if not area_id:
                return web.json_response({"error": "area_id is required"}, status=400)

            # Fire event for main.py to handle
            _, ws_url, token = self._get_ha_api_config()
            if ws_url and token:
                success = await self._fire_event_via_websocket(
                    ws_url, token, 'circadian_light_service_event',
                    {'service': 'glo_reset', 'area_id': area_id}
                )
                if success:
                    logger.info(f"Fired glo_reset event for area {area_id}")
                    return web.json_response({"status": "ok", "action": "glo_reset", "area_id": area_id})
                else:
                    return web.json_response({"error": "Failed to fire event"}, status=500)
            else:
                return web.json_response({"error": "HA API not configured"}, status=503)

        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)
        except Exception as e:
            logger.error(f"Error handling glo_reset: {e}")
            return web.json_response({"error": str(e)}, status=500)

    # -------------------------------------------------------------------------
    # Area Action API endpoint
    # -------------------------------------------------------------------------

    async def handle_area_action(self, request: Request) -> Response:
        """Handle area action - execute a primitive for an area.

        Supported actions:
        - lights_on, lights_off, lights_toggle
        - circadian_on, circadian_off
        - step_up, step_down
        - bright_up, bright_down
        - color_up, color_down
        - freeze_toggle, reset
        - glo_up, glo_down, glo_reset
        """
        VALID_ACTIONS = {
            'lights_on', 'lights_off', 'lights_toggle',
            'circadian_on', 'circadian_off',
            'step_up', 'step_down',
            'bright_up', 'bright_down',
            'color_up', 'color_down',
            'freeze_toggle', 'reset',
            'glo_up', 'glo_down', 'glo_reset',
            'boost'
        }

        try:
            data = await request.json()
            area_id = data.get("area_id")
            action = data.get("action")

            if not area_id:
                return web.json_response({"error": "area_id is required"}, status=400)
            if not action:
                return web.json_response({"error": "action is required"}, status=400)
            if action not in VALID_ACTIONS:
                return web.json_response({"error": f"Invalid action: {action}. Valid actions: {sorted(VALID_ACTIONS)}"}, status=400)

            # Fire event for main.py to handle
            _, ws_url, token = self._get_ha_api_config()
            if ws_url and token:
                success = await self._fire_event_via_websocket(
                    ws_url, token, 'circadian_light_service_event',
                    {'service': action, 'area_id': area_id}
                )
                if success:
                    logger.info(f"Fired {action} event for area {area_id}")
                    return web.json_response({"status": "ok", "action": action, "area_id": area_id})
                else:
                    return web.json_response({"error": "Failed to fire event"}, status=500)
            else:
                return web.json_response({"error": "HA API not configured"}, status=503)

        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)
        except Exception as e:
            logger.error(f"Error handling area action: {e}")
            return web.json_response({"error": str(e)}, status=500)

    # -------------------------------------------------------------------------
    # Switch Management API endpoints
    # -------------------------------------------------------------------------

    async def serve_switches(self, request: Request) -> Response:
        """Serve the Switches configuration page."""
        return await self.serve_page("switches")

    async def get_switches(self, request: Request) -> Response:
        """Get all configured switches with area names looked up from HA."""
        try:
            switches_data = switches.get_switches_summary()

            # Try to enrich with area names from HA device registry
            try:
                device_area_map = await self._fetch_device_areas()
                for sw in switches_data:
                    device_id = sw.get("device_id")
                    if device_id and device_id in device_area_map:
                        sw["area_name"] = device_area_map[device_id]
            except Exception as e:
                logger.warning(f"Could not fetch device areas: {e}")

            return web.json_response({"switches": switches_data})
        except Exception as e:
            logger.error(f"Error getting switches: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def _fetch_device_areas(self) -> Dict[str, str]:
        """Fetch device_id -> area_name mapping from HA."""
        rest_url, ws_url, token = self._get_ha_api_config()
        if not token or not ws_url:
            return {}

        try:
            async with websockets.connect(ws_url) as ws:
                # Auth
                msg = json.loads(await ws.recv())
                if msg.get('type') != 'auth_required':
                    return {}
                await ws.send(json.dumps({'type': 'auth', 'access_token': token}))
                msg = json.loads(await ws.recv())
                if msg.get('type') != 'auth_ok':
                    return {}

                # Get area registry
                await ws.send(json.dumps({'id': 1, 'type': 'config/area_registry/list'}))
                area_msg = json.loads(await ws.recv())
                area_names = {}
                if area_msg.get('success') and area_msg.get('result'):
                    area_names = {a['area_id']: a['name'] for a in area_msg['result']}

                # Get device registry
                await ws.send(json.dumps({'id': 2, 'type': 'config/device_registry/list'}))
                device_msg = json.loads(await ws.recv())
                device_areas = {}
                if device_msg.get('success') and device_msg.get('result'):
                    for device in device_msg['result']:
                        device_id = device.get('id')
                        area_id = device.get('area_id')
                        if device_id and area_id and area_id in area_names:
                            device_areas[device_id] = area_names[area_id]

                return device_areas
        except Exception as e:
            logger.warning(f"Error fetching device areas: {e}")
            return {}

    async def get_controls(self, request: Request) -> Response:
        """Get all controls from HA, merged with our configuration.

        Fetches devices from HA, filters to potential controls (remotes, motion sensors, etc.),
        and merges with our config to determine status (active, not_configured, unsupported).
        """
        try:
            # Fetch controls from HA
            ha_controls = await self._fetch_ha_controls()

            # Get our configured switches and motion sensors
            configured_switches = {sw["id"]: sw for sw in switches.get_switches_summary()}
            configured_motion = switches.get_all_motion_sensors()

            # Merge and determine status
            controls = []
            for ctrl in ha_controls:
                ieee = ctrl.get("ieee")
                device_id = ctrl.get("device_id")
                category = ctrl.get("category")

                # Get config based on category
                if category == "motion_sensor":
                    # Look up by device_id for motion sensors
                    motion_config = switches.get_motion_sensor_by_device_id(device_id) if device_id else None
                    config = motion_config.to_dict() if motion_config else {}
                    config_areas = config.get("areas", [])
                    is_configured = bool(config_areas)
                elif category == "contact_sensor":
                    # Look up by device_id for contact sensors
                    contact_config = switches.get_contact_sensor_by_device_id(device_id) if device_id else None
                    config = contact_config.to_dict() if contact_config else {}
                    config_areas = config.get("areas", [])
                    is_configured = bool(config_areas)
                else:
                    # Look up by ieee for switches
                    config = configured_switches.get(ieee, {})
                    is_configured = config and config.get("scopes") and any(s.get("areas") for s in config.get("scopes", []))

                # Determine status
                is_inactive = config.get("inactive", False)
                if ctrl.get("supported"):
                    if is_configured and is_inactive:
                        status = "inactive"
                    elif is_configured:
                        status = "active"
                    else:
                        status = "not_configured"
                else:
                    status = "unsupported"

                # Try looking up last_action by ieee first, then by device_id
                # (Hue hub devices use device_id for events, not ieee)
                last_action = switches.get_last_action(ieee)
                if not last_action and device_id:
                    last_action = switches.get_last_action(device_id)
                logger.info(f"[Controls] Looking up last_action for '{ieee}': {last_action}")

                # Build response - include appropriate config based on category
                control_data = {
                    "id": ieee,
                    "device_id": device_id,
                    "name": ctrl.get("name"),
                    "manufacturer": ctrl.get("manufacturer"),
                    "model": ctrl.get("model"),
                    "area_name": ctrl.get("area_name"),
                    "category": category,
                    "integration": ctrl.get("integration"),
                    "type": ctrl.get("type"),
                    "type_name": ctrl.get("type_name"),
                    "supported": ctrl.get("supported"),
                    "status": status,
                    "last_action": last_action,
                }

                if category in ("motion_sensor", "contact_sensor"):
                    control_data["areas"] = config.get("areas", [])
                    control_data["inactive"] = config.get("inactive", False)
                else:
                    control_data["scopes"] = config.get("scopes", [])

                controls.append(control_data)

            return web.json_response({"controls": controls})
        except Exception as e:
            logger.error(f"Error getting controls: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)

    async def _fetch_ha_controls(self) -> List[Dict[str, Any]]:
        """Fetch potential control devices from HA.

        Identifies controls by entity types:
        - binary_sensor.*_motion, *_occupancy, *_contact → sensors
        - Devices with only battery sensor and no lights → likely remotes
        """
        rest_url, ws_url, token = self._get_ha_api_config()
        if not token or not ws_url:
            return []

        try:
            async with websockets.connect(ws_url) as ws:
                # Auth
                msg = json.loads(await ws.recv())
                if msg.get('type') != 'auth_required':
                    return []
                await ws.send(json.dumps({'type': 'auth', 'access_token': token}))
                msg = json.loads(await ws.recv())
                if msg.get('type') != 'auth_ok':
                    return []

                # Get area registry
                await ws.send(json.dumps({'id': 1, 'type': 'config/area_registry/list'}))
                area_msg = json.loads(await ws.recv())
                area_names = {}
                if area_msg.get('success') and area_msg.get('result'):
                    area_names = {a['area_id']: a['name'] for a in area_msg['result']}

                # Get device registry
                await ws.send(json.dumps({'id': 2, 'type': 'config/device_registry/list'}))
                device_msg = json.loads(await ws.recv())
                devices = {}
                if device_msg.get('success') and device_msg.get('result'):
                    for device in device_msg['result']:
                        device_id = device.get('id')
                        if device_id:
                            # Extract unique ID from identifiers (ZHA or Hue)
                            unique_id = None
                            integration = None
                            for identifier in device.get('identifiers', []):
                                if isinstance(identifier, list) and len(identifier) >= 2:
                                    if identifier[0] == 'zha':
                                        unique_id = identifier[1]  # IEEE address
                                        integration = 'zha'
                                        break
                                    elif identifier[0] == 'hue':
                                        unique_id = identifier[1]  # Hue device ID
                                        integration = 'hue'
                                        break
                            if unique_id:
                                logger.debug(f"[Controls] HA device {device.get('name')}: id={unique_id} ({integration})")
                                # Use model_id if available (more specific), otherwise model
                                model = device.get('model_id') or device.get('model')
                                devices[device_id] = {
                                    'device_id': device_id,
                                    'ieee': unique_id,  # Keep 'ieee' key for compatibility
                                    'integration': integration,
                                    'name': device.get('name_by_user') or device.get('name'),
                                    'manufacturer': device.get('manufacturer'),
                                    'model': model,
                                    'area_id': device.get('area_id'),
                                    'area_name': area_names.get(device.get('area_id')),
                                }

                # Get entity registry to identify control types
                await ws.send(json.dumps({'id': 3, 'type': 'config/entity_registry/list'}))
                entity_msg = json.loads(await ws.recv())

                # Track entity types per device
                device_entities: Dict[str, Dict[str, bool]] = {}
                if entity_msg.get('success') and entity_msg.get('result'):
                    for entity in entity_msg['result']:
                        device_id = entity.get('device_id')
                        if not device_id or device_id not in devices:
                            continue

                        entity_id = entity.get('entity_id', '')
                        if device_id not in device_entities:
                            device_entities[device_id] = {
                                'has_light': False,
                                'has_motion': False,
                                'has_occupancy': False,
                                'has_contact': False,
                                'has_button': False,
                                'has_battery': False,
                            }

                        if entity_id.startswith('light.'):
                            device_entities[device_id]['has_light'] = True
                        elif entity_id.startswith('button.'):
                            # Ignore identify buttons (most lights have these)
                            if '_identify' not in entity_id and not entity_id.endswith('_identify'):
                                device_entities[device_id]['has_button'] = True
                        elif entity_id.startswith('binary_sensor.'):
                            if '_motion' in entity_id:
                                device_entities[device_id]['has_motion'] = True
                                logger.info(f"[Controls] Found motion entity: {entity_id} for device {device_id}")
                            elif '_occupancy' in entity_id:
                                device_entities[device_id]['has_occupancy'] = True
                                logger.info(f"[Controls] Found occupancy entity: {entity_id} for device {device_id}")
                            elif '_contact' in entity_id or '_opening' in entity_id:
                                device_entities[device_id]['has_contact'] = True
                        elif entity_id.startswith('sensor.') and '_battery' in entity_id:
                            device_entities[device_id]['has_battery'] = True

                # Filter to potential controls
                controls = []
                for device_id, device in devices.items():
                    entities = device_entities.get(device_id, {})

                    # Skip if it's primarily a light
                    if entities.get('has_light') and not any([
                        entities.get('has_motion'),
                        entities.get('has_occupancy'),
                        entities.get('has_contact'),
                        entities.get('has_button'),
                    ]):
                        continue

                    # Include if it has control-like entities
                    is_control = any([
                        entities.get('has_motion'),
                        entities.get('has_occupancy'),
                        entities.get('has_contact'),
                        entities.get('has_button'),
                        # Remote: has battery but no lights
                        (entities.get('has_battery') and not entities.get('has_light')),
                    ])

                    if not is_control:
                        continue

                    # Filter out Hue "Room" virtual devices (not physical controls)
                    # Hue creates these to represent rooms but they're not actual hardware
                    model = device.get('model', '')
                    if model and model.lower() == 'room':
                        logger.debug(f"[Controls] Skipping Hue Room device: {device.get('name')}")
                        continue

                    # Determine category based on entity types
                    if entities.get('has_motion') or entities.get('has_occupancy'):
                        category = 'motion_sensor'
                        logger.info(f"[Controls] Identified motion sensor: {device.get('name')} (device_id={device_id})")
                    elif entities.get('has_contact'):
                        category = 'contact_sensor'
                    elif entities.get('has_button') or (entities.get('has_battery') and not entities.get('has_light')):
                        category = 'switch'
                    else:
                        category = 'unknown'

                    # Check if it's a known/supported type (only for switches for now)
                    detected_type = None
                    if category == 'switch':
                        detected_type = switches.detect_switch_type(
                            device.get('manufacturer'),
                            device.get('model')
                        )
                        if not detected_type:
                            logger.info(f"[Controls] Unrecognized switch: manufacturer='{device.get('manufacturer')}' model='{device.get('model')}' name='{device.get('name')}'")

                    type_info = switches.SWITCH_TYPES.get(detected_type, {}) if detected_type else {}

                    # Get display name based on category
                    if detected_type:
                        type_name = type_info.get('name')
                    elif category in ('motion_sensor', 'contact_sensor'):
                        type_name = switches.get_sensor_name(
                            device.get('manufacturer'),
                            device.get('model')
                        )
                    else:
                        type_name = None

                    # Determine if supported:
                    # - Switches: need a recognized type
                    # - Motion/contact sensors: always supported (configured via area settings)
                    is_supported = (
                        category in ('motion_sensor', 'contact_sensor') or
                        detected_type is not None
                    )

                    controls.append({
                        **device,
                        'category': category,
                        'type': detected_type,
                        'type_name': type_name,
                        'supported': is_supported,
                    })

                logger.info(f"[Controls] Returning {len(controls)} controls: {[(c.get('name'), c.get('category')) for c in controls]}")
                return controls
        except Exception as e:
            logger.error(f"Error fetching HA controls: {e}", exc_info=True)
            return []

    async def configure_control(self, request: Request) -> Response:
        """Configure a control (add/update scopes for switches, areas for motion sensors)."""
        try:
            control_id = request.match_info.get("control_id")
            if not control_id:
                return web.json_response({"error": "Control ID is required"}, status=400)

            data = await request.json()
            category = data.get("category", "switch")
            name = data.get("name", f"Control ({control_id[-8:]})")
            device_id = data.get("device_id")

            if category == "motion_sensor":
                # Handle motion sensor configuration
                areas_data = data.get("areas", [])
                areas = []
                for area_data in areas_data:
                    # Use from_dict for migration support (function -> mode)
                    areas.append(switches.MotionAreaConfig.from_dict(area_data))

                motion_config = switches.MotionSensorConfig(
                    id=control_id,
                    name=name,
                    areas=areas,
                    device_id=device_id,
                    inactive=data.get("inactive", False),
                )

                switches.add_motion_sensor(motion_config)
            elif category == "contact_sensor":
                # Handle contact sensor configuration
                areas_data = data.get("areas", [])
                areas = []
                for area_data in areas_data:
                    # Use from_dict for migration support (function -> mode)
                    areas.append(switches.ContactAreaConfig.from_dict(area_data))

                contact_config = switches.ContactSensorConfig(
                    id=control_id,
                    name=name,
                    areas=areas,
                    device_id=device_id,
                    inactive=data.get("inactive", False),
                )

                switches.add_contact_sensor(contact_config)
            else:
                # Handle switch configuration
                control_type = data.get("type", "hue_4button_v2")

                # Build scopes
                scopes_data = data.get("scopes", [])
                scopes = []
                for scope_data in scopes_data:
                    scope_areas = scope_data.get("areas", [])
                    scopes.append(switches.SwitchScope(areas=scope_areas))

                if not scopes:
                    scopes = [switches.SwitchScope(areas=[])]

                # Create/update switch config
                switch_config = switches.SwitchConfig(
                    id=control_id,
                    name=name,
                    type=control_type,
                    scopes=scopes,
                    device_id=device_id,
                )

                switches.add_switch(switch_config)

            return web.json_response({"status": "ok"})
        except Exception as e:
            logger.error(f"Error configuring control: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def remove_control_config(self, request: Request) -> Response:
        """Remove configuration from a control (keeps it in list as 'not_configured')."""
        try:
            control_id = request.match_info.get("control_id")
            if not control_id:
                return web.json_response({"error": "Control ID is required"}, status=400)

            # Try to delete from both switch and motion sensor configs
            removed = switches.remove_switch(control_id)
            if not removed:
                removed = switches.remove_motion_sensor(control_id)
            if not removed:
                switches.remove_contact_sensor(control_id)

            return web.json_response({"status": "ok"})
        except Exception as e:
            logger.error(f"Error removing control config: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def create_switch(self, request: Request) -> Response:
        """Create a new switch configuration."""
        try:
            data = await request.json()

            switch_id = data.get("id")
            if not switch_id:
                return web.json_response({"error": "Switch ID is required"}, status=400)

            name = data.get("name", f"Switch ({switch_id[-8:]})")
            switch_type = data.get("type", "hue_4button_v2")

            # Validate switch type
            if switch_type not in switches.SWITCH_TYPES:
                return web.json_response(
                    {"error": f"Invalid switch type: {switch_type}"},
                    status=400
                )

            # Build scopes from data
            scopes_data = data.get("scopes", [])
            scopes = []
            for scope_data in scopes_data:
                areas = scope_data.get("areas", [])
                scopes.append(switches.SwitchScope(areas=areas))

            # Ensure at least one scope
            if not scopes:
                scopes = [switches.SwitchScope(areas=[])]

            # Create switch config
            switch_config = switches.SwitchConfig(
                id=switch_id,
                name=name,
                type=switch_type,
                scopes=scopes,
                button_overrides=data.get("button_overrides", {}),
                device_id=data.get("device_id"),
            )

            switches.add_switch(switch_config)

            return web.json_response({
                "status": "ok",
                "switch": switch_config.to_dict()
            })

        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)
        except Exception as e:
            logger.error(f"Error creating switch: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def update_switch(self, request: Request) -> Response:
        """Update an existing switch configuration."""
        try:
            switch_id = request.match_info.get("switch_id")
            if not switch_id:
                return web.json_response({"error": "Switch ID is required"}, status=400)

            existing = switches.get_switch(switch_id)
            if not existing:
                return web.json_response({"error": "Switch not found"}, status=404)

            data = await request.json()

            # Update fields if provided
            name = data.get("name", existing.name)
            switch_type = data.get("type", existing.type)

            # Validate switch type
            if switch_type not in switches.SWITCH_TYPES:
                return web.json_response(
                    {"error": f"Invalid switch type: {switch_type}"},
                    status=400
                )

            # Update scopes if provided
            if "scopes" in data:
                scopes = []
                for scope_data in data["scopes"]:
                    areas = scope_data.get("areas", [])
                    scopes.append(switches.SwitchScope(areas=areas))
            else:
                scopes = existing.scopes

            # Ensure at least one scope
            if not scopes:
                scopes = [switches.SwitchScope(areas=[])]

            # Update button overrides if provided
            button_overrides = data.get("button_overrides", existing.button_overrides)

            # Preserve device_id (or update if provided)
            device_id = data.get("device_id", existing.device_id)

            # Create updated config
            switch_config = switches.SwitchConfig(
                id=switch_id,
                name=name,
                type=switch_type,
                scopes=scopes,
                button_overrides=button_overrides,
                device_id=device_id,
            )

            switches.add_switch(switch_config)

            return web.json_response({
                "status": "ok",
                "switch": switch_config.to_dict()
            })

        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)
        except Exception as e:
            logger.error(f"Error updating switch: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def delete_switch(self, request: Request) -> Response:
        """Delete a switch configuration."""
        try:
            switch_id = request.match_info.get("switch_id")
            if not switch_id:
                return web.json_response({"error": "Switch ID is required"}, status=400)

            if switches.remove_switch(switch_id):
                return web.json_response({"status": "ok", "deleted": switch_id})
            else:
                return web.json_response({"error": "Switch not found"}, status=404)

        except Exception as e:
            logger.error(f"Error deleting switch: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def get_switch_types(self, request: Request) -> Response:
        """Get all available switch type definitions."""
        try:
            types = switches.get_all_switch_types()
            # Format for API response
            result = {}
            for type_id, type_info in types.items():
                result[type_id] = {
                    "name": type_info.get("name"),
                    "manufacturer": type_info.get("manufacturer"),
                    "models": type_info.get("models", []),
                    "buttons": type_info.get("buttons", []),
                    "action_types": type_info.get("action_types", []),
                    "default_mapping": type_info.get("default_mapping", {}),
                }
            return web.json_response({"types": result})
        except Exception as e:
            logger.error(f"Error getting switch types: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def start(self):
        """Start the web server."""
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', self.port)
        await site.start()
        logger.info(f"Light Designer server started on port {self.port}")
        
        # Keep the server running
        try:
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            pass
        finally:
            await runner.cleanup()

async def main():
    """Main entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    port = int(os.getenv("INGRESS_PORT", "8099"))
    server = LightDesignerServer(port)
    await server.start()

if __name__ == "__main__":
    asyncio.run(main())
