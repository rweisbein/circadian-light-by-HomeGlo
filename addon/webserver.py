#!/usr/bin/env python3
"""Web server for Home Assistant ingress - Light Designer interface."""

import asyncio
import json
import logging
import math
import os
import tempfile
import time
from typing import Any, Dict, List, Optional
from aiohttp import web, ClientSession
from aiohttp.web import Request, Response
import websockets
import aiofiles
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from astral import LocationInfo
from astral.sun import sun, elevation as solar_elevation

import state
import switches
import glozone
import glozone_state
import lux_tracker
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
    apply_light_filter_pipeline,
)

logger = logging.getLogger(__name__)

# Webhook for unsupported-device reports — Cloudflare Worker that files
# submissions as GitHub issues in rweisbein/device-requests.
HOMEGLO_REPORT_WEBHOOK_URL = "https://homeglo-device-reports.rweisbein.workers.dev"


def _get_addon_version() -> str:
    """Return addon version. Prefers ADDON_VERSION env var (set by
    Dockerfile from the build arg); falls back to reading config.yaml
    for local development. Cached after first call.
    """
    global _ADDON_VERSION_CACHE
    if _ADDON_VERSION_CACHE is not None:
        return _ADDON_VERSION_CACHE
    env_val = os.environ.get("ADDON_VERSION")
    if env_val:
        _ADDON_VERSION_CACHE = env_val
        return env_val
    try:
        config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
        with open(config_path) as f:
            for line in f:
                if line.startswith("version:"):
                    val = line.split(":", 1)[1].strip().strip('"').strip("'")
                    _ADDON_VERSION_CACHE = val
                    return val
    except Exception:
        pass
    _ADDON_VERSION_CACHE = "unknown"
    return _ADDON_VERSION_CACHE


_ADDON_VERSION_CACHE: Optional[str] = None


def _get_channel() -> str:
    """Return release channel ('dev', 'beta', or 'main'). Read once
    from addon/.channel; defaults to 'main' when missing."""
    global _CHANNEL_CACHE
    if _CHANNEL_CACHE is not None:
        return _CHANNEL_CACHE
    try:
        path = os.path.join(os.path.dirname(__file__), ".channel")
        with open(path) as f:
            val = f.read().strip().lower()
            if val in ("dev", "beta", "main"):
                _CHANNEL_CACHE = val
                return val
    except Exception:
        pass
    _CHANNEL_CACHE = "main"
    return _CHANNEL_CACHE


_CHANNEL_CACHE: Optional[str] = None


def calculate_step_sequence(
    current_hour: float, action: str, max_steps: int, config: dict
) -> list:
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
    latitude = config.get("latitude")
    longitude = config.get("longitude")
    timezone = config.get("timezone")

    if not latitude or not longitude or not timezone:
        logger.error("Missing location data in config")
        return steps

    # Use the current date but calculate proper solar times
    try:
        tzinfo = ZoneInfo(timezone)
    except:
        tzinfo = ZoneInfo("UTC")

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
                    latitude=config.get("latitude"),
                    longitude=config.get("longitude"),
                    timezone=config.get("timezone"),
                    current_time=adjusted_time,
                    config=config,
                )
                steps.append(
                    {
                        "hour": current_hour,
                        "brightness": lighting_values["brightness"],
                        "kelvin": lighting_values["kelvin"],
                        "rgb": lighting_values.get("rgb", [255, 255, 255]),
                    }
                )
            else:
                # Calculate the next step
                result = calculate_dimming_step(
                    current_time=adjusted_time,
                    action=action,
                    latitude=config.get("latitude"),
                    longitude=config.get("longitude"),
                    timezone=config.get("timezone"),
                    max_steps=max_steps,
                    min_color_temp=config.get("min_color_temp", 500),
                    max_color_temp=config.get("max_color_temp", 6500),
                    min_brightness=config.get("min_brightness", 1),
                    max_brightness=config.get("max_brightness", 100),
                    config=config,
                )

                # Check if we've reached a boundary (no change)
                if abs(result["time_offset_minutes"]) < 0.1:
                    break

                # Apply the time offset
                adjusted_time += timedelta(minutes=result["time_offset_minutes"])

                # Convert back to clock hour (0-24 scale)
                new_hour = adjusted_time.hour + adjusted_time.minute / 60.0

                steps.append(
                    {
                        "hour": new_hour,
                        "brightness": result["brightness"],
                        "kelvin": result["kelvin"],
                        "rgb": result.get("rgb", [255, 255, 255]),
                    }
                )

                # Update for next iteration
                current_hour = new_hour

    except Exception as e:
        logger.error(f"Error calculating step sequence: {e}")
        logger.error(f"Config: {config}")
        logger.error(
            f"Current hour: {current_hour}, action: {action}, max_steps: {max_steps}"
        )
        # Return at least the first step if possible
        if not steps:
            try:
                # Try to get just the current position without stepping
                lighting_values = get_circadian_lighting(
                    latitude=config.get("latitude"),
                    longitude=config.get("longitude"),
                    timezone=config.get("timezone"),
                    current_time=adjusted_time,
                    config=config,
                )
                steps.append(
                    {
                        "hour": current_hour,
                        "brightness": lighting_values["brightness"],
                        "kelvin": lighting_values["kelvin"],
                        "rgb": lighting_values.get("rgb", [255, 255, 255]),
                    }
                )
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
        latitude = config.get("latitude", 35.0)
        longitude = config.get("longitude", -78.6)
        timezone = config.get("timezone", "US/Eastern")
        month = config.get("month", 6)  # Test month for UI

        # Create timezone info
        try:
            tzinfo = ZoneInfo(timezone)
        except:
            tzinfo = ZoneInfo("UTC")

        # Use current date but for the specified test month
        today = datetime.now(tzinfo).replace(
            month=month, day=15
        )  # Mid-month for consistency
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
        base_time = datetime.now(tzinfo).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

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
                min_color_temp=config.get("min_color_temp", 500),
                max_color_temp=config.get("max_color_temp", 6500),
                min_brightness=config.get("min_brightness", 1),
                max_brightness=config.get("max_brightness", 100),
                config=config,
            )

            brightness = lighting_values["brightness"]
            cct = lighting_values["kelvin"]
            rgb = lighting_values.get("rgb", [255, 255, 255])

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
            if "sunrise" in solar_events and solar_events["sunrise"]:
                sunrise_hour = (
                    solar_events["sunrise"].hour + solar_events["sunrise"].minute / 60.0
                )

            if "sunset" in solar_events and solar_events["sunset"]:
                sunset_hour = (
                    solar_events["sunset"].hour + solar_events["sunset"].minute / 60.0
                )
        except:
            pass

        return {
            "hours": hours,
            "bris": brightness_values,
            "ccts": cct_values,
            "sunPower": sun_power_values,
            "morn": {
                "hours": morning_hours,
                "bris": morning_brightness,
                "ccts": morning_cct,
            },
            "eve": {
                "hours": evening_hours,
                "bris": evening_brightness,
                "ccts": evening_cct,
            },
            "solar": {
                "sunrise": sunrise_hour,
                "sunset": sunset_hour,
                "solarNoon": solar_noon_hour,
                "solarMidnight": solar_midnight_hour,
            },
        }

    except Exception as e:
        logger.error(f"Error generating curve data: {e}")
        # Return minimal valid structure on error
        return {
            "hours": [0, 12, 24],
            "bris": [1, 100, 1],
            "ccts": [500, 6500, 500],
            "sunPower": [0, 300, 0],
            "morn": {"hours": [0, 12], "bris": [1, 100], "ccts": [500, 6500]},
            "eve": {"hours": [12, 24], "bris": [100, 1], "ccts": [6500, 500]},
            "solar": {"sunrise": 6, "sunset": 18, "solarNoon": 12, "solarMidnight": 0},
        }


LIVE_DESIGN_TIMEOUT_SEC = 60
LIVE_DESIGN_WATCHER_INTERVAL_SEC = 15


