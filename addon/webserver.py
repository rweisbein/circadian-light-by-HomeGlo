#!/usr/bin/env python3
"""Web server for Home Assistant ingress - Light Designer interface."""

import asyncio
import json
import logging
import math
import os
import tempfile
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

        # Areas cache - populated once on first request, refreshed by sync-devices
        self.cached_areas_list: list = None  # List of {area_id, name} for areas with lights

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

        # GloZone API routes - Circadian Rhythms CRUD
        self.app.router.add_route('GET', '/{path:.*}/api/circadian-rhythms', self.get_circadian_rhythms)
        self.app.router.add_route('POST', '/{path:.*}/api/circadian-rhythms', self.create_circadian_rhythm)
        self.app.router.add_route('PUT', '/{path:.*}/api/circadian-rhythms/{name}', self.update_circadian_rhythm)
        self.app.router.add_route('DELETE', '/{path:.*}/api/circadian-rhythms/{name}', self.delete_circadian_rhythm)
        self.app.router.add_get('/api/circadian-rhythms', self.get_circadian_rhythms)
        self.app.router.add_post('/api/circadian-rhythms', self.create_circadian_rhythm)
        self.app.router.add_put('/api/circadian-rhythms/{name}', self.update_circadian_rhythm)
        self.app.router.add_delete('/api/circadian-rhythms/{name}', self.delete_circadian_rhythm)

        # GloZone API routes - Zones CRUD
        # Reorder routes MUST be registered before {name} wildcard routes
        self.app.router.add_route('PUT', '/{path:.*}/api/glozones/reorder', self.reorder_glozones)
        self.app.router.add_put('/api/glozones/reorder', self.reorder_glozones)
        self.app.router.add_route('GET', '/{path:.*}/api/glozones', self.get_glozones)
        self.app.router.add_route('POST', '/{path:.*}/api/glozones', self.create_glozone)
        self.app.router.add_route('PUT', '/{path:.*}/api/glozones/{name}/reorder-areas', self.reorder_zone_areas)
        self.app.router.add_route('PUT', '/{path:.*}/api/glozones/{name}', self.update_glozone)
        self.app.router.add_route('DELETE', '/{path:.*}/api/glozones/{name}', self.delete_glozone)
        self.app.router.add_route('POST', '/{path:.*}/api/glozones/{name}/areas', self.add_area_to_zone)
        self.app.router.add_route('DELETE', '/{path:.*}/api/glozones/{name}/areas/{area_id}', self.remove_area_from_zone)
        self.app.router.add_get('/api/glozones', self.get_glozones)
        self.app.router.add_post('/api/glozones', self.create_glozone)
        self.app.router.add_put('/api/glozones/{name}/reorder-areas', self.reorder_zone_areas)
        self.app.router.add_put('/api/glozones/{name}', self.update_glozone)
        self.app.router.add_delete('/api/glozones/{name}', self.delete_glozone)
        self.app.router.add_post('/api/glozones/{name}/areas', self.add_area_to_zone)
        self.app.router.add_delete('/api/glozones/{name}/areas/{area_id}', self.remove_area_from_zone)

        # Moments API routes
        self.app.router.add_route('GET', '/{path:.*}/api/moments', self.get_moments)
        self.app.router.add_route('POST', '/{path:.*}/api/moments', self.create_moment)
        self.app.router.add_route('GET', '/{path:.*}/api/moments/{moment_id}', self.get_moment)
        self.app.router.add_route('PUT', '/{path:.*}/api/moments/{moment_id}', self.update_moment)
        self.app.router.add_route('DELETE', '/{path:.*}/api/moments/{moment_id}', self.delete_moment)
        self.app.router.add_get('/api/moments', self.get_moments)
        self.app.router.add_post('/api/moments', self.create_moment)
        self.app.router.add_get('/api/moments/{moment_id}', self.get_moment)
        self.app.router.add_put('/api/moments/{moment_id}', self.update_moment)
        self.app.router.add_delete('/api/moments/{moment_id}', self.delete_moment)

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

        # Zone action API route
        self.app.router.add_route('POST', '/{path:.*}/api/zone/action', self.handle_zone_action)
        self.app.router.add_post('/api/zone/action', self.handle_zone_action)

        # Manual sync endpoint
        self.app.router.add_route('POST', '/{path:.*}/api/sync-devices', self.handle_sync_devices)
        self.app.router.add_post('/api/sync-devices', self.handle_sync_devices)

        # Controls API routes (new unified endpoint)
        self.app.router.add_route('GET', '/{path:.*}/api/controls', self.get_controls)
        self.app.router.add_route('POST', '/{path:.*}/api/controls/{control_id}/configure', self.configure_control)
        self.app.router.add_route('DELETE', '/{path:.*}/api/controls/{control_id}/configure', self.remove_control_config)
        self.app.router.add_route('GET', '/{path:.*}/api/area-lights', self.get_area_lights)
        self.app.router.add_get('/api/controls', self.get_controls)
        self.app.router.add_post('/api/controls/{control_id}/configure', self.configure_control)
        self.app.router.add_delete('/api/controls/{control_id}/configure', self.remove_control_config)
        self.app.router.add_get('/api/area-lights', self.get_area_lights)
        self.app.router.add_route('POST', '/{path:.*}/api/flash-light', self.flash_light)
        self.app.router.add_post('/api/flash-light', self.flash_light)

        # ZHA motion sensor settings API routes
        self.app.router.add_route('GET', '/{path:.*}/api/controls/{device_id}/zha-settings', self.get_zha_motion_settings)
        self.app.router.add_route('POST', '/{path:.*}/api/controls/{device_id}/zha-settings', self.set_zha_motion_settings)
        self.app.router.add_get('/api/controls/{device_id}/zha-settings', self.get_zha_motion_settings)
        self.app.router.add_post('/api/controls/{device_id}/zha-settings', self.set_zha_motion_settings)

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

        # Switchmap API routes
        self.app.router.add_route('GET', '/{path:.*}/api/switchmap', self.get_switchmap)
        self.app.router.add_route('POST', '/{path:.*}/api/switchmap', self.save_switchmap)
        self.app.router.add_route('GET', '/{path:.*}/api/switchmap/actions', self.get_switchmap_actions)
        self.app.router.add_get('/api/switchmap', self.get_switchmap)
        self.app.router.add_post('/api/switchmap', self.save_switchmap)
        self.app.router.add_get('/api/switchmap/actions', self.get_switchmap_actions)

        # Page routes - specific pages first, then catch-all
        # With ingress path prefix
        self.app.router.add_route('GET', '/{path:.*}/switchmap', self.serve_switchmap)
        self.app.router.add_route('GET', '/{path:.*}/switches', self.serve_switches)
        self.app.router.add_route('GET', '/{path:.*}/rhythm/{rhythm_name}', self.serve_rhythm_design)
        self.app.router.add_route('GET', '/{path:.*}/rhythm', self.serve_rhythm_list)
        self.app.router.add_route('GET', '/{path:.*}/glo/{glo_name}', self.redirect_glo_to_rhythm)
        self.app.router.add_route('GET', '/{path:.*}/glo', self.redirect_glo_to_rhythm)
        self.app.router.add_route('GET', '/{path:.*}/settings', self.serve_settings)
        self.app.router.add_route('GET', '/{path:.*}/moments', self.serve_moments)
        self.app.router.add_route('GET', '/{path:.*}/', self.serve_home)
        # Without ingress path prefix
        self.app.router.add_get('/switchmap', self.serve_switchmap)
        self.app.router.add_get('/rhythm/{rhythm_name}', self.serve_rhythm_design)
        self.app.router.add_get('/rhythm', self.serve_rhythm_list)
        self.app.router.add_get('/glo/{glo_name}', self.redirect_glo_to_rhythm)
        self.app.router.add_get('/glo', self.redirect_glo_to_rhythm)
        self.app.router.add_get('/settings', self.serve_settings)
        self.app.router.add_get('/moments', self.serve_moments)
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

    async def serve_rhythm_list(self, request: Request) -> Response:
        """Serve the Rhythm list page."""
        return await self.serve_page("rhythm")

    async def serve_rhythm_design(self, request: Request) -> Response:
        """Serve the Rhythm Design page."""
        rhythm_name = request.match_info.get("rhythm_name")
        return await self.serve_page("rhythm-design", {"selectedRhythm": rhythm_name})

    async def redirect_glo_to_rhythm(self, request: Request) -> Response:
        """Legacy redirect: /glo → /rhythm."""
        glo_name = request.match_info.get("glo_name", "")
        # Build the new path preserving any ingress prefix
        path = request.path
        if glo_name:
            new_path = path.replace(f"/glo/{glo_name}", f"/rhythm/{glo_name}")
        else:
            new_path = path.replace("/glo", "/rhythm")
        raise web.HTTPFound(new_path)

    async def serve_settings(self, request: Request) -> Response:
        """Serve the Settings page."""
        return await self.serve_page("settings")

    async def serve_moments(self, request: Request) -> Response:
        """Serve the Moments page."""
        return await self.serve_page("moments")

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
        - Flat rhythm settings are merged into the active rhythm
        - circadian_rhythms and glozones are merged at their level
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
            incoming_rhythms = data.pop("circadian_rhythms", None)
            incoming_glozones = data.pop("glozones", None)
            logger.info(f"[SaveConfig] After pop - incoming_glozones: {incoming_glozones}")

            # Handle incoming preset and glozone structures
            if incoming_rhythms:
                config["circadian_rhythms"].update(incoming_rhythms)

            if incoming_glozones:
                logger.info(f"[SaveConfig] Updating glozones with: {list(incoming_glozones.keys())}")
                config["glozones"].update(incoming_glozones)

            # Remaining data could be flat preset settings or global settings
            rhythm_updates = {}
            global_updates = {}

            for key, value in data.items():
                if key in self.RHYTHM_SETTINGS:
                    rhythm_updates[key] = value
                elif key in self.GLOBAL_SETTINGS:
                    global_updates[key] = value
                # Ignore unknown keys

            # Apply rhythm updates to the first rhythm (active rhythm)
            if rhythm_updates and config.get("circadian_rhythms"):
                first_rhythm_name = list(config["circadian_rhythms"].keys())[0]
                config["circadian_rhythms"][first_rhythm_name].update(rhythm_updates)
                logger.debug(f"Updated rhythm '{first_rhythm_name}' with: {list(rhythm_updates.keys())}")

            # Apply global updates to top level
            config.update(global_updates)

            # Log what we're about to save
            logger.info(f"[SaveConfig] Final glozones to save: {list(config.get('glozones', {}).keys())}")
            for zn, zc in config.get('glozones', {}).items():
                areas = zc.get('areas', [])
                logger.info(f"[SaveConfig]   Zone '{zn}': {len(areas)} areas, rhythm={zc.get('rhythm')}")

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
            from zoneinfo import ZoneInfo

            # Get parameters from query, falling back to HA environment vars
            date_str = request.query.get('date')
            lat = float(request.query.get('latitude', os.getenv("HASS_LATITUDE", "35.0")))
            lon = float(request.query.get('longitude', os.getenv("HASS_LONGITUDE", "-78.6")))
            timezone = os.getenv("HASS_TIME_ZONE", "US/Eastern")

            try:
                tzinfo = ZoneInfo(timezone)
            except Exception:
                tzinfo = None

            if not date_str:
                # Default to today in local timezone
                now = datetime.now(tzinfo) if tzinfo else datetime.now()
                date_str = now.strftime('%Y-%m-%d')

            # Calculate sun times using brain.py function
            sun_times = calculate_sun_times(lat, lon, date_str)

            # Helper to convert ISO string to hour (with timezone conversion)
            def iso_to_hour(iso_str, default):
                if not iso_str:
                    return default
                try:
                    dt = datetime.fromisoformat(iso_str)
                    # Convert to local timezone if available
                    if tzinfo and dt.tzinfo:
                        dt = dt.astimezone(tzinfo)
                    return dt.hour + dt.minute / 60.0 + dt.second / 3600.0
                except Exception:
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

            # Get zones and rhythms from glozone module (consistent with area-status)
            zones = glozone.get_glozones()

            logger.debug(f"[ZoneStates] Found {len(zones)} zones: {list(zones.keys())}")

            zone_states = {}
            for zone_name, zone_config in zones.items():
                # Get the rhythm for this zone using glozone module
                rhythm_name = zone_config.get("rhythm", glozone.DEFAULT_RHYTHM)
                preset_config = glozone.get_rhythm_config(rhythm_name)
                logger.debug(f"[ZoneStates] Zone '{zone_name}' rhythm_config keys: {list(preset_config.keys())}")
                logger.debug(f"[ZoneStates] Zone '{zone_name}' rhythm min/max bri: {preset_config.get('min_brightness')}/{preset_config.get('max_brightness')}")

                # Get zone runtime state (from GloUp/GloDown adjustments)
                runtime_state = glozone_state.get_zone_state(zone_name)
                logger.debug(f"[ZoneStates] Zone '{zone_name}' runtime_state: {runtime_state}")

                # Build Config from preset using from_dict (handles all fields with defaults)
                brain_config = Config.from_dict(preset_config)
                logger.debug(f"[ZoneStates] Zone '{zone_name}' brain_config: wake={brain_config.wake_time}, bed={brain_config.bed_time}, min_bri={brain_config.min_brightness}, max_bri={brain_config.max_brightness}, warm_night={brain_config.warm_night_enabled}")

                # Build AreaState from zone runtime state
                area_state = AreaState(
                    is_circadian=True,
                    is_on=True,
                    brightness_mid=runtime_state.get('brightness_mid'),
                    color_mid=runtime_state.get('color_mid'),
                    frozen_at=runtime_state.get('frozen_at'),
                    color_override=runtime_state.get('color_override'),
                )
                logger.debug(f"[ZoneStates] Zone '{zone_name}' area_state: brightness_mid={area_state.brightness_mid}, color_mid={area_state.color_mid}, frozen_at={area_state.frozen_at}")

                # Calculate lighting values - use frozen_at if set, otherwise current time
                calc_hour = area_state.frozen_at if area_state.frozen_at is not None else hour
                result = CircadianLight.calculate_lighting(calc_hour, brain_config, area_state, sun_times=sun_times)

                zone_states[zone_name] = {
                    "brightness": result.brightness,
                    "kelvin": result.color_temp,
                    "rhythm": rhythm_name,
                    "runtime_state": runtime_state,
                }
                logger.debug(f"[ZoneStates] Zone '{zone_name}': {result.brightness}% {result.color_temp}K at hour {calc_hour:.2f} (rhythm: {rhythm_name}, sun_times: sunrise={sun_times.sunrise:.2f}, sunset={sun_times.sunset:.2f})")

            logger.debug(f"[ZoneStates] Returning {len(zone_states)} zone states")
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

    # Settings that are per-rhythm (not global)
    RHYTHM_SETTINGS = {
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

    # Settings that are global (not per-rhythm)
    GLOBAL_SETTINGS = {
        "latitude", "longitude", "timezone", "use_ha_location", "month",
        "turn_on_transition",  # Transition time in tenths of seconds for turn-on operations
        "turn_off_transition",  # Transition time in tenths of seconds for turn-off operations
        "two_step_delay",  # Delay between two-step phases in tenths of seconds (default 3 = 300ms)
        "multi_click_enabled",  # Enable multi-click detection for Hue Hub switches
        "multi_click_speed",  # Multi-click window in tenths of seconds
        "circadian_refresh",  # How often to refresh circadian lighting (seconds)
        "log_periodic",  # Whether to log periodic update details (default false)
        "home_refresh_interval",  # How often to refresh home page cards (seconds, default 10)
        "motion_warning_time",  # Seconds before motion timer expires to trigger warning dim
        "motion_warning_blink_threshold",  # Brightness % below which warning blinks instead of dims
        "freeze_off_rise",  # Transition time in tenths of seconds for unfreeze rise (default 10 = 1.0s)
        "limit_warning_speed",  # Transition time in tenths of seconds for limit bounce animation (default 3 = 0.3s)
        "limit_bounce_max_percent",  # Percentage of range to dip when hitting max limit (default 30)
        "limit_bounce_min_percent",  # Percentage of range to flash when hitting min limit (default 10)
        "reach_dip_percent",  # Percentage of current brightness to dip for reach feedback (default 50)
        "boost_default",  # Default boost percentage (10-100, default 30)
        "reach_learn_mode",  # Reach feedback uses single indicator light (default true)
        "long_press_repeat_interval",  # Long-press repeat interval in tenths of seconds (default 3 = 300ms)
        "controls_ui",  # Controls page UI preferences (sort, filter)
        "areas_ui",  # Areas page UI preferences (sort, filter)
        "area_settings",  # Per-area settings (motion_function, motion_duration)
        "home_name",  # Display name for the home (shown on areas page)
        "ct_comp_enabled",  # Enable CT brightness compensation for warm colors
        "ct_comp_begin",  # Handover zone begin (warmer end) in Kelvin
        "ct_comp_end",  # Handover zone end (cooler end) in Kelvin
        "ct_comp_factor",  # Max brightness compensation factor (e.g., 1.4 = 40% boost)
    }

    def _migrate_to_glozone_format(self, config: dict) -> dict:
        """Migrate old flat config to new GloZone format.

        Also migrates circadian_presets → circadian_rhythms and
        zone preset → rhythm field names.

        Args:
            config: The loaded config dict

        Returns:
            Migrated config dict
        """
        # Migrate circadian_presets → circadian_rhythms
        if "circadian_presets" in config and "circadian_rhythms" not in config:
            config["circadian_rhythms"] = config.pop("circadian_presets")

        # Migrate zone "preset" → "rhythm" field
        for zone in config.get("glozones", {}).values():
            if "preset" in zone and "rhythm" not in zone:
                zone["rhythm"] = zone.pop("preset")

        # Check if already migrated
        if "circadian_rhythms" in config and "glozones" in config:
            logger.debug("Config already in GloZone format")
            return config

        logger.info("Migrating config to GloZone format...")

        # Extract rhythm settings from flat config
        rhythm_config = {}
        for key in self.RHYTHM_SETTINGS:
            if key in config:
                rhythm_config[key] = config[key]

        # Extract global settings
        global_config = {}
        for key in self.GLOBAL_SETTINGS:
            if key in config:
                global_config[key] = config[key]

        # Build new config structure
        new_config = {
            "circadian_rhythms": {
                glozone.DEFAULT_RHYTHM: rhythm_config
            },
            "glozones": {
                glozone.INITIAL_ZONE_NAME: {
                    "rhythm": glozone.DEFAULT_RHYTHM,
                    "areas": [],
                    "is_default": True
                }
            },
        }

        # Add global settings
        new_config.update(global_config)

        logger.info(f"Migration complete: created rhythm '{glozone.DEFAULT_RHYTHM}' "
                    f"and zone '{glozone.INITIAL_ZONE_NAME}' (default)")

        return new_config

    def _get_effective_config(self, config: dict) -> dict:
        """Get effective config by merging rhythm settings with global settings.

        For backward compatibility with code that expects flat config,
        this merges the first rhythm's settings into the top level.

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

        # Get the first rhythm's settings (or default rhythm)
        rhythms = config.get("circadian_rhythms", {})
        if rhythms:
            # Use first rhythm for backward compatibility
            first_rhythm_name = list(rhythms.keys())[0]
            first_rhythm = rhythms[first_rhythm_name]
            result.update(first_rhythm)

        # Keep the new structure available
        result["circadian_rhythms"] = config.get("circadian_rhythms", {})
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
            "log_periodic": False,  # log periodic update details
            "home_refresh_interval": 10,  # seconds (home page card refresh)

            # Motion warning settings
            "motion_warning_time": 0,  # seconds (0 = disabled)
            "motion_warning_blink_threshold": 15,  # percent brightness

            # Visual feedback settings
            "freeze_off_rise": 10,  # tenths of seconds (1.0s)
            "limit_warning_speed": 3,  # tenths of seconds (0.3s)
            "limit_bounce_max_percent": 30,  # % of range (hitting max)
            "limit_bounce_min_percent": 10,  # % of range (hitting min)
            "reach_dip_percent": 50,  # % of current brightness

            # Reach feedback
            "reach_learn_mode": True,  # Use single indicator light for reach feedback
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

        # Ensure top-level rhythm settings are merged INTO the rhythm
        # This handles cases where config was partially migrated
        if "circadian_rhythms" in config and config["circadian_rhythms"]:
            first_rhythm_name = list(config["circadian_rhythms"].keys())[0]
            first_rhythm = config["circadian_rhythms"][first_rhythm_name]
            for key in list(config.keys()):
                if key in self.RHYTHM_SETTINGS:
                    if key not in first_rhythm:
                        first_rhythm[key] = config[key]
                    del config[key]

        # Update glozone module with current config
        glozone.set_config(config)

        # Return effective config (flat format for backward compatibility)
        return self._get_effective_config(config)

    async def load_raw_config(self) -> dict:
        """Load raw configuration without flattening.

        Returns the GloZone-format config with circadian_rhythms and glozones.
        Used internally for save operations.
        """
        # Start with global-only defaults. RHYTHM_SETTINGS are intentionally NOT
        # included here — they belong inside rhythm dicts, not at the top level.
        # Having them here caused them to be saved to designer_config.json at the
        # top level, which then poisoned load_config_from_files() on next startup
        # (top-level false values would override preset's true values).
        # Missing rhythm keys are handled by get_rhythm_config() and Config.from_dict().
        config: dict = {
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
            "log_periodic": False,  # log periodic update details
            "home_refresh_interval": 10,  # seconds (home page card refresh)
            # Motion warning settings
            "motion_warning_time": 0,  # seconds (0 = disabled)
            "motion_warning_blink_threshold": 15,  # percent brightness
            # Visual feedback settings
            "freeze_off_rise": 10,  # tenths of seconds (1.0s)
            "limit_warning_speed": 3,  # tenths of seconds (0.3s)
            "limit_bounce_max_percent": 30,  # % of range (hitting max)
            "limit_bounce_min_percent": 10,  # % of range (hitting min)
            "reach_dip_percent": 50,  # % of current brightness
            # Reach feedback
            "reach_learn_mode": True,
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

        # Ensure top-level rhythm settings are merged INTO the rhythm before removing them
        # This handles cases where config was partially migrated (has circadian_rhythms structure
        # but settings are still at top level)
        if "circadian_rhythms" in config and config["circadian_rhythms"]:
            first_rhythm_name = list(config["circadian_rhythms"].keys())[0]
            first_rhythm = config["circadian_rhythms"][first_rhythm_name]

            # Copy any top-level rhythm settings into the rhythm (if not already there)
            for key in list(config.keys()):
                if key in self.RHYTHM_SETTINGS:
                    if key not in first_rhythm:
                        first_rhythm[key] = config[key]
                        logger.debug(f"Migrated top-level key '{key}' into rhythm '{first_rhythm_name}'")
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
            # Remove internal tracking flags and top-level RHYTHM_SETTINGS before saving.
            # RHYTHM_SETTINGS belong inside rhythm dicts, not at the top level.
            # If left at the top level, they poison load_config_from_files() on next
            # startup (e.g., warm_night_enabled=false overrides rhythm's true).
            save_config = {
                k: v for k, v in config.items()
                if not k.startswith("_") and k not in self.RHYTHM_SETTINGS
            }
            # Use a unique temp file to prevent concurrent write collisions
            dir_path = os.path.dirname(self.designer_file)
            fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp", prefix=".designer_")
            try:
                with os.fdopen(fd, 'w') as f:
                    json.dump(save_config, f, indent=2)
                os.replace(tmp_path, self.designer_file)
            except BaseException:
                # Clean up temp file on failure
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
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
        logger.debug(f"Fetching areas via WebSocket: {ws_url}")
        try:
            async with websockets.connect(ws_url) as ws:
                # Wait for auth_required message
                msg = json.loads(await ws.recv())
                if msg.get('type') != 'auth_required':
                    logger.error(f"Unexpected WS message during areas fetch: {msg}")
                    return []

                # Send auth
                await ws.send(json.dumps({
                    'type': 'auth',
                    'access_token': token
                }))

                # Wait for auth response
                msg = json.loads(await ws.recv())
                if msg.get('type') != 'auth_ok':
                    logger.error(f"WS auth failed during areas fetch: {msg}")
                    return []

                # Request area registry
                await ws.send(json.dumps({
                    'id': 1,
                    'type': 'config/area_registry/list'
                }))

                # Get area response
                area_msg = json.loads(await ws.recv())
                if not area_msg.get('success') or not area_msg.get('result'):
                    logger.error(f"Failed to get areas: {area_msg}")
                    return []

                all_areas = {a['area_id']: a['name'] for a in area_msg['result']}

                # Request device registry (lights often get area from device)
                await ws.send(json.dumps({
                    'id': 2,
                    'type': 'config/device_registry/list'
                }))

                # Get device response
                device_msg = json.loads(await ws.recv())
                device_areas = {}
                if device_msg.get('success') and device_msg.get('result'):
                    for device in device_msg['result']:
                        device_id = device.get('id')
                        area_id = device.get('area_id')
                        if device_id and area_id:
                            device_areas[device_id] = area_id

                # Request entity registry to find light entities
                await ws.send(json.dumps({
                    'id': 3,
                    'type': 'config/entity_registry/list'
                }))

                # Get entity response
                entity_msg = json.loads(await ws.recv())
                if not entity_msg.get('success') or not entity_msg.get('result'):
                    logger.error(f"Failed to get entities: {entity_msg}")
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

                # Return only areas that have lights (exclude internal groups area)
                areas = [
                    {'area_id': area_id, 'name': all_areas[area_id]}
                    for area_id in areas_with_lights
                    if area_id in all_areas
                    and all_areas[area_id] != 'Circadian_Zigbee_Groups'
                ]
                areas.sort(key=lambda x: x['name'].lower())
                logger.info(f"Fetched {len(areas)} areas with lights from HA")
                return areas

        except Exception as e:
            logger.error(f"WebSocket error fetching areas: {e}", exc_info=True)
            return []

    async def get_areas(self, request: Request) -> Response:
        """Return cached areas list, fetching from HA only if cache is empty."""
        # Return cached areas if available
        if self.cached_areas_list is not None:
            logger.debug(f"Returning {len(self.cached_areas_list)} cached areas")
            return web.json_response(self.cached_areas_list)

        # Cache miss - fetch from HA
        rest_url, ws_url, token = self._get_ha_api_config()

        if not token:
            logger.warning("No HA token configured for areas fetch")
            return web.json_response(
                {'error': 'Home Assistant API not configured'},
                status=503
            )

        if not ws_url:
            logger.warning("No WebSocket URL configured for areas fetch")
            return web.json_response(
                {'error': 'WebSocket URL not configured'},
                status=503
            )

        try:
            areas = await self._fetch_areas_via_websocket(ws_url, token)
            self.cached_areas_list = areas  # Cache the result
            logger.info(f"Cached {len(areas)} areas from HA")
            return web.json_response(areas)
        except Exception as e:
            logger.error(f"Error fetching areas: {e}")
            return web.json_response(
                {'error': str(e)},
                status=500
            )

    async def get_area_status(self, request: Request) -> Response:
        """Get status for areas using Circadian Light state (no HA polling).

        Supports optional ?area_id=X query param to return a single area.

        Uses in-memory state from state.py and glozone_state.py, and calculates
        brightness from the circadian curve. This matches what lights are set to
        after each circadian update cycle.

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

            # Load config to get glozone mappings and rhythms
            config = await self.load_config()
            glozones = config.get('glozones', {})
            rhythms = config.get('circadian_rhythms', {})

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

            # Optional single-area filter
            filter_area_id = request.query.get('area_id')

            # Build response for each area in zones (including Unassigned)
            area_status = {}
            for zone_name, zone_data in glozones.items():
                # Add status for each area in this zone
                for area in zone_data.get('areas', []):
                    # Areas can be stored as {id, name} or just string
                    area_id = area.get('id') if isinstance(area, dict) else area

                    # Skip if filtering for a specific area
                    if filter_area_id and area_id != filter_area_id:
                        continue

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
                    boost_state = state.get_boost_state(area_id) if is_boosted else {}
                    if is_boosted:
                        boost_amount = boost_state.get('boost_brightness') or 0
                        brightness = min(100, brightness + boost_amount)

                    # Get motion timer state
                    motion_expires_at = state.get_motion_expires(area_id)
                    motion_warning_active = state.is_motion_warned(area_id)

                    area_status[area_id] = {
                        'is_circadian': area_state.is_circadian,
                        'is_on': area_state.is_on,
                        'brightness': brightness,
                        'kelvin': kelvin,
                        'frozen': area_state.frozen_at is not None,
                        'boosted': is_boosted,
                        'boost_brightness': boost_state.get('boost_brightness') if is_boosted else None,
                        'boost_expires_at': boost_state.get('boost_expires_at') if is_boosted else None,
                        'boost_started_from_off': boost_state.get('boost_started_from_off', False) if is_boosted else None,
                        'is_motion_coupled': boost_state.get('is_motion_coupled', False) if is_boosted else False,
                        'motion_expires_at': motion_expires_at,
                        'motion_warning_active': motion_warning_active,
                        'zone_name': zone_name if zone_name != 'Unassigned' else None,
                        'preset_name': zone_data.get('rhythm', 'Glo 1'),
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
    # GloZone API - Circadian Rhythms CRUD
    # -------------------------------------------------------------------------

    async def get_circadian_rhythms(self, request: Request) -> Response:
        """Get all circadian rhythms."""
        try:
            config = await self.load_raw_config()
            rhythms = config.get("circadian_rhythms", {})
            return web.json_response({"rhythms": rhythms})
        except Exception as e:
            logger.error(f"Error getting circadian rhythms: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def create_circadian_rhythm(self, request: Request) -> Response:
        """Create a new circadian rhythm."""
        try:
            data = await request.json()
            name = data.get("name")
            settings = data.get("settings", {})

            if not name:
                return web.json_response({"error": "name is required"}, status=400)

            config = await self.load_raw_config()

            if name in config.get("circadian_rhythms", {}):
                return web.json_response({"error": f"Rhythm '{name}' already exists"}, status=409)

            # Create the rhythm with defaults, then overlay any provided settings
            defaults = {
                "activity_preset": "adult",
                "wake_time": 7.0,
                "bed_time": 21.0,
                "wake_speed": 6,
                "bed_speed": 4,
                "ascend_start": 3.0,
                "descend_start": 12.0,
                "min_color_temp": 500,
                "max_color_temp": 6500,
                "min_brightness": 1,
                "max_brightness": 100,
                "max_dim_steps": 10,
                "warm_night_enabled": True,
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
            }
            config.setdefault("circadian_rhythms", {})[name] = {**defaults, **settings}

            await self.save_config_to_file(config)
            glozone.set_config(config)

            logger.info(f"Created circadian rhythm: {name}")
            return web.json_response({"status": "created", "name": name})
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)
        except Exception as e:
            logger.error(f"Error creating rhythm: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def update_circadian_rhythm(self, request: Request) -> Response:
        """Update a circadian rhythm (settings or rename)."""
        try:
            name = request.match_info.get("name")
            data = await request.json()

            config = await self.load_raw_config()

            if name not in config.get("circadian_rhythms", {}):
                return web.json_response({"error": f"Rhythm '{name}' not found"}, status=404)

            # Handle rename if "name" field is provided
            new_name = data.pop("name", None)
            if new_name and new_name != name:
                if new_name in config.get("circadian_rhythms", {}):
                    return web.json_response(
                        {"error": f"Rhythm '{new_name}' already exists"},
                        status=400
                    )
                # Rename the rhythm
                config["circadian_rhythms"][new_name] = config["circadian_rhythms"].pop(name)
                # Update all zones using this rhythm
                for zone_name, zone_data in config.get("glozones", {}).items():
                    if zone_data.get("rhythm") == name:
                        zone_data["rhythm"] = new_name
                logger.info(f"Renamed circadian rhythm: {name} -> {new_name}")
                name = new_name

            # Update the rhythm settings if any remain
            if data:
                config["circadian_rhythms"][name].update(data)

            await self.save_config_to_file(config)
            glozone.set_config(config)

            # Fire refresh event to notify main.py to reload config
            _, ws_url, token = self._get_ha_api_config()
            if ws_url and token:
                await self._fire_event_via_websocket(ws_url, token, 'circadian_light_refresh', {})
                logger.info("Fired circadian_light_refresh event after rhythm update")

            logger.info(f"Updated circadian rhythm: {name}")
            return web.json_response({"status": "updated", "name": name})
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)
        except Exception as e:
            logger.error(f"Error updating rhythm: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def delete_circadian_rhythm(self, request: Request) -> Response:
        """Delete a circadian rhythm."""
        try:
            name = request.match_info.get("name")

            config = await self.load_raw_config()
            rhythms = config.get("circadian_rhythms", {})

            if name not in rhythms:
                return web.json_response({"error": f"Rhythm '{name}' not found"}, status=404)

            # Cannot delete the last rhythm
            if len(rhythms) <= 1:
                return web.json_response(
                    {"error": "Cannot delete the last rhythm"},
                    status=400
                )

            # Cannot delete a rhythm that's in use by a zone
            zones_using = [
                zn for zn, zc in config.get("glozones", {}).items()
                if zc.get("rhythm") == name
            ]
            if zones_using:
                zone_list = ", ".join(zones_using)
                return web.json_response(
                    {"error": f"Cannot delete rhythm '{name}' — it is used by zone(s): {zone_list}. Reassign them first."},
                    status=400
                )

            del config["circadian_rhythms"][name]

            await self.save_config_to_file(config)
            glozone.set_config(config)

            logger.info(f"Deleted circadian rhythm: {name}")
            return web.json_response({"status": "deleted", "name": name})
        except Exception as e:
            logger.error(f"Error deleting rhythm: {e}")
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

            # Check if any areas are missing names before fetching from HA
            needs_name_enrichment = False
            for zone_config in zones.values():
                for area in zone_config.get("areas", []):
                    if isinstance(area, str) or (isinstance(area, dict) and not area.get("name")):
                        needs_name_enrichment = True
                        break
                if needs_name_enrichment:
                    break

            # Only fetch HA area names if there are areas missing names
            ha_area_names = {}
            if needs_name_enrichment:
                try:
                    _, ws_url, token = self._get_ha_api_config()
                    if ws_url and token:
                        ha_areas = await self._fetch_areas_via_websocket(ws_url, token)
                        ha_area_names = {a['area_id']: a.get('name', a['area_id']) for a in (ha_areas or [])}
                except Exception as e:
                    logger.debug(f"Could not fetch HA area names: {e}")

            # Enrich with runtime state and area names
            result = {}
            for zone_name, zone_config in zones.items():
                runtime = glozone_state.get_zone_state(zone_name)
                # Enrich areas with friendly names from HA if missing
                areas = []
                for area in zone_config.get("areas", []):
                    if isinstance(area, dict):
                        area_id = area.get("id")
                        # Use HA name if area doesn't have one stored
                        if not area.get("name") and area_id in ha_area_names:
                            area = {**area, "name": ha_area_names[area_id]}
                        areas.append(area)
                    else:
                        # Legacy: area stored as just a string ID
                        area_id = area
                        areas.append({"id": area_id, "name": ha_area_names.get(area_id, area_id)})

                result[zone_name] = {
                    "rhythm": zone_config.get("rhythm"),
                    "areas": areas,
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

            # Safety: if zones already have areas, this isn't a fresh install.
            # Set the flag and skip — the migration is only for first-time setup.
            if assigned_area_ids:
                logger.info(f"Zones already have {len(assigned_area_ids)} assigned areas - marking migration complete")
                config["areas_migrated_v1"] = True
                await self.save_config_to_file(config)
                glozone.set_config(config)
                return

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
            rhythm = data.get("rhythm")

            if not name:
                return web.json_response({"error": "name is required"}, status=400)

            config = await self.load_raw_config()

            if name in config.get("glozones", {}):
                return web.json_response({"error": f"Zone '{name}' already exists"}, status=409)

            rhythms = config.setdefault("circadian_rhythms", {})

            if rhythm and rhythm in rhythms:
                # Use the explicitly provided rhythm
                pass
            else:
                # Auto-create a rhythm named after the zone with defaults
                rhythm = name
                if rhythm not in rhythms:
                    rhythms[rhythm] = {}
                    logger.info(f"Auto-created rhythm '{rhythm}' for new zone")

            # Create the zone
            config.setdefault("glozones", {})[name] = {
                "rhythm": rhythm,
                "areas": []
            }

            await self.save_config_to_file(config)
            glozone.set_config(config)

            # Fire refresh event to notify main.py to reload config
            _, ws_url, token = self._get_ha_api_config()
            if ws_url and token:
                await self._fire_event_via_websocket(ws_url, token, 'circadian_light_refresh', {})
                logger.info("Fired circadian_light_refresh event after zone create")

            logger.info(f"Created GloZone: {name} with rhythm {rhythm}")
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

            # Track whether lighting-relevant fields changed
            needs_refresh = False

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

            # Update rhythm if provided
            if "rhythm" in data:
                rhythm = data["rhythm"]
                if rhythm not in config.get("circadian_rhythms", {}):
                    return web.json_response(
                        {"error": f"Rhythm '{rhythm}' not found"},
                        status=400
                    )
                config["glozones"][name]["rhythm"] = rhythm
                needs_refresh = True

            # Update areas if provided (replaces entire list)
            if "areas" in data:
                config["glozones"][name]["areas"] = data["areas"]
                needs_refresh = True

            # Handle is_default - setting this zone as the default
            if data.get("is_default"):
                # Clear is_default from all zones, set on this one
                for zn, zc in config["glozones"].items():
                    zc["is_default"] = (zn == name)
                logger.info(f"Set '{name}' as default zone")
                needs_refresh = True

            await self.save_config_to_file(config)
            glozone.set_config(config)

            # Fire refresh event only when lighting-relevant fields changed
            if needs_refresh:
                _, ws_url, token = self._get_ha_api_config()
                if ws_url and token:
                    await self._fire_event_via_websocket(ws_url, token, 'circadian_light_refresh', {})
                    logger.info("Fired circadian_light_refresh event after zone update")

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

            # Fire refresh event to notify main.py to reload config
            _, ws_url, token = self._get_ha_api_config()
            if ws_url and token:
                await self._fire_event_via_websocket(ws_url, token, 'circadian_light_refresh', {})
                logger.info("Fired circadian_light_refresh event after zone delete")

            logger.info(f"Deleted GloZone: {name}")
            return web.json_response({"status": "deleted", "name": name})
        except Exception as e:
            logger.error(f"Error deleting zone: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def reorder_glozones(self, request: Request) -> Response:
        """Reorder GloZones by rebuilding the dict in the specified key order."""
        try:
            data = await request.json()
            order = data.get("order")

            if not order or not isinstance(order, list):
                return web.json_response({"error": "order must be a list of zone names"}, status=400)

            config = await self.load_raw_config()
            zones = config.get("glozones", {})

            # Validate all names match existing zones
            if set(order) != set(zones.keys()):
                return web.json_response(
                    {"error": "order must contain exactly the existing zone names"},
                    status=400
                )

            # Rebuild dict in new order
            config["glozones"] = {name: zones[name] for name in order}

            await self.save_config_to_file(config)
            glozone.set_config(config)

            logger.info(f"Reordered GloZones: {order}")
            return web.json_response({"status": "reordered"})
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)
        except Exception as e:
            logger.error(f"Error reordering zones: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def reorder_zone_areas(self, request: Request) -> Response:
        """Reorder areas within a GloZone."""
        try:
            name = request.match_info.get("name")
            data = await request.json()
            area_ids = data.get("area_ids")

            if not area_ids or not isinstance(area_ids, list):
                return web.json_response({"error": "area_ids must be a list"}, status=400)

            config = await self.load_raw_config()
            zones = config.get("glozones", {})

            if name not in zones:
                return web.json_response({"error": f"Zone '{name}' not found"}, status=404)

            zone_areas = zones[name].get("areas", [])

            # Build lookup: area_id -> area entry
            area_lookup = {}
            for area in zone_areas:
                aid = area.get("id") if isinstance(area, dict) else area
                area_lookup[aid] = area

            # Validate all IDs exist in this zone
            if set(area_ids) != set(area_lookup.keys()):
                return web.json_response(
                    {"error": "area_ids must contain exactly the areas in this zone"},
                    status=400
                )

            # Rebuild areas list in new order
            zones[name]["areas"] = [area_lookup[aid] for aid in area_ids]

            await self.save_config_to_file(config)
            glozone.set_config(config)

            logger.info(f"Reordered areas in zone '{name}': {area_ids}")
            return web.json_response({"status": "reordered"})
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)
        except Exception as e:
            logger.error(f"Error reordering zone areas: {e}")
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
    # Moments API - CRUD for whole-home presets
    # -------------------------------------------------------------------------

    # Reserved preset names that cannot be used for moments
    RESERVED_PRESET_NAMES = {"wake", "bed", "nitelite", "britelite"}

    def _slugify_moment_name(self, name: str, existing_ids: set, exclude_id: str = None) -> str:
        """Convert moment name to a URL-safe slug, handling duplicates.

        Args:
            name: The display name to slugify
            existing_ids: Set of existing moment IDs
            exclude_id: ID to exclude from duplicate check (for renames)

        Returns:
            Unique slug like 'sleep' or 'sleep_2' if duplicate
        """
        import re
        # Lowercase, replace spaces/dashes with underscores, remove other special chars
        slug = name.lower().strip()
        slug = re.sub(r'[\s\-]+', '_', slug)  # spaces/dashes to underscores
        slug = re.sub(r'[^a-z0-9_]', '', slug)  # remove non-alphanumeric
        slug = re.sub(r'_+', '_', slug)  # collapse multiple underscores
        slug = slug.strip('_')  # remove leading/trailing underscores

        if not slug:
            slug = 'moment'

        # Check for duplicates and append number if needed
        base_slug = slug
        counter = 2
        check_ids = existing_ids - {exclude_id} if exclude_id else existing_ids
        while slug in check_ids or slug in self.RESERVED_PRESET_NAMES:
            slug = f"{base_slug}_{counter}"
            counter += 1

        return slug

    async def get_moments(self, request: Request) -> Response:
        """Get all moments."""
        try:
            config = await self.load_raw_config()
            moments = config.get("moments", {})
            return web.json_response({"moments": moments})
        except Exception as e:
            logger.error(f"Error getting moments: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def get_moment(self, request: Request) -> Response:
        """Get a single moment by ID."""
        try:
            moment_id = request.match_info.get("moment_id")
            config = await self.load_raw_config()
            moments = config.get("moments", {})

            if moment_id not in moments:
                return web.json_response({"error": f"Moment '{moment_id}' not found"}, status=404)

            return web.json_response({"moment": moments[moment_id], "id": moment_id})
        except Exception as e:
            logger.error(f"Error getting moment: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def create_moment(self, request: Request) -> Response:
        """Create a new moment."""
        try:
            data = await request.json()
            name = data.get("name", "").strip()

            if not name:
                return web.json_response({"error": "Moment name is required"}, status=400)

            config = await self.load_raw_config()
            moments = config.setdefault("moments", {})

            # Generate unique slug from name
            moment_id = self._slugify_moment_name(name, set(moments.keys()))

            # Create the moment with defaults
            moments[moment_id] = {
                "name": name,
                "icon": data.get("icon", "mdi:lightbulb"),
                "category": data.get("category", "utility"),
                "trigger": data.get("trigger", {"type": "primitive"}),
                "default_action": data.get("default_action", "off"),
                "exceptions": data.get("exceptions", {}),
            }

            # Add fun moment fields if applicable
            if data.get("category") == "fun":
                moments[moment_id]["default_participation"] = data.get("default_participation", "if_on")
                if "effect" in data:
                    moments[moment_id]["effect"] = data["effect"]

            await self.save_config_to_file(config)

            logger.info(f"Created moment: {name} (id: {moment_id})")
            return web.json_response({"status": "created", "id": moment_id, "moment": moments[moment_id]})
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)
        except Exception as e:
            logger.error(f"Error creating moment: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def update_moment(self, request: Request) -> Response:
        """Update a moment."""
        try:
            moment_id = request.match_info.get("moment_id")
            data = await request.json()

            config = await self.load_raw_config()
            moments = config.get("moments", {})

            if moment_id not in moments:
                return web.json_response({"error": f"Moment '{moment_id}' not found"}, status=404)

            moment = moments[moment_id]

            # Handle rename if name changed
            new_name = data.get("name")
            if new_name and new_name != moment.get("name"):
                new_id = self._slugify_moment_name(new_name, set(moments.keys()), exclude_id=moment_id)
                # Rename: create new key, delete old
                if new_id != moment_id:
                    moments[new_id] = moment
                    del moments[moment_id]
                    moment_id = new_id
                    moment = moments[moment_id]

            # Update fields
            for field in ["name", "icon", "category", "trigger", "default_action",
                          "exceptions", "default_participation", "effect"]:
                if field in data:
                    moment[field] = data[field]

            await self.save_config_to_file(config)

            logger.info(f"Updated moment: {moment_id}")
            return web.json_response({"status": "updated", "id": moment_id, "moment": moment})
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)
        except Exception as e:
            logger.error(f"Error updating moment: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def delete_moment(self, request: Request) -> Response:
        """Delete a moment."""
        try:
            moment_id = request.match_info.get("moment_id")

            config = await self.load_raw_config()
            moments = config.get("moments", {})

            if moment_id not in moments:
                return web.json_response({"error": f"Moment '{moment_id}' not found"}, status=404)

            del moments[moment_id]
            await self.save_config_to_file(config)

            # Clean up magic button references in all switches
            action_ref = f"set_{moment_id}"
            cleaned = 0
            for sw in switches.get_all_switches().values():
                orphaned_keys = [k for k, v in sw.magic_buttons.items() if v == action_ref]
                for k in orphaned_keys:
                    del sw.magic_buttons[k]
                    cleaned += 1
            if cleaned:
                switches._save()
                logger.info(f"Removed {cleaned} magic button reference(s) to deleted moment '{moment_id}'")

            logger.info(f"Deleted moment: {moment_id}")
            return web.json_response({"status": "deleted", "id": moment_id})
        except Exception as e:
            logger.error(f"Error deleting moment: {e}")
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
        - freeze_toggle
        - glo_up, glo_down, glo_reset
        """
        VALID_ACTIONS = {
            'lights_on', 'lights_off', 'lights_toggle',
            'circadian_on', 'circadian_off',
            'step_up', 'step_down',
            'bright_up', 'bright_down',
            'color_up', 'color_down',
            'freeze_toggle',
            'glo_up', 'glo_down', 'glo_reset',
            'boost',
            'set_nitelite', 'set_britelite',
            'set_position',
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

            # For boost, set state directly in webserver process for immediate UI feedback,
            # then fire event so main.py applies the actual lighting change
            if action == 'boost':
                # Reload state from disk (main.py may have updated it)
                state.init()
                if state.is_boosted(area_id):
                    # End boost: clear state, fire event for main.py to restore lighting
                    state.clear_boost(area_id)
                    logger.info(f"[boost] Cleared boost state for area {area_id}, firing event for lighting restore")
                    action = 'boost_off'
                else:
                    # Start boost: set state, fire event for main.py to apply lighting
                    raw_config = glozone.load_config_from_files()
                    boost_amount = raw_config.get("boost_default", 30)
                    is_on = state.is_circadian(area_id) and state.get_is_on(area_id)
                    state.set_boost(area_id, started_from_off=not is_on, expires_at="forever", brightness=boost_amount)
                    if not glozone.is_area_in_any_zone(area_id):
                        glozone.add_area_to_default_zone(area_id)
                    state.enable_circadian_and_set_on(area_id, True)
                    logger.info(f"[boost] Set boost state for area {area_id} (amount={boost_amount}%), firing event for lighting")
                    action = 'boost_on'

            # Build event data
            event_data = {'service': action, 'area_id': area_id}
            if action == 'set_position':
                value = data.get("value")
                if value is None:
                    return web.json_response({"error": "value required for set_position"}, status=400)
                event_data['value'] = float(value)
                event_data['mode'] = data.get("mode", "step")

            # Fire event for main.py to handle
            _, ws_url, token = self._get_ha_api_config()
            if ws_url and token:
                success = await self._fire_event_via_websocket(
                    ws_url, token, 'circadian_light_service_event',
                    event_data
                )
                if success:
                    logger.info(f"Fired {action} event for area {area_id}")
                    return web.json_response({"status": "ok", "action": action, "area_id": area_id})
                else:
                    # Event failed but state was already set for boost - return ok for UI
                    if action in ('boost_on', 'boost_off'):
                        logger.warning(f"Event fire failed for {action}, but state was set directly")
                        return web.json_response({"status": "ok", "action": action, "area_id": area_id})
                    return web.json_response({"error": "Failed to fire event"}, status=500)
            else:
                return web.json_response({"error": "HA API not configured"}, status=503)

        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)
        except Exception as e:
            logger.error(f"Error handling area action: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def handle_zone_action(self, request: Request) -> Response:
        """Handle zone-level action (modifies zone state only, no light control).

        Fires a circadian_light_zone_action event for main.py to handle.
        Valid actions: step_up, step_down, bright_up, bright_down, color_up, color_down
        """
        VALID_ZONE_ACTIONS = {
            'step_up', 'step_down',
            'bright_up', 'bright_down',
            'color_up', 'color_down',
            'glozone_reset', 'glozone_down',
            'set_position',
        }

        try:
            data = await request.json()
            zone_name = data.get("zone_name")
            action = data.get("action")

            if not zone_name:
                return web.json_response({"error": "zone_name is required"}, status=400)
            if not action:
                return web.json_response({"error": "action is required"}, status=400)
            if action not in VALID_ZONE_ACTIONS:
                return web.json_response({"error": f"Invalid zone action: {action}. Valid: {sorted(VALID_ZONE_ACTIONS)}"}, status=400)

            # Build event data
            zone_event_data = {'service': action, 'zone_name': zone_name}
            if action == 'set_position':
                value = data.get("value")
                if value is None:
                    return web.json_response({"error": "value required for set_position"}, status=400)
                zone_event_data['value'] = float(value)
                zone_event_data['mode'] = data.get("mode", "step")

            # Fire event for main.py to handle
            _, ws_url, token = self._get_ha_api_config()
            if ws_url and token:
                success = await self._fire_event_via_websocket(
                    ws_url, token, 'circadian_light_zone_action',
                    zone_event_data
                )
                if success:
                    logger.info(f"Fired zone {action} event for zone '{zone_name}'")
                    return web.json_response({"status": "ok", "action": action, "zone_name": zone_name})
                else:
                    return web.json_response({"error": "Failed to fire event"}, status=500)
            else:
                return web.json_response({"error": "HA API not configured"}, status=503)

        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)
        except Exception as e:
            logger.error(f"Error handling zone action: {e}")
            return web.json_response({"error": str(e)}, status=500)

    # -------------------------------------------------------------------------
    # Manual Sync
    # -------------------------------------------------------------------------

    async def handle_sync_devices(self, request: Request) -> Response:
        """Trigger manual device/area/group sync.

        Re-scans Home Assistant for new/moved lights, areas, and ZHA devices.
        Fires an event that main.py listens for to trigger the actual sync.
        """
        try:
            # Clear areas cache so it gets refreshed on next request
            self.cached_areas_list = None
            logger.info("Cleared areas cache for sync")

            # Fire event for main.py to handle the sync
            _, ws_url, token = self._get_ha_api_config()
            if ws_url and token:
                fired = await self._fire_event_via_websocket(
                    ws_url, token, 'circadian_light_sync_devices', {}
                )
                if fired:
                    logger.info("Fired circadian_light_sync_devices event")
                    return web.json_response({"success": True, "message": "Device sync triggered"})
                else:
                    return web.json_response({"error": "Failed to fire sync event"}, status=500)
            else:
                return web.json_response({"error": "WebSocket not configured"}, status=503)
        except Exception as e:
            logger.error(f"Error triggering device sync: {e}")
            return web.json_response({"error": str(e)}, status=500)

    # -------------------------------------------------------------------------
    # Switch Management API endpoints
    # -------------------------------------------------------------------------

    async def serve_switches(self, request: Request) -> Response:
        """Serve the Switches configuration page."""
        return await self.serve_page("switches")

    async def serve_switchmap(self, request: Request) -> Response:
        """Serve the Switchmap Designer page."""
        return await self.serve_page("switchmap")

    async def get_switchmap(self, request: Request) -> Response:
        """Get current switch button mappings.

        Returns the custom mappings from designer_config.json merged with defaults.
        """
        try:
            # Get custom mappings (loads from designer_config.json)
            custom = switches.get_custom_mappings()

            # Build response with defaults and custom overrides
            mappings = {}
            for switch_type, type_info in switches.SWITCH_TYPES.items():
                # Start with default mapping
                default_mapping = type_info.get("default_mapping", {})

                # Merge custom mappings on top
                effective = dict(default_mapping)
                if switch_type in custom:
                    effective.update(custom[switch_type])

                mappings[switch_type] = {
                    "name": type_info.get("name", switch_type),
                    "buttons": type_info.get("buttons", []),
                    "action_types": type_info.get("action_types", []),
                    "repeat_on_hold": type_info.get("repeat_on_hold", []),
                    "default_mapping": default_mapping,
                    "effective_mapping": effective,
                    "has_custom": switch_type in custom,
                }

            return web.json_response({
                "mappings": mappings,
                "custom_mappings": custom,
            })
        except Exception as e:
            logger.error(f"Error getting switchmap: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def save_switchmap(self, request: Request) -> Response:
        """Save switch button mappings.

        POST body: {"hue_4button_v2": {"on_short_release": "toggle", ...}, ...}
        """
        try:
            data = await request.json()

            # Validate the data structure
            if not isinstance(data, dict):
                return web.json_response({"error": "Expected object with switch_type keys"}, status=400)

            # Save the mappings
            if switches.save_custom_mappings(data):
                return web.json_response({"status": "success"})
            else:
                return web.json_response({"error": "Failed to save mappings"}, status=500)

        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)
        except Exception as e:
            logger.error(f"Error saving switchmap: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def get_switchmap_actions(self, request: Request) -> Response:
        """Get available actions for switchmap, organized by category."""
        try:
            categories = switches.get_categorized_actions()
            when_off_options = switches.get_when_off_options()

            return web.json_response({
                "categories": categories,
                "when_off_options": when_off_options,
            })
        except Exception as e:
            logger.error(f"Error getting switchmap actions: {e}")
            return web.json_response({"error": str(e)}, status=500)

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

    async def flash_light(self, request: Request) -> Response:
        """Flash a light entity briefly so the user can identify it.

        POST body: {"entity_id": "light.xyz"}
        """
        try:
            data = await request.json()
            entity_id = data.get("entity_id")
            if not entity_id or not entity_id.startswith("light."):
                return web.json_response({"error": "Valid light entity_id required"}, status=400)

            rest_url, ws_url, token = self._get_ha_api_config()
            if not token or not ws_url:
                return web.json_response({"error": "HA not configured"}, status=500)

            async with websockets.connect(ws_url) as ws:
                # Auth
                msg = json.loads(await ws.recv())
                if msg.get('type') != 'auth_required':
                    return web.json_response({"error": "Auth failed"}, status=500)
                await ws.send(json.dumps({'type': 'auth', 'access_token': token}))
                msg = json.loads(await ws.recv())
                if msg.get('type') != 'auth_ok':
                    return web.json_response({"error": "Auth failed"}, status=500)

                # Get current state
                await ws.send(json.dumps({
                    'id': 1, 'type': 'get_states'
                }))
                states_msg = json.loads(await ws.recv())
                current_state = None
                if states_msg.get('success') and states_msg.get('result'):
                    for s in states_msg['result']:
                        if s.get('entity_id') == entity_id:
                            current_state = s
                            break

                was_on = current_state and current_state.get('state') == 'on'
                attrs = current_state.get('attributes', {}) if was_on else {}
                orig_brightness = attrs.get('brightness', 128)

                # Flash: turn on bright
                msg_id = 2
                await ws.send(json.dumps({
                    'id': msg_id, 'type': 'call_service',
                    'domain': 'light', 'service': 'turn_on',
                    'service_data': {'brightness': 255, 'transition': 0},
                    'target': {'entity_id': entity_id}
                }))
                await ws.recv()

                await asyncio.sleep(0.5)

                # Restore
                msg_id += 1
                if not was_on:
                    await ws.send(json.dumps({
                        'id': msg_id, 'type': 'call_service',
                        'domain': 'light', 'service': 'turn_off',
                        'service_data': {'transition': 0},
                        'target': {'entity_id': entity_id}
                    }))
                else:
                    restore_data = {'brightness': orig_brightness, 'transition': 0}
                    xy = attrs.get('xy_color')
                    ct = attrs.get('color_temp')
                    if xy:
                        restore_data['xy_color'] = xy
                    elif ct:
                        restore_data['color_temp'] = ct
                    await ws.send(json.dumps({
                        'id': msg_id, 'type': 'call_service',
                        'domain': 'light', 'service': 'turn_on',
                        'service_data': restore_data,
                        'target': {'entity_id': entity_id}
                    }))
                await ws.recv()

            return web.json_response({"status": "ok"})
        except Exception as e:
            logger.error(f"Error flashing light: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)

    async def get_area_lights(self, request: Request) -> Response:
        """Get light entities for a given area, or all lights.

        Query params:
        - area_id: Filter to specific area
        - all: If 'true', return all lights with area prefix in name

        Returns list of {entity_id, name} for light entities.
        """
        area_id = request.query.get("area_id")
        show_all = request.query.get("all") == "true"

        if not area_id and not show_all:
            return web.json_response({"lights": []})

        try:
            rest_url, ws_url, token = self._get_ha_api_config()
            if not token or not ws_url:
                return web.json_response({"lights": []})

            async with websockets.connect(ws_url) as ws:
                # Auth
                msg = json.loads(await ws.recv())
                if msg.get('type') != 'auth_required':
                    return web.json_response({"lights": []})
                await ws.send(json.dumps({'type': 'auth', 'access_token': token}))
                msg = json.loads(await ws.recv())
                if msg.get('type') != 'auth_ok':
                    return web.json_response({"lights": []})

                # Get area registry for area names
                await ws.send(json.dumps({'id': 1, 'type': 'config/area_registry/list'}))
                area_msg = json.loads(await ws.recv())
                area_names = {}
                if area_msg.get('success') and area_msg.get('result'):
                    area_names = {a['area_id']: a['name'] for a in area_msg['result']}

                # Get device registry to find devices and their areas
                await ws.send(json.dumps({'id': 2, 'type': 'config/device_registry/list'}))
                device_msg = json.loads(await ws.recv())
                device_areas = {}  # device_id -> area_id
                area_device_ids = set()  # devices in target area (for filtered mode)
                if device_msg.get('success') and device_msg.get('result'):
                    for device in device_msg['result']:
                        device_areas[device.get('id')] = device.get('area_id')
                        if device.get('area_id') == area_id:
                            area_device_ids.add(device.get('id'))

                # Get states for friendly names and detect groups
                await ws.send(json.dumps({'id': 3, 'type': 'get_states'}))
                states_msg = json.loads(await ws.recv())
                friendly_names = {}
                light_groups = set()  # entity_ids that are groups (have child entities)
                if states_msg.get('success') and states_msg.get('result'):
                    for state in states_msg['result']:
                        entity_id = state.get('entity_id', '')
                        if entity_id.startswith('light.'):
                            attrs = state.get('attributes', {})
                            friendly_names[entity_id] = attrs.get('friendly_name', '')
                            # Detect if this is a group (has entity_id list or is_group attribute)
                            if attrs.get('entity_id') or attrs.get('is_group') or attrs.get('is_hue_group'):
                                light_groups.add(entity_id)

                # Get entity registry to find light entities
                await ws.send(json.dumps({'id': 4, 'type': 'config/entity_registry/list'}))
                entity_msg = json.loads(await ws.recv())
                lights = []
                entire_area_lights = []  # Groups go at top
                if entity_msg.get('success') and entity_msg.get('result'):
                    for entity in entity_msg['result']:
                        entity_id = entity.get('entity_id', '')
                        if not entity_id.startswith('light.'):
                            continue

                        # Determine entity's area (direct or via device)
                        entity_area = entity.get('area_id') or device_areas.get(entity.get('device_id'))
                        is_group = entity_id in light_groups

                        # Skip lights in Circadian_Zigbee_Groups area (internal use only)
                        area_name_check = area_names.get(entity_area, '')
                        if area_name_check == 'Circadian_Zigbee_Groups':
                            continue

                        if show_all:
                            # Include all lights, prefix with area name
                            area_name = area_names.get(entity_area, 'Unknown')
                            if is_group:
                                name = f"Entire area: {area_name}"
                                entire_area_lights.append({"entity_id": entity_id, "name": name, "area_id": entity_area, "is_group": True})
                            else:
                                base_name = friendly_names.get(entity_id) or entity.get('name') or entity.get('original_name') or entity_id.replace('light.', '').replace('_', ' ').title()
                                name = f"{area_name}: {base_name}"
                                lights.append({"entity_id": entity_id, "name": name, "area_id": entity_area})
                        else:
                            # Filter to target area
                            if entity.get('area_id') == area_id or entity.get('device_id') in area_device_ids:
                                area_name = area_names.get(entity_area, '')
                                if is_group:
                                    name = f"Entire area: {area_name}" if area_name else "Entire area"
                                    entire_area_lights.append({"entity_id": entity_id, "name": name, "is_group": True})
                                else:
                                    name = friendly_names.get(entity_id) or entity.get('name') or entity.get('original_name') or entity_id.replace('light.', '').replace('_', ' ').title()
                                    lights.append({"entity_id": entity_id, "name": name})

                # Sort: entire area lights first, then others alphabetically
                entire_area_lights.sort(key=lambda x: x['name'].lower())
                lights.sort(key=lambda x: x['name'].lower())
                lights = entire_area_lights + lights

                return web.json_response({"lights": lights})
        except Exception as e:
            logger.error(f"Error fetching area lights: {e}", exc_info=True)
            return web.json_response({"lights": []})

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
                    # A switch is configured if it has scopes with areas OR has magic buttons assigned
                    has_areas = config and config.get("scopes") and any(s.get("areas") for s in config.get("scopes", []))
                    has_magic = config and config.get("magic_buttons") and any(v for v in config.get("magic_buttons", {}).values())
                    is_configured = has_areas or has_magic

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
                    "area_id": ctrl.get("area_id"),
                    "area_name": ctrl.get("area_name"),
                    "category": category,
                    "integration": ctrl.get("integration"),
                    "type": ctrl.get("type"),
                    "type_name": ctrl.get("type_name"),
                    "supported": ctrl.get("supported"),
                    "status": status,
                    "last_action": last_action,
                    "illuminance": ctrl.get("illuminance"),
                }

                control_data["inactive"] = config.get("inactive", False)
                if category in ("motion_sensor", "contact_sensor"):
                    control_data["areas"] = config.get("areas", [])
                else:
                    control_data["scopes"] = config.get("scopes", [])
                    control_data["indicator_light"] = config.get("indicator_light")
                    control_data["magic_buttons"] = config.get("magic_buttons", {})

                controls.append(control_data)

            return web.json_response({"controls": controls})
        except Exception as e:
            logger.error(f"Error getting controls: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)

    async def _fetch_ha_controls(self) -> List[Dict[str, Any]]:
        """Fetch potential control devices from HA.

        Identifies controls by entity types:
        - binary_sensor.*_motion, *_occupancy, *_presence, *_contact → sensors
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
                            # Extract unique ID from identifiers (ZHA, Hue, or Matter)
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
                                    elif identifier[0] == 'matter':
                                        unique_id = identifier[1]  # Matter device ID
                                        integration = 'matter'
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
                device_entities: Dict[str, Dict[str, Any]] = {}
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
                                'has_presence': False,
                                'has_contact': False,
                                'has_button': False,
                                'has_battery': False,
                                'illuminance_entity': None,
                                'sensitivity_entity': None,
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
                            elif '_presence' in entity_id:
                                device_entities[device_id]['has_presence'] = True
                                logger.info(f"[Controls] Found presence entity: {entity_id} for device {device_id}")
                            elif '_contact' in entity_id or '_opening' in entity_id:
                                device_entities[device_id]['has_contact'] = True
                        elif entity_id.startswith('sensor.') and '_battery' in entity_id:
                            device_entities[device_id]['has_battery'] = True
                        elif entity_id.startswith('sensor.') and ('illuminance' in entity_id or '_lux' in entity_id):
                            device_entities[device_id]['illuminance_entity'] = entity_id
                        # Detect sensitivity entities (select or number) for motion sensors
                        elif (entity_id.startswith('select.') or entity_id.startswith('number.')) and 'sensitivity' in entity_id.lower():
                            device_entities[device_id]['sensitivity_entity'] = entity_id
                            logger.debug(f"[Controls] Found sensitivity entity: {entity_id} for device {device_id}")

                # Fetch current entity states for illuminance readings
                entity_states = {}
                illuminance_entities = {
                    de['illuminance_entity']
                    for de in device_entities.values()
                    if de.get('illuminance_entity')
                }
                if illuminance_entities:
                    await ws.send(json.dumps({'id': 4, 'type': 'get_states'}))
                    states_msg = json.loads(await ws.recv())
                    if states_msg.get('success') and states_msg.get('result'):
                        for state in states_msg['result']:
                            eid = state.get('entity_id', '')
                            if eid in illuminance_entities:
                                entity_states[eid] = state.get('state')

                # Filter to potential controls
                controls = []
                for device_id, device in devices.items():
                    entities = device_entities.get(device_id, {})

                    # Skip if it's primarily a light
                    if entities.get('has_light') and not any([
                        entities.get('has_motion'),
                        entities.get('has_occupancy'),
                        entities.get('has_presence'),
                        entities.get('has_contact'),
                        entities.get('has_button'),
                    ]):
                        continue

                    # Include if it has control-like entities
                    is_control = any([
                        entities.get('has_motion'),
                        entities.get('has_occupancy'),
                        entities.get('has_presence'),
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
                    if entities.get('has_motion') or entities.get('has_occupancy') or entities.get('has_presence'):
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

                    # Attach illuminance entity info if present
                    illum_entity = entities.get('illuminance_entity')
                    illum_info = None
                    if illum_entity:
                        raw_val = entity_states.get(illum_entity)
                        try:
                            illum_val = round(float(raw_val)) if raw_val not in (None, 'unavailable', 'unknown') else None
                        except (ValueError, TypeError):
                            illum_val = None
                        illum_info = {
                            'entity_id': illum_entity,
                            'value': illum_val,
                            'unit': 'lx',
                        }

                    # Include sensitivity entity for motion sensors (ZHA only)
                    sensitivity_entity = entities.get('sensitivity_entity') if category == 'motion_sensor' else None

                    controls.append({
                        **device,
                        'category': category,
                        'type': detected_type,
                        'type_name': type_name,
                        'supported': is_supported,
                        'illuminance': illum_info,
                        'sensitivity_entity': sensitivity_entity,
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
                # Support both old format (areas with area_id) and new format (scopes with areas array)
                scopes_data = data.get("scopes")
                areas_data = data.get("areas", [])
                areas = []

                if scopes_data:
                    # New format: scopes with multiple areas sharing settings
                    # Expand each scope into individual MotionAreaConfig entries
                    for scope in scopes_data:
                        scope_areas = scope.get("areas", [])
                        mode = scope.get("mode", "on_off")
                        duration = scope.get("duration", 60)
                        boost_enabled = scope.get("boost_enabled", False)
                        boost_brightness = scope.get("boost_brightness", 50)
                        active_when = scope.get("active_when", "always")
                        active_offset = scope.get("active_offset", 0)

                        for area_id in scope_areas:
                            areas.append(switches.MotionAreaConfig(
                                area_id=area_id,
                                mode=mode,
                                duration=duration,
                                boost_enabled=boost_enabled,
                                boost_brightness=boost_brightness,
                                active_when=active_when,
                                active_offset=active_offset,
                            ))
                else:
                    # Old format: areas with area_id per entry
                    for area_data in areas_data:
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
                # Support both old format (areas with area_id) and new format (scopes with areas array)
                scopes_data = data.get("scopes")
                areas_data = data.get("areas", [])
                areas = []

                if scopes_data:
                    # New format: scopes with multiple areas sharing settings
                    # Expand each scope into individual ContactAreaConfig entries
                    for scope in scopes_data:
                        scope_areas = scope.get("areas", [])
                        mode = scope.get("mode", "on_off")
                        duration = scope.get("duration", 60)
                        boost_enabled = scope.get("boost_enabled", False)
                        boost_brightness = scope.get("boost_brightness", 50)

                        for area_id in scope_areas:
                            areas.append(switches.ContactAreaConfig(
                                area_id=area_id,
                                mode=mode,
                                duration=duration,
                                boost_enabled=boost_enabled,
                                boost_brightness=boost_brightness,
                            ))
                else:
                    # Old format: areas with area_id per entry
                    for area_data in areas_data:
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
                control_type = data.get("type", "hue_dimmer")

                # Build scopes
                scopes_data = data.get("scopes", [])
                scopes = []
                for scope_data in scopes_data:
                    scope_areas = scope_data.get("areas", [])
                    scopes.append(switches.SwitchScope(areas=scope_areas))

                if not scopes:
                    scopes = [switches.SwitchScope(areas=[])]

                # Create/update switch config
                indicator_light = data.get("indicator_light") or None
                switch_config = switches.SwitchConfig(
                    id=control_id,
                    name=name,
                    type=control_type,
                    scopes=scopes,
                    magic_buttons=data.get("magic_buttons", {}),
                    device_id=device_id,
                    indicator_light=indicator_light,
                    inactive=data.get("inactive", False),
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

    async def get_zha_motion_settings(self, request: Request) -> Response:
        """Get ZHA motion sensor settings (sensitivity and timeout).

        Returns:
            - sensitivity: current value and available options (from HA select/number entity)
            - timeout: occupancy timeout in seconds (from ZHA cluster attribute)
            - is_zha: whether this is a ZHA device
        """
        device_id = request.match_info.get('device_id')
        if not device_id:
            return web.json_response({"error": "Device ID is required"}, status=400)

        rest_url, ws_url, token = self._get_ha_api_config()
        if not token or not ws_url:
            return web.json_response({"error": "HA API not configured"}, status=500)

        try:
            async with websockets.connect(ws_url) as ws:
                # Auth
                msg = json.loads(await ws.recv())
                if msg.get('type') != 'auth_required':
                    return web.json_response({"error": "Auth failed"}, status=500)
                await ws.send(json.dumps({'type': 'auth', 'access_token': token}))
                msg = json.loads(await ws.recv())
                if msg.get('type') != 'auth_ok':
                    return web.json_response({"error": "Auth failed"}, status=500)

                msg_id = 1

                # Get device info to find IEEE address
                await ws.send(json.dumps({'id': msg_id, 'type': 'config/device_registry/list'}))
                msg_id += 1
                device_msg = json.loads(await ws.recv())

                device_ieee = None
                is_zha = False
                if device_msg.get('success') and device_msg.get('result'):
                    for device in device_msg['result']:
                        if device.get('id') == device_id:
                            for identifier in device.get('identifiers', []):
                                if isinstance(identifier, list) and len(identifier) >= 2:
                                    if identifier[0] == 'zha':
                                        device_ieee = identifier[1]
                                        is_zha = True
                                        break
                            break

                if not is_zha:
                    return web.json_response({
                        "is_zha": False,
                        "sensitivity": None,
                        "timeout": None,
                    })

                # Get entity registry to find sensitivity entity
                await ws.send(json.dumps({'id': msg_id, 'type': 'config/entity_registry/list'}))
                msg_id += 1
                entity_msg = json.loads(await ws.recv())

                sensitivity_entity = None
                if entity_msg.get('success') and entity_msg.get('result'):
                    for entity in entity_msg['result']:
                        if entity.get('device_id') == device_id:
                            entity_id = entity.get('entity_id', '')
                            if 'sensitivity' in entity_id.lower() and (
                                entity_id.startswith('select.') or entity_id.startswith('number.')
                            ):
                                sensitivity_entity = entity_id
                                break

                # Get current states
                await ws.send(json.dumps({'id': msg_id, 'type': 'get_states'}))
                msg_id += 1
                states_msg = json.loads(await ws.recv())

                sensitivity_info = None
                if sensitivity_entity and states_msg.get('success') and states_msg.get('result'):
                    for state in states_msg['result']:
                        if state.get('entity_id') == sensitivity_entity:
                            attrs = state.get('attributes', {})
                            sensitivity_info = {
                                'entity_id': sensitivity_entity,
                                'value': state.get('state'),
                                'options': attrs.get('options', []),  # For select entities
                                'min': attrs.get('min'),  # For number entities
                                'max': attrs.get('max'),
                                'step': attrs.get('step'),
                            }
                            break

                # Read occupancy timeout from ZHA cluster attribute
                # Cluster 0x0406 (1030), attribute 0x0010 (16), endpoint 2
                timeout_value = None
                try:
                    await ws.send(json.dumps({
                        'id': msg_id,
                        'type': 'zha/devices/clusters/attributes/value',
                        'ieee': device_ieee,
                        'endpoint_id': 2,
                        'cluster_id': 1030,  # 0x0406
                        'cluster_type': 'in',
                        'attribute': 16,  # 0x0010
                    }))
                    msg_id += 1
                    timeout_msg = json.loads(await ws.recv())
                    if timeout_msg.get('success') and timeout_msg.get('result') is not None:
                        timeout_value = timeout_msg['result']
                except Exception as e:
                    logger.warning(f"[ZHA Settings] Could not read timeout for {device_ieee}: {e}")

                return web.json_response({
                    "is_zha": True,
                    "ieee": device_ieee,
                    "sensitivity": sensitivity_info,
                    "timeout": timeout_value,
                })

        except Exception as e:
            logger.error(f"Error getting ZHA motion settings: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)

    async def set_zha_motion_settings(self, request: Request) -> Response:
        """Set ZHA motion sensor settings (sensitivity and/or timeout).

        Request body:
            - sensitivity: new sensitivity value (string for select, number for number entity)
            - timeout: new occupancy timeout in seconds
        """
        device_id = request.match_info.get('device_id')
        if not device_id:
            return web.json_response({"error": "Device ID is required"}, status=400)

        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        new_sensitivity = data.get('sensitivity')
        new_timeout = data.get('timeout')

        if new_sensitivity is None and new_timeout is None:
            return web.json_response({"error": "No settings provided"}, status=400)

        rest_url, ws_url, token = self._get_ha_api_config()
        if not token or not ws_url:
            return web.json_response({"error": "HA API not configured"}, status=500)

        try:
            async with websockets.connect(ws_url) as ws:
                # Auth
                msg = json.loads(await ws.recv())
                if msg.get('type') != 'auth_required':
                    return web.json_response({"error": "Auth failed"}, status=500)
                await ws.send(json.dumps({'type': 'auth', 'access_token': token}))
                msg = json.loads(await ws.recv())
                if msg.get('type') != 'auth_ok':
                    return web.json_response({"error": "Auth failed"}, status=500)

                msg_id = 1

                # Get device info to find IEEE address
                await ws.send(json.dumps({'id': msg_id, 'type': 'config/device_registry/list'}))
                msg_id += 1
                device_msg = json.loads(await ws.recv())

                device_ieee = None
                for device in device_msg.get('result', []):
                    if device.get('id') == device_id:
                        for identifier in device.get('identifiers', []):
                            if isinstance(identifier, list) and len(identifier) >= 2:
                                if identifier[0] == 'zha':
                                    device_ieee = identifier[1]
                                    break
                        break

                if not device_ieee:
                    return web.json_response({"error": "Not a ZHA device"}, status=400)

                results = {}

                # Set sensitivity via HA service call
                if new_sensitivity is not None:
                    # Find sensitivity entity
                    await ws.send(json.dumps({'id': msg_id, 'type': 'config/entity_registry/list'}))
                    msg_id += 1
                    entity_msg = json.loads(await ws.recv())

                    sensitivity_entity = None
                    for entity in entity_msg.get('result', []):
                        if entity.get('device_id') == device_id:
                            entity_id = entity.get('entity_id', '')
                            if 'sensitivity' in entity_id.lower() and (
                                entity_id.startswith('select.') or entity_id.startswith('number.')
                            ):
                                sensitivity_entity = entity_id
                                break

                    if sensitivity_entity:
                        # Determine service based on entity type
                        if sensitivity_entity.startswith('select.'):
                            service_call = {
                                'id': msg_id,
                                'type': 'call_service',
                                'domain': 'select',
                                'service': 'select_option',
                                'service_data': {'option': new_sensitivity},
                                'target': {'entity_id': sensitivity_entity},
                            }
                        else:  # number entity
                            service_call = {
                                'id': msg_id,
                                'type': 'call_service',
                                'domain': 'number',
                                'service': 'set_value',
                                'service_data': {'value': new_sensitivity},
                                'target': {'entity_id': sensitivity_entity},
                            }
                        await ws.send(json.dumps(service_call))
                        msg_id += 1
                        result = json.loads(await ws.recv())
                        results['sensitivity'] = result.get('success', False)
                        logger.info(f"[ZHA Settings] Set sensitivity for {device_id}: {new_sensitivity} -> {results['sensitivity']}")
                    else:
                        results['sensitivity'] = False
                        results['sensitivity_error'] = 'No sensitivity entity found'

                # Set timeout via ZHA cluster attribute
                if new_timeout is not None:
                    try:
                        timeout_int = int(new_timeout)
                        await ws.send(json.dumps({
                            'id': msg_id,
                            'type': 'call_service',
                            'domain': 'zha',
                            'service': 'set_zigbee_cluster_attribute',
                            'service_data': {
                                'ieee': device_ieee,
                                'endpoint_id': 2,
                                'cluster_id': 1030,  # 0x0406
                                'cluster_type': 'in',
                                'attribute': 16,  # 0x0010
                                'value': timeout_int,
                            },
                        }))
                        msg_id += 1
                        result = json.loads(await ws.recv())
                        results['timeout'] = result.get('success', False)
                        logger.info(f"[ZHA Settings] Set timeout for {device_ieee}: {timeout_int}s -> {results['timeout']}")
                    except (ValueError, TypeError) as e:
                        results['timeout'] = False
                        results['timeout_error'] = f'Invalid timeout value: {e}'

                return web.json_response({"status": "ok", "results": results})

        except Exception as e:
            logger.error(f"Error setting ZHA motion settings: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)

    async def create_switch(self, request: Request) -> Response:
        """Create a new switch configuration."""
        try:
            data = await request.json()

            switch_id = data.get("id")
            if not switch_id:
                return web.json_response({"error": "Switch ID is required"}, status=400)

            name = data.get("name", f"Switch ({switch_id[-8:]})")
            switch_type = data.get("type", "hue_dimmer")

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
                magic_buttons=data.get("magic_buttons", {}),
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

            # Update magic buttons if provided
            magic_buttons = data.get("magic_buttons", existing.magic_buttons)

            # Preserve device_id (or update if provided)
            device_id = data.get("device_id", existing.device_id)

            # Create updated config
            switch_config = switches.SwitchConfig(
                id=switch_id,
                name=name,
                type=switch_type,
                scopes=scopes,
                magic_buttons=magic_buttons,
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
