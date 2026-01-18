#!/usr/bin/env python3
"""Web server for Home Assistant ingress - Light Designer interface."""

import asyncio
import json
import logging
import math
import os
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
from brain import (
    CircadianLight,
    Config,
    AreaState,
    DEFAULT_MAX_DIM_STEPS,
    calculate_dimming_step,
    get_circadian_lighting,
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
        # In Home Assistant, /data directory exists. In dev, use local directory
        if os.path.exists("/data"):
            # Running in Home Assistant
            self.data_dir = "/data"
        else:
            # Running in development - use local .data directory
            self.data_dir = os.path.join(os.path.dirname(__file__), ".data")
            # Create directory if it doesn't exist
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
        
    def setup_routes(self):
        """Set up web routes."""
        # API routes - must handle all ingress prefixes
        self.app.router.add_route('GET', '/{path:.*}/api/config', self.get_config)
        self.app.router.add_route('POST', '/{path:.*}/api/config', self.save_config)
        self.app.router.add_route('GET', '/{path:.*}/api/steps', self.get_step_sequences)
        self.app.router.add_route('GET', '/{path:.*}/api/curve', self.get_curve_data)
        self.app.router.add_route('GET', '/{path:.*}/api/time', self.get_time)
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
        self.app.router.add_get('/api/presets', self.get_presets)
        self.app.router.add_get('/api/sun_times', self.get_sun_times)
        self.app.router.add_get('/health', self.health_check)

        # Live Design API routes
        self.app.router.add_get('/api/areas', self.get_areas)
        self.app.router.add_post('/api/apply-light', self.apply_light)
        self.app.router.add_post('/api/circadian-mode', self.set_circadian_mode)

        # Handle root and any other paths (catch-all must be last)
        self.app.router.add_get('/', self.serve_designer)
        self.app.router.add_get('/{path:.*}', self.serve_designer)
        
    async def serve_designer(self, request: Request) -> Response:
        """Serve the Light Designer HTML page."""
        try:
            # Read the current configuration (merged options + designer overrides)
            config = await self.load_config()
            
            # Read the designer HTML template
            html_path = Path(__file__).parent / "designer.html"
            async with aiofiles.open(html_path, 'r') as f:
                html_content = await f.read()
            
            # Inject current configuration into the HTML
            config_script = f"""
            <script>
            // Load saved configuration
            window.savedConfig = {json.dumps(config)};
            </script>
            """
            
            # Insert the config script before the closing body tag
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
            logger.error(f"Error serving designer page: {e}")
            return web.Response(text=f"Error: {str(e)}", status=500)
    
    async def get_config(self, request: Request) -> Response:
        """Get current curve configuration."""
        try:
            config = await self.load_config()
            return web.json_response(config)
        except Exception as e:
            logger.error(f"Error getting config: {e}")
            return web.json_response({"error": str(e)}, status=500)
    
    async def save_config(self, request: Request) -> Response:
        """Save curve configuration."""
        try:
            data = await request.json()

            # Load existing config
            config = await self.load_config()

            # Update with new curve parameters
            config.update(data)

            # Save to file
            await self.save_config_to_file(config)

            # Trigger refresh of enabled areas via circadian.refresh service
            # This goes through main.py using the same path as the 30s refresh
            # Must use WebSocket since circadian.refresh is not a registered HA service
            refreshed = False
            _, ws_url, token = self._get_ha_api_config()
            if ws_url and token:
                refreshed = await self._call_service_via_websocket(
                    ws_url, token, 'circadian', 'refresh'
                )
                if refreshed:
                    logger.info("Triggered circadian.refresh after config save")
                else:
                    logger.warning("Failed to trigger circadian.refresh")

            return web.json_response({"status": "success", "config": config, "refreshed": refreshed})
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

            return web.json_response({
                "date": date_str,
                "latitude": lat,
                "longitude": lon,
                "sunrise": sun_times.get("sunrise"),
                "sunset": sun_times.get("sunset"),
                "solar_noon": sun_times.get("solar_noon"),
                "solar_midnight": sun_times.get("solar_midnight"),
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
            'warm_night_sunset_start', 'warm_night_sunrise_end',
            'cool_day_target', 'cool_day_fade',
            'cool_day_sunrise_start', 'cool_day_sunset_end',
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

    async def load_config(self) -> dict:
        """Load configuration, merging HA options with designer overrides.

        Order of precedence (later wins):
          defaults -> options.json -> designer_config.json
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
            "warm_night_sunset_start": -60,  # minutes before sunset
            "warm_night_sunrise_end": 60,    # minutes after sunrise
            "warm_night_fade": 60,           # fade duration in minutes

            # Cool during day rule
            "cool_day_enabled": False,
            "cool_day_mode": "all",
            "cool_day_target": 6500,
            "cool_day_sunrise_start": 0,
            "cool_day_sunset_end": 0,
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

        return config
    
    async def save_config_to_file(self, config: dict):
        """Save designer configuration to persistent file distinct from options.json."""
        try:
            async with aiofiles.open(self.designer_file, 'w') as f:
                await f.write(json.dumps(config, indent=2))
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
                            'transition': 0.3,
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
                            'transition': 0.3,
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
                    'transition': 0.3,
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
        When circadian mode is disabled (enabled=False), Live Design becomes active
        and we fetch light capabilities for that area.
        """
        try:
            data = await request.json()
            area_id = data.get('area_id')
            enabled = data.get('enabled', True)

            if not area_id:
                return web.json_response(
                    {'error': 'area_id is required'},
                    status=400
                )

            state.set_enabled(area_id, enabled)

            if not enabled:
                # Live Design is starting - fetch light capabilities for this area
                rest_url, ws_url, token = self._get_ha_api_config()
                if ws_url and token:
                    color_lights, ct_lights = await self._fetch_area_light_capabilities(ws_url, token, area_id)
                    self.live_design_area = area_id
                    self.live_design_color_lights = color_lights
                    self.live_design_ct_lights = ct_lights
                    logger.info(f"[Live Design] Started for area {area_id}: {len(color_lights)} color, {len(ct_lights)} CT-only")
                else:
                    logger.warning("[Live Design] Cannot fetch capabilities - no HA API config")
                    self.live_design_area = area_id
                    self.live_design_color_lights = []
                    self.live_design_ct_lights = []
            else:
                # Live Design is ending - clear cache
                if self.live_design_area == area_id:
                    logger.info(f"[Live Design] Ended for area {area_id}")
                    self.live_design_area = None
                    self.live_design_color_lights = []
                    self.live_design_ct_lights = []

            logger.info(f"[Live Design] Circadian mode {'enabled' if enabled else 'disabled'} for area {area_id}")

            return web.json_response({'status': 'ok', 'enabled': enabled})
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