class LightDesignerServer:
    """Web server for the Light Designer ingress interface."""

    def __init__(self, port: int = 8099):
        self.port = port
        self.app = web.Application()
        self.setup_routes()
        self.client = None  # Set by main.py after client is created

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
            logger.info(
                f"Development mode: using {self.data_dir} for configuration storage"
            )

        # Set file paths based on data directory
        self.options_file = os.path.join(self.data_dir, "options.json")
        self.designer_file = os.path.join(self.data_dir, "designer_config.json")

        # Live Design capability cache (one area at a time)
        # Populated when Live Design is enabled for an area
        self.live_design_area: str = None  # Currently active Live Design area
        self.live_design_color_lights: list = []  # Color-capable lights in area
        self.live_design_ct_lights: list = []  # CT-only lights in area
        self.live_design_saved_states: dict = (
            {}
        )  # Saved light states to restore when ending
        # Heartbeat watchdog — abandoned browser safety net.
        # Browser pings /api/live-design/heartbeat every ~30s; the watcher
        # ends Live Design if no ping arrives for LIVE_DESIGN_TIMEOUT_SEC.
        self.live_design_started_at: float = 0.0
        self.live_design_last_heartbeat: float = 0.0
        self._live_design_watcher_task = None

        # Areas cache - populated once on first request, refreshed by sync-devices
        self.cached_areas_list: list = (
            None  # List of {area_id, name} for areas with lights
        )

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
                    logger.info(
                        f"Migrated {filename} from {old_data_dir} to {self.data_dir}"
                    )
                except Exception as e:
                    logger.warning(f"Failed to migrate {filename}: {e}")

    def setup_routes(self):
        """Set up web routes."""
        # API routes - must handle all ingress prefixes
        self.app.router.add_route("GET", "/{path:.*}/api/config", self.get_config)
        self.app.router.add_route("POST", "/{path:.*}/api/config", self.save_config)
        self.app.router.add_route(
            "GET", "/{path:.*}/api/steps", self.get_step_sequences
        )
        self.app.router.add_route("GET", "/{path:.*}/api/curve", self.get_curve_data)
        self.app.router.add_route("GET", "/{path:.*}/api/time", self.get_time)
        self.app.router.add_route(
            "GET", "/{path:.*}/api/zone-states", self.get_zone_states
        )
        self.app.router.add_route("GET", "/{path:.*}/api/presets", self.get_presets)
        self.app.router.add_route("GET", "/{path:.*}/api/sun_times", self.get_sun_times)
        self.app.router.add_route("GET", "/{path:.*}/api/channel", self.get_channel)
        self.app.router.add_route("GET", "/{path:.*}/health", self.health_check)
        self.app.router.add_route("GET", "/{path:.*}/api/areas", self.get_areas)
        self.app.router.add_route(
            "POST", "/{path:.*}/api/apply-light", self.apply_light
        )
        self.app.router.add_route(
            "POST", "/{path:.*}/api/circadian-mode", self.set_circadian_mode
        )

        # Direct API routes (for non-ingress access)
        self.app.router.add_get("/api/config", self.get_config)
        self.app.router.add_post("/api/config", self.save_config)
        self.app.router.add_get("/api/steps", self.get_step_sequences)
        self.app.router.add_get("/api/curve", self.get_curve_data)
        self.app.router.add_get("/api/time", self.get_time)
        self.app.router.add_get("/api/zone-states", self.get_zone_states)
        self.app.router.add_get("/api/presets", self.get_presets)
        self.app.router.add_get("/api/sun_times", self.get_sun_times)
        self.app.router.add_get("/api/channel", self.get_channel)
        self.app.router.add_get("/health", self.health_check)

        # Live Design API routes
        self.app.router.add_get("/api/areas", self.get_areas)
        self.app.router.add_route(
            "GET", "/{path:.*}/api/area-status", self.get_area_status
        )
        self.app.router.add_get("/api/area-status", self.get_area_status)
        self.app.router.add_route(
            "POST", "/{path:.*}/api/refresh-outdoor", self.refresh_outdoor
        )
        self.app.router.add_post("/api/refresh-outdoor", self.refresh_outdoor)
        self.app.router.add_route(
            "GET", "/{path:.*}/api/area-settings/{area_id}", self.get_area_settings
        )
        self.app.router.add_route(
            "POST", "/{path:.*}/api/area-settings/{area_id}", self.save_area_settings
        )
        self.app.router.add_get("/api/area-settings/{area_id}", self.get_area_settings)
        self.app.router.add_post(
            "/api/area-settings/{area_id}", self.save_area_settings
        )
        self.app.router.add_post("/api/apply-light", self.apply_light)
        self.app.router.add_post("/api/circadian-mode", self.set_circadian_mode)
        # Live Design heartbeat — browser pings ~30s while page is open;
        # watcher in start_serving ends Live Design if pings stop.
        self.app.router.add_route(
            "POST",
            "/{path:.*}/api/live-design/heartbeat",
            self.live_design_heartbeat,
        )
        self.app.router.add_post(
            "/api/live-design/heartbeat", self.live_design_heartbeat
        )

        # GloZone API routes - Zones CRUD
        # Reorder routes MUST be registered before {name} wildcard routes
        self.app.router.add_route(
            "PUT", "/{path:.*}/api/glozones/reorder", self.reorder_glozones
        )
        self.app.router.add_put("/api/glozones/reorder", self.reorder_glozones)
        self.app.router.add_route("GET", "/{path:.*}/api/glozones", self.get_glozones)
        self.app.router.add_route(
            "POST", "/{path:.*}/api/glozones", self.create_glozone
        )
        self.app.router.add_route(
            "PUT",
            "/{path:.*}/api/glozones/{name}/reorder-areas",
            self.reorder_zone_areas,
        )
        self.app.router.add_route(
            "PUT",
            "/{path:.*}/api/glozones/{name}/settings",
            self.update_glozone_settings,
        )
        self.app.router.add_route(
            "PUT", "/{path:.*}/api/glozones/{name}", self.update_glozone
        )
        self.app.router.add_route(
            "DELETE", "/{path:.*}/api/glozones/{name}", self.delete_glozone
        )
        self.app.router.add_route(
            "POST", "/{path:.*}/api/glozones/{name}/areas", self.add_area_to_zone
        )
        self.app.router.add_route(
            "DELETE",
            "/{path:.*}/api/glozones/{name}/areas/{area_id}",
            self.remove_area_from_zone,
        )
        self.app.router.add_get("/api/glozones", self.get_glozones)
        self.app.router.add_post("/api/glozones", self.create_glozone)
        self.app.router.add_put(
            "/api/glozones/{name}/reorder-areas", self.reorder_zone_areas
        )
        self.app.router.add_put(
            "/api/glozones/{name}/settings", self.update_glozone_settings
        )
        self.app.router.add_put("/api/glozones/{name}", self.update_glozone)
        self.app.router.add_delete("/api/glozones/{name}", self.delete_glozone)
        self.app.router.add_post("/api/glozones/{name}/areas", self.add_area_to_zone)
        self.app.router.add_delete(
            "/api/glozones/{name}/areas/{area_id}", self.remove_area_from_zone
        )
        self.app.router.add_route(
            "DELETE",
            "/{path:.*}/api/areas/{area_id}/purge",
            self.purge_area_from_config,
        )
        self.app.router.add_delete(
            "/api/areas/{area_id}/purge", self.purge_area_from_config
        )

        # Moments API routes
        self.app.router.add_route("GET", "/{path:.*}/api/moments", self.get_moments)
        self.app.router.add_route("POST", "/{path:.*}/api/moments", self.create_moment)
        self.app.router.add_route(
            "GET", "/{path:.*}/api/moments/{moment_id}", self.get_moment
        )
        self.app.router.add_route(
            "PUT", "/{path:.*}/api/moments/{moment_id}", self.update_moment
        )
        self.app.router.add_route(
            "DELETE", "/{path:.*}/api/moments/{moment_id}", self.delete_moment
        )
        self.app.router.add_get("/api/moments", self.get_moments)
        self.app.router.add_post("/api/moments", self.create_moment)
        self.app.router.add_get("/api/moments/{moment_id}", self.get_moment)
        self.app.router.add_put("/api/moments/{moment_id}", self.update_moment)
        self.app.router.add_delete("/api/moments/{moment_id}", self.delete_moment)
        self.app.router.add_route(
            "POST",
            "/{path:.*}/api/moments/{moment_id}/run",
            self.run_moment,
        )
        self.app.router.add_post("/api/moments/{moment_id}/run", self.run_moment)

        # GloZone API routes - Actions
        self.app.router.add_route(
            "POST", "/{path:.*}/api/glozone/glo-up", self.handle_glo_up
        )
        self.app.router.add_route(
            "POST", "/{path:.*}/api/glozone/glo-down", self.handle_glo_down
        )
        self.app.router.add_route(
            "POST", "/{path:.*}/api/glozone/glo-reset", self.handle_glo_reset
        )
        self.app.router.add_post("/api/glozone/glo-up", self.handle_glo_up)
        self.app.router.add_post("/api/glozone/glo-down", self.handle_glo_down)
        self.app.router.add_post("/api/glozone/glo-reset", self.handle_glo_reset)

        # Area action API route
        self.app.router.add_route(
            "POST", "/{path:.*}/api/area/action", self.handle_area_action
        )
        self.app.router.add_post("/api/area/action", self.handle_area_action)

        # Slider preview API route
        self.app.router.add_route(
            "GET",
            "/{path:.*}/api/area/slider-preview",
            self.get_slider_preview,
        )
        self.app.router.add_get("/api/area/slider-preview", self.get_slider_preview)

        # Zone action API route
        self.app.router.add_route(
            "POST", "/{path:.*}/api/zone/action", self.handle_zone_action
        )
        self.app.router.add_post("/api/zone/action", self.handle_zone_action)

        # Manual sync endpoint
        self.app.router.add_route(
            "POST", "/{path:.*}/api/sync-devices", self.handle_sync_devices
        )
        self.app.router.add_post("/api/sync-devices", self.handle_sync_devices)

        # Controls API routes (new unified endpoint)
        self.app.router.add_route("GET", "/{path:.*}/api/controls", self.get_controls)
        self.app.router.add_route(
            "POST",
            "/{path:.*}/api/controls/{control_id}/configure",
            self.configure_control,
        )
        self.app.router.add_route(
            "DELETE",
            "/{path:.*}/api/controls/{control_id}/configure",
            self.remove_control_config,
        )
        self.app.router.add_route(
            "GET", "/{path:.*}/api/area-lights", self.get_area_lights
        )
        self.app.router.add_get("/api/controls", self.get_controls)
        self.app.router.add_get("/api/devices/search", self.search_devices)
        self.app.router.add_route(
            "GET", "/{path:.*}/api/devices/search", self.search_devices
        )
        self.app.router.add_post("/api/controls/add", self.add_control_source)
        self.app.router.add_route(
            "POST", "/{path:.*}/api/controls/add", self.add_control_source
        )
        self.app.router.add_post("/api/devices/report", self.report_device)
        self.app.router.add_route(
            "POST", "/{path:.*}/api/devices/report", self.report_device
        )
        self.app.router.add_post(
            "/api/controls/{control_id}/configure", self.configure_control
        )
        self.app.router.add_delete(
            "/api/controls/{control_id}/configure", self.remove_control_config
        )
        self.app.router.add_route(
            "GET",
            "/{path:.*}/api/controls/refresh",
            self.get_controls_refresh,
        )
        self.app.router.add_get("/api/controls/refresh", self.get_controls_refresh)
        self.app.router.add_get("/api/area-lights", self.get_area_lights)
        self.app.router.add_route(
            "POST", "/{path:.*}/api/flash-light", self.flash_light
        )
        self.app.router.add_post("/api/flash-light", self.flash_light)

        # ZHA motion sensor settings API routes
        self.app.router.add_route(
            "GET",
            "/{path:.*}/api/controls/{device_id}/zha-settings",
            self.get_zha_motion_settings,
        )
        self.app.router.add_route(
            "POST",
            "/{path:.*}/api/controls/{device_id}/zha-settings",
            self.set_zha_motion_settings,
        )
        self.app.router.add_get(
            "/api/controls/{device_id}/zha-settings", self.get_zha_motion_settings
        )
        self.app.router.add_post(
            "/api/controls/{device_id}/zha-settings", self.set_zha_motion_settings
        )

        # Legacy switches API routes (keeping for backwards compat)
        self.app.router.add_route("GET", "/{path:.*}/api/switches", self.get_switches)
        self.app.router.add_route("POST", "/{path:.*}/api/switches", self.create_switch)
        self.app.router.add_route(
            "PUT", "/{path:.*}/api/switches/{switch_id}", self.update_switch
        )
        self.app.router.add_route(
            "DELETE", "/{path:.*}/api/switches/{switch_id}", self.delete_switch
        )
        self.app.router.add_route(
            "GET", "/{path:.*}/api/switch-types", self.get_switch_types
        )
        self.app.router.add_get("/api/switches", self.get_switches)
        self.app.router.add_post("/api/switches", self.create_switch)
        self.app.router.add_put("/api/switches/{switch_id}", self.update_switch)
        self.app.router.add_delete("/api/switches/{switch_id}", self.delete_switch)
        self.app.router.add_get("/api/switch-types", self.get_switch_types)

        # Switchmap API routes
        self.app.router.add_route("GET", "/{path:.*}/api/switchmap", self.get_switchmap)
        self.app.router.add_route(
            "POST", "/{path:.*}/api/switchmap", self.save_switchmap
        )
        self.app.router.add_route(
            "GET", "/{path:.*}/api/switchmap/actions", self.get_switchmap_actions
        )
        self.app.router.add_get("/api/switchmap", self.get_switchmap)
        self.app.router.add_post("/api/switchmap", self.save_switchmap)
        self.app.router.add_get("/api/switchmap/actions", self.get_switchmap_actions)

        # Page routes - specific pages first, then catch-all
        # Light filters API
        self.app.router.add_route(
            "GET", "/{path:.*}/api/light-filters", self.get_light_filters
        )
        self.app.router.add_route(
            "POST",
            "/{path:.*}/api/light-filters/area-brightness",
            self.save_area_brightness,
        )
        self.app.router.add_route(
            "POST", "/{path:.*}/api/light-filters/light-filter", self.save_light_filter
        )
        self.app.router.add_route(
            "POST", "/{path:.*}/api/light-filters/reassign-preset", self.reassign_preset
        )
        self.app.router.add_get("/api/light-filters", self.get_light_filters)
        self.app.router.add_post(
            "/api/light-filters/area-brightness", self.save_area_brightness
        )
        self.app.router.add_post(
            "/api/light-filters/light-filter", self.save_light_filter
        )
        self.app.router.add_route(
            "POST", "/{path:.*}/api/light-filters/bulk", self.save_light_filters_bulk
        )
        self.app.router.add_post(
            "/api/light-filters/bulk", self.save_light_filters_bulk
        )
        self.app.router.add_post(
            "/api/light-filters/reassign-preset", self.reassign_preset
        )
        self.app.router.add_get("/api/sensors", self.get_sensors)
        self.app.router.add_route("GET", "/{path:.*}/api/sensors", self.get_sensors)

        # Outdoor brightness API routes
        self.app.router.add_post("/api/outdoor-override", self.set_outdoor_override)
        self.app.router.add_route(
            "POST", "/{path:.*}/api/outdoor-override", self.set_outdoor_override
        )
        self.app.router.add_delete("/api/outdoor-override", self.clear_outdoor_override)
        self.app.router.add_route(
            "DELETE", "/{path:.*}/api/outdoor-override", self.clear_outdoor_override
        )
        self.app.router.add_get("/api/outdoor-status", self.get_outdoor_status)
        self.app.router.add_route(
            "GET", "/{path:.*}/api/outdoor-status", self.get_outdoor_status
        )

        # Per-zone schedule override API routes
        self.app.router.add_put(
            "/api/glozones/{name}/schedule-override",
            self.set_schedule_override,
        )
        self.app.router.add_route(
            "PUT",
            "/{path:.*}/api/glozones/{name}/schedule-override",
            self.set_schedule_override,
        )
        self.app.router.add_delete(
            "/api/glozones/{name}/schedule-override",
            self.clear_schedule_override,
        )
        self.app.router.add_route(
            "DELETE",
            "/{path:.*}/api/glozones/{name}/schedule-override",
            self.clear_schedule_override,
        )
        self.app.router.add_get(
            "/api/glozones/{name}/schedule-override",
            self.get_schedule_override,
        )
        self.app.router.add_route(
            "GET",
            "/{path:.*}/api/glozones/{name}/schedule-override",
            self.get_schedule_override,
        )
        self.app.router.add_get(
            "/api/glozones/{name}/next-times",
            self.get_zone_next_times,
        )
        self.app.router.add_route(
            "GET",
            "/{path:.*}/api/glozones/{name}/next-times",
            self.get_zone_next_times,
        )
        self.app.router.add_post("/api/learn-baselines", self.learn_baselines)
        self.app.router.add_route(
            "POST", "/{path:.*}/api/learn-baselines", self.learn_baselines
        )

        # With ingress path prefix
        self.app.router.add_route("GET", "/{path:.*}/switchmap", self.serve_switchmap)
        self.app.router.add_route(
            "GET", "/{path:.*}/control/{control_id}", self.serve_control_detail
        )
        self.app.router.add_route("GET", "/{path:.*}/switches", self.serve_switches)
        self.app.router.add_route(
            "GET", "/{path:.*}/zone-design/{zone_name}", self.serve_zone_design
        )
        self.app.router.add_route(
            "GET",
            "/{path:.*}/rhythm/{rhythm_name}",
            self.redirect_rhythm_to_zone_design,
        )
        self.app.router.add_route(
            "GET", "/{path:.*}/rhythm", self.redirect_rhythm_to_home
        )
        self.app.router.add_route(
            "GET", "/{path:.*}/glo/{glo_name}", self.redirect_rhythm_to_zone_design
        )
        self.app.router.add_route("GET", "/{path:.*}/glo", self.redirect_rhythm_to_home)
        self.app.router.add_route(
            "GET", "/{path:.*}/area/{area_id}", self.serve_area_detail
        )
        self.app.router.add_route(
            "GET", "/{path:.*}/zone/{zone_name}", self.serve_zone_detail
        )
        self.app.router.add_route("GET", "/{path:.*}/tune", self.serve_tune)
        self.app.router.add_route("GET", "/{path:.*}/settings", self.serve_settings)
        self.app.router.add_route(
            "GET", "/{path:.*}/moment/{moment_id}", self.serve_moment_detail
        )
        self.app.router.add_route("GET", "/{path:.*}/moments", self.serve_moments)
        self.app.router.add_route("GET", "/{path:.*}/", self.serve_home)
        # Without ingress path prefix
        self.app.router.add_get("/control/{control_id}", self.serve_control_detail)
        self.app.router.add_get("/switches", self.serve_switches)
        self.app.router.add_get("/switchmap", self.serve_switchmap)
        self.app.router.add_get("/zone-design/{zone_name}", self.serve_zone_design)
        self.app.router.add_get(
            "/rhythm/{rhythm_name}", self.redirect_rhythm_to_zone_design
        )
        self.app.router.add_get("/rhythm", self.redirect_rhythm_to_home)
        self.app.router.add_get("/glo/{glo_name}", self.redirect_rhythm_to_zone_design)
        self.app.router.add_get("/glo", self.redirect_rhythm_to_home)
        self.app.router.add_get("/area/{area_id}", self.serve_area_detail)
        self.app.router.add_get("/zone/{zone_name}", self.serve_zone_detail)
        self.app.router.add_get("/tune", self.serve_tune)
        self.app.router.add_get("/settings", self.serve_settings)
        self.app.router.add_get("/moment/{moment_id}", self.serve_moment_detail)
        self.app.router.add_get("/moments", self.serve_moments)
        self.app.router.add_get("/", self.serve_home)
        # Legacy routes
        self.app.router.add_get("/designer", self.serve_home)
        self.app.router.add_get("/areas", self.serve_home)
        self.app.router.add_route("GET", "/{path:.*}/areas", self.serve_home)

    async def serve_page(self, page_name: str, extra_data: dict = None) -> Response:
        """Generic page serving function."""
        try:
            config = await self.load_config()

            html_path = Path(__file__).parent / f"{page_name}.html"
            if not html_path.exists():
                logger.error(f"Page not found: {page_name}.html")
                return web.Response(text=f"Page not found: {page_name}", status=404)

            async with aiofiles.open(html_path, "r") as f:
                html_content = await f.read()

            # Inline shared.js content (avoids routing issues with ingress paths)
            shared_js_path = Path(__file__).parent / "shared.js"
            if shared_js_path.exists():
                async with aiofiles.open(shared_js_path, "r") as f:
                    shared_js_content = await f.read()
                # Replace external script reference with inline script (simple string replace)
                inline_script = f"<script>\n{shared_js_content}\n</script>"
                original_len = len(html_content)
                # Try multiple possible formats
                for pattern in [
                    '<script src="./shared.js"></script>',
                    '<script src="shared.js"></script>',
                    "<script src='./shared.js'></script>",
                    "<script src='shared.js'></script>",
                ]:
                    if pattern in html_content:
                        html_content = html_content.replace(pattern, inline_script)
                        break

            # Inline icon.png as base64 data URI (avoids routing issues with ingress paths)
            icon_path = Path(__file__).parent / "icon.png"
            if icon_path.exists() and 'src="./icon.png"' in html_content:
                import base64

                icon_b64 = base64.b64encode(icon_path.read_bytes()).decode()
                html_content = html_content.replace(
                    'src="./icon.png"',
                    f'src="data:image/png;base64,{icon_b64}"',
                )

            # Substitute HA location into config when use_ha_location is true
            if config.get("use_ha_location", True):
                config["latitude"] = float(
                    os.getenv("HASS_LATITUDE", config.get("latitude", 35.0))
                )
                config["longitude"] = float(
                    os.getenv("HASS_LONGITUDE", config.get("longitude", -78.6))
                )
                config["timezone"] = os.getenv(
                    "HASS_TIME_ZONE", config.get("timezone", "US/Eastern")
                )

            # Build injected data
            inject_data = {"config": config}
            if extra_data:
                inject_data.update(extra_data)

            config_script = f"""
            <script>
            window.circadianData = {json.dumps(inject_data)};
            </script>
            """

            html_content = html_content.replace("</body>", f"{config_script}</body>")

            return web.Response(
                text=html_content,
                content_type="text/html",
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                },
            )
        except Exception as e:
            logger.error(f"Error serving {page_name} page: {e}")
            return web.Response(text=f"Error: {str(e)}", status=500)

    async def serve_home(self, request: Request) -> Response:
        """Serve the Home page (areas)."""
        return await self.serve_page("areas")

    async def serve_zone_design(self, request: Request) -> Response:
        """Serve the Zone Design page (rhythm settings for a zone)."""
        zone_name = request.match_info.get("zone_name")
        return await self.serve_page("rhythm-design", {"selectedZoneName": zone_name})

    async def redirect_rhythm_to_zone_design(self, request: Request) -> Response:
        """Legacy redirect: /rhythm/{name} or /glo/{name} → /zone-design/{name}."""
        name = request.match_info.get("rhythm_name") or request.match_info.get(
            "glo_name", ""
        )
        path = request.path
        # Replace the old path segment with zone-design
        for old_prefix in [f"/rhythm/{name}", f"/glo/{name}"]:
            if old_prefix in path:
                new_path = path.replace(old_prefix, f"/zone-design/{name}")
                raise web.HTTPFound(new_path)
        raise web.HTTPFound("/")

    async def redirect_rhythm_to_home(self, request: Request) -> Response:
        """Legacy redirect: /rhythm or /glo → home page."""
        path = request.path
        for old in ["/rhythm", "/glo"]:
            if old in path:
                new_path = path.replace(old, "/")
                raise web.HTTPFound(new_path)
        raise web.HTTPFound("/")

    async def serve_area_detail(self, request: Request) -> Response:
        """Serve the Area detail page."""
        area_id = request.match_info.get("area_id")
        return await self.serve_page("area", {"selectedAreaId": area_id})

    async def serve_zone_detail(self, request: Request) -> Response:
        """Serve the Zone detail page (unified with rhythm-design)."""
        zone_name = request.match_info.get("zone_name")
        return await self.serve_page("rhythm-design", {"selectedZoneName": zone_name})

    async def serve_tune(self, request: Request) -> Response:
        """Serve the Tune page."""
        return await self.serve_page("tune")

    async def serve_settings(self, request: Request) -> Response:
        """Serve the Settings page."""
        return await self.serve_page("settings")

    async def get_light_filters(self, request: Request) -> Response:
        """Get all data for the Filters page.

        Returns zones, areas, lights with names, filter assignments,
        brightness factors, and presets in one call.
        """
        try:
            glozones = glozone.get_glozones()
            presets = glozone.get_light_filter_presets()
            off_threshold = glozone.get_off_threshold()

            # Build zone/area structure with filter data
            zones = {}
            for zone_name, zone_config in glozones.items():
                zone_areas = []
                for area in zone_config.get("areas", []):
                    if isinstance(area, dict):
                        area_id = area.get("id")
                        area_name = area.get("name", area_id)
                    else:
                        area_id = area
                        area_name = area
                    if not area_id:
                        continue
                    is_boosted = state.is_boosted(area_id)
                    boost_brightness = (
                        state.get_area(area_id).get("boost_brightness", 0)
                        if is_boosted
                        else 0
                    )
                    # Compute decayed brightness override
                    effective_bri_override = 0
                    area_st = state.get_area(area_id)
                    bri_override_raw = area_st.get("brightness_override")
                    if bri_override_raw is not None:
                        from brain import CircadianLight, Config, compute_override_decay

                        preset_config = glozone.get_effective_config_for_zone(zone_name)
                        brain_config = Config.from_dict(preset_config)
                        now = datetime.now()
                        hour = now.hour + now.minute / 60 + now.second / 3600
                        in_ascend, h48, t_ascend, t_descend, _ = (
                            CircadianLight.get_phase_info(hour, brain_config)
                        )
                        next_phase = t_descend if in_ascend else t_ascend + 24
                        bri_decay = compute_override_decay(
                            area_st.get("brightness_override_set_at"),
                            h48,
                            next_phase,
                            t_ascend=t_ascend,
                        )
                        effective_bri_override = round(bri_override_raw * bri_decay, 1)
                    zone_areas.append(
                        {
                            "id": area_id,
                            "name": area_name,
                            "brightness_factor": glozone.get_area_brightness_factor(
                                area_id
                            ),
                            "natural_light_exposure": glozone.get_area_natural_light_exposure(
                                area_id
                            ),
                            "light_filters": glozone.get_area_light_filters(area_id),
                            "feedback_target": glozone.get_area_feedback_target(
                                area_id
                            ),
                            "is_on": state.get_is_on(area_id),
                            "last_sent_kelvin": state.get_last_sent_kelvin(area_id),
                            "color_mid": area_st.get("color_mid"),
                            "color_override": area_st.get("color_override"),
                            "color_override_set_at": area_st.get(
                                "color_override_set_at"
                            ),
                            "boosted": is_boosted,
                            "boost_brightness": boost_brightness or 0,
                            "bri_override": effective_bri_override,
                            **self._get_fade_info(area_id),
                        }
                    )
                zone_cfg = glozone.get_zone_config(zone_name)
                zones[zone_name] = {
                    "daylight_fade": zone_cfg.get("daylight_fade", 60),
                    "min_brightness": zone_cfg.get("min_brightness", 1),
                    "max_brightness": zone_cfg.get("max_brightness", 100),
                    "areas": zone_areas,
                }

            # Get light entities per area from client cache
            area_lights = {}
            if self.client:
                for a_id, entities in self.client.area_lights.items():
                    area_lights[a_id] = []
                    for eid in entities:
                        s = self.client.cached_states.get(eid, {})
                        name = s.get("attributes", {}).get("friendly_name", eid)
                        area_lights[a_id].append({"entity_id": eid, "name": name})

            raw_config = glozone.get_config()
            return web.json_response(
                {
                    "outdoor_normalized": lux_tracker.get_outdoor_normalized() or 0.0,
                    "ct_comp_enabled": raw_config.get("ct_comp_enabled", True),
                    "ct_comp_begin": raw_config.get("ct_comp_begin", 1650),
                    "ct_comp_end": raw_config.get("ct_comp_end", 2250),
                    "ct_comp_factor": raw_config.get("ct_comp_factor", 1.7),
                    "zones": zones,
                    "presets": presets,
                    "off_threshold": off_threshold,
                    "area_lights": area_lights,
                }
            )
        except Exception as e:
            logger.error(f"Error getting light filters: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def save_area_brightness(self, request: Request) -> Response:
        """Save brightness factor and/or natural light exposure for an area."""
        try:
            data = await request.json()
            area_id = data.get("area_id")

            if not area_id:
                return web.json_response({"error": "area_id required"}, status=400)

            # Load raw config and find the area entry
            config = await self.load_raw_config()
            glozones = config.get("glozones", {})
            found = False
            for zone_config in glozones.values():
                for area in zone_config.get("areas", []):
                    if isinstance(area, dict) and area.get("id") == area_id:
                        if "brightness_factor" in data:
                            area["brightness_factor"] = round(
                                float(data["brightness_factor"]), 2
                            )
                        if "natural_light_exposure" in data:
                            area["natural_light_exposure"] = round(
                                float(data["natural_light_exposure"]), 2
                            )
                        if "feedback_target" in data:
                            val = data["feedback_target"]
                            if val:
                                area["feedback_target"] = val
                            elif "feedback_target" in area:
                                del area["feedback_target"]
                        found = True
                        break
                if found:
                    break

            if not found:
                return web.json_response(
                    {"error": f"Area {area_id} not found"}, status=404
                )

            await self.save_config_to_file(config)
            glozone.set_config(config)

            if self.client:
                await self.client.handle_config_refresh()
                # Re-sync batch groups — area_factor change affects group membership
                await self.client.sync_batch_groups()

            return web.json_response({"status": "ok"})
        except Exception as e:
            logger.error(f"Error saving area brightness: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def save_light_filter(self, request: Request) -> Response:
        """Save filter assignment for a light entity."""
        try:
            data = await request.json()
            area_id = data.get("area_id")
            entity_id = data.get("entity_id")
            filter_name = data.get("filter", "Standard")

            if not area_id or not entity_id:
                return web.json_response(
                    {"error": "area_id and entity_id required"}, status=400
                )

            config = await self.load_raw_config()
            glozones = config.get("glozones", {})
            found = False
            for zone_config in glozones.values():
                for area in zone_config.get("areas", []):
                    if isinstance(area, dict) and area.get("id") == area_id:
                        if "light_filters" not in area:
                            area["light_filters"] = {}
                        if filter_name == "Standard":
                            area["light_filters"].pop(entity_id, None)
                        else:
                            area["light_filters"][entity_id] = filter_name
                        # Clean up empty dict
                        if not area["light_filters"]:
                            del area["light_filters"]
                        found = True
                        break
                if found:
                    break

            if not found:
                return web.json_response(
                    {"error": f"Area {area_id} not found"}, status=404
                )

            await self.save_config_to_file(config)
            glozone.set_config(config)

            if self.client:
                await self.client.handle_config_refresh()
                # Re-sync ZHA groups — purpose change affects group membership
                await self.client.run_manual_sync()
                logger.info("Device sync triggered after purpose change")

            return web.json_response({"status": "ok"})
        except Exception as e:
            logger.error(f"Error saving light filter: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def save_light_filters_bulk(self, request: Request) -> Response:
        """Save filter assignments for multiple lights in one area.

        Expects JSON: {"area_id": "...", "filters": [{"entity_id": "...", "filter": "..."}, ...]}
        Saves config once, refreshes once, syncs once.
        """
        try:
            data = await request.json()
            area_id = data.get("area_id")
            filters = data.get("filters", [])

            if not area_id or not filters:
                return web.json_response(
                    {"error": "area_id and filters required"}, status=400
                )

            config = await self.load_raw_config()
            glozones = config.get("glozones", {})
            area_cfg = None
            for zone_config in glozones.values():
                for area in zone_config.get("areas", []):
                    if isinstance(area, dict) and area.get("id") == area_id:
                        area_cfg = area
                        break
                if area_cfg:
                    break

            if not area_cfg:
                return web.json_response(
                    {"error": f"Area {area_id} not found"}, status=404
                )

            if "light_filters" not in area_cfg:
                area_cfg["light_filters"] = {}

            for entry in filters:
                entity_id = entry.get("entity_id")
                filter_name = entry.get("filter", "Standard")
                if not entity_id:
                    continue
                if filter_name == "Standard":
                    area_cfg["light_filters"].pop(entity_id, None)
                else:
                    area_cfg["light_filters"][entity_id] = filter_name

            if not area_cfg["light_filters"]:
                area_cfg.pop("light_filters", None)

            await self.save_config_to_file(config)
            glozone.set_config(config)

            if self.client:
                await self.client.handle_config_refresh()
                await self.client.run_manual_sync()
                logger.info(
                    f"Device sync triggered after bulk purpose change "
                    f"({len(filters)} lights in {area_id})"
                )

            return web.json_response({"status": "ok"})
        except Exception as e:
            logger.error(f"Error saving bulk light filters: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def reassign_preset(self, request: Request) -> Response:
        """Reassign all lights from one filter preset to another."""
        try:
            data = await request.json()
            from_preset = data.get("from_preset")
            to_preset = data.get("to_preset", "Standard")

            if not from_preset:
                return web.json_response({"error": "from_preset required"}, status=400)

            config = await self.load_raw_config()
            glozones = config.get("glozones", {})
            reassigned = 0

            for zone_config in glozones.values():
                for area in zone_config.get("areas", []):
                    if not isinstance(area, dict):
                        continue
                    light_filters = area.get("light_filters", {})
                    entities_to_update = [
                        eid
                        for eid, preset in light_filters.items()
                        if preset == from_preset
                    ]
                    for eid in entities_to_update:
                        if to_preset == "Standard":
                            del light_filters[eid]
                        else:
                            light_filters[eid] = to_preset
                        reassigned += 1
                    if not light_filters and "light_filters" in area:
                        del area["light_filters"]

            await self.save_config_to_file(config)
            glozone.set_config(config)

            if reassigned > 0 and self.client:
                await self.client.handle_config_refresh()

            return web.json_response({"status": "ok", "reassigned": reassigned})
        except Exception as e:
            logger.error(f"Error reassigning preset: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def serve_moments(self, request: Request) -> Response:
        """Serve the Moments page."""
        return await self.serve_page("moments")

    async def serve_moment_detail(self, request: Request) -> Response:
        """Serve the Moment detail page."""
        moment_id = request.match_info.get("moment_id")
        return await self.serve_page("moment", {"selectedMomentId": moment_id})

    async def serve_control_detail(self, request: Request) -> Response:
        """Serve the Control detail page."""
        control_id = request.match_info.get("control_id")
        return await self.serve_page("control", {"selectedControlId": control_id})

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

        Handles both legacy flat config and Rhythm Zone format.
        - Flat rhythm settings are merged into the first zone
        - glozones are merged at their level
        - Global settings are merged at top level
        """
        try:
            data = await request.json()

            # Load existing raw config (GloZone format)
            config = await self.load_raw_config()

            # Separate incoming data into categories
            incoming_glozones = data.pop("glozones", None)
            # Legacy: accept circadian_rhythms but ignore it
            data.pop("circadian_rhythms", None)

            if incoming_glozones:
                config["glozones"].update(incoming_glozones)

            # Remaining data could be flat rhythm settings or global settings
            zone_updates = {}
            global_updates = {}

            for key, value in data.items():
                if key in self.RHYTHM_SETTINGS:
                    zone_updates[key] = value
                elif key in self.GLOBAL_SETTINGS:
                    global_updates[key] = value
                # Ignore unknown keys

            # Apply rhythm updates to the first zone
            if zone_updates and config.get("glozones"):
                first_zone_name = list(config["glozones"].keys())[0]
                config["glozones"][first_zone_name].update(zone_updates)
                logger.debug(
                    f"Updated zone '{first_zone_name}' with: {list(zone_updates.keys())}"
                )

            # Apply global updates to top level
            config.update(global_updates)

            # Save the raw config (GloZone format)
            await self.save_config_to_file(config)

            # Update glozone module with new config
            glozone.set_config(config)

            # Re-read lux tracker config (source, sensor, smoothing) without resetting runtime state
            lux_tracker.reload_config(config)

            # Signal periodic updater to pick up new config
            refreshed = False
            if self.client:
                await self.client.handle_config_refresh()
                refreshed = True
                logger.info("Config refresh signaled after config save")

            # Return effective config for backward compatibility
            effective_config = self._get_effective_config(config)
            return web.json_response(
                {
                    "status": "success",
                    "config": effective_config,
                    "refreshed": refreshed,
                }
            )
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
            return web.json_response({"presets": presets, "names": get_preset_names()})
        except Exception as e:
            logger.error(f"Error getting presets: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def get_sun_times(self, request: Request) -> Response:
        """Get sun times for a specific date (for date slider preview)."""
        try:
            from zoneinfo import ZoneInfo

            # Get parameters from query, falling back to HA environment vars
            date_str = request.query.get("date")
            lat = float(
                request.query.get("latitude", os.getenv("HASS_LATITUDE", "35.0"))
            )
            lon = float(
                request.query.get("longitude", os.getenv("HASS_LONGITUDE", "-78.6"))
            )
            timezone = os.getenv("HASS_TIME_ZONE", "US/Eastern")

            try:
                tzinfo = ZoneInfo(timezone)
            except Exception:
                tzinfo = None

            if not date_str:
                # Default to today in local timezone
                now = datetime.now(tzinfo) if tzinfo else datetime.now()
                date_str = now.strftime("%Y-%m-%d")

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

            return web.json_response(
                {
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
                }
            )
        except Exception as e:
            logger.error(f"Error getting sun times: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def get_channel(self, request: Request) -> Response:
        """Return the release channel — 'dev' / 'beta' / 'main'."""
        return web.json_response({"channel": _get_channel()})

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
                min_color_temp=config.get("min_color_temp", 500),
                max_color_temp=config.get("max_color_temp", 6500),
                min_brightness=config.get("min_brightness", 1),
                max_brightness=config.get("max_brightness", 100),
                config=config,
            )

            return web.json_response(
                {
                    "current_time": now.isoformat(),
                    "current_hour": current_hour,
                    "timezone": timezone,
                    "latitude": latitude,
                    "longitude": longitude,
                    "lighting": {
                        "brightness": lighting_values.get("brightness", 0),
                        "kelvin": lighting_values.get("kelvin", 0),
                        "solar_position": lighting_values.get("solar_position", 0),
                    },
                }
            )

        except Exception as e:
            logger.error(f"Error getting time info: {e}")
            return web.json_response(
                {"error": f"Failed to get time info: {e}"}, status=500
            )

    async def get_zone_states(self, request: Request) -> Response:
        """Get current circadian values for each Glo Zone.

        Returns brightness and kelvin for each zone, accounting for:
        - The zone's Glo preset configuration
        - The zone's runtime state (brightness_mid, color_mid, frozen_at from GloUp/GloDown)
        - Solar rules (warm_night, daylight blend) based on actual sun times

        This is per-zone, not per-preset, because two zones can share the same
        Glo but have different runtime states.
        """
        try:
            from zoneinfo import ZoneInfo
            from brain import (
                CircadianLight,
                Config,
                AreaState,
                SunTimes,
                calculate_sun_times,
                compute_daylight_fade_weight,
                DEFAULT_DAYLIGHT_FADE,
            )

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
                date_str = now.strftime("%Y-%m-%d")
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

                # Outdoor data is shared in-memory (main.py seeds lux_tracker from live events)
                outdoor_norm = lux_tracker.get_outdoor_normalized()
                outdoor_source = lux_tracker.get_outdoor_source()
                if outdoor_norm is None:
                    outdoor_norm = 0.0
                    outdoor_source = "none"
                sun_times.outdoor_normalized = outdoor_norm
                sun_times.outdoor_source = outdoor_source
            except Exception as e:
                logger.debug(f"[ZoneStates] Error calculating sun times: {e}")

            # Get zones and rhythms from glozone module (consistent with area-status)
            zones = glozone.get_glozones()

            logger.debug(f"[ZoneStates] Found {len(zones)} zones: {list(zones.keys())}")

            zone_states = {}
            for zone_name, zone_config in zones.items():
                preset_config = glozone.get_effective_config_for_zone(zone_name)
                logger.debug(
                    f"[ZoneStates] Zone '{zone_name}' config keys: {list(preset_config.keys())}"
                )
                logger.debug(
                    f"[ZoneStates] Zone '{zone_name}' min/max bri: {preset_config.get('min_brightness')}/{preset_config.get('max_brightness')}"
                )

                # Get zone runtime state (from GloUp/GloDown adjustments)
                runtime_state = glozone_state.get_zone_state(zone_name)
                logger.debug(
                    f"[ZoneStates] Zone '{zone_name}' runtime_state: {runtime_state}"
                )

                # Build Config from preset using from_dict (handles all fields with defaults)
                brain_config = Config.from_dict(preset_config)
                logger.debug(
                    f"[ZoneStates] Zone '{zone_name}' brain_config: wake={brain_config.wake_time}, bed={brain_config.bed_time}, min_bri={brain_config.min_brightness}, max_bri={brain_config.max_brightness}, warm_night={brain_config.warm_night_enabled}"
                )

                # Build AreaState from zone runtime state
                area_state = AreaState(
                    is_circadian=True,
                    is_on=True,
                    brightness_mid=runtime_state.get("brightness_mid"),
                    color_mid=runtime_state.get("color_mid"),
                    frozen_at=runtime_state.get("frozen_at"),
                    color_override=runtime_state.get("color_override"),
                )
                logger.debug(
                    f"[ZoneStates] Zone '{zone_name}' area_state: brightness_mid={area_state.brightness_mid}, color_mid={area_state.color_mid}, frozen_at={area_state.frozen_at}"
                )

                # Calculate lighting values - use frozen_at if set, otherwise current time
                calc_hour = (
                    area_state.frozen_at if area_state.frozen_at is not None else hour
                )
                result = CircadianLight.calculate_lighting(
                    calc_hour, brain_config, area_state, sun_times=sun_times
                )

                # Compute brightness fade weight for this zone
                zone_daylight_fade = preset_config.get(
                    "daylight_fade", DEFAULT_DAYLIGHT_FADE
                )
                zone_bri_fade_weight = compute_daylight_fade_weight(
                    calc_hour,
                    sun_times.sunrise,
                    sun_times.sunset,
                    zone_daylight_fade,
                )

                zone_states[zone_name] = {
                    "brightness": result.brightness,
                    "kelvin": result.color_temp,
                    "brightness_fade_weight": 1.0,  # Fade applies to color only, not brightness
                    "min_brightness": brain_config.min_brightness,
                    "max_brightness": brain_config.max_brightness,
                    "brightness_sensitivity": preset_config.get(
                        "brightness_sensitivity", 1.0
                    ),
                    "runtime_state": runtime_state,
                    "solar_cache": glozone_state.get_zone_solar_cache(zone_name),
                }
                logger.debug(
                    f"[ZoneStates] Zone '{zone_name}': {result.brightness}% {result.color_temp}K at hour {calc_hour:.2f} "
                    f"(sun_times: sunrise={sun_times.sunrise:.2f}, sunset={sun_times.sunset:.2f})"
                )

            logger.debug(f"[ZoneStates] Returning {len(zone_states)} zone states")
            return web.json_response({"zone_states": zone_states})

        except Exception as e:
            logger.error(f"Error getting zone states: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)

    def apply_query_overrides(self, config: dict, query) -> dict:
        """Apply UI query parameters to a config dict for live previews."""
        # Float parameters (ascend/descend model)
        float_params = [
            "min_color_temp",
            "max_color_temp",
            "min_brightness",
            "max_brightness",
            "ascend_start",
            "descend_start",
            "wake_time",
            "bed_time",
            "latitude",
            "longitude",
            "warm_night_target",
            "warm_night_fade",
            "warm_night_start",
            "warm_night_end",
            "brightness_sensitivity",
            "color_sensitivity",
            "daylight_fade",
        ]

        # Integer parameters
        int_params = [
            "month",
            "wake_speed",
            "bed_speed",
            "max_dim_steps",
            "step_fallback_minutes",
            "daylight_cct",
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
        bool_params = ["warm_night_enabled", "daylight_enabled", "use_ha_location"]
        for param_name in bool_params:
            if param_name in query:
                config[param_name] = query[param_name].lower() in (
                    "true",
                    "1",
                    "yes",
                    "on",
                )

        # String parameters
        string_params = ["activity_preset", "warm_night_mode", "timezone"]
        for param_name in string_params:
            if param_name in query:
                config[param_name] = query[param_name]

        return config

    async def get_step_sequences(self, request: Request) -> Response:
        """Calculate step sequences for visualization."""
        try:
            # Get parameters from query string
            current_hour = float(request.query.get("hour", 12.0))
            max_steps = int(request.query.get("max_steps", 10))

            # Load current configuration
            config = await self.load_config()

            # Apply overrides from UI for live preview
            config = self.apply_query_overrides(config, request.query)

            # Calculate step sequences in both directions
            step_up_sequence = calculate_step_sequence(
                current_hour, "brighten", max_steps, config
            )
            step_down_sequence = calculate_step_sequence(
                current_hour, "dim", max_steps, config
            )

            return web.json_response(
                {
                    "step_up": {"steps": step_up_sequence},
                    "step_down": {"steps": step_down_sequence},
                }
            )

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
        "color_mode",
        "min_color_temp",
        "max_color_temp",
        "min_brightness",
        "max_brightness",
        "ascend_start",
        "descend_start",
        "wake_time",
        "bed_time",
        "wake_speed",
        "bed_speed",
        "wake_alt_time",
        "wake_alt_days",
        "bed_alt_time",
        "bed_alt_days",
        "wake_brightness",
        "bed_brightness",
        "warm_night_enabled",
        "warm_night_mode",
        "warm_night_target",
        "warm_night_start",
        "warm_night_end",
        "warm_night_fade",
        "daylight_enabled",
        "daylight_cct",
        "daylight_start",
        "daylight_end",
        "daylight_fade",
        "color_sensitivity",
        "activity_preset",
        "max_dim_steps",
        "step_fallback_minutes",
    }

    # Settings that are global (not per-rhythm)
    GLOBAL_SETTINGS = {
        "latitude",
        "longitude",
        "timezone",
        "use_ha_location",
        "month",
        "sun_saturation",  # Sun intensity saturation cap (1-100, default 40)
        "sun_saturation_ramp",  # Ramp curve: 'linear' or 'squared' (default squared)
        "turn_on_transition",  # Transition time in tenths of seconds for turn-on operations
        "turn_off_transition",  # Transition time in tenths of seconds for turn-off operations
        "two_step_bri_threshold",  # Min brightness change (%) to trigger 2-step (default 15)
        "two_step_delay",  # Delay between two-step phases in tenths of seconds (default 5 = 500ms)
        "nudge_delay",  # Post-command nudge delay in tenths of seconds (default 10 = 1.0s, 0 = disabled)
        "multi_click_enabled",  # Enable multi-click detection for Hue Hub switches
        "multi_click_speed",  # Multi-click window in tenths of seconds
        "circadian_refresh",  # How often to refresh circadian lighting (seconds)
        "log_periodic",  # Whether to log periodic update details (default false)
        "home_refresh_interval",  # How often to refresh home page cards (seconds, default 10)
        "motion_warning_time",  # Seconds before motion timer expires to trigger warning dim
        "motion_blink_threshold",  # Brightness % below which motion warning blinks instead of dims
        "freeze_feedback_enabled",  # Whether freeze/unfreeze shows visual dip-and-restore cue (default true)
        "freeze_off_rise",  # Transition time in tenths of seconds for unfreeze rise (default 10 = 1.0s)
        "alert_bounce_speed",  # Transition time in tenths of seconds for alert bounce animation (default 10 = 1.0s)
        "limit_bounce_enabled",  # Whether to show visual bounce when hitting step limits (default true)
        "limit_warning_speed",  # Transition time in tenths of seconds for limit bounce animation (default 3 = 0.3s)
        "limit_bounce_max_percent",  # Percentage of range to dip when hitting max limit (default 25)
        "limit_bounce_min_percent",  # Percentage of range to flash when hitting min limit (default 13)
        "post_action_burst_count",  # Number of burst refreshes after switch actions (0-3, default 3)
        "reach_daytime_threshold",  # Brightness % below which reach feedback flashes UP when sun bright > 0 (default 50)
        "reach_feedback_enabled",  # Whether reach scope changes flash lights (default true)
        "feedback_restrict_to_primary",  # Restrict feedback to primary (starred) area only (default false)
        "boost_default",  # Default boost percentage (10-100, default 30)
        "long_press_repeat_interval",  # Long-press repeat interval in tenths of seconds (default 7 = 700ms)
        "controls_ui",  # Controls page UI preferences (sort, filter)
        "areas_ui",  # Areas page UI preferences (sort, filter)
        "area_settings",  # Per-area settings (motion_function, motion_duration)
        "home_name",  # Display name for the home (shown on areas page)
        "ct_comp_enabled",  # Enable CT brightness compensation for warm colors
        "ct_comp_begin",  # Handover zone begin (warmer end) in Kelvin
        "ct_comp_end",  # Handover zone end (cooler end) in Kelvin
        "ct_comp_factor",  # Max brightness compensation factor (e.g., 1.4 = 40% boost)
        "light_filters",  # Filter presets + off threshold for per-light brightness curves
        "weather_condition_map",  # User overrides for weather condition multipliers
        "outdoor_lux_sensor",  # Entity ID of outdoor illuminance sensor
        "lux_smoothing_interval",  # EMA smoothing time constant in seconds (default 300)
        "lux_learned_ceiling",  # Learned bright-day lux baseline (85th percentile)
        "lux_learned_floor",  # Learned dark-day lux baseline (5th percentile)
        "outdoor_brightness_source",  # Preferred outdoor brightness source: "lux", "weather", or "angle"
        "periodic_transition_day",  # Periodic transition speed during day (tenths of seconds, default 1)
        "periodic_transition_night",  # Periodic transition speed at night (tenths of seconds, default 1)
        "power_recovery",  # Power failure recovery: "bright" or "last_state" (default "last_state")
        "advanced_logging_until",  # ISO timestamp or "forever" for advanced logging expiry
        "confirm_zone_pushes",  # Show confirmation dialogs for zone push actions (default true)
        "home_slider_mode",  # Homepage slider: "brightness", "step", or "color" (default "brightness")
        "home_buttons_mode",  # Homepage up/down buttons: "step", "bright", or "color" (default "step")
    }

    def _migrate_to_glozone_format(self, config: dict) -> dict:
        """Migrate old config formats to Rhythm Zone format.

        Handles:
        - circadian_presets → circadian_rhythms (legacy step)
        - zone preset → rhythm field (legacy step)
        - circadian_rhythms collapse into glozones (Rhythm Zone migration)
        - Flat config → glozones with inline rhythm settings

        Args:
            config: The loaded config dict

        Returns:
            Migrated config dict
        """
        # Legacy step: migrate circadian_presets → circadian_rhythms
        if "circadian_presets" in config and "circadian_rhythms" not in config:
            config["circadian_rhythms"] = config.pop("circadian_presets")

        # Legacy step: migrate zone "preset" → "rhythm" field
        for zone in config.get("glozones", {}).values():
            if "preset" in zone and "rhythm" not in zone:
                zone["rhythm"] = zone.pop("preset")

        # Collapse circadian_rhythms into glozones
        if "circadian_rhythms" in config and "glozones" in config:
            first_zone = next(iter(config["glozones"].values()), {})
            if "wake_time" not in first_zone or "rhythm" in first_zone:
                rhythms = config["circadian_rhythms"]
                for zone_name, zone in config["glozones"].items():
                    rhythm_ref = zone.pop("rhythm", None)
                    if rhythm_ref and rhythm_ref in rhythms:
                        rhythm_data = rhythms[rhythm_ref]
                        for k, v in rhythm_data.items():
                            if k not in zone:
                                zone[k] = v
                    elif rhythms:
                        first_rhythm = next(iter(rhythms.values()))
                        for k, v in first_rhythm.items():
                            if k not in zone:
                                zone[k] = v
                del config["circadian_rhythms"]
                logger.info(
                    "Collapsed circadian_rhythms into glozones (Rhythm Zone migration)"
                )
            else:
                config.pop("circadian_rhythms", None)
            return config

        # Already migrated (has glozones, no circadian_rhythms)
        if "glozones" in config:
            return config

        logger.info("Migrating flat config to Rhythm Zone format...")

        # Extract rhythm settings from flat config
        rhythm_settings = {}
        for key in self.RHYTHM_SETTINGS:
            if key in config:
                rhythm_settings[key] = config[key]

        # Extract global settings
        global_config = {}
        for key in self.GLOBAL_SETTINGS:
            if key in config:
                global_config[key] = config[key]

        # Build new config: inline rhythm settings into zone
        new_config = {
            "glozones": {
                glozone.INITIAL_ZONE_NAME: {
                    **rhythm_settings,
                    "areas": [],
                    "is_default": True,
                }
            },
        }

        # Add global settings
        new_config.update(global_config)

        logger.info(
            f"Migration complete: created zone '{glozone.INITIAL_ZONE_NAME}' (default) "
            f"with inline rhythm settings"
        )

        return new_config

    def _get_effective_config(self, config: dict) -> dict:
        """Get effective config by merging first zone's settings with global settings.

        For backward compatibility with code that expects flat config,
        this merges the first zone's rhythm settings into the top level.

        Args:
            config: The Rhythm Zone format config

        Returns:
            Flat config dict with all settings merged
        """
        result = {}

        # Start with global settings
        for key in self.GLOBAL_SETTINGS:
            if key in config:
                result[key] = config[key]

        # Get the first zone's rhythm settings
        glozones = config.get("glozones", {})
        if glozones:
            first_zone_name = list(glozones.keys())[0]
            first_zone = glozones[first_zone_name]
            for key in self.RHYTHM_SETTINGS:
                if key in first_zone:
                    result[key] = first_zone[key]

        # Keep the zone structure available
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
            "warm_night_end": 60,  # minutes offset from sunrise (positive = after)
            "warm_night_fade": 60,  # fade duration in minutes
            # Daylight blend
            "daylight_enabled": True,
            "daylight_cct": 5500,
            "daylight_fade": 60,
            "color_sensitivity": 1.0,
            # Activity preset
            "activity_preset": "adult",
            # Location (default to HA, allow override)
            "latitude": 35.0,
            "longitude": -78.6,
            "timezone": "US/Eastern",
            "use_ha_location": True,
            # Dimming steps
            "max_dim_steps": DEFAULT_MAX_DIM_STEPS,
            "step_fallback_minutes": 30,
            # UI preview settings
            "month": 6,
            # Advanced timing settings (tenths of seconds unless noted)
            "turn_on_transition": 3,
            "turn_off_transition": 3,
            "two_step_bri_threshold": 15,
            "two_step_delay": 5,
            "nudge_delay": 10,
            "multi_click_enabled": True,
            "multi_click_speed": 15,
            "circadian_refresh": 20,  # seconds
            "log_periodic": False,  # log periodic update details
            "home_refresh_interval": 3,  # seconds (home page card refresh)
            # Motion warning settings
            "motion_warning_time": 20,  # seconds (0 = disabled)
            "motion_blink_threshold": 15,  # percent brightness
            # Visual feedback settings
            "freeze_feedback_enabled": True,  # Show visual dip on freeze/unfreeze
            "freeze_off_rise": 10,  # tenths of seconds (1.0s)
            "limit_bounce_enabled": True,  # Show visual bounce at step limits
            "limit_warning_speed": 3,  # tenths of seconds (0.3s)
            "limit_bounce_max_percent": 25,  # % of range (hitting max)
            "limit_bounce_min_percent": 13,  # % of range (hitting min)
            "alert_bounce_speed": 10,  # tenths of seconds (1.0s)
            # Reach feedback
            "post_action_burst_count": 1,  # 0-3 burst refreshes after actions
            "reach_feedback_enabled": True,  # Flash lights on reach change
            "reach_daytime_threshold": 50,  # % brightness
            "feedback_restrict_to_primary": False,  # All areas get feedback (not just starred)
        }

        # Merge supervisor-managed options.json (if present)
        try:
            if os.path.exists(self.options_file):
                async with aiofiles.open(self.options_file, "r") as f:
                    content = await f.read()
                    opts = json.loads(content)
                    if isinstance(opts, dict):
                        config.update(opts)
        except Exception as e:
            logger.warning(f"Error loading {self.options_file}: {e}")

        # Merge user-saved designer config (persists across restarts)
        try:
            if os.path.exists(self.designer_file):
                async with aiofiles.open(self.designer_file, "r") as f:
                    content = await f.read()
                    overrides = json.loads(content)
                    if isinstance(overrides, dict):
                        config.update(overrides)
        except Exception as e:
            logger.warning(f"Error loading {self.designer_file}: {e}")

        # Migrate home_refresh_interval: polling is now lightweight (no WebSocket/disk I/O),
        # so reduce from old default to 3s for faster UI updates
        if config.get("home_refresh_interval", 3) > 3:
            config["home_refresh_interval"] = 3

        # Migrate renamed settings
        if (
            "motion_warning_blink_threshold" in config
            and "motion_blink_threshold" not in config
        ):
            config["motion_blink_threshold"] = config.pop(
                "motion_warning_blink_threshold"
            )
        elif "motion_warning_blink_threshold" in config:
            del config["motion_warning_blink_threshold"]
        if "reach_dip_percent" in config and "reach_daytime_threshold" not in config:
            config["reach_daytime_threshold"] = config.pop("reach_dip_percent")
        elif "reach_dip_percent" in config:
            del config["reach_dip_percent"]

        # Migrate to GloZone format if needed
        config = self._migrate_to_glozone_format(config)

        # Ensure top-level rhythm settings are merged INTO the first zone
        glozones = config.get("glozones", {})
        if glozones:
            first_zone_name = list(glozones.keys())[0]
            first_zone = glozones[first_zone_name]
            for key in list(config.keys()):
                if key in self.RHYTHM_SETTINGS:
                    if key not in first_zone:
                        first_zone[key] = config[key]
                    del config[key]

        # Update glozone module with current config
        glozone.set_config(config)

        # Return effective config (flat format for backward compatibility)
        return self._get_effective_config(config)

    async def load_raw_config(self) -> dict:
        """Load raw configuration without flattening.

        Returns the Rhythm Zone format config with glozones.
        Used internally for save operations.
        """
        # Start with global-only defaults. RHYTHM_SETTINGS are intentionally NOT
        # included here — they belong inside zone dicts, not at the top level.
        # Having them here caused them to be saved to designer_config.json at the
        # top level, which then poisoned load_config_from_files() on next startup
        # (top-level false values would override correct zone values).
        # Missing rhythm keys are handled by get_zone_config() and Config.from_dict().
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
            "two_step_bri_threshold": 15,
            "two_step_delay": 5,
            "nudge_delay": 10,
            "multi_click_enabled": True,
            "multi_click_speed": 15,
            "circadian_refresh": 20,  # seconds
            "log_periodic": False,  # log periodic update details
            "home_refresh_interval": 3,  # seconds (home page card refresh)
            # Motion warning settings
            "motion_warning_time": 20,  # seconds (0 = disabled)
            "motion_blink_threshold": 15,  # percent brightness
            # Visual feedback settings
            "freeze_feedback_enabled": True,
            "freeze_off_rise": 10,  # tenths of seconds (1.0s)
            "limit_bounce_enabled": True,  # Show visual bounce at step limits
            "limit_warning_speed": 3,  # tenths of seconds (0.3s)
            "limit_bounce_max_percent": 25,  # % of range (hitting max)
            "limit_bounce_min_percent": 13,  # % of range (hitting min)
            "alert_bounce_speed": 10,
            "post_action_burst_count": 1,
            # Reach feedback
            "reach_feedback_enabled": True,
            "reach_daytime_threshold": 50,  # % brightness
            "feedback_restrict_to_primary": False,
        }

        # Merge options.json
        try:
            if os.path.exists(self.options_file):
                async with aiofiles.open(self.options_file, "r") as f:
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
                async with aiofiles.open(self.designer_file, "r") as f:
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
                        logger.info(
                            "Successfully repaired and loaded designer_config.json"
                        )
                except Exception as repair_err:
                    logger.error(f"Failed to repair {self.designer_file}: {repair_err}")
        except Exception as e:
            logger.error(f"CRITICAL: Failed to load {self.designer_file}: {e}")
            # Mark as not loaded to prevent accidental overwrites
            designer_loaded = False

        # Track load status to prevent saving incomplete data
        config["_designer_loaded"] = designer_loaded
        if not designer_loaded:
            logger.error(
                "Designer config load failed - saves will be blocked to prevent data loss"
            )

        # Migrate to GloZone format if needed
        config = self._migrate_to_glozone_format(config)

        # Ensure top-level rhythm settings are merged INTO the first zone
        glozones = config.get("glozones", {})
        if glozones:
            first_zone_name = list(glozones.keys())[0]
            first_zone = glozones[first_zone_name]

            # Copy any top-level rhythm settings into the zone (if not already there)
            for key in list(config.keys()):
                if key in self.RHYTHM_SETTINGS:
                    if key not in first_zone:
                        first_zone[key] = config[key]
                        logger.debug(
                            f"Migrated top-level key '{key}' into zone '{first_zone_name}'"
                        )
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
            async with aiofiles.open(filepath, "r") as f:
                content = await f.read()

            # Use JSONDecoder to extract just the first valid JSON object
            decoder = json.JSONDecoder()
            repaired_data, end_idx = decoder.raw_decode(content)

            if isinstance(repaired_data, dict):
                # Backup the corrupted file
                backup_path = filepath + ".corrupted"
                async with aiofiles.open(backup_path, "w") as f:
                    await f.write(content)
                logger.info(f"Backed up corrupted file to {backup_path}")

                # Write the repaired JSON
                async with aiofiles.open(filepath, "w") as f:
                    await f.write(json.dumps(repaired_data, indent=2))
                logger.info(
                    f"Repaired {filepath} (extracted {end_idx} of {len(content)} chars)"
                )

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
            logger.error(
                "REFUSING TO SAVE: config was not loaded successfully - would cause data loss"
            )
            raise RuntimeError(
                "Cannot save config: original file was not loaded successfully"
            )

        try:
            # Remove internal tracking flags and top-level RHYTHM_SETTINGS before saving.
            # RHYTHM_SETTINGS belong inside rhythm dicts, not at the top level.
            # If left at the top level, they poison load_config_from_files() on next
            # startup (e.g., warm_night_enabled=false overrides rhythm's true).
            save_config = {
                k: v
                for k, v in config.items()
                if not k.startswith("_") and k not in self.RHYTHM_SETTINGS
            }
            # Use a unique temp file to prevent concurrent write collisions
            dir_path = os.path.dirname(self.designer_file)
            fd, tmp_path = tempfile.mkstemp(
                dir=dir_path, suffix=".tmp", prefix=".designer_"
            )
            try:
                with os.fdopen(fd, "w") as f:
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
        token = os.environ.get("HA_TOKEN")
        if not token:
            return None, None, None

        # Check for explicit URLs first (set by run script in addon mode)
        rest_url = os.environ.get("HA_REST_URL")
        ws_url = os.environ.get("HA_WEBSOCKET_URL")

        if rest_url and ws_url:
            return rest_url, ws_url, token

        # Fall back to constructing URLs from host/port
        host = os.environ.get("HA_HOST")
        port = os.environ.get("HA_PORT", "8123")
        use_ssl = os.environ.get("HA_USE_SSL", "false").lower() == "true"

        if host:
            http_protocol = "https" if use_ssl else "http"
            ws_protocol = "wss" if use_ssl else "ws"
            rest_url = f"{http_protocol}://{host}:{port}/api"
            ws_url = f"{ws_protocol}://{host}:{port}/api/websocket"
            return rest_url, ws_url, token

        return None, None, None

    async def _trigger_batch_group_sync(self) -> bool:
        """Trigger batch group sync via direct client call.

        Returns:
            True if sync was triggered successfully
        """
        if self.client:
            await self.client.sync_batch_groups()
            return True
        return False

    async def _trigger_batch_group_sync_if_needed(self, scopes: list) -> bool:
        """Trigger batch group sync if any scope has multiple areas.

        Only fires the sync event if there's a multi-area scope that would
        benefit from batch group optimization.

        Args:
            scopes: List of SwitchScope objects

        Returns:
            True if sync was triggered, False otherwise
        """
        # Check if any scope has multiple areas
        has_multi_area_scope = any(len(scope.areas) >= 2 for scope in scopes)
        if has_multi_area_scope:
            logger.info("Multi-area scope detected, triggering batch group sync")
            return await self._trigger_batch_group_sync()
        return False

    async def get_areas(self, request: Request) -> Response:
        """Return areas list from client cache."""
        # Return cached areas if available
        if self.cached_areas_list is not None:
            logger.debug(f"Returning {len(self.cached_areas_list)} cached areas")
            return web.json_response(self.cached_areas_list)

        if not self.client:
            return web.json_response(
                {"error": "Home Assistant client not ready"}, status=503
            )

        try:
            areas = []
            for area_id, area_name in self.client.area_id_to_name.items():
                if self.client.area_lights.get(area_id):
                    areas.append({"area_id": area_id, "name": area_name})
            areas.sort(key=lambda x: x["name"].lower())
            self.cached_areas_list = areas
            logger.info(f"Cached {len(areas)} areas from client")
            return web.json_response(areas)
        except Exception as e:
            logger.error(f"Error fetching areas: {e}")
            return web.json_response({"error": str(e)}, status=500)

    _sun_hours_cache = {}  # "YYYY-MM-DD" -> (sunrise_h, sunset_h)

    @staticmethod
    def _get_sun_hours_for_date(date_str):
        """Get sunrise/sunset as decimal hours for an arbitrary date (cached)."""
        if date_str in LightDesignerServer._sun_hours_cache:
            return LightDesignerServer._sun_hours_cache[date_str]
        try:
            from brain import calculate_sun_times
            from zoneinfo import ZoneInfo

            latitude = float(os.getenv("HASS_LATITUDE", "35.0"))
            longitude = float(os.getenv("HASS_LONGITUDE", "-78.6"))
            timezone = os.getenv("HASS_TIME_ZONE", "US/Eastern")
            try:
                tzinfo = ZoneInfo(timezone)
            except Exception:
                tzinfo = None

            sun_dict = calculate_sun_times(latitude, longitude, date_str)

            def iso_to_hour(iso_str, default):
                if not iso_str:
                    return default
                try:
                    dt = datetime.fromisoformat(iso_str)
                    if tzinfo and dt.tzinfo:
                        dt = dt.astimezone(tzinfo)
                    return dt.hour + dt.minute / 60.0 + dt.second / 3600.0
                except Exception:
                    return default

            result = (
                iso_to_hour(sun_dict.get("sunrise"), 6.0),
                iso_to_hour(sun_dict.get("sunset"), 18.0),
            )

            # Prune stale entries (dates before today)
            today_str = datetime.now().strftime("%Y-%m-%d")
            for k in list(LightDesignerServer._sun_hours_cache):
                if k < today_str:
                    del LightDesignerServer._sun_hours_cache[k]

            LightDesignerServer._sun_hours_cache[date_str] = result
            return result
        except Exception:
            return (6.0, 18.0)

    @staticmethod
    def _get_fade_info(area_id):
        """Get fade state for API responses."""
        if not state.is_fading(area_id):
            return {
                "fade_direction": None,
                "fade_progress": None,
                "fade_target_preset": None,
                "fade_remaining": None,
            }
        fs = state.get_fade_state(area_id)
        progress = state.get_fade_progress(area_id) or 0
        duration = fs.get("fade_duration") or 0
        remaining = max(0, duration * (1 - progress))
        return {
            "fade_direction": fs.get("fade_direction"),
            "fade_progress": round(progress, 3),
            "fade_target_preset": fs.get("fade_target_preset"),
            "fade_remaining": round(remaining),
        }

    @staticmethod
    def _get_sun_hours():
        """Get today's sunrise/sunset as decimal hours."""
        from zoneinfo import ZoneInfo

        timezone = os.getenv("HASS_TIME_ZONE", "US/Eastern")
        try:
            tzinfo = ZoneInfo(timezone)
        except Exception:
            tzinfo = None
        now = datetime.now(tzinfo)
        return LightDesignerServer._get_sun_hours_for_date(now.strftime("%Y-%m-%d"))

    @staticmethod
    def _compute_next_auto_time(settings, prefix, sunrise_hour=6.0, sunset_hour=18.0):
        """Compute next auto schedule trigger for auto_on or auto_off.

        Args:
            settings: Per-area settings dict
            prefix: "auto_on" or "auto_off"
            sunrise_hour: Decimal hour of today's sunrise
            sunset_hour: Decimal hour of today's sunset

        Returns: {"time": "7:15a", "day": "today", "offset": 0, ...} or None
        """
        if not settings.get(f"{prefix}_enabled"):
            return None

        from zoneinfo import ZoneInfo
        from datetime import date as date_cls, timedelta

        timezone = os.getenv("HASS_TIME_ZONE", "US/Eastern")
        try:
            tzinfo = ZoneInfo(timezone)
        except Exception:
            tzinfo = None
        now = datetime.now(tzinfo)
        today_wd = now.weekday()
        now_decimal = now.hour + now.minute / 60.0
        today_date = now.date()

        day_abbrs = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

        def fmt_time(decimal_hours):
            h_raw = int(decimal_hours % 24)
            m_raw = round((decimal_hours - int(decimal_hours)) * 60)
            suffix = "a" if h_raw < 12 else "p"
            h_display = h_raw
            if h_display == 0:
                h_display = 12
            elif h_display > 12:
                h_display -= 12
            return f"{h_display}:{m_raw:02d}{suffix}"

        # Override handling
        override = settings.get(f"{prefix}_override")
        override_is_pause = False
        override_time = None
        override_until_date = None

        if override:
            mode = override.get("mode")
            until_str = override.get("until_date")
            if until_str:
                try:
                    override_until_date = date_cls.fromisoformat(until_str)
                except ValueError:
                    pass

            expired = (
                override_until_date is not None and override_until_date < today_date
            )
            if not expired:
                if mode == "pause":
                    override_is_pause = True
                    if (
                        not override_until_date
                        or (override_until_date - today_date).days > 365
                    ):
                        return {"time": "paused", "day": "", "offset": -1}
                else:
                    override_time = override.get("time")

        source = settings.get(
            f"{prefix}_source", "sunset" if prefix == "auto_on" else "sunrise"
        )

        def get_normal_time(py_day):
            """Get trigger time from normal schedule (no override)."""
            if source in ("sunrise", "sunset"):
                active_days = settings.get(f"{prefix}_days", [0, 1, 2, 3, 4, 5, 6])
                if py_day not in active_days:
                    return None
                base = sunrise_hour if source == "sunrise" else sunset_hour
                offset_min = settings.get(f"{prefix}_offset", 0)
                return base + offset_min / 60.0
            elif source == "custom":
                days_1 = settings.get(f"{prefix}_days_1", [])
                days_2 = settings.get(f"{prefix}_days_2", [])
                if py_day in days_1:
                    return settings.get(f"{prefix}_time_1")
                elif py_day in days_2:
                    return settings.get(f"{prefix}_time_2")
            return None

        # Calculate pause skip days
        pause_skip = 0
        if override_is_pause and override_until_date:
            pause_skip = (override_until_date - today_date).days + 1

        # Scan forward for next fire day
        fire_offset = None
        fire_day = None
        fire_time = None
        fire_source = None
        scan_range = max(14, pause_skip + 7)

        for i in range(scan_range):
            py_day = (today_wd + i) % 7
            day_date = today_date + timedelta(days=i)

            if override_is_pause and i < pause_skip:
                continue

            # During active non-pause override, use override time every day
            if (
                override_time is not None
                and override_until_date
                and day_date <= override_until_date
            ):
                at = override_time
                at_source = "override"
            else:
                at = get_normal_time(py_day)
                at_source = source

            if at is None:
                continue
            if i == 0 and now_decimal >= at:
                continue

            fire_offset = i
            fire_day = py_day
            fire_time = at
            fire_source = at_source
            break

        if fire_time is None:
            return None

        # Re-resolve sun times for the actual fire date when it's in the future
        if fire_offset > 0 and source in ("sunrise", "sunset"):
            try:
                fire_date = today_date + timedelta(days=fire_offset)
                sr_h, ss_h = LightDesignerServer._get_sun_hours_for_date(
                    fire_date.isoformat()
                )
                base = sr_h if source == "sunrise" else ss_h
                offset_min = settings.get(f"{prefix}_offset", 0)
                fire_time = base + offset_min / 60.0
            except Exception:
                pass  # keep already-computed fire_time

        time_str = fmt_time(fire_time)
        display_offset = fire_offset
        if fire_offset == 1 and fire_time < now_decimal:
            display_offset = 0

        if fire_offset == 0:
            day_label = "today"
        elif fire_offset == 1:
            day_label = f"tom ({day_abbrs[fire_day]})"
        elif fire_offset > 5:
            fire_date = today_date + timedelta(days=fire_offset)
            month_abbrs = [
                "Jan",
                "Feb",
                "Mar",
                "Apr",
                "May",
                "Jun",
                "Jul",
                "Aug",
                "Sep",
                "Oct",
                "Nov",
                "Dec",
            ]
            day_label = (
                f"{day_abbrs[fire_day]} "
                f"({month_abbrs[fire_date.month - 1]} {fire_date.day})"
            )
        else:
            day_label = day_abbrs[fire_day]

        result = {
            "time": time_str,
            "day": day_label,
            "offset": display_offset,
            "fire_offset": fire_offset,
            "day_abbr": day_abbrs[fire_day],
            "decimal_hour": round(fire_time, 2),
        }
        if fire_source in ("sunrise", "sunset"):
            result["source"] = fire_source
            result["sun_offset_min"] = settings.get(f"{prefix}_offset", 0)
        if fire_offset > 6:
            fire_date_r = today_date + timedelta(days=fire_offset)
            month_abbrs = [
                "Jan",
                "Feb",
                "Mar",
                "Apr",
                "May",
                "Jun",
                "Jul",
                "Aug",
                "Sep",
                "Oct",
                "Nov",
                "Dec",
            ]
            result["date_short"] = (
                f"{month_abbrs[fire_date_r.month - 1]} {fire_date_r.day}"
            )
        return result

    def _compute_next_auto_off_with_untouched(
        self, area_id, settings, sunrise_hour, sunset_hour
    ):
        """Compute next auto-off time, suppressing if untouched guard would block.

        When auto_off_only_untouched is enabled and the user has interacted
        since auto-on fired, auto-off will be skipped — so don't show it
        as the next scheduled time.
        """
        result = self._compute_next_auto_time(
            settings, "auto_off", sunrise_hour, sunset_hour
        )
        if not result or not settings.get("auto_off_only_untouched", False):
            return result

        prims = self.client.primitives
        auto_on_fired = prims._auto_fired.get(area_id, {}).get("auto_on", {})
        auto_on_date = auto_on_fired.get("date")
        auto_on_time = auto_on_fired.get("time")

        if not auto_on_date:
            # Auto-on has never fired (this session) — no baseline to compare
            # "untouched" against. Show the scheduled auto-off time anyway so
            # the user isn't left with a blank header.
            return result

        # Check if user touched since last auto-on (regardless of day)
        last_action = state.get_last_user_action(area_id)
        if not last_action:
            return result  # No user action recorded — untouched

        try:
            action_dt = datetime.fromisoformat(last_action)
            auto_on_h = int(auto_on_time)
            auto_on_m = int((auto_on_time - auto_on_h) * 60)
            auto_on_dt = datetime.fromisoformat(
                f"{auto_on_date}T{auto_on_h:02d}:{auto_on_m:02d}:00"
            )
            if action_dt > auto_on_dt:
                # User touched since last auto-on — suppress auto-off
                # until next auto-on fires and resets untouched state.
                return None
        except Exception:
            pass

        return result

    async def get_area_status(self, request: Request) -> Response:
        """Get status for areas using Circadian Light state.

        Supports optional query params:
            ?area_id=X — return a single area
            ?lite=true — lightweight mode for homepage (reads stored state,
                         skips curve/solar/sun-bright computation)

        Returns a dict mapping area_id to status.
        """
        # Lite mode: pure state reads, no computation
        is_lite = request.query.get("lite", "").lower() in ("true", "1")
        if is_lite:
            return await self._get_area_status_lite(request)

        try:
            from brain import (
                SunTimes,
                SPEED_TO_SLOPE,
                calculate_sun_times,
                calculate_natural_light_factor,
                compute_daylight_fade_weight,
                compute_override_decay,
                compute_shifted_midpoint,
                midpoint_to_time,
                resolve_effective_timing,
                DEFAULT_DAYLIGHT_FADE,
            )

            # Load config to get glozone mappings
            config = await self.load_config()
            glozones = config.get("glozones", {})

            # State is shared in-memory (same process as main.py)

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
                date_str = now.strftime("%Y-%m-%d")
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

            # Outdoor data is shared in-memory (main.py seeds lux_tracker from live events)
            outdoor_norm = lux_tracker.get_outdoor_normalized()
            outdoor_source = lux_tracker.get_outdoor_source()
            if outdoor_norm is None:
                outdoor_norm = 0.0
                outdoor_source = "none"

            sun_times.outdoor_normalized = outdoor_norm
            sun_times.outdoor_source = outdoor_source

            # Optional single-area filter
            filter_area_id = request.query.get("area_id")

            # Build response for each area in zones (including Unassigned)
            area_status = {}
            for zone_name, zone_data in glozones.items():
                # Add status for each area in this zone
                for area in zone_data.get("areas", []):
                    # Areas can be stored as {id, name} or just string
                    area_id = area.get("id") if isinstance(area, dict) else area

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
                    calc_hour = (
                        area_state.frozen_at
                        if area_state.frozen_at is not None
                        else current_hour
                    )

                    # Apply color override decay for slider-originated overrides
                    render_state = area_state
                    if (
                        area_state.color_override is not None
                        and area_state.color_override_set_at is not None
                    ):
                        _in_asc, _h48, _t_asc, _t_desc, _ = (
                            CircadianLight.get_phase_info(calc_hour, area_config)
                        )
                        _next_ph = _t_desc if _in_asc else _t_asc + 24
                        _col_decay = compute_override_decay(
                            area_state.color_override_set_at,
                            _h48,
                            _next_ph,
                            t_ascend=_t_asc,
                        )
                        if _col_decay < 1.0:
                            render_state = AreaState(
                                is_circadian=area_state.is_circadian,
                                is_on=area_state.is_on,
                                frozen_at=area_state.frozen_at,
                                brightness_mid=area_state.brightness_mid,
                                color_mid=area_state.color_mid,
                                color_override=(
                                    area_state.color_override * _col_decay
                                    if _col_decay > 0
                                    else None
                                ),
                                color_override_set_at=(
                                    area_state.color_override_set_at
                                    if _col_decay > 0
                                    else None
                                ),
                                brightness_override=area_state.brightness_override,
                                brightness_override_set_at=area_state.brightness_override_set_at,
                            )

                    # Calculate using area's actual state (which has brightness_mid, color_mid)
                    brightness = 50
                    kelvin = 4000
                    try:
                        result = CircadianLight.calculate_lighting(
                            calc_hour, area_config, render_state, sun_times=sun_times
                        )
                        brightness = result.brightness
                        kelvin = result.color_temp
                    except Exception as e:
                        logger.warning(
                            f"Error calculating lighting for area {area_id}: {e}"
                        )

                    # Check if area is boosted and add boost brightness
                    is_boosted = state.is_boosted(area_id)
                    boost_state = state.get_boost_state(area_id) if is_boosted else {}

                    # Keep curve brightness before sun bright (pure circadian value)
                    curve_brightness = brightness
                    boost_amount = (
                        (boost_state.get("boost_brightness") or 0) if is_boosted else 0
                    )

                    # Get motion timer state
                    motion_expires_at = state.get_motion_expires(area_id)
                    motion_warning_active = state.is_motion_warned(area_id)

                    # Natural light factor for this area
                    area_sun_exposure = glozone.get_area_natural_light_exposure(area_id)
                    rhythm_cfg = glozone.get_zone_config_for_area(area_id)
                    area_brightness_sensitivity = rhythm_cfg.get(
                        "brightness_sensitivity", 1.0
                    )
                    # Brightness sun bright uses raw outdoor_norm (no daylight fade —
                    # fade applies to color solar rules only, not brightness)
                    sun_bright_factor = calculate_natural_light_factor(
                        area_sun_exposure,
                        outdoor_norm,
                        area_brightness_sensitivity,
                    )

                    # Apply natural light reduction to brightness (matches main.py)
                    if sun_bright_factor < 1.0:
                        brightness = max(1, int(round(brightness * sun_bright_factor)))

                    # Base kelvin (before solar rules) and solar rule breakdown
                    base_kelvin = 4000
                    solar_breakdown = None
                    try:
                        base_kelvin = CircadianLight.calculate_color_at_hour(
                            calc_hour,
                            area_config,
                            area_state,
                            apply_solar_rules=False,
                            sun_times=sun_times,
                        )
                        solar_breakdown = CircadianLight.get_solar_rule_breakdown(
                            base_kelvin, calc_hour, area_config, area_state, sun_times
                        )
                    except Exception as e:
                        logger.debug(
                            f"[AreaStatus] Error computing solar breakdown for {area_id}: {e}"
                        )

                    # Lux tracker data
                    lux_sensor = lux_tracker.get_sensor_entity()
                    lux_smoothed = lux_tracker._ema_lux if lux_sensor else None
                    lux_ceiling = lux_tracker._learned_ceiling if lux_sensor else None
                    lux_floor = lux_tracker._learned_floor if lux_sensor else None

                    # --- Override decay & actual brightness ---
                    area_factor = glozone.get_area_brightness_factor(area_id)
                    effective_bri_override = 0
                    bri_override_raw = area_state.brightness_override
                    if bri_override_raw is not None:
                        in_ascend, h48, t_ascend, t_descend, _ = (
                            CircadianLight.get_phase_info(calc_hour, area_config)
                        )
                        next_phase = t_descend if in_ascend else t_ascend + 24
                        bri_decay = compute_override_decay(
                            area_state.brightness_override_set_at,
                            h48,
                            next_phase,
                            t_ascend=t_ascend,
                        )
                        effective_bri_override = bri_override_raw * bri_decay

                    # Use cached last-sent brightness — always matches what
                    # pipeline computed and delivered to lights
                    last_bri = state.get_last_sent_brightness(area_id)
                    actual_brightness = (
                        last_bri
                        if last_bri is not None
                        else int(
                            min(
                                100,
                                max(
                                    0,
                                    round(
                                        brightness * area_factor
                                        + effective_bri_override
                                        + boost_amount
                                    ),
                                ),
                            )
                        )
                    )

                    # --- Adjusted bed/wake time from midpoint shift ---
                    weekday = datetime.now().weekday()
                    eff_wake, eff_bed = resolve_effective_timing(
                        area_config, calc_hour, weekday
                    )
                    _in_ascend_phase, _, _t_asc, _t_desc, _ = (
                        CircadianLight.get_phase_info(calc_hour, area_config)
                    )
                    adjusted_wake_time = None
                    adjusted_bed_time = None
                    if area_state.brightness_mid is not None:
                        in_ascend_adj, h48_adj, t_asc_adj, t_desc_adj, slope_adj = (
                            CircadianLight.get_phase_info(calc_hour, area_config)
                        )
                        # Compute the TRUE default midpoint (including bed/wake brightness shift)
                        raw_default = eff_wake if in_ascend_adj else eff_bed
                        default_mid = raw_default
                        bri_pct = (
                            area_config.wake_brightness
                            if in_ascend_adj
                            else area_config.bed_brightness
                        )
                        if bri_pct != 50:
                            b_min_n = area_config.min_brightness / 100.0
                            b_max_n = area_config.max_brightness / 100.0
                            if in_ascend_adj:
                                mid48_r = CircadianLight.lift_midpoint_to_phase(
                                    default_mid, t_asc_adj, t_desc_adj
                                )
                            else:
                                mid48_r = CircadianLight.lift_midpoint_to_phase(
                                    default_mid, t_desc_adj, t_asc_adj + 24
                                )
                            default_mid = (
                                compute_shifted_midpoint(
                                    mid48_r, bri_pct, slope_adj, b_min_n, b_max_n
                                )
                                % 24
                            )

                        mid_shift = area_state.brightness_mid - default_mid
                        if abs(mid_shift) > 0.01:
                            b_min_n2 = area_config.min_brightness / 100.0
                            b_max_n2 = area_config.max_brightness / 100.0
                            if in_ascend_adj:
                                mid48_stepped = CircadianLight.lift_midpoint_to_phase(
                                    area_state.brightness_mid, t_asc_adj, t_desc_adj
                                )
                                adjusted_wake_time = (
                                    midpoint_to_time(
                                        mid48_stepped,
                                        area_config.wake_brightness,
                                        slope_adj,
                                        b_min_n2,
                                        b_max_n2,
                                    )
                                    % 24
                                )
                            else:
                                mid48_stepped = CircadianLight.lift_midpoint_to_phase(
                                    area_state.brightness_mid,
                                    t_desc_adj,
                                    t_asc_adj + 24,
                                )
                                adjusted_bed_time = (
                                    midpoint_to_time(
                                        mid48_stepped,
                                        area_config.bed_brightness,
                                        slope_adj,
                                        b_min_n2,
                                        b_max_n2,
                                    )
                                    % 24
                                )

                    area_status[area_id] = {
                        "is_circadian": area_state.is_circadian,
                        "is_on": area_state.is_on,
                        "brightness": brightness,
                        "curve_brightness": curve_brightness,
                        "kelvin": state.get_last_sent_kelvin(area_id) or kelvin,
                        "frozen": area_state.frozen_at is not None,
                        "boosted": is_boosted,
                        "boost_brightness": (
                            boost_state.get("boost_brightness") if is_boosted else None
                        ),
                        "boost_expires_at": (
                            boost_state.get("boost_expires_at") if is_boosted else None
                        ),
                        "boost_started_from_off": (
                            boost_state.get("boost_started_from_off", False)
                            if is_boosted
                            else None
                        ),
                        "is_motion_coupled": (
                            boost_state.get("is_motion_coupled", False)
                            if is_boosted
                            else False
                        ),
                        "motion_expires_at": motion_expires_at,
                        "motion_warning_active": motion_warning_active,
                        "dim_factor": state.get_dim_factor(area_id),
                        **self._get_fade_info(area_id),
                        "zone_name": zone_name if zone_name != "Unassigned" else None,
                        "preset_name": zone_name,
                        # Effective brightness/CCT range for this area's rhythm
                        "min_brightness": area_config.min_brightness,
                        "max_brightness": area_config.max_brightness,
                        "min_color_temp": area_config.min_color_temp,
                        "max_color_temp": area_config.max_color_temp,
                        # Raw state model
                        "brightness_mid": area_state.brightness_mid,
                        "color_mid": area_state.color_mid,
                        "color_override": area_state.color_override,
                        "brightness_override": bri_override_raw,
                        "brightness_override_set_at": area_state.brightness_override_set_at,
                        "color_override_set_at": area_state.color_override_set_at,
                        "effective_bri_override": (
                            round(effective_bri_override, 1)
                            if effective_bri_override
                            else 0
                        ),
                        "frozen_at": area_state.frozen_at,
                        # Override + area factor derived values
                        "actual_brightness": actual_brightness,
                        "area_factor": round(area_factor, 3),
                        "eff_wake_time": eff_wake,
                        "eff_bed_time": eff_bed,
                        "adjusted_wake_time": adjusted_wake_time,
                        "adjusted_bed_time": adjusted_bed_time,
                        "phase": "wake" if _in_ascend_phase else "bed",
                        "phase_midpoint": round(
                            (
                                (
                                    adjusted_wake_time
                                    if adjusted_wake_time is not None
                                    else eff_wake
                                )
                                if _in_ascend_phase
                                else (
                                    adjusted_bed_time
                                    if adjusted_bed_time is not None
                                    else eff_bed
                                )
                            ),
                            2,
                        ),
                        # Solar / natural light
                        "sun_elevation": round(lux_tracker.compute_sun_elevation(), 1),
                        "natural_light_exposure": area_sun_exposure,
                        "sun_bright_factor": round(sun_bright_factor, 3),
                        "brightness_fade_weight": 1.0,  # Fade applies to color only, not brightness
                        "outdoor_normalized": round(outdoor_norm, 3),
                        "outdoor_source": outdoor_source,
                        "condition_multiplier": round(
                            lux_tracker.get_condition_multiplier(), 2
                        ),
                        "angle_factor": round(lux_tracker.get_angle_factor(), 3),
                        "sun_saturation": lux_tracker.get_sun_saturation(),
                        "sun_saturation_ramp": lux_tracker.get_sun_saturation_ramp(),
                        "max_summer_elevation": round(
                            lux_tracker.get_max_summer_elevation(), 1
                        ),
                        "outdoor_source_entity": (
                            lux_tracker.get_sensor_entity()
                            if outdoor_source == "lux"
                            else (
                                lux_tracker.get_weather_entity()
                                if outdoor_source == "weather"
                                else None
                            )
                        ),
                        "outdoor_last_update": lux_tracker.get_last_outdoor_update(),
                        "sun_factor": round(outdoor_norm, 3),  # backward compat alias
                        "brightness_sensitivity": area_brightness_sensitivity,
                        "lux_smoothed": (
                            round(lux_smoothed, 1) if lux_smoothed is not None else None
                        ),
                        "lux_ceiling": (
                            round(lux_ceiling, 1) if lux_ceiling is not None else None
                        ),
                        "lux_floor": (
                            round(lux_floor, 1) if lux_floor is not None else None
                        ),
                        "base_kelvin": base_kelvin,
                        "solar_breakdown": solar_breakdown,
                        "weather_condition": lux_tracker._weather_condition,
                        "next_auto_on": self._compute_next_auto_time(
                            config.get("area_settings", {}).get(area_id, {}),
                            "auto_on",
                            sun_times.sunrise,
                            sun_times.sunset,
                        ),
                        "next_auto_off": self._compute_next_auto_off_with_untouched(
                            area_id,
                            config.get("area_settings", {}).get(area_id, {}),
                            sun_times.sunrise,
                            sun_times.sunset,
                        ),
                    }

            return web.json_response(area_status)

        except Exception as e:
            logger.error(f"[Area Status] Error: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)

    async def _get_area_status_lite(self, request: Request) -> Response:
        """Lightweight area status: reads stored state, no computation.

        Used by homepage which refreshes every 2-3s. Returns last-sent
        brightness/kelvin from state, plus config values and runtime flags.
        """
        try:
            from brain import (
                AreaState,
                CircadianLight,
                Config,
                resolve_effective_timing,
                midpoint_to_time,
                SPEED_TO_SLOPE,
            )

            config = await self.load_config()
            glozones = config.get("glozones", {})
            area_settings = config.get("area_settings", {})
            _sunrise_h, _sunset_h = self._get_sun_hours()
            current_hour = get_current_hour()
            weekday = datetime.now().weekday()

            filter_area_id = request.query.get("area_id")
            area_status = {}

            for zone_name, zone_data in glozones.items():
                for area in zone_data.get("areas", []):
                    area_id = area.get("id") if isinstance(area, dict) else area
                    if filter_area_id and area_id != filter_area_id:
                        continue

                    area_state_dict = state.get_area(area_id)
                    area_state = AreaState.from_dict(area_state_dict)
                    config_dict = glozone.get_effective_config_for_area(area_id)
                    area_config = Config.from_dict(config_dict)

                    is_boosted = state.is_boosted(area_id)
                    boost_state = state.get_boost_state(area_id) if is_boosted else {}

                    last_bri = state.get_last_sent_brightness(area_id)
                    last_kelvin = state.get_last_sent_kelvin(area_id)

                    area_status[area_id] = {
                        "is_circadian": area_state.is_circadian,
                        "is_on": area_state.is_on,
                        "actual_brightness": last_bri if last_bri is not None else 0,
                        "kelvin": last_kelvin if last_kelvin is not None else 4000,
                        "frozen": area_state.frozen_at is not None,
                        "frozen_at": area_state.frozen_at,
                        "boosted": is_boosted,
                        "boost_brightness": (
                            boost_state.get("boost_brightness") if is_boosted else None
                        ),
                        "boost_expires_at": (
                            boost_state.get("boost_expires_at") if is_boosted else None
                        ),
                        "boost_started_from_off": (
                            boost_state.get("boost_started_from_off", False)
                            if is_boosted
                            else None
                        ),
                        "is_motion_coupled": (
                            boost_state.get("is_motion_coupled", False)
                            if is_boosted
                            else False
                        ),
                        "motion_expires_at": state.get_motion_expires(area_id),
                        "motion_warning_active": state.is_motion_warned(area_id),
                        **self._get_fade_info(area_id),
                        "zone_name": (zone_name if zone_name != "Unassigned" else None),
                        "preset_name": zone_name,
                        "min_brightness": area_config.min_brightness,
                        "max_brightness": area_config.max_brightness,
                        "min_color_temp": area_config.min_color_temp,
                        "max_color_temp": area_config.max_color_temp,
                        "dim_factor": state.get_dim_factor(area_id),
                        # Raw state for mismatch detection
                        "brightness_mid": area_state.brightness_mid,
                        "color_mid": area_state.color_mid,
                        "color_override": area_state.color_override,
                        "brightness_override": area_state.brightness_override,
                        "brightness_override_set_at": area_state.brightness_override_set_at,
                        "color_override_set_at": area_state.color_override_set_at,
                        "next_auto_on": self._compute_next_auto_time(
                            area_settings.get(area_id, {}),
                            "auto_on",
                            _sunrise_h,
                            _sunset_h,
                        ),
                        "next_auto_off": self._compute_next_auto_off_with_untouched(
                            area_id,
                            area_settings.get(area_id, {}),
                            _sunrise_h,
                            _sunset_h,
                        ),
                    }

                    # Phase midpoint: determine current phase and effective wake/bed time
                    try:
                        in_ascend, _, t_ascend, t_descend, _ = (
                            CircadianLight.get_phase_info(current_hour, area_config)
                        )
                        eff_wake, eff_bed = resolve_effective_timing(
                            area_config, current_hour, weekday
                        )
                        b_min_n = area_config.min_brightness / 100.0
                        b_max_n = area_config.max_brightness / 100.0

                        if in_ascend:
                            slope = SPEED_TO_SLOPE[
                                max(1, min(10, area_config.wake_speed))
                            ]
                            bri_pct = area_config.wake_brightness
                            if area_state.brightness_mid is not None:
                                # Reverse-compute: what wake time does this midpoint correspond to?
                                mid48 = CircadianLight.lift_midpoint_to_phase(
                                    area_state.brightness_mid, t_ascend, t_descend
                                )
                                effective_time = (
                                    midpoint_to_time(
                                        mid48, bri_pct, slope, b_min_n, b_max_n
                                    )
                                    % 24
                                )
                            else:
                                effective_time = eff_wake
                            area_status[area_id]["phase"] = "wake"
                            area_status[area_id]["phase_midpoint"] = round(
                                effective_time, 2
                            )
                        else:
                            slope = -SPEED_TO_SLOPE[
                                max(1, min(10, area_config.bed_speed))
                            ]
                            bri_pct = area_config.bed_brightness
                            if area_state.brightness_mid is not None:
                                mid48 = CircadianLight.lift_midpoint_to_phase(
                                    area_state.brightness_mid, t_descend, t_ascend + 24
                                )
                                effective_time = (
                                    midpoint_to_time(
                                        mid48, bri_pct, slope, b_min_n, b_max_n
                                    )
                                    % 24
                                )
                            else:
                                effective_time = eff_bed
                            area_status[area_id]["phase"] = "bed"
                            area_status[area_id]["phase_midpoint"] = round(
                                effective_time, 2
                            )
                    except Exception:
                        pass

            return web.json_response(area_status)

        except Exception as e:
            logger.error(f"[Area Status Lite] Error: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)

    async def refresh_outdoor(self, request: Request) -> Response:
        """Force HA to re-poll the outdoor brightness source entity."""
        try:
            import lux_tracker

            source = lux_tracker.get_outdoor_source()
            entity = None
            if source == "lux":
                entity = lux_tracker.get_sensor_entity()
            elif source == "weather":
                entity = lux_tracker.get_weather_entity()

            if not entity:
                return web.json_response({"status": "no_entity", "source": source})

            if not self.client:
                return web.json_response({"error": "Client not ready"}, status=500)

            await self.client.call_service(
                "homeassistant",
                "update_entity",
                {},
                {"entity_id": entity},
            )
            logger.info(f"[RefreshOutdoor] Triggered update_entity for {entity}")
            return web.json_response({"status": "ok", "entity": entity})
        except Exception as e:
            logger.error(f"[RefreshOutdoor] Error: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)

    async def get_area_settings(self, request: Request) -> Response:
        """Get settings for a specific area.

        Returns motion_function, motion_duration for the area.
        """
        area_id = request.match_info.get("area_id")
        if not area_id:
            return web.json_response({"error": "area_id required"}, status=400)

        try:
            config = await self.load_config()
            area_settings = config.get("area_settings", {})
            defaults = {
                "motion_function": "disabled",
                "motion_duration": 60,
                # Auto On
                "auto_on_enabled": False,
                "auto_on_source": "sunset",
                "auto_on_offset": 0,
                "auto_on_days": [0, 1, 2, 3, 4, 5, 6],
                "auto_on_time_1": None,
                "auto_on_days_1": [],
                "auto_on_time_2": None,
                "auto_on_days_2": [],
                "auto_on_fade": 0,
                "auto_on_skip_if_brighter": False,
                "auto_on_trigger_mode": "always",
                "auto_on_light": "circadian",
                "auto_on_override": None,
                # Auto Off
                "auto_off_enabled": False,
                "auto_off_source": "sunrise",
                "auto_off_offset": 0,
                "auto_off_days": [0, 1, 2, 3, 4, 5, 6],
                "auto_off_time_1": None,
                "auto_off_days_1": [],
                "auto_off_time_2": None,
                "auto_off_days_2": [],
                "auto_off_fade": 0,
                "auto_off_only_untouched": False,
                "auto_off_override": None,
            }
            # Migrate old wake_alarm keys if present
            area_data = area_settings.get(area_id, {})
            if "wake_alarm" in area_data:
                self._migrate_wake_alarm(area_data)
            settings = {**defaults, **area_settings.get(area_id, {})}
            return web.json_response(settings)

        except Exception as e:
            logger.error(f"[Area Settings] Error getting settings for {area_id}: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def save_area_settings(self, request: Request) -> Response:
        """Save settings for a specific area.

        Expects JSON body with motion_function and/or motion_duration.
        """
        area_id = request.match_info.get("area_id")
        if not area_id:
            return web.json_response({"error": "area_id required"}, status=400)

        try:
            data = await request.json()

            # Validate motion_function if provided
            valid_functions = ["disabled", "boost", "on_off", "on_only"]
            if (
                "motion_function" in data
                and data["motion_function"] not in valid_functions
            ):
                return web.json_response(
                    {
                        "error": f"Invalid motion_function. Must be one of: {valid_functions}"
                    },
                    status=400,
                )

            # Load raw config to preserve all keys (moments, switch_configs, etc.)
            config = await self.load_raw_config()

            # Initialize area_settings if not present
            if "area_settings" not in config:
                config["area_settings"] = {}

            # Initialize this area's settings if not present
            if area_id not in config["area_settings"]:
                config["area_settings"][area_id] = {
                    "motion_function": "disabled",
                    "motion_duration": 60,
                }

            area_cfg = config["area_settings"][area_id]

            # Migrate old wake_alarm keys if present
            if "wake_alarm" in area_cfg:
                self._migrate_wake_alarm(area_cfg)

            # Update with provided values
            if "motion_function" in data:
                area_cfg["motion_function"] = data["motion_function"]
            if "motion_duration" in data:
                area_cfg["motion_duration"] = int(data["motion_duration"])

            # Auto On/Off fields
            for prefix in ("auto_on", "auto_off"):
                for key in ("enabled", "skip_if_brighter", "only_untouched"):
                    full = f"{prefix}_{key}"
                    if full in data:
                        area_cfg[full] = bool(data[full])
                for key in ("source", "trigger_mode", "light"):
                    full = f"{prefix}_{key}"
                    if full in data:
                        area_cfg[full] = str(data[full])
                for key in ("offset", "fade"):
                    full = f"{prefix}_{key}"
                    if full in data:
                        area_cfg[full] = int(data[full])
                for key in ("days", "days_1", "days_2"):
                    full = f"{prefix}_{key}"
                    if full in data:
                        area_cfg[full] = list(data[full])
                for key in ("time_1", "time_2"):
                    full = f"{prefix}_{key}"
                    if full in data:
                        val = data[full]
                        area_cfg[full] = float(val) if val is not None else None
                for key in ("override",):
                    full = f"{prefix}_{key}"
                    if full in data:
                        area_cfg[full] = data[full]  # dict or None

            # Save config and update in-memory cache
            await self.save_config_to_file(config)
            glozone.set_config(config)

            # Clear fired state when auto schedule settings change
            # so edited schedules can re-trigger
            if self.client and hasattr(self.client, "primitives"):
                # Clear + re-mark fired state for changed auto schedules.
                # clear_auto_fired_for handles re-marking if trigger time
                # already passed today (prevents catch-up fire on save).
                prims = self.client.primitives
                for prefix in ("auto_on", "auto_off"):
                    if any(k.startswith(prefix + "_") for k in data):
                        prims.clear_auto_fired_for(area_id, prefix)

            logger.info(
                f"[Area Settings] Saved settings for {area_id}: {config['area_settings'][area_id]}"
            )
            return web.json_response(
                {"success": True, "settings": config["area_settings"][area_id]}
            )

        except Exception as e:
            logger.error(f"[Area Settings] Error saving settings for {area_id}: {e}")
            return web.json_response({"error": str(e)}, status=500)

    @staticmethod
    def _migrate_wake_alarm(settings: dict) -> None:
        """Migrate old wake_alarm keys to auto_on equivalents."""
        if settings.get("wake_alarm"):
            settings["auto_on_enabled"] = True
            mode = settings.get("wake_alarm_mode", "rhythm")
            if mode == "custom":
                settings["auto_on_source"] = "custom"
                settings["auto_on_time_1"] = settings.get("wake_alarm_time")
                settings["auto_on_days_1"] = settings.get(
                    "wake_alarm_days", [0, 1, 2, 3, 4, 5, 6]
                )
            else:
                # Rhythm mode used zone wake time + offset — migrate to sunrise
                # with the offset preserved. User may need to adjust.
                settings["auto_on_source"] = "sunrise"
                settings["auto_on_offset"] = settings.get("wake_alarm_offset", 0)
                settings["auto_on_days"] = settings.get(
                    "wake_alarm_days", [0, 1, 2, 3, 4, 5, 6]
                )
        # Clean up old keys
        for old_key in (
            "wake_alarm",
            "wake_alarm_mode",
            "wake_alarm_offset",
            "wake_alarm_time",
            "wake_alarm_days",
        ):
            settings.pop(old_key, None)

    def _ct_compensate(self, brightness: int, color_temp: int) -> int:
        """Apply CT brightness compensation for warm color temperatures."""
        try:
            raw_config = glozone.load_config_from_files()
            if not raw_config.get("ct_comp_enabled", False):
                return brightness
            handover_begin = raw_config.get("ct_comp_begin", 1650)
            handover_end = raw_config.get("ct_comp_end", 2250)
            max_factor = raw_config.get("ct_comp_factor", 1.7)
            if color_temp >= handover_end:
                return brightness
            if color_temp <= handover_begin:
                factor = max_factor
            else:
                pos = (handover_end - color_temp) / (handover_end - handover_begin)
                factor = 1.0 + pos * (max_factor - 1.0)
            return min(100, round(brightness * factor))
        except Exception:
            return brightness

    async def apply_light(self, request: Request) -> Response:
        """Apply brightness and color temperature to lights in an area.

        Uses per-light filter pipeline (area_factor, filter presets, off_threshold)
        to calculate individual brightness per filter group, then dispatches:
        - Color-capable lights: xy_color for full color range
        - CT-only lights: color_temp_kelvin (clamped to 2000K minimum)
        - Lights below off_threshold: turn_off
        """
        if not self.client:
            return web.json_response(
                {"error": "Home Assistant client not ready"}, status=503
            )

        try:
            data = await request.json()
            area_id = data.get("area_id")
            base_brightness = data.get("brightness")
            color_temp = data.get("color_temp")
            transition = data.get("transition", 0.3)

            if not area_id:
                return web.json_response({"error": "area_id is required"}, status=400)

            # Send through pipeline — applies sun bright, area factor, filters, CT comp
            bri = int(base_brightness) if base_brightness is not None else None
            ct = int(color_temp) if color_temp is not None else None
            await self.client.send_light(
                area_id,
                {"brightness": bri, "kelvin": ct},
                transition=transition,
            )

            logger.info(
                f"Live Design: Applied {bri}% / {ct}K to area {area_id} via pipeline"
            )
            return web.json_response({"status": "ok"})
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)
        except Exception as e:
            logger.error(f"Error applying light: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def set_circadian_mode(self, request: Request) -> Response:
        """Enable or disable Circadian mode for an area.

        Used by Live Design to pause automatic updates while designing.
        When circadian mode is disabled (is_circadian=False), Live Design becomes active
        and we fetch light capabilities for that area, save current light states,
        and notify main.py to skip this area in periodic updates.
        """
        try:
            data = await request.json()
            area_id = data.get("area_id")
            # Support both 'is_circadian' (new) and 'enabled' (legacy) field names
            is_circadian = data.get("is_circadian", data.get("enabled", True))

            if not area_id:
                return web.json_response({"error": "area_id is required"}, status=400)

            state.set_is_circadian(area_id, is_circadian)

            if not is_circadian:
                # Live Design is starting - get light capabilities from client cache
                if self.client:
                    area_lights = self.client.area_lights.get(area_id, [])
                    color_lights = []
                    ct_lights = []
                    for eid in area_lights:
                        modes = self.client.light_color_modes.get(eid, set())
                        if "xy" in modes or "hs" in modes or "rgb" in modes:
                            color_lights.append(eid)
                        else:
                            ct_lights.append(eid)

                    self.live_design_area = area_id
                    self.live_design_color_lights = color_lights
                    self.live_design_ct_lights = ct_lights
                    self.live_design_started_at = time.time()
                    self.live_design_last_heartbeat = time.time()

                    # Save current light states from cache for restoration later
                    all_lights = color_lights + ct_lights
                    self.live_design_saved_states = {}
                    for eid in all_lights:
                        s = self.client.cached_states.get(eid, {})
                        if s.get("state") == "on":
                            self.live_design_saved_states[eid] = s.get("attributes", {})

                    logger.info(
                        f"[Live Design] Started for area {area_id}: {len(color_lights)} color, {len(ct_lights)} CT-only, saved {len(self.live_design_saved_states)} states"
                    )

                    # Visual feedback: fade to off over 2 seconds
                    await self.client.call_service(
                        "light",
                        "turn_off",
                        {"transition": 2},
                        {"entity_id": all_lights},
                    )

                    self.client.handle_live_design(area_id, True)
                else:
                    logger.warning(
                        "[Live Design] Cannot fetch capabilities - client not ready"
                    )
                    self.live_design_area = area_id
                    self.live_design_color_lights = []
                    self.live_design_ct_lights = []
                    self.live_design_saved_states = {}
                    self.live_design_started_at = time.time()
                    self.live_design_last_heartbeat = time.time()
            else:
                # Live Design is ending - restore saved states and clear cache
                if self.live_design_area == area_id:
                    logger.info(f"[Live Design] Ended for area {area_id}")

                    all_lights = (
                        self.live_design_color_lights + self.live_design_ct_lights
                    )

                    # Visual feedback: fade to off over 2 seconds, then restore
                    if all_lights and self.client:
                        await self.client.call_service(
                            "light",
                            "turn_off",
                            {"transition": 2},
                            {"entity_id": all_lights},
                        )

                    # Restore saved light states with 2s transition
                    if self.live_design_saved_states and self.client:
                        for eid, attrs in self.live_design_saved_states.items():
                            restore_data = {"transition": 2}
                            if attrs.get("brightness"):
                                restore_data["brightness"] = attrs["brightness"]
                            xy = attrs.get("xy_color")
                            ct = attrs.get("color_temp")
                            if xy:
                                restore_data["xy_color"] = xy
                            elif ct:
                                restore_data["color_temp"] = ct
                            await self.client.call_service(
                                "light",
                                "turn_on",
                                restore_data,
                                {"entity_id": eid},
                            )
                        logger.info(
                            f"[Live Design] Restored {len(self.live_design_saved_states)} light states"
                        )

                    if self.client:
                        self.client.handle_live_design(area_id, False)

                    self.live_design_area = None
                    self.live_design_color_lights = []
                    self.live_design_ct_lights = []
                    self.live_design_saved_states = {}
                    self.live_design_started_at = 0.0
                    self.live_design_last_heartbeat = 0.0

            logger.info(
                f"[Live Design] Circadian mode {'enabled' if is_circadian else 'disabled'} for area {area_id}"
            )

            return web.json_response({"status": "ok", "is_circadian": is_circadian})
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)
        except Exception as e:
            logger.error(f"Error setting circadian mode: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def live_design_heartbeat(self, request: Request) -> Response:
        """Browser pings this while the rhythm-design page is open.

        Updates `live_design_last_heartbeat` only if the area_id matches
        the currently-active Live Design area, so a stale ping from a
        different area can't keep the wrong session alive.
        """
        try:
            data = await request.json()
            area_id = data.get("area_id")
            if not area_id:
                return web.json_response(
                    {"error": "area_id is required"}, status=400
                )
            if self.live_design_area == area_id:
                self.live_design_last_heartbeat = time.time()
                return web.json_response({"status": "ok", "active": True})
            return web.json_response({"status": "ok", "active": False})
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)
        except Exception as e:
            logger.error(f"Error processing live design heartbeat: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def _live_design_watcher(self):
        """Background loop that ends Live Design if heartbeats go stale.

        Handles the abandoned-browser case (closed tab, slept laptop, network
        drop). Lights resume circadian on the next periodic update; we don't
        attempt the saved-state restoration the manual-end path does, since
        the user's intent is to resume normal operation, not freeze them.
        """
        while True:
            try:
                await asyncio.sleep(LIVE_DESIGN_WATCHER_INTERVAL_SEC)
                if not self.live_design_area:
                    continue
                age = time.time() - (self.live_design_last_heartbeat or 0)
                if age <= LIVE_DESIGN_TIMEOUT_SEC:
                    continue
                area_id = self.live_design_area
                logger.info(
                    f"[Live Design] Watchdog: ending area {area_id} "
                    f"(no heartbeat for {age:.0f}s, threshold {LIVE_DESIGN_TIMEOUT_SEC}s)"
                )
                state.set_is_circadian(area_id, True)
                if self.client:
                    self.client.handle_live_design(area_id, False)
                self.live_design_area = None
                self.live_design_color_lights = []
                self.live_design_ct_lights = []
                self.live_design_saved_states = {}
                self.live_design_started_at = 0.0
                self.live_design_last_heartbeat = 0.0
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Live Design watcher error: {e}")

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

            # Use in-memory area names from main.py (shared process)
            ha_area_names = self.client.area_id_to_name if self.client else {}

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
                        areas.append(
                            {"id": area_id, "name": ha_area_names.get(area_id, area_id)}
                        )

                # Include rhythm settings from zone
                zone_cfg = glozone.get_zone_config(zone_name)
                result[zone_name] = {
                    **zone_cfg,
                    "areas": areas,
                    "runtime": runtime,
                    "is_default": zone_config.get("is_default", False),
                    "schedule_override": zone_config.get("schedule_override"),
                    "next_times": glozone.get_next_active_times(zone_name),
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

            if not self.client:
                return

            # Get areas from client cache
            ha_areas = [
                {"area_id": aid, "name": aname}
                for aid, aname in self.client.area_id_to_name.items()
            ]
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
                logger.info(
                    f"Zones already have {len(assigned_area_ids)} assigned areas - marking migration complete"
                )
                config["areas_migrated_v1"] = True
                await self.save_config_to_file(config)
                glozone.set_config(config)
                return

            # Find the default zone
            default_zone_name = next(
                (name for name, zc in zones.items() if zc.get("is_default")),
                next(iter(zones.keys()), None),
            )
            if not default_zone_name:
                logger.warning("No default zone found - skipping migration")
                return

            # Add unassigned areas to default zone
            unassigned = [
                a for a in ha_areas if a.get("area_id") not in assigned_area_ids
            ]

            if unassigned:
                logger.info(
                    f"Migrating {len(unassigned)} unassigned areas to default zone '{default_zone_name}'"
                )
                for area in unassigned:
                    zones[default_zone_name].setdefault("areas", []).append(
                        {
                            "id": area["area_id"],
                            "name": area.get("name", area["area_id"]),
                        }
                    )

            # Mark migration as complete (even if no areas to migrate)
            config["areas_migrated_v1"] = True

            # Save the updated config
            await self.save_config_to_file(config)
            glozone.set_config(config)
            logger.info(f"Area migration complete - migrated {len(unassigned)} areas")

        except Exception as e:
            logger.warning(f"Could not migrate unassigned areas: {e}")

    async def create_glozone(self, request: Request) -> Response:
        """Create a new Rhythm Zone."""
        try:
            data = await request.json()
            name = data.get("name")
            copy_from = data.get("copy_from")

            if not name:
                return web.json_response({"error": "name is required"}, status=400)

            config = await self.load_raw_config()

            if name in config.get("glozones", {}):
                return web.json_response(
                    {"error": f"Zone '{name}' already exists"}, status=409
                )

            # Build zone settings: copy from existing zone or use defaults
            zone_settings = {"areas": []}
            if copy_from and copy_from in config.get("glozones", {}):
                source_zone = config["glozones"][copy_from]
                for key in glozone.RHYTHM_SETTINGS:
                    if key in source_zone:
                        zone_settings[key] = source_zone[key]

            # Create the zone
            config.setdefault("glozones", {})[name] = zone_settings

            await self.save_config_to_file(config)
            glozone.set_config(config)

            if self.client:
                await self.client.handle_config_refresh()
                logger.info("Config refresh signaled after zone create")

            logger.info(f"Created Rhythm Zone: {name}")
            return web.json_response({"status": "created", "name": name})
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)
        except Exception as e:
            logger.error(f"Error creating zone: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def update_glozone(self, request: Request) -> Response:
        """Update a Rhythm Zone (areas, rename, or set as default)."""
        try:
            name = request.match_info.get("name")
            data = await request.json()

            config = await self.load_raw_config()

            if name not in config.get("glozones", {}):
                return web.json_response(
                    {"error": f"Rhythm Zone '{name}' not found"}, status=404
                )

            # Track whether lighting-relevant fields changed
            needs_refresh = False

            # Handle rename if "name" field is provided
            new_name = data.pop("name", None)
            if new_name and new_name != name:
                if new_name in config.get("glozones", {}):
                    return web.json_response(
                        {"error": f"Rhythm Zone '{new_name}' already exists"},
                        status=400,
                    )
                # Rename the zone (preserve is_default status)
                config["glozones"][new_name] = config["glozones"].pop(name)
                logger.info(f"Renamed Rhythm Zone: {name} -> {new_name}")
                name = new_name

            # Update areas if provided (replaces entire list)
            if "areas" in data:
                config["glozones"][name]["areas"] = data["areas"]
                needs_refresh = True

            # Accept RHYTHM_SETTINGS keys directly
            for key in glozone.RHYTHM_SETTINGS:
                if key in data:
                    config["glozones"][name][key] = data[key]
                    needs_refresh = True

            # Handle is_default - setting this zone as the default
            if data.get("is_default"):
                # Clear is_default from all zones, set on this one
                for zn, zc in config["glozones"].items():
                    zc["is_default"] = zn == name
                logger.info(f"Set '{name}' as default zone")
                needs_refresh = True

            await self.save_config_to_file(config)
            glozone.set_config(config)

            if needs_refresh and self.client:
                await self.client.handle_config_refresh()
                logger.info("Config refresh signaled after zone update")

            logger.info(f"Updated Rhythm Zone: {name}")
            return web.json_response({"status": "updated", "name": name})
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)
        except Exception as e:
            logger.error(f"Error updating zone: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def update_glozone_settings(self, request: Request) -> Response:
        """Update only the rhythm settings of a Rhythm Zone."""
        try:
            name = request.match_info.get("name")
            data = await request.json()

            config = await self.load_raw_config()

            if name not in config.get("glozones", {}):
                return web.json_response(
                    {"error": f"Rhythm Zone '{name}' not found"}, status=404
                )

            # Handle rename via "name" field
            new_name = data.pop("name", None)
            if new_name and new_name != name:
                if new_name in config.get("glozones", {}):
                    return web.json_response(
                        {"error": f"Rhythm Zone '{new_name}' already exists"},
                        status=400,
                    )
                config["glozones"][new_name] = config["glozones"].pop(name)
                logger.info(f"Renamed Rhythm Zone: {name} -> {new_name}")
                name = new_name

            # Update only RHYTHM_SETTINGS keys
            updated_keys = []
            for key, value in data.items():
                if key in glozone.RHYTHM_SETTINGS:
                    config["glozones"][name][key] = value
                    updated_keys.append(key)

            await self.save_config_to_file(config)
            glozone.set_config(config)

            if updated_keys and self.client:
                await self.client.handle_config_refresh()
                logger.info(
                    f"Config refresh signaled after zone settings update: {updated_keys}"
                )

            logger.info(f"Updated Rhythm Zone settings: {name} ({updated_keys})")
            return web.json_response({"status": "updated", "name": name})
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)
        except Exception as e:
            logger.error(f"Error updating zone settings: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def delete_glozone(self, request: Request) -> Response:
        """Delete a GloZone (moves areas to default zone)."""
        try:
            name = request.match_info.get("name")

            config = await self.load_raw_config()
            zones = config.get("glozones", {})

            if name not in zones:
                return web.json_response(
                    {"error": f"Zone '{name}' not found"}, status=404
                )

            # Cannot delete the last zone
            if len(zones) <= 1:
                return web.json_response(
                    {"error": "Cannot delete the last zone"}, status=400
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
                next((zn for zn in zones.keys() if zn != name), None),
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

            if self.client:
                await self.client.handle_config_refresh()
                logger.info("Config refresh signaled after zone delete")

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
                return web.json_response(
                    {"error": "order must be a list of zone names"}, status=400
                )

            config = await self.load_raw_config()
            zones = config.get("glozones", {})

            # Validate all names match existing zones
            if set(order) != set(zones.keys()):
                return web.json_response(
                    {"error": "order must contain exactly the existing zone names"},
                    status=400,
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
                return web.json_response(
                    {"error": "area_ids must be a list"}, status=400
                )

            config = await self.load_raw_config()
            zones = config.get("glozones", {})

            if name not in zones:
                return web.json_response(
                    {"error": f"Zone '{name}' not found"}, status=404
                )

            zone_areas = zones[name].get("areas", [])

            # Build lookup: area_id -> area entry
            area_lookup = {}
            for area in zone_areas:
                aid = area.get("id") if isinstance(area, dict) else area
                area_lookup[aid] = area

            # Validate submitted IDs exist in this zone
            unknown = set(area_ids) - set(area_lookup.keys())
            if unknown:
                return web.json_response(
                    {"error": f"Unknown area IDs: {unknown}"}, status=400
                )

            # Rebuild areas list in new order, keeping orphan areas at end
            submitted = set(area_ids)
            orphans = [area_lookup[aid] for aid in area_lookup if aid not in submitted]
            if orphans:
                orphan_ids = [
                    a.get("id") if isinstance(a, dict) else a for a in orphans
                ]
                logger.info(
                    f"Zone '{name}' has {len(orphans)} areas not in HA, keeping at end: {orphan_ids}"
                )
            zones[name]["areas"] = [area_lookup[aid] for aid in area_ids] + orphans

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
                return web.json_response(
                    {"error": f"Zone '{zone_name}' not found"}, status=404
                )

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
                    a
                    for a in zc.get("areas", [])
                    if (isinstance(a, dict) and a.get("id") != area_id)
                    or (isinstance(a, str) and a != area_id)
                ]

            # Add to target zone
            config["glozones"][zone_name]["areas"].append(
                {"id": area_id, "name": area_name}
            )

            await self.save_config_to_file(config)
            glozone.set_config(config)

            # Reset area state if moving to a different zone (new Glo config)
            if current_zone and current_zone != zone_name:
                state.update_area(
                    area_id,
                    {
                        "frozen_at": None,
                        "brightness_mid": None,
                        "color_mid": None,
                    },
                )
                logger.info(
                    f"Reset state for area {area_id} (moved from {current_zone} to {zone_name})"
                )

            logger.info(f"Added area {area_id} to zone {zone_name}")
            return web.json_response(
                {"status": "added", "area_id": area_id, "zone": zone_name}
            )
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
                return web.json_response(
                    {"error": f"Zone '{zone_name}' not found"}, status=404
                )

            # Find the default zone
            default_zone = next(
                (zn for zn, zc in zones.items() if zc.get("is_default")),
                next(iter(zones.keys()), None),
            )

            # Can't remove from default zone (areas must always be in a zone)
            if zone_name == default_zone:
                return web.json_response(
                    {
                        "error": "Cannot remove area from default zone. Move it to another zone instead."
                    },
                    status=400,
                )

            # Find and remove the area
            areas = zones[zone_name].get("areas", [])
            area_entry = None
            new_areas = []
            for a in areas:
                if (isinstance(a, dict) and a.get("id") == area_id) or (
                    isinstance(a, str) and a == area_id
                ):
                    area_entry = a
                else:
                    new_areas.append(a)

            if area_entry is None:
                return web.json_response(
                    {"error": f"Area '{area_id}' not found in zone '{zone_name}'"},
                    status=404,
                )

            config["glozones"][zone_name]["areas"] = new_areas

            # Add to default zone
            if default_zone:
                zones[default_zone].setdefault("areas", []).append(area_entry)

            await self.save_config_to_file(config)
            glozone.set_config(config)

            logger.info(
                f"Removed area {area_id} from zone {zone_name}, moved to {default_zone}"
            )
            return web.json_response({"status": "removed", "area_id": area_id})
        except Exception as e:
            logger.error(f"Error removing area from zone: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def purge_area_from_config(self, request: Request) -> Response:
        """Remove an area from all zones in config (for areas deleted from HA)."""
        try:
            area_id = request.match_info.get("area_id")
            config = await self.load_raw_config()
            zones = config.get("glozones", {})

            removed_from = []
            for zone_name, zone_config in zones.items():
                areas = zone_config.get("areas", [])
                new_areas = [
                    a
                    for a in areas
                    if not (
                        (isinstance(a, dict) and a.get("id") == area_id)
                        or (isinstance(a, str) and a == area_id)
                    )
                ]
                if len(new_areas) < len(areas):
                    zone_config["areas"] = new_areas
                    removed_from.append(zone_name)

            # Remove area from switch scopes, motion sensors, and contact sensors
            # These are stored in switches_config.json, not designer_config
            controls_cleaned = switches.purge_area(area_id)

            # Always remove from runtime state so periodic refresh stops updating it
            state.remove_area(area_id)

            config_changed = removed_from or controls_cleaned
            if removed_from:
                await self.save_config_to_file(config)
                glozone.set_config(config)
                parts = [f"zones: {removed_from}"]
                if controls_cleaned:
                    parts.append(f"{controls_cleaned} control config(s)")
                logger.info(f"Purged area {area_id} from {', '.join(parts)}")
            elif controls_cleaned:
                logger.info(
                    f"Purged area {area_id} from {controls_cleaned} control config(s)"
                )

            if self.client:
                await self.client.handle_service_event("purge_area", area_id)

            return web.json_response(
                {"status": "purged", "area_id": area_id, "removed_from": removed_from}
            )
        except Exception as e:
            logger.error(f"Error purging area from config: {e}")
            return web.json_response({"error": str(e)}, status=500)

    # -------------------------------------------------------------------------
    # Moments API - CRUD for whole-home presets
    # -------------------------------------------------------------------------

    def _next_moment_id(self, existing_ids: set) -> str:
        """Generate next auto-increment moment ID (moment_1, moment_2, ...)."""
        counter = 1
        while f"moment_{counter}" in existing_ids:
            counter += 1
        return f"moment_{counter}"

    @staticmethod
    def _normalize_moment(moment: dict) -> dict:
        """Normalize moment exceptions to {action, timer} format."""
        exceptions = moment.get("exceptions", {})
        if exceptions:
            normalized = {}
            for area_id, val in exceptions.items():
                if isinstance(val, str):
                    normalized[area_id] = {"action": val, "timer": 0}
                elif isinstance(val, dict):
                    normalized[area_id] = {
                        "action": val.get("action", "leave_alone"),
                        "timer": val.get("timer", 0),
                    }
                else:
                    normalized[area_id] = {"action": "leave_alone", "timer": 0}
            moment = {**moment, "exceptions": normalized}
        return moment

    async def get_moments(self, request: Request) -> Response:
        """Get all moments."""
        try:
            config = await self.load_raw_config()
            moments = config.get("moments", {})
            moments = {k: self._normalize_moment(v) for k, v in moments.items()}
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
                return web.json_response(
                    {"error": f"Moment '{moment_id}' not found"}, status=404
                )

            return web.json_response(
                {"moment": self._normalize_moment(moments[moment_id]), "id": moment_id}
            )
        except Exception as e:
            logger.error(f"Error getting moment: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def create_moment(self, request: Request) -> Response:
        """Create a new moment."""
        try:
            data = await request.json()
            name = data.get("name", "").strip()

            if not name:
                return web.json_response(
                    {"error": "Moment name is required"}, status=400
                )

            config = await self.load_raw_config()
            moments = config.setdefault("moments", {})

            # Generate stable auto-increment ID
            moment_id = self._next_moment_id(set(moments.keys()))

            # Create the moment with defaults
            moments[moment_id] = {
                "name": name,
                "icon": data.get("icon", "mdi:lightbulb"),
                "category": data.get("category", "utility"),
                "trigger": data.get("trigger", {"type": "primitive"}),
                "default_action": data.get("default_action", "off"),
                "exceptions": data.get("exceptions", {}),
                "timer": data.get("timer", 0),
            }

            # Add fun moment fields if applicable
            if data.get("category") == "fun":
                moments[moment_id]["default_participation"] = data.get(
                    "default_participation", "if_on"
                )
                if "effect" in data:
                    moments[moment_id]["effect"] = data["effect"]

            await self.save_config_to_file(config)

            logger.info(f"Created moment: {name} (id: {moment_id})")
            return web.json_response(
                {"status": "created", "id": moment_id, "moment": moments[moment_id]}
            )
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
                return web.json_response(
                    {"error": f"Moment '{moment_id}' not found"}, status=404
                )

            moment = moments[moment_id]

            # Update fields (ID stays stable; only the name field changes)
            for field in [
                "name",
                "icon",
                "category",
                "trigger",
                "default_action",
                "exceptions",
                "default_participation",
                "effect",
                "timer",
            ]:
                if field in data:
                    moment[field] = data[field]

            await self.save_config_to_file(config)

            logger.info(f"Updated moment: {moment_id}")
            return web.json_response(
                {"status": "updated", "id": moment_id, "moment": moment}
            )
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
                return web.json_response(
                    {"error": f"Moment '{moment_id}' not found"}, status=404
                )

            del moments[moment_id]
            await self.save_config_to_file(config)

            # Clean up magic button references in all switches
            action_ref = f"set_{moment_id}"
            cleaned = 0
            for sw in switches.get_all_switches().values():
                orphaned_keys = [
                    k for k, v in sw.magic_buttons.items() if v == action_ref
                ]
                for k in orphaned_keys:
                    del sw.magic_buttons[k]
                    cleaned += 1
            if cleaned:
                switches._save()
                logger.info(
                    f"Removed {cleaned} magic button reference(s) to deleted moment '{moment_id}'"
                )

            logger.info(f"Deleted moment: {moment_id}")
            return web.json_response({"status": "deleted", "id": moment_id})
        except Exception as e:
            logger.error(f"Error deleting moment: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def run_moment(self, request: Request) -> Response:
        """Run a moment – apply set_<moment_id> via direct client call."""
        try:
            moment_id = request.match_info.get("moment_id")
            config = await self.load_raw_config()
            moments = config.get("moments", {})
            if moment_id not in moments:
                return web.json_response(
                    {"error": f"Moment '{moment_id}' not found"}, status=404
                )

            if self.client:
                await self.client.handle_service_event(f"set_{moment_id}", "__moment__")
                logger.info(f"Applied moment '{moment_id}'")
                return web.json_response({"status": "ok", "moment_id": moment_id})
            return web.json_response({"error": "Client not connected"}, status=503)
        except Exception as e:
            logger.error(f"Error running moment: {e}")
            return web.json_response({"error": str(e)}, status=500)

    # -------------------------------------------------------------------------
    # GloZone API - Actions (glo_up, glo_down, glo_reset)
    # -------------------------------------------------------------------------

    async def handle_glo_up(self, request: Request) -> Response:
        """Handle glo_up action - push area state to zone, propagate to all areas."""
        try:
            data = await request.json()
            area_id = data.get("area_id")

            if not area_id:
                return web.json_response({"error": "area_id is required"}, status=400)

            if self.client:
                await self.client.handle_service_event("glo_up", area_id)
                return web.json_response(
                    {"status": "ok", "action": "glo_up", "area_id": area_id}
                )
            return web.json_response({"error": "Client not connected"}, status=503)

        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)
        except Exception as e:
            logger.error(f"Error handling glo_up: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def handle_glo_down(self, request: Request) -> Response:
        """Handle glo_down action - pull zone state to area."""
        try:
            data = await request.json()
            area_id = data.get("area_id")

            if not area_id:
                return web.json_response({"error": "area_id is required"}, status=400)

            if self.client:
                await self.client.handle_service_event("glo_down", area_id)
                return web.json_response(
                    {"status": "ok", "action": "glo_down", "area_id": area_id}
                )
            return web.json_response({"error": "Client not connected"}, status=503)

        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)
        except Exception as e:
            logger.error(f"Error handling glo_down: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def handle_glo_reset(self, request: Request) -> Response:
        """Handle glo_reset action - reset zone and all member areas."""
        try:
            data = await request.json()
            area_id = data.get("area_id")

            if not area_id:
                return web.json_response({"error": "area_id is required"}, status=400)

            if self.client:
                await self.client.handle_service_event("glo_reset", area_id)
                return web.json_response(
                    {"status": "ok", "action": "glo_reset", "area_id": area_id}
                )
            return web.json_response({"error": "Client not connected"}, status=503)

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
            "lights_on",
            "lights_off",
            "lights_toggle",
            "circadian_on",
            "circadian_off",
            "step_up",
            "step_down",
            "bright_up",
            "bright_down",
            "color_up",
            "color_down",
            "freeze_toggle",
            "glo_up",
            "glo_down",
            "glo_reset",
            "boost",
            "full_send",
            "set_nitelite",
            "set_britelite",
            "set_circadian",
            "set_position",
            "set_phase_time",
            "reset_brightness_override",
            "reset_color_override",
            "reset_phase",
            "circadian_adjust",
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
                return web.json_response(
                    {
                        "error": f"Invalid action: {action}. Valid actions: {sorted(VALID_ACTIONS)}"
                    },
                    status=400,
                )

            # For boost, set state directly for immediate UI feedback
            if action == "boost":
                # State is shared in-memory (same process as main.py)
                if state.is_boosted(area_id):
                    # End boost: clear state, restore lighting
                    state.clear_boost(area_id)
                    logger.info(
                        f"[boost] Cleared boost state for area {area_id}, restoring lighting"
                    )
                    action = "boost_off"
                else:
                    # Start boost: set state, apply lighting
                    raw_config = glozone.load_config_from_files()
                    boost_amount = raw_config.get("boost_default", 30)
                    is_on = state.is_circadian(area_id) and state.get_is_on(area_id)
                    state.set_boost(
                        area_id,
                        started_from_off=not is_on,
                        expires_at="forever",
                        brightness=boost_amount,
                    )
                    if not glozone.is_area_in_any_zone(area_id):
                        glozone.add_area_to_default_zone(area_id)
                    state.enable_circadian_and_set_on(area_id, True)
                    logger.info(
                        f"[boost] Set boost state for area {area_id} (amount={boost_amount}%), applying lighting"
                    )
                    action = "boost_on"

            # Build extra kwargs for actions that need them
            extra_kwargs = {}
            if action == "set_position":
                value = data.get("value")
                if value is None:
                    return web.json_response(
                        {"error": "value required for set_position"}, status=400
                    )
                extra_kwargs["value"] = float(value)
                extra_kwargs["mode"] = data.get("mode", "step")
            elif action == "set_phase_time":
                target_time = data.get("target_time")
                if target_time is None:
                    return web.json_response(
                        {"error": "target_time required for set_phase_time"}, status=400
                    )
                extra_kwargs["target_time"] = float(target_time)
            elif action == "circadian_adjust":
                value = data.get("value")
                if value is None:
                    return web.json_response(
                        {"error": "value required for circadian_adjust"},
                        status=400,
                    )
                extra_kwargs["target_brightness"] = float(value)
            elif action == "set_circadian":
                value = data.get("value")
                if value is not None:
                    extra_kwargs["brightness"] = float(value)

            if self.client:
                result = await self.client.handle_service_event(
                    action, area_id, **extra_kwargs
                )
                logger.info(f"Executed {action} for area {area_id}")
                resp = {"status": "ok", "action": action, "area_id": area_id}
                # Signal "at limit" so UI callers (e.g. the Adjust-card hero
                # arrows) can fall through to a time-based shift on plateau.
                # step_up returns None or "sun_dimming_limit" at limit; step_down
                # returns None at limit; both return True on success.
                if action in ("step_up", "step_down") and result is not True:
                    resp["at_limit"] = True
                # Check for sun dimming hint on step_up
                if action == "step_up" and result == "sun_dimming_limit":
                    resp["hint"] = (
                        "Circadian curve at max — use bright up to override sun dimming"
                    )
                return web.json_response(resp)
            return web.json_response({"error": "Client not connected"}, status=503)

        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)
        except Exception as e:
            logger.error(f"Error handling area action: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def get_slider_preview(self, request: Request) -> Response:
        """Return kelvin values at 10 brightness sample points for slider gradient.

        Called on-demand (pointerdown on homepage, page load on area detail).
        Simulates what circadian_adjust P2 would produce at each brightness.

        Query params: area_id (required), points (optional, default 10)
        Returns: {"points": [{"brightness": N, "kelvin": N}, ...]}
        """
        area_id = request.query.get("area_id")
        if not area_id:
            return web.json_response({"error": "area_id is required"}, status=400)

        num_points = int(request.query.get("points", 10))
        num_points = max(3, min(20, num_points))

        try:
            from brain import (
                CircadianLight,
                Config,
                AreaState,
                SunTimes,
                calculate_sun_times,
                calculate_natural_light_factor,
            )

            config_dict = glozone.get_effective_config_for_area(area_id)
            area_config = Config.from_dict(config_dict)
            area_state_dict = state.get_area(area_id)
            area_state = AreaState.from_dict(area_state_dict)

            hour = (
                area_state.frozen_at
                if area_state.frozen_at is not None
                else get_current_hour()
            )

            # Sun times
            sun_times = SunTimes()
            try:
                from zoneinfo import ZoneInfo

                latitude = float(os.getenv("HASS_LATITUDE", "35.0"))
                longitude = float(os.getenv("HASS_LONGITUDE", "-78.6"))
                timezone = os.getenv("HASS_TIME_ZONE", "US/Eastern")
                try:
                    tzinfo = ZoneInfo(timezone)
                except Exception:
                    tzinfo = None
                now = datetime.now(tzinfo)
                date_str = now.strftime("%Y-%m-%d")
                sun_dict = calculate_sun_times(latitude, longitude, date_str)

                def iso_to_hour(iso_str, default):
                    if not iso_str:
                        return default
                    try:
                        dt = datetime.fromisoformat(iso_str)
                        if tzinfo and dt.tzinfo:
                            dt = dt.astimezone(tzinfo)
                        return dt.hour + dt.minute / 60.0 + dt.second / 3600.0
                    except Exception:
                        return default

                sun_times = SunTimes(
                    sunrise=iso_to_hour(sun_dict.get("sunrise"), 6.0),
                    sunset=iso_to_hour(sun_dict.get("sunset"), 18.0),
                    solar_noon=iso_to_hour(sun_dict.get("noon"), 12.0),
                    solar_mid=(iso_to_hour(sun_dict.get("noon"), 12.0) + 12.0) % 24.0,
                )

                outdoor_norm = lux_tracker.get_outdoor_normalized()
                outdoor_source = lux_tracker.get_outdoor_source()
                if outdoor_norm is None:
                    outdoor_norm = 0.0
                    outdoor_source = "none"
                sun_times.outdoor_normalized = outdoor_norm
                sun_times.outdoor_source = outdoor_source
            except Exception as e:
                logger.debug(f"[SliderPreview] Error calculating sun times: {e}")

            b_min = area_config.min_brightness
            b_max = area_config.max_brightness

            # Pipeline factors for inverting actual → curve brightness
            area_sun_exposure = glozone.get_area_natural_light_exposure(area_id)
            area_bri_sensitivity = glozone.get_zone_config_for_area(area_id).get(
                "brightness_sensitivity", 1.0
            )
            outdoor_norm = lux_tracker.get_outdoor_normalized() or 0.0
            sun_bright_factor = calculate_natural_light_factor(
                area_sun_exposure, outdoor_norm, area_bri_sensitivity
            )
            area_factor = glozone.get_area_brightness_factor(area_id)

            boost_amount = 0
            if state.is_boosted(area_id):
                boost_st = state.get_boost_state(area_id)
                boost_amount = boost_st.get("boost_brightness") or 0

            # Compute curve limits in actual-brightness space
            # Pipeline: curve × sun_bright × area_factor + override + boost
            denominator = max(0.01, sun_bright_factor * area_factor)
            curve_max_actual = b_max * denominator + boost_amount
            curve_min_actual = max(0, b_min * denominator + boost_amount)

            # Kelvin at curve limits (computed once)
            preview_state = AreaState(
                is_circadian=area_state.is_circadian,
                is_on=area_state.is_on,
                frozen_at=area_state.frozen_at,
                brightness_mid=area_state.brightness_mid,
                color_mid=area_state.color_mid,
            )
            result_max = CircadianLight.calculate_set_position(
                hour=hour,
                position=100,
                dimension="step",
                config=area_config,
                state=preview_state,
                sun_times=sun_times,
            )
            result_min = CircadianLight.calculate_set_position(
                hour=hour,
                position=0,
                dimension="step",
                config=area_config,
                state=preview_state,
                sun_times=sun_times,
            )
            kelvin_at_max = result_max.color_temp
            kelvin_at_min = result_min.color_temp

            # Sample points across the actual brightness range (b_min to b_max)
            points = []
            for i in range(num_points + 1):
                frac = i / num_points
                target_actual = b_min + (b_max - b_min) * frac

                if target_actual >= curve_max_actual:
                    # P3 territory (above curve max) — color holds at max
                    kelvin = kelvin_at_max
                elif target_actual <= curve_min_actual:
                    # P3 territory (below curve min) — color holds at min
                    kelvin = kelvin_at_min
                else:
                    # P2 territory — invert to curve brightness, get color
                    curve_bri = (target_actual - boost_amount) / denominator
                    curve_bri = max(b_min, min(b_max, curve_bri))
                    b_range = b_max - b_min
                    position = (
                        ((curve_bri - b_min) / b_range * 100) if b_range > 0 else 50
                    )
                    position = max(0, min(100, position))

                    result = CircadianLight.calculate_set_position(
                        hour=hour,
                        position=position,
                        dimension="step",
                        config=area_config,
                        state=preview_state,
                        sun_times=sun_times,
                    )
                    kelvin = result.color_temp

                points.append(
                    {
                        "brightness": round(target_actual),
                        "kelvin": round(kelvin),
                    }
                )

            return web.json_response({"points": points})

        except Exception as e:
            logger.error(f"[SliderPreview] Error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def handle_zone_action(self, request: Request) -> Response:
        """Handle zone-level action (modifies zone state only, no light control).

        Valid actions: step_up, step_down, bright_up, bright_down, color_up, color_down
        """
        VALID_ZONE_ACTIONS = {
            "step_up",
            "step_down",
            "bright_up",
            "bright_down",
            "color_up",
            "color_down",
            "glozone_reset",
            "glozone_reset_full",
            "glozone_down",
            "set_position",
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
                return web.json_response(
                    {
                        "error": f"Invalid zone action: {action}. Valid: {sorted(VALID_ZONE_ACTIONS)}"
                    },
                    status=400,
                )

            # Build extra kwargs for set_position
            extra_kwargs = {}
            if action == "set_position":
                value = data.get("value")
                if value is None:
                    return web.json_response(
                        {"error": "value required for set_position"}, status=400
                    )
                extra_kwargs["value"] = float(value)
                extra_kwargs["mode"] = data.get("mode", "step")

            if self.client:
                await self.client.handle_zone_action(action, zone_name, **extra_kwargs)
                logger.info(f"Executed zone {action} for zone '{zone_name}'")
                return web.json_response(
                    {"status": "ok", "action": action, "zone_name": zone_name}
                )
            return web.json_response({"error": "Client not connected"}, status=503)

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
        Also auto-creates inactive control configs for unconfigured devices.
        """
        try:
            # Clear areas cache so it gets refreshed on next request
            self.cached_areas_list = None
            logger.info("Cleared areas cache for sync")

            if self.client:
                await self.client.run_manual_sync()
            else:
                return web.json_response({"error": "Client not connected"}, status=503)

            return web.json_response(
                {"success": True, "message": "Device sync triggered"}
            )
        except Exception as e:
            logger.error(f"Error triggering device sync: {e}")
            return web.json_response({"error": str(e)}, status=500)

    def _auto_create_controls(self, ha_controls, configured_switches) -> int:
        """Auto-create inactive control configs for unconfigured HA devices.

        Uses already-fetched HA controls and configured switches to avoid
        duplicate API calls. Called from get_controls() on page load.
        """
        try:
            created = 0
            for ctrl in ha_controls:
                ieee = ctrl.get("ieee")
                device_id = ctrl.get("device_id")
                category = ctrl.get("category")
                area_id = ctrl.get("area_id")
                name = ctrl.get("name", "Unknown")

                if not ctrl.get("supported"):
                    continue
                if not area_id:
                    continue  # Can't auto-scope without an area

                if category == "switch":
                    detected_type = ctrl.get("type")
                    if not detected_type or not ieee:
                        continue
                    if ieee in configured_switches:
                        continue
                    switches.add_switch(
                        switches.SwitchConfig(
                            id=ieee,
                            name=name,
                            type=detected_type,
                            scopes=[switches.SwitchScope(areas=[area_id])],
                            device_id=device_id,
                            inactive=True,
                        )
                    )
                    logger.info(
                        f"[sync] Auto-created switch: {name} ({ieee}) -> area {area_id}"
                    )
                    created += 1

                elif category in ("motion_sensor", "camera"):
                    if not device_id:
                        continue
                    existing = switches.get_motion_sensor_by_device_id(device_id)
                    if existing:
                        continue
                    switches.add_motion_sensor(
                        switches.MotionSensorConfig(
                            id=device_id,
                            name=name,
                            scopes=[switches.MotionScope(areas=[area_id])],
                            device_id=device_id,
                            inactive=True,
                        )
                    )
                    logger.info(
                        f"[sync] Auto-created motion sensor: {name} ({device_id}) -> area {area_id}"
                    )
                    created += 1

                elif category == "contact_sensor":
                    if not device_id:
                        continue
                    existing = switches.get_contact_sensor_by_device_id(device_id)
                    if existing:
                        continue
                    switches.add_contact_sensor(
                        switches.ContactSensorConfig(
                            id=device_id,
                            name=name,
                            scopes=[switches.ContactScope(areas=[area_id])],
                            device_id=device_id,
                            inactive=True,
                        )
                    )
                    logger.info(
                        f"[sync] Auto-created contact sensor: {name} ({device_id}) -> area {area_id}"
                    )
                    created += 1

            if created:
                logger.info(f"[sync] Auto-created {created} control(s) as inactive")
            return created
        except Exception as e:
            logger.error(f"[sync] Error auto-creating controls: {e}")
            return 0

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

            return web.json_response(
                {
                    "mappings": mappings,
                    "custom_mappings": custom,
                }
            )
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
                return web.json_response(
                    {"error": "Expected object with switch_type keys"}, status=400
                )

            # Save the mappings
            if switches.save_custom_mappings(data):
                return web.json_response({"status": "success"})
            else:
                return web.json_response(
                    {"error": "Failed to save mappings"}, status=500
                )

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

            return web.json_response(
                {
                    "categories": categories,
                    "when_off_options": when_off_options,
                }
            )
        except Exception as e:
            logger.error(f"Error getting switchmap actions: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def get_switches(self, request: Request) -> Response:
        """Get all configured switches with area names looked up from HA."""
        try:
            switches_data = switches.get_switches_summary()

            # Try to enrich with area names and detect stale devices
            try:
                device_area_map, all_device_ids = await self._fetch_device_areas()
                for sw in switches_data:
                    device_id = sw.get("device_id")
                    if device_id and device_id in device_area_map:
                        sw["area_name"] = device_area_map[device_id]
                    # Mark as stale if device_id is set but not in HA device registry
                    if device_id and all_device_ids and device_id not in all_device_ids:
                        sw["stale"] = True
            except Exception as e:
                logger.warning(f"Could not fetch device areas: {e}")

            return web.json_response({"switches": switches_data})
        except Exception as e:
            logger.error(f"Error getting switches: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def _fetch_device_areas(self):
        """Get device_id -> area_name mapping and all device IDs from client cache."""
        if not self.client:
            return {}, set()

        device_areas = {}
        all_device_ids = set()
        for device_id, device_info in self.client.device_registry.items():
            all_device_ids.add(device_id)
            area_id = device_info.get("area_id")
            if area_id:
                area_name = self.client.area_id_to_name.get(area_id)
                if area_name:
                    device_areas[device_id] = area_name

        return device_areas, all_device_ids

    async def flash_light(self, request: Request) -> Response:
        """Flash a light entity briefly so the user can identify it.

        POST body: {"entity_id": "light.xyz"}
        """
        try:
            data = await request.json()
            entity_id = data.get("entity_id")
            if not entity_id or not entity_id.startswith("light."):
                return web.json_response(
                    {"error": "Valid light entity_id required"}, status=400
                )

            if not self.client:
                return web.json_response({"error": "Client not ready"}, status=500)

            # Get current state from cache
            current_state = self.client.cached_states.get(entity_id, {})
            was_on = current_state.get("state") == "on"
            attrs = current_state.get("attributes", {}) if was_on else {}
            orig_brightness = attrs.get("brightness", 128)

            # Flash: turn on bright
            await self.client.call_service(
                "light",
                "turn_on",
                {"brightness": 255, "transition": 0},
                {"entity_id": entity_id},
            )

            await asyncio.sleep(0.5)

            # Restore
            if not was_on:
                await self.client.call_service(
                    "light",
                    "turn_off",
                    {"transition": 0},
                    {"entity_id": entity_id},
                )
            else:
                restore_data = {"brightness": orig_brightness, "transition": 0}
                xy = attrs.get("xy_color")
                ct = attrs.get("color_temp")
                if xy:
                    restore_data["xy_color"] = xy
                elif ct:
                    restore_data["color_temp"] = ct
                await self.client.call_service(
                    "light",
                    "turn_on",
                    restore_data,
                    {"entity_id": entity_id},
                )

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

        if not self.client:
            return web.json_response({"lights": []})

        try:
            lights = []
            entire_area_lights = []

            # Determine which areas to scan
            if show_all:
                target_areas = list(self.client.area_lights.keys())
            else:
                target_areas = [area_id] if area_id in self.client.area_lights else []

            for aid in target_areas:
                area_name = self.client.area_id_to_name.get(aid, "Unknown")
                for eid in self.client.area_lights.get(aid, []):
                    s = self.client.cached_states.get(eid, {})
                    attrs = s.get("attributes", {})
                    is_group = bool(
                        attrs.get("entity_id")
                        or attrs.get("is_group")
                        or attrs.get("is_hue_group")
                    )

                    if show_all:
                        if is_group:
                            entire_area_lights.append(
                                {
                                    "entity_id": eid,
                                    "name": f"Entire area: {area_name}",
                                    "area_id": aid,
                                    "is_group": True,
                                }
                            )
                        else:
                            base_name = (
                                attrs.get("friendly_name")
                                or eid.replace("light.", "").replace("_", " ").title()
                            )
                            lights.append(
                                {
                                    "entity_id": eid,
                                    "name": f"{area_name}: {base_name}",
                                    "area_id": aid,
                                }
                            )
                    else:
                        if is_group:
                            name = (
                                f"Entire area: {area_name}"
                                if area_name
                                else "Entire area"
                            )
                            entire_area_lights.append(
                                {"entity_id": eid, "name": name, "is_group": True}
                            )
                        else:
                            name = (
                                attrs.get("friendly_name")
                                or eid.replace("light.", "").replace("_", " ").title()
                            )
                            lights.append({"entity_id": eid, "name": name})

            entire_area_lights.sort(key=lambda x: x["name"].lower())
            lights.sort(key=lambda x: x["name"].lower())
            return web.json_response({"lights": entire_area_lights + lights})
        except Exception as e:
            logger.error(f"Error fetching area lights: {e}", exc_info=True)
            return web.json_response({"lights": []})

    async def get_sensors(self, request: Request) -> Response:
        """Get sensor entities from HA, optionally filtered by device_class.

        Query params:
        - device_class: Filter to specific device class (e.g. 'illuminance')

        Returns list of {entity_id, name, state, unit} sorted by name.
        """
        device_class_filter = request.query.get("device_class")

        if not self.client:
            return web.json_response({"sensors": []})

        try:
            sensors = []
            for eid, s in self.client.cached_states.items():
                if not eid.startswith("sensor."):
                    continue
                attrs = s.get("attributes", {})
                dc = attrs.get("device_class", "")
                if device_class_filter and dc != device_class_filter:
                    continue
                # Only include sensors with state_class (HA records
                # long-term statistics for these — needed for baseline
                # learning and filters out diagnostic duplicates)
                if not attrs.get("state_class"):
                    continue
                name = attrs.get("friendly_name", eid)
                sensors.append(
                    {
                        "entity_id": eid,
                        "name": name,
                        "state": s.get("state"),
                        "unit": attrs.get("unit_of_measurement", ""),
                    }
                )

            sensors.sort(key=lambda x: x["name"].lower())
            return web.json_response({"sensors": sensors})
        except Exception as e:
            logger.error(f"Error fetching sensors: {e}", exc_info=True)
            return web.json_response({"sensors": []})

    async def set_outdoor_override(self, request: Request) -> Response:
        """Set a temporary outdoor brightness override."""
        try:
            data = await request.json()
            condition = data.get("condition")
            duration = data.get("duration_minutes", 60)
            if not condition:
                return web.json_response({"error": "condition required"}, status=400)
            lux_tracker.set_override(condition, int(duration))

            if self.client:
                self.client.handle_outdoor_override(condition, int(duration))

            return web.json_response({"status": "ok"})
        except Exception as e:
            logger.error(f"Error setting outdoor override: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def clear_outdoor_override(self, request: Request) -> Response:
        """Clear the outdoor brightness override."""
        lux_tracker.clear_override()

        if self.client:
            self.client.handle_outdoor_override()

        return web.json_response({"status": "ok"})

    async def set_schedule_override(self, request: Request) -> Response:
        """Set a per-zone schedule override."""
        try:
            name = request.match_info.get("name", "")
            data = await request.json()
            mode = data.get("mode")
            if mode not in ("main", "alt", "custom", "off"):
                return web.json_response(
                    {"error": "mode must be main, alt, custom, or off"}, status=400
                )
            override = {
                "mode": mode,
                "custom_wake": data.get("custom_wake"),
                "custom_bed": data.get("custom_bed"),
                "until_date": data.get("until_date"),
                "until_event": data.get("until_event", "wake"),
            }
            glozones = glozone.get_glozones()
            if name not in glozones:
                return web.json_response(
                    {"error": f"Zone '{name}' not found"}, status=404
                )
            glozones[name]["schedule_override"] = override
            glozone.save_config()
            return web.json_response({"status": "ok", "override": override})
        except Exception as e:
            logger.error(f"Error setting schedule override: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def clear_schedule_override(self, request: Request) -> Response:
        """Clear a zone's schedule override."""
        try:
            name = request.match_info.get("name", "")
            glozones = glozone.get_glozones()
            if name not in glozones:
                return web.json_response(
                    {"error": f"Zone '{name}' not found"}, status=404
                )
            glozones[name]["schedule_override"] = None
            glozone.save_config()
            return web.json_response({"status": "ok"})
        except Exception as e:
            logger.error(f"Error clearing schedule override: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def get_schedule_override(self, request: Request) -> Response:
        """Get a zone's current schedule override and resolved times."""
        try:
            name = request.match_info.get("name", "")
            config = await self.load_config()
            glozones = config.get("glozones", {})
            if name not in glozones:
                return web.json_response(
                    {"error": f"Zone '{name}' not found"}, status=404
                )
            override = glozones[name].get("schedule_override")
            next_times = glozone.get_next_active_times(name)
            return web.json_response({"override": override, "next_times": next_times})
        except Exception as e:
            logger.error(f"Error getting schedule override: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def get_zone_next_times(self, request: Request) -> Response:
        """Get next effective wake/bed times for a zone."""
        try:
            name = request.match_info.get("name", "")
            next_times = glozone.get_next_active_times(name)
            if next_times is None:
                return web.json_response(
                    {"error": f"Zone '{name}' not found"}, status=404
                )
            return web.json_response(next_times)
        except Exception as e:
            logger.error(f"Error getting next times: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def get_outdoor_status(self, request: Request) -> Response:
        """Get current outdoor brightness state for settings page."""
        config = await self.load_config()
        # Build illuminance sensor list from client cache
        illuminance_sensors = []
        if self.client:
            for eid, s in self.client.cached_states.items():
                if eid.startswith("sensor."):
                    attrs = s.get("attributes", {})
                    if attrs.get("device_class") == "illuminance":
                        illuminance_sensors.append(
                            {"entity_id": eid, "name": attrs.get("friendly_name", eid)}
                        )
            illuminance_sensors.sort(key=lambda x: x["name"].lower())

        outdoor_norm = lux_tracker.get_outdoor_normalized()

        # Build weather condition groups with effective multipliers
        saved_map = config.get("weather_condition_map", {})
        weather_groups = [
            {
                "label": "Sunny",
                "key": "sunny",
                "multiplier": saved_map.get("sunny", 1.0),
            },
            {
                "label": "Partly cloudy",
                "key": "mixed",
                "multiplier": saved_map.get(
                    "mixed", saved_map.get("partlycloudy", 0.6)
                ),
            },
            {
                "label": "Cloudy",
                "key": "cloudy",
                "multiplier": saved_map.get("cloudy", 0.3),
            },
            {
                "label": "Rainy",
                "key": "rainy",
                "multiplier": saved_map.get("rainy", 0.2),
            },
            {
                "label": "Snow",
                "key": "snowy",
                "multiplier": saved_map.get("snowy", 0.2),
            },
            {"label": "Fog", "key": "fog", "multiplier": saved_map.get("fog", 0.15)},
            {
                "label": "Pouring",
                "key": "pouring",
                "multiplier": saved_map.get("pouring", 0.1),
            },
            {
                "label": "Storm",
                "key": "lightning",
                "multiplier": saved_map.get("lightning", 0.08),
            },
            {"label": "Dark", "key": "dark", "multiplier": 0.0},
        ]

        return web.json_response(
            {
                "outdoor_normalized": round(
                    outdoor_norm if outdoor_norm is not None else 0, 3
                ),
                "source": lux_tracker.get_outdoor_source(),
                "preferred_source": lux_tracker.get_preferred_source(),
                "override": lux_tracker.get_override_info(),
                "weather_cloud_cover": lux_tracker._cloud_cover,
                "weather_condition": lux_tracker._weather_condition,
                "lux_smoothed": lux_tracker._ema_lux,
                "lux_learned_ceiling": lux_tracker._learned_ceiling,
                "lux_learned_floor": lux_tracker._learned_floor,
                "sun_elevation": round(lux_tracker.compute_sun_elevation(), 1),
                "sensor_entity": lux_tracker.get_sensor_entity(),
                "illuminance_sensors": illuminance_sensors,
                "weather_groups": weather_groups,
                "condition_multiplier": round(
                    lux_tracker.get_condition_multiplier(), 2
                ),
                "angle_factor": round(lux_tracker.get_angle_factor(), 3),
                "sun_saturation": lux_tracker._sun_saturation,
                "sun_saturation_ramp": lux_tracker._sun_saturation_ramp,
                "max_summer_elevation": round(lux_tracker._max_summer_elevation, 1),
            }
        )

    async def learn_baselines(self, request: Request) -> Response:
        """Trigger baseline learning for the outdoor lux sensor.

        Queries HA recorder for hourly stats, filters to daytime,
        and computes ceiling/floor percentiles. Saves to config on success.

        Accepts optional JSON body: {"since": "2025-01-15T00:00"}
        Defaults to 90 days ago if not provided.
        """
        try:
            # Parse optional start date from request body
            since_str = None
            try:
                body = await request.json()
                since_str = body.get("since")
            except Exception:
                pass

            config = await self.load_config()
            lux_tracker.init(config)
            sensor_entity = lux_tracker.get_sensor_entity()
            if not sensor_entity:
                return web.json_response(
                    {"error": "No lux sensor configured"}, status=400
                )

            # Get location from client cache
            if not self.client:
                return web.json_response({"error": "Client not ready"}, status=500)
            lat = self.client.latitude
            lon = self.client.longitude
            tz_name = self.client.timezone
            if not lat or not lon or not tz_name:
                return web.json_response(
                    {"error": "No location data in HA"}, status=500
                )

            from datetime import datetime, timedelta
            from zoneinfo import ZoneInfo

            local_tz = ZoneInfo(tz_name)
            now = datetime.now(local_tz)
            if since_str:
                try:
                    start = datetime.fromisoformat(since_str)
                    if start.tzinfo is None:
                        start = start.replace(tzinfo=local_tz)
                except (ValueError, TypeError):
                    start = now - timedelta(days=90)
            else:
                start = now - timedelta(days=90)

            # Query recorder statistics via throwaway WS (needs request-response)
            rest_url, ws_url, token = self._get_ha_api_config()
            if not token or not ws_url:
                return web.json_response({"error": "No HA connection"}, status=500)

            async with websockets.connect(ws_url, max_size=16 * 1024 * 1024) as ws:
                msg = json.loads(await ws.recv())
                if msg.get("type") != "auth_required":
                    return web.json_response({"error": "WS auth failed"}, status=500)
                await ws.send(json.dumps({"type": "auth", "access_token": token}))
                msg = json.loads(await ws.recv())
                if msg.get("type") != "auth_ok":
                    return web.json_response({"error": "WS auth failed"}, status=500)

                await ws.send(
                    json.dumps(
                        {
                            "id": 1,
                            "type": "recorder/statistics_during_period",
                            "start_time": start.isoformat(),
                            "end_time": now.isoformat(),
                            "statistic_ids": [sensor_entity],
                            "period": "hour",
                            "types": ["mean"],
                        }
                    )
                )
                stats_msg = json.loads(await ws.recv())

                if not stats_msg.get("success"):
                    return web.json_response(
                        {
                            "error": f"Recorder returned no data for {sensor_entity}. "
                            "Ensure the sensor has state_class: measurement."
                        },
                        status=404,
                    )

                result = stats_msg.get("result", {})
                if sensor_entity not in result:
                    return web.json_response(
                        {
                            "error": f"No statistics found for {sensor_entity}. "
                            "The sensor may not have state_class: measurement."
                        },
                        status=404,
                    )

                stats = result[sensor_entity]

                # Filter to daytime hours (elevation > 10°)
                try:
                    from astral import LocationInfo
                    from astral.sun import elevation as solar_elev_fn
                except ImportError:
                    solar_elev_fn = None

                daytime_means = []
                diag = {
                    "total": len(stats),
                    "no_mean": 0,
                    "no_start": 0,
                    "parse_fail": 0,
                    "nighttime": 0,
                    "elev_error": 0,
                    "sample_entry": None,
                }
                for entry in stats:
                    if diag["sample_entry"] is None:
                        diag["sample_entry"] = {
                            k: str(type(v).__name__) + ":" + repr(v)
                            for k, v in list(entry.items())[:5]
                        }
                    mean_val = entry.get("mean")
                    if mean_val is None:
                        diag["no_mean"] += 1
                        continue
                    mean_val = float(mean_val)

                    start_val = entry.get("start")
                    if not start_val:
                        diag["no_start"] += 1
                        continue
                    try:
                        if isinstance(start_val, (int, float)):
                            # HA may return ms or s — normalize to seconds
                            ts = start_val / 1000 if start_val > 1e12 else start_val
                            dt = datetime.fromtimestamp(ts, tz=local_tz)
                        else:
                            dt = datetime.fromisoformat(start_val)
                            if dt.tzinfo is None:
                                dt = dt.replace(tzinfo=local_tz)
                            else:
                                dt = dt.astimezone(local_tz)
                    except (ValueError, TypeError, OSError):
                        diag["parse_fail"] += 1
                        continue

                    if solar_elev_fn is not None:
                        try:
                            loc = LocationInfo(
                                latitude=lat, longitude=lon, timezone=tz_name
                            )
                            elev = solar_elev_fn(loc.observer, dt)
                            if elev <= 10:
                                diag["nighttime"] += 1
                                continue
                        except Exception as ex:
                            diag["elev_error"] += 1
                            if "elev_err_msg" not in diag:
                                diag["elev_err_msg"] = str(ex)
                            continue

                    daytime_means.append(mean_val)

                if len(daytime_means) < 10:
                    return web.json_response(
                        {
                            "error": f"Only {len(daytime_means)} daytime samples found (need 10+). "
                            "The sensor may not have enough history yet.",
                            "diagnostics": diag,
                        },
                        status=404,
                    )

                # Remove outlier spikes (e.g. direct sun hitting sensor)
                # using IQR fence: values above Q3 + 3*IQR are excluded
                daytime_means.sort()
                n = len(daytime_means)
                q1 = daytime_means[int(n * 0.25)]
                q3 = daytime_means[int(n * 0.75)]
                iqr = q3 - q1
                upper_fence = q3 + 3.0 * iqr
                trimmed = [v for v in daytime_means if v <= upper_fence]
                if len(trimmed) >= 10:
                    daytime_means = trimmed
                    n = len(daytime_means)

                # Compute percentiles
                floor_val = daytime_means[max(0, int(n * 0.05))]
                ceiling_val = daytime_means[min(n - 1, int(n * 0.85))]

                if ceiling_val <= floor_val or ceiling_val <= 0:
                    return web.json_response(
                        {
                            "error": f"Bad percentiles (floor={floor_val}, ceiling={ceiling_val})"
                        },
                        status=500,
                    )

                # Save to config and update in-memory baselines
                # Use load_raw_config + save_config_to_file (same path as /api/save)
                # to avoid glozone's sync file reads potentially missing recent writes
                save_cfg = await self.load_raw_config()
                save_cfg["lux_learned_ceiling"] = ceiling_val
                save_cfg["lux_learned_floor"] = floor_val
                await self.save_config_to_file(save_cfg)
                glozone.set_config(save_cfg)
                lux_tracker.set_learned_baselines(ceiling_val, floor_val)

                logger.info(
                    f"Baselines learned from {len(daytime_means)} samples "
                    f"(sensor={sensor_entity}): "
                    f"ceiling={ceiling_val:.0f}, floor={floor_val:.0f}"
                )
                return web.json_response(
                    {
                        "ceiling": ceiling_val,
                        "floor": floor_val,
                        "samples": len(daytime_means),
                        "sensor": sensor_entity,
                    }
                )

        except Exception as e:
            logger.error(f"Learn baselines failed: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)

    async def get_controls(self, request: Request) -> Response:
        """Get all controls from HA, merged with our configuration.

        Fetches devices from HA, filters to potential controls (remotes, motion sensors, etc.),
        and merges with our config to determine status (active, not_configured, unsupported).
        """
        try:
            # Fetch controls from HA
            ha_controls = await self._fetch_ha_controls()

            # Get our configured switches and motion sensors
            configured_switches = {
                sw["id"]: sw for sw in switches.get_switches_summary()
            }
            configured_motion = switches.get_all_motion_sensors()

            # Auto-create controls for unconfigured devices (first load picks up new devices)
            created = self._auto_create_controls(ha_controls, configured_switches)
            if created:
                # Re-fetch configs since we just added new ones
                configured_switches = {
                    sw["id"]: sw for sw in switches.get_switches_summary()
                }
                configured_motion = switches.get_all_motion_sensors()

            # Pre-load last actions once (avoids N file reads in the loop)
            all_last_actions = switches.get_all_last_actions()

            # Merge and determine status
            controls = []
            for ctrl in ha_controls:
                ieee = ctrl.get("ieee")
                device_id = ctrl.get("device_id")
                category = ctrl.get("category")

                # Get config based on category
                if category in ("motion_sensor", "camera"):
                    # Look up by device_id for motion sensors
                    motion_config = (
                        switches.get_motion_sensor_by_device_id(device_id)
                        if device_id
                        else None
                    )
                    config = motion_config.to_dict() if motion_config else {}
                    config_scopes = config.get("scopes", [])
                    is_configured = any(s.get("areas") for s in config_scopes)
                elif category == "contact_sensor":
                    # Look up by device_id for contact sensors
                    contact_config = (
                        switches.get_contact_sensor_by_device_id(device_id)
                        if device_id
                        else None
                    )
                    config = contact_config.to_dict() if contact_config else {}
                    config_scopes = config.get("scopes", [])
                    is_configured = any(s.get("areas") for s in config_scopes)
                else:
                    # Look up by ieee for switches
                    config = configured_switches.get(ieee, {})
                    # A switch is configured if it has scopes with areas OR has magic buttons assigned
                    has_areas = (
                        config
                        and config.get("scopes")
                        and any(s.get("areas") for s in config.get("scopes", []))
                    )
                    has_magic = (
                        config
                        and config.get("magic_buttons")
                        and any(v for v in config.get("magic_buttons", {}).values())
                    )
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

                # Look up last_action from pre-loaded dict
                # Motion/contact sensors save under device_id; switches save under ieee
                if (
                    category in ("motion_sensor", "camera", "contact_sensor")
                    and device_id
                ):
                    last_action = all_last_actions.get(device_id)
                    if not last_action:
                        last_action = all_last_actions.get(ieee)
                else:
                    last_action = all_last_actions.get(ieee)
                    if not last_action and device_id:
                        last_action = all_last_actions.get(device_id)
                logger.debug(f"[Controls] last_action for '{ieee}': {last_action}")

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
                    "battery": ctrl.get("battery"),
                }

                control_data["inactive"] = config.get("inactive", False)
                control_data["inactive_until"] = config.get("inactive_until")
                if category in ("motion_sensor", "camera", "contact_sensor"):
                    control_data["scopes"] = config.get("scopes", [])
                    control_data["cooldown"] = config.get("cooldown", 0)
                    control_data["trigger_entities"] = config.get(
                        "trigger_entities", []
                    )
                    if "binary_sensors" not in control_data:
                        control_data["binary_sensors"] = ctrl.get("binary_sensors", [])
                else:
                    control_data["scopes"] = config.get("scopes", [])
                    control_data["magic_buttons"] = config.get("magic_buttons", {})

                controls.append(control_data)

            # Surface stale config entries (not found in HA)
            seen_ids = {c["id"] for c in controls}
            seen_device_ids = {c["device_id"] for c in controls if c.get("device_id")}

            # Stale switches
            for ieee, sw_config in configured_switches.items():
                if ieee not in seen_ids:
                    last_action = all_last_actions.get(ieee)
                    controls.append(
                        {
                            "id": ieee,
                            "device_id": sw_config.get("device_id"),
                            "name": sw_config.get("name", f"Switch ({ieee[-8:]})"),
                            "manufacturer": None,
                            "model": None,
                            "area_id": None,
                            "area_name": None,
                            "category": "switch",
                            "integration": None,
                            "type": sw_config.get("type"),
                            "type_name": sw_config.get("type_name"),
                            "supported": True,
                            "status": "stale",
                            "stale": True,
                            "last_action": last_action,
                            "illuminance": None,
                            "inactive": sw_config.get("inactive", False),
                            "inactive_until": sw_config.get("inactive_until"),
                            "scopes": sw_config.get("scopes", []),
                            "magic_buttons": sw_config.get("magic_buttons", {}),
                        }
                    )

            # Stale motion sensors
            for sensor_id, sensor in configured_motion.items():
                if (sensor.device_id and sensor.device_id not in seen_device_ids) or (
                    not sensor.device_id and sensor_id not in seen_ids
                ):
                    config = sensor.to_dict()
                    controls.append(
                        {
                            "id": sensor_id,
                            "device_id": sensor.device_id or sensor_id,
                            "name": config.get("name", sensor_id),
                            "manufacturer": None,
                            "model": None,
                            "area_id": None,
                            "area_name": None,
                            "category": "motion_sensor",
                            "integration": None,
                            "type": None,
                            "type_name": None,
                            "supported": True,
                            "status": "stale",
                            "stale": True,
                            "last_action": all_last_actions.get(sensor_id),
                            "illuminance": None,
                            "inactive": config.get("inactive", False),
                            "inactive_until": config.get("inactive_until"),
                            "scopes": config.get("scopes", []),
                            "cooldown": config.get("cooldown", 0),
                        }
                    )

            # Stale contact sensors
            configured_contact = switches.get_all_contact_sensors()
            for sensor_id, sensor in configured_contact.items():
                if (sensor.device_id and sensor.device_id not in seen_device_ids) or (
                    not sensor.device_id and sensor_id not in seen_ids
                ):
                    config = sensor.to_dict()
                    controls.append(
                        {
                            "id": sensor_id,
                            "device_id": sensor.device_id or sensor_id,
                            "name": config.get("name", sensor_id),
                            "manufacturer": None,
                            "model": None,
                            "area_id": None,
                            "area_name": None,
                            "category": "contact_sensor",
                            "integration": None,
                            "type": None,
                            "type_name": None,
                            "supported": True,
                            "status": "stale",
                            "stale": True,
                            "last_action": all_last_actions.get(sensor_id),
                            "illuminance": None,
                            "inactive": config.get("inactive", False),
                            "inactive_until": config.get("inactive_until"),
                            "scopes": config.get("scopes", []),
                            "cooldown": config.get("cooldown", 0),
                        }
                    )

            return web.json_response({"controls": controls})
        except Exception as e:
            logger.error(f"Error getting controls: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)

    async def _fetch_ha_controls(self) -> List[Dict[str, Any]]:
        """Fetch potential control devices from client caches.

        Identifies controls by entity types:
        - binary_sensor.*_motion, *_occupancy, *_presence, *_contact → sensors
        - Devices with only battery sensor and no lights → likely remotes
        """
        if not self.client:
            return []

        try:
            # Build device info from client cache
            devices = {}
            for device_id, device in self.client.device_registry.items():
                unique_id = None
                integration = None
                for identifier in device.get("identifiers", []):
                    if isinstance(identifier, list) and len(identifier) >= 2:
                        if identifier[0] in ("zha", "hue", "matter"):
                            unique_id = identifier[1]
                            integration = identifier[0]
                            break
                if not unique_id:
                    # Fall back to any device with identifiers (cameras, ESPHome, etc.)
                    for identifier in device.get("identifiers", []):
                        if isinstance(identifier, list) and len(identifier) >= 2:
                            integration = identifier[0]
                            unique_id = identifier[1]
                            break
                if unique_id:
                    model = device.get("model_id") or device.get("model")
                    area_id = device.get("area_id")
                    devices[device_id] = {
                        "device_id": device_id,
                        "ieee": unique_id,
                        "integration": integration,
                        "name": device.get("name_by_user") or device.get("name"),
                        "manufacturer": device.get("manufacturer"),
                        "model": model,
                        "area_id": area_id,
                        "area_name": self.client.area_id_to_name.get(area_id),
                    }

            # Track entity metadata per device using entity_registry cache
            device_entities: Dict[str, Dict[str, Any]] = {}
            for entity_id, entity in self.client.entity_registry.items():
                device_id = entity.get("device_id")
                if not device_id or device_id not in devices:
                    continue

                if device_id not in device_entities:
                    device_entities[device_id] = {
                        "has_light": False,
                        "illuminance_entity": None,
                        "sensitivity_entity": None,
                        "battery_entity": None,
                        "binary_sensors": [],
                    }

                if entity_id.startswith("light."):
                    device_entities[device_id]["has_light"] = True
                elif entity_id.startswith("binary_sensor."):
                    dc = (
                        entity.get("device_class")
                        or entity.get("original_device_class")
                        or ""
                    )
                    if not dc:
                        s = self.client.cached_states.get(entity_id, {})
                        dc = s.get("attributes", {}).get("device_class", "")
                    device_entities[device_id]["binary_sensors"].append(
                        {
                            "entity_id": entity_id,
                            "device_class": dc,
                            "name": entity.get("name")
                            or entity.get("original_name")
                            or entity_id.split(".")[-1].replace("_", " ").title(),
                        }
                    )
                elif entity_id.startswith("sensor."):
                    dc = (
                        entity.get("device_class")
                        or entity.get("original_device_class")
                        or ""
                    )
                    if not dc:
                        # Fallback: check cached_states for device_class
                        s = self.client.cached_states.get(entity_id, {})
                        dc = s.get("attributes", {}).get("device_class", "")
                    if dc == "battery" or "_battery" in entity_id:
                        device_entities[device_id]["battery_entity"] = entity_id
                    elif "illuminance" in entity_id or "_lux" in entity_id:
                        device_entities[device_id]["illuminance_entity"] = entity_id
                elif (
                    entity_id.startswith("select.") or entity_id.startswith("number.")
                ) and "sensitivity" in entity_id.lower():
                    device_entities[device_id]["sensitivity_entity"] = entity_id

            # Filter to allowlisted controls
            controls = []
            for device_id, device in devices.items():
                entities = device_entities.get(device_id, {})

                # Allowlist check: manufacturer+model must be in our curated lists
                control_info = switches.detect_control_type(
                    device.get("manufacturer"), device.get("model")
                )
                if not control_info:
                    continue

                category = control_info["category"]

                # Skip light-only devices that happen to match a manufacturer
                if entities.get("has_light") and category != "switch":
                    if not entities.get("binary_sensors"):
                        continue

                # Skip motion/camera devices with no binary_sensors
                # (e.g. SwitchBot Hub 3 HumiSensor/TempSensor sub-devices)
                if category in ("motion_sensor", "camera") and not entities.get(
                    "binary_sensors"
                ):
                    continue

                detected_type = control_info.get("type")
                type_name = control_info.get("name")
                is_supported = True

                # Illuminance from cached_states
                illum_entity = entities.get("illuminance_entity")
                illum_info = None
                if illum_entity:
                    raw_val = self.client.cached_states.get(illum_entity, {}).get(
                        "state"
                    )
                    try:
                        illum_val = (
                            round(float(raw_val))
                            if raw_val not in (None, "unavailable", "unknown")
                            else None
                        )
                    except (ValueError, TypeError):
                        illum_val = None
                    illum_info = {
                        "entity_id": illum_entity,
                        "value": illum_val,
                        "unit": "lx",
                    }

                sensitivity_entity = (
                    entities.get("sensitivity_entity")
                    if category in ("motion_sensor", "camera")
                    else None
                )

                # Battery level
                batt_entity = entities.get("battery_entity")
                batt_info = None
                if batt_entity:
                    raw_batt = self.client.cached_states.get(batt_entity, {}).get(
                        "state"
                    )
                    try:
                        batt_val = (
                            round(float(raw_batt))
                            if raw_batt not in (None, "unavailable", "unknown")
                            else None
                        )
                    except (ValueError, TypeError):
                        batt_val = None
                    batt_info = {"entity_id": batt_entity, "value": batt_val}

                controls.append(
                    {
                        **device,
                        "category": category,
                        "type": detected_type,
                        "type_name": type_name,
                        "supported": is_supported,
                        "illuminance": illum_info,
                        "battery": batt_info,
                        "sensitivity_entity": sensitivity_entity,
                        "binary_sensors": entities.get("binary_sensors", []),
                    }
                )

            logger.info(f"[Controls] Returning {len(controls)} controls")
            return controls
        except Exception as e:
            logger.error(f"Error fetching HA controls: {e}", exc_info=True)
            return []

    async def search_devices(self, request: Request) -> Response:
        """Search HA devices that have binary_sensor entities.

        For the 'Add control source' picker. Returns devices not already
        in the controls list, with their binary_sensor entities listed.
        Query: ?q=search_term (optional, filters by device name)
        """
        if not self.client:
            return web.json_response([])

        query = (request.query.get("q") or "").lower()

        try:
            # Get device_ids of all already-configured controls (motion
            # sensors, switches, contact sensors) so they don't show up
            # in the Add control picker.
            configured_device_ids = set()
            for sensor in switches.get_all_motion_sensors().values():
                if sensor.device_id:
                    configured_device_ids.add(sensor.device_id)
            for switch in switches.get_all_switches().values():
                if switch.device_id:
                    configured_device_ids.add(switch.device_id)
            for sensor in switches.get_all_contact_sensors().values():
                if sensor.device_id:
                    configured_device_ids.add(sensor.device_id)

            results = []
            # Scan all devices for binary_sensor entities
            device_sensors = {}  # device_id -> list of binary_sensor info
            for entity_id, entity in self.client.entity_registry.items():
                if not entity_id.startswith("binary_sensor."):
                    continue
                device_id = entity.get("device_id")
                if not device_id:
                    continue
                if device_id not in device_sensors:
                    device_sensors[device_id] = []
                dc = (
                    entity.get("device_class")
                    or entity.get("original_device_class")
                    or ""
                )
                name = (
                    entity.get("name")
                    or entity.get("original_name")
                    or entity_id.split(".")[-1].replace("_", " ").title()
                )
                device_sensors[device_id].append(
                    {
                        "entity_id": entity_id,
                        "device_class": dc,
                        "name": name,
                    }
                )

            for device_id, sensors in device_sensors.items():
                if device_id in configured_device_ids:
                    continue
                device = self.client.device_registry.get(device_id)
                if not device:
                    continue
                dev_name = device.get("name_by_user") or device.get("name") or ""
                if query and query not in dev_name.lower():
                    continue
                area_id = device.get("area_id")
                results.append(
                    {
                        "device_id": device_id,
                        "name": dev_name,
                        "manufacturer": device.get("manufacturer"),
                        "model": device.get("model_id") or device.get("model"),
                        "area_id": area_id,
                        "area_name": self.client.area_id_to_name.get(area_id),
                        "binary_sensors": sensors,
                    }
                )

            return web.json_response(results)
        except Exception as e:
            logger.error(f"Error searching devices: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)

    async def add_control_source(self, request: Request) -> Response:
        """Manually add a device as a control source (motion trigger).

        Expects JSON: {"device_id": "...", "name": "...", "trigger_entities": ["binary_sensor.xxx", ...]}
        Creates an unconfigured MotionSensorConfig with trigger_entities.
        """
        try:
            data = await request.json()
            device_id = data.get("device_id")
            name = data.get("name", "Unknown")
            trigger_entities = data.get("trigger_entities", [])

            if not device_id:
                return web.json_response({"error": "device_id required"}, status=400)

            # Check if already exists
            existing = switches.get_motion_sensor_by_device_id(device_id)
            if existing:
                return web.json_response(
                    {"error": "Device already configured", "id": existing.id},
                    status=409,
                )

            # Create motion sensor config (no scopes yet — user assigns area
            # on the control detail page after adding)
            sensor_config = switches.MotionSensorConfig(
                id=device_id,
                name=name,
                scopes=[],
                device_id=device_id,
                trigger_entities=trigger_entities,
                inactive=True,
            )
            switches.add_motion_sensor(sensor_config)

            # Register trigger entities in the motion sensor cache
            if self.client and trigger_entities:
                for entity_id in trigger_entities:
                    self.client.motion_sensor_ids[entity_id] = device_id
                logger.info(
                    f"[Controls] Registered {len(trigger_entities)} trigger entities "
                    f"for {name} ({device_id})"
                )

            logger.info(f"[Controls] Added control source: {name} ({device_id})")
            return web.json_response({"status": "ok", "id": device_id})
        except Exception as e:
            logger.error(f"Error adding control source: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)

    async def report_device(self, request: Request) -> Response:
        """Submit an unsupported-device report to the homeglo webhook.

        Builds a payload (manufacturer, model, integration, sw_version,
        binary_sensors with device_class) from the device + entity
        registry and forwards it to HOMEGLO_REPORT_WEBHOOK_URL, which
        files it as a GitHub issue in rweisbein/device-requests.

        Expects JSON: {"device_id": "..."}
        """
        if not self.client:
            return web.json_response({"error": "Client not connected"}, status=503)

        try:
            data = await request.json()
            device_id = data.get("device_id")
            if not device_id:
                return web.json_response({"error": "device_id required"}, status=400)

            device = self.client.device_registry.get(device_id)
            if not device:
                return web.json_response({"error": "Device not found"}, status=404)

            # Pick the first identifier's integration name (zha, hue,
            # matter, eufy_security, reolink, etc.)
            integration = None
            for identifier in device.get("identifiers", []):
                if isinstance(identifier, list) and len(identifier) >= 1:
                    integration = identifier[0]
                    break

            # Collect all binary_sensor entities for this device, with
            # device_class (the signal we use to pick triggers).
            binary_sensors = []
            for entity_id, entity in self.client.entity_registry.items():
                if entity.get("device_id") != device_id:
                    continue
                if not entity_id.startswith("binary_sensor."):
                    continue
                dc = (
                    entity.get("device_class")
                    or entity.get("original_device_class")
                    or ""
                )
                if not dc:
                    s = self.client.cached_states.get(entity_id, {})
                    dc = s.get("attributes", {}).get("device_class", "")
                binary_sensors.append(
                    {
                        "entity_id": entity_id,
                        "device_class": dc,
                        "name": entity.get("name") or entity.get("original_name") or "",
                    }
                )

            payload = {
                "manufacturer": device.get("manufacturer") or "(unknown)",
                "model": device.get("model") or "(unknown)",
                "model_id": device.get("model_id") or "",
                "integration": integration,
                "sw_version": device.get("sw_version") or "",
                "addon_version": _get_addon_version(),
                "binary_sensors": binary_sensors,
            }

            try:
                async with ClientSession() as session:
                    async with session.post(
                        HOMEGLO_REPORT_WEBHOOK_URL,
                        json=payload,
                        headers={"Content-Type": "application/json"},
                        timeout=10,
                    ) as resp:
                        if resp.status == 200:
                            result = await resp.json()
                            logger.info(
                                f"[Report] Submitted {payload['manufacturer']} "
                                f"{payload['model']}: {result.get('issue_url')}"
                            )
                            return web.json_response(
                                {
                                    "ok": True,
                                    "issue_url": result.get("issue_url"),
                                }
                            )
                        err_text = await resp.text()
                        logger.error(f"[Report] Webhook {resp.status}: {err_text}")
                        return web.json_response(
                            {
                                "error": "Webhook returned error",
                                "status": resp.status,
                            },
                            status=502,
                        )
            except asyncio.TimeoutError:
                logger.error("[Report] Webhook timed out")
                return web.json_response({"error": "Webhook timeout"}, status=504)
        except Exception as e:
            logger.error(f"Error reporting device: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)

    async def get_controls_refresh(self, request: Request) -> Response:
        """Lightweight refresh endpoint for controls page polling.

        Returns only last_actions and pause_states — no HA registry
        iteration, no config merge, no stale detection. All in-memory.
        """
        try:
            all_actions = switches.get_all_last_actions()
            pause_states = switches.get_all_pause_states()
            return web.json_response(
                {
                    "last_actions": all_actions,
                    "pause_states": pause_states,
                }
            )
        except Exception:
            return web.json_response({"last_actions": {}, "pause_states": {}})

    async def configure_control(self, request: Request) -> Response:
        """Configure a control (add/update scopes for switches, areas for motion sensors)."""
        try:
            control_id = request.match_info.get("control_id")
            if not control_id:
                return web.json_response(
                    {"error": "Control ID is required"}, status=400
                )

            data = await request.json()
            category = data.get("category", "switch")
            name = data.get("name", f"Control ({control_id[-8:]})")
            device_id = data.get("device_id")

            if category in ("motion_sensor", "camera"):
                # Handle motion sensor configuration
                scopes_data = data.get("scopes", [])
                scopes = [switches.MotionScope.from_dict(s) for s in scopes_data]

                # Resolve correct storage ID: if an existing config was stored
                # by device_id (from auto-create), use that ID to update in place
                # rather than creating a duplicate entry keyed by ieee.
                sensor_id = control_id
                if device_id:
                    existing = switches.get_motion_sensor_by_device_id(device_id)
                    if existing and existing.id != control_id:
                        # Remove the old entry so we don't leave a duplicate
                        switches.remove_motion_sensor(existing.id)
                        sensor_id = control_id
                    # Remove any stale contact sensor config for same device
                    old_contact = switches.get_contact_sensor_by_device_id(device_id)
                    if old_contact:
                        logger.info(
                            f"Removing stale contact config for device {device_id} (now motion)"
                        )
                        switches.remove_contact_sensor(old_contact.id)

                # Compute device-level trigger_entities as union of all scope lists
                all_triggers = set()
                for s in scopes:
                    all_triggers.update(s.trigger_entities)
                # Also include any device-level triggers from the payload
                all_triggers.update(data.get("trigger_entities", []))

                motion_config = switches.MotionSensorConfig(
                    id=sensor_id,
                    name=name,
                    scopes=scopes,
                    device_id=device_id,
                    inactive=data.get("inactive", False),
                    inactive_until=data.get("inactive_until"),
                    trigger_entities=sorted(all_triggers) if all_triggers else [],
                )

                switches.add_motion_sensor(motion_config)
            elif category == "contact_sensor":
                # Handle contact sensor configuration
                scopes_data = data.get("scopes", [])
                scopes = [switches.ContactScope.from_dict(s) for s in scopes_data]

                # Resolve correct storage ID (same as motion sensor above)
                sensor_id = control_id
                if device_id:
                    existing = switches.get_contact_sensor_by_device_id(device_id)
                    if existing and existing.id != control_id:
                        switches.remove_contact_sensor(existing.id)
                        sensor_id = control_id
                    # Remove any stale motion sensor config for same device
                    old_motion = switches.get_motion_sensor_by_device_id(device_id)
                    if old_motion:
                        logger.info(
                            f"Removing stale motion config for device {device_id} (now contact)"
                        )
                        switches.remove_motion_sensor(old_motion.id)

                contact_config = switches.ContactSensorConfig(
                    id=sensor_id,
                    name=name,
                    scopes=scopes,
                    device_id=device_id,
                    inactive=data.get("inactive", False),
                    inactive_until=data.get("inactive_until"),
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
                    feedback_area = scope_data.get("feedback_area")
                    scopes.append(
                        switches.SwitchScope(
                            areas=scope_areas, feedback_area=feedback_area
                        )
                    )

                if not scopes:
                    scopes = [switches.SwitchScope(areas=[])]

                # Create/update switch config
                switch_config = switches.SwitchConfig(
                    id=control_id,
                    name=name,
                    type=control_type,
                    scopes=scopes,
                    magic_buttons=data.get("magic_buttons", {}),
                    device_id=device_id,
                    inactive=data.get("inactive", False),
                    inactive_until=data.get("inactive_until"),
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
                return web.json_response(
                    {"error": "Control ID is required"}, status=400
                )

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
        device_id = request.match_info.get("device_id")
        if not device_id:
            return web.json_response({"error": "Device ID is required"}, status=400)

        if not self.client:
            return web.json_response({"error": "Client not ready"}, status=500)

        try:
            # Look up device IEEE from client cache
            device_info = self.client.device_registry.get(device_id)
            if not device_info:
                return web.json_response({"error": "Device not found"}, status=404)

            device_ieee = None
            is_zha = False
            for identifier in device_info.get("identifiers", []):
                if isinstance(identifier, list) and len(identifier) >= 2:
                    if identifier[0] == "zha":
                        device_ieee = identifier[1]
                        is_zha = True
                        break

            if not is_zha:
                return web.json_response(
                    {"is_zha": False, "sensitivity": None, "timeout": None}
                )

            # Find sensitivity entity from entity_registry cache
            sensitivity_entity = None
            for eid, entity in self.client.entity_registry.items():
                if entity.get("device_id") == device_id:
                    if "sensitivity" in eid.lower() and (
                        eid.startswith("select.") or eid.startswith("number.")
                    ):
                        sensitivity_entity = eid
                        break

            # Read sensitivity state from cached_states
            sensitivity_info = None
            if sensitivity_entity:
                s = self.client.cached_states.get(sensitivity_entity, {})
                attrs = s.get("attributes", {})
                sensitivity_info = {
                    "entity_id": sensitivity_entity,
                    "value": s.get("state"),
                    "options": attrs.get("options", []),
                    "min": attrs.get("min"),
                    "max": attrs.get("max"),
                    "step": attrs.get("step"),
                }

            # Read occupancy timeout from ZHA cluster attribute (needs throwaway WS)
            timeout_value = None
            rest_url, ws_url, token = self._get_ha_api_config()
            if ws_url and token:
                try:
                    async with websockets.connect(
                        ws_url, max_size=16 * 1024 * 1024
                    ) as ws:
                        msg = json.loads(await ws.recv())
                        if msg.get("type") == "auth_required":
                            await ws.send(
                                json.dumps({"type": "auth", "access_token": token})
                            )
                            msg = json.loads(await ws.recv())
                            if msg.get("type") == "auth_ok":
                                await ws.send(
                                    json.dumps(
                                        {
                                            "id": 1,
                                            "type": "zha/devices/clusters/attributes/value",
                                            "ieee": device_ieee,
                                            "endpoint_id": 2,
                                            "cluster_id": 1030,
                                            "cluster_type": "in",
                                            "attribute": 16,
                                        }
                                    )
                                )
                                timeout_msg = json.loads(await ws.recv())
                                if (
                                    timeout_msg.get("success")
                                    and timeout_msg.get("result") is not None
                                ):
                                    timeout_value = timeout_msg["result"]
                except Exception as e:
                    logger.warning(
                        f"[ZHA Settings] Could not read timeout for {device_ieee}: {e}"
                    )

            return web.json_response(
                {
                    "is_zha": True,
                    "ieee": device_ieee,
                    "sensitivity": sensitivity_info,
                    "timeout": timeout_value,
                }
            )

        except Exception as e:
            logger.error(f"Error getting ZHA motion settings: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)

    async def set_zha_motion_settings(self, request: Request) -> Response:
        """Set ZHA motion sensor settings (sensitivity and/or timeout).

        Request body:
            - sensitivity: new sensitivity value (string for select, number for number entity)
            - timeout: new occupancy timeout in seconds
        """
        device_id = request.match_info.get("device_id")
        if not device_id:
            return web.json_response({"error": "Device ID is required"}, status=400)

        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        new_sensitivity = data.get("sensitivity")
        new_timeout = data.get("timeout")

        if new_sensitivity is None and new_timeout is None:
            return web.json_response({"error": "No settings provided"}, status=400)

        if not self.client:
            return web.json_response({"error": "Client not ready"}, status=500)

        try:
            # Look up device IEEE from client cache
            device_info = self.client.device_registry.get(device_id)
            if not device_info:
                return web.json_response({"error": "Device not found"}, status=404)

            device_ieee = None
            for identifier in device_info.get("identifiers", []):
                if isinstance(identifier, list) and len(identifier) >= 2:
                    if identifier[0] == "zha":
                        device_ieee = identifier[1]
                        break

            if not device_ieee:
                return web.json_response({"error": "Not a ZHA device"}, status=400)

            results = {}

            # Set sensitivity via client.call_service
            if new_sensitivity is not None:
                # Find sensitivity entity from entity_registry cache
                sensitivity_entity = None
                for eid, entity in self.client.entity_registry.items():
                    if entity.get("device_id") == device_id:
                        if "sensitivity" in eid.lower() and (
                            eid.startswith("select.") or eid.startswith("number.")
                        ):
                            sensitivity_entity = eid
                            break

                if sensitivity_entity:
                    if sensitivity_entity.startswith("select."):
                        await self.client.call_service(
                            "select",
                            "select_option",
                            {"option": new_sensitivity},
                            {"entity_id": sensitivity_entity},
                        )
                    else:
                        await self.client.call_service(
                            "number",
                            "set_value",
                            {"value": new_sensitivity},
                            {"entity_id": sensitivity_entity},
                        )
                    results["sensitivity"] = True
                    logger.info(
                        f"[ZHA Settings] Set sensitivity for {device_id}: {new_sensitivity}"
                    )
                else:
                    results["sensitivity"] = False
                    results["sensitivity_error"] = "No sensitivity entity found"

            # Set timeout via ZHA cluster attribute (needs call_service for ZHA)
            if new_timeout is not None:
                try:
                    timeout_int = int(new_timeout)
                    await self.client.call_service(
                        "zha",
                        "set_zigbee_cluster_attribute",
                        {
                            "ieee": device_ieee,
                            "endpoint_id": 2,
                            "cluster_id": 1030,
                            "cluster_type": "in",
                            "attribute": 16,
                            "value": timeout_int,
                        },
                    )
                    results["timeout"] = True
                    logger.info(
                        f"[ZHA Settings] Set timeout for {device_ieee}: {timeout_int}s"
                    )
                except (ValueError, TypeError) as e:
                    results["timeout"] = False
                    results["timeout_error"] = f"Invalid timeout value: {e}"

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
                    {"error": f"Invalid switch type: {switch_type}"}, status=400
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

            # Trigger reach group sync if any scope has multiple areas
            await self._trigger_batch_group_sync_if_needed(switch_config.scopes)

            return web.json_response(
                {"status": "ok", "switch": switch_config.to_dict()}
            )

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
                    {"error": f"Invalid switch type: {switch_type}"}, status=400
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

            # Trigger reach group sync if scopes changed and any has multiple areas
            if "scopes" in data:
                await self._trigger_batch_group_sync_if_needed(scopes)

            return web.json_response(
                {"status": "ok", "switch": switch_config.to_dict()}
            )

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
                # Trigger reach group sync to clean up any orphaned reach groups
                await self._trigger_batch_group_sync()
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

    async def start_serving(self):
        """Start the web server without blocking.

        Returns the AppRunner so the caller can clean up later.
        Used when embedded in main.py's event loop.
        """
        self._runner = web.AppRunner(self.app, access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "0.0.0.0", self.port)
        await site.start()
        logger.info(f"Light Designer server started on port {self.port}")
        if self._live_design_watcher_task is None:
            self._live_design_watcher_task = asyncio.create_task(
                self._live_design_watcher()
            )
        return self._runner

    async def start(self):
        """Start the web server (blocking). Used for standalone mode."""
        await self.start_serving()
        try:
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            pass
        finally:
            await self._runner.cleanup()


async def main():
    """Main entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    port = int(os.getenv("INGRESS_PORT", "8099"))
    server = LightDesignerServer(port)
    await server.start()


if __name__ == "__main__":
    asyncio.run(main())
