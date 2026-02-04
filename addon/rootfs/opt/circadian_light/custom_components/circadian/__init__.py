"""The Circadian Light integration."""
from __future__ import annotations

import logging
from typing import Any
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import (
    DOMAIN,
    SERVICE_STEP_UP,
    SERVICE_STEP_DOWN,
    SERVICE_BRIGHT_UP,
    SERVICE_BRIGHT_DOWN,
    SERVICE_COLOR_UP,
    SERVICE_COLOR_DOWN,
    SERVICE_RESET,
    SERVICE_LIGHTS_ON,
    SERVICE_LIGHTS_OFF,
    SERVICE_LIGHTS_TOGGLE,
    SERVICE_CIRCADIAN_ON,
    SERVICE_CIRCADIAN_OFF,
    SERVICE_FREEZE_TOGGLE,
    SERVICE_SET,
    SERVICE_BROADCAST,
    SERVICE_REFRESH,
    SERVICE_GLO_UP,
    SERVICE_GLO_DOWN,
    SERVICE_GLO_RESET,
    SERVICE_GLOZONE_RESET,
    SERVICE_GLOZONE_DOWN,
    SERVICE_FULL_SEND,
    ATTR_AREA_ID,
    ATTR_ZONE_NAME,
    ATTR_PRESET,
    ATTR_FROZEN_AT,
    ATTR_COPY_FROM,
    ATTR_IS_ON,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Circadian Light component."""
    _LOGGER.debug("[%s] async_setup called with config keys: %s", DOMAIN, list(config.keys()))

    hass.data.setdefault(DOMAIN, {})

    # Register services globally (not per config entry)
    if "services_registered" not in hass.data[DOMAIN]:
        _LOGGER.info("[%s] Registering services from async_setup", DOMAIN)
        await _register_services(hass)
        hass.data[DOMAIN]["services_registered"] = True
    else:
        _LOGGER.debug("[%s] Services already registered; skipping registration in async_setup", DOMAIN)

    # Auto-create a config entry on startup if none exists
    if not hass.config_entries.async_entries(DOMAIN):
        _LOGGER.info("[%s] No config entries found; starting IMPORT flow to auto-create one.", DOMAIN)
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_IMPORT},
                data={},
            )
        )
    else:
        _LOGGER.debug("[%s] Config entry already exists; not starting IMPORT flow.", DOMAIN)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Circadian Light from a config entry."""
    _LOGGER.info("[%s] async_setup_entry: id=%s title=%s", DOMAIN, entry.entry_id, entry.title)

    domain_data = hass.data.setdefault(DOMAIN, {})
    domain_data[entry.entry_id] = entry.data
    _LOGGER.debug("[%s] Stored config entry. Domain data keys now: %s", DOMAIN, list(domain_data.keys()))

    # Ensure services are registered even if async_setup wasn't called
    if not domain_data.get("services_registered"):
        _LOGGER.info("[%s] Registering services from async_setup_entry", DOMAIN)
        await _register_services(hass)
        domain_data["services_registered"] = True
    else:
        _LOGGER.debug("[%s] Services already registered; skipping registration in async_setup_entry", DOMAIN)

    return True


async def _register_services(hass: HomeAssistant) -> None:
    """Register Circadian Light services."""
    _LOGGER.debug("[%s] _register_services invoked", DOMAIN)

    async def handle_step_up(call: ServiceCall) -> None:
        area_id = call.data.get(ATTR_AREA_ID)
        _LOGGER.info("[%s] step_up called: area_id=%s", DOMAIN, area_id)

    async def handle_step_down(call: ServiceCall) -> None:
        area_id = call.data.get(ATTR_AREA_ID)
        _LOGGER.info("[%s] step_down called: area_id=%s", DOMAIN, area_id)

    async def handle_bright_up(call: ServiceCall) -> None:
        area_id = call.data.get(ATTR_AREA_ID)
        _LOGGER.info("[%s] bright_up called: area_id=%s", DOMAIN, area_id)

    async def handle_bright_down(call: ServiceCall) -> None:
        area_id = call.data.get(ATTR_AREA_ID)
        _LOGGER.info("[%s] bright_down called: area_id=%s", DOMAIN, area_id)

    async def handle_color_up(call: ServiceCall) -> None:
        area_id = call.data.get(ATTR_AREA_ID)
        _LOGGER.info("[%s] color_up called: area_id=%s", DOMAIN, area_id)

    async def handle_color_down(call: ServiceCall) -> None:
        area_id = call.data.get(ATTR_AREA_ID)
        _LOGGER.info("[%s] color_down called: area_id=%s", DOMAIN, area_id)

    async def handle_reset(call: ServiceCall) -> None:
        area_id = call.data.get(ATTR_AREA_ID)
        _LOGGER.info("[%s] reset called: area_id=%s", DOMAIN, area_id)

    async def handle_lights_on(call: ServiceCall) -> None:
        area_id = call.data.get(ATTR_AREA_ID)
        _LOGGER.info("[%s] lights_on called: area_id=%s", DOMAIN, area_id)

    async def handle_lights_off(call: ServiceCall) -> None:
        area_id = call.data.get(ATTR_AREA_ID)
        _LOGGER.info("[%s] lights_off called: area_id=%s", DOMAIN, area_id)

    async def handle_lights_toggle(call: ServiceCall) -> None:
        area_id = call.data.get(ATTR_AREA_ID)
        _LOGGER.info("[%s] lights_toggle called: area_id=%s", DOMAIN, area_id)

    async def handle_circadian_on(call: ServiceCall) -> None:
        area_id = call.data.get(ATTR_AREA_ID)
        _LOGGER.info("[%s] circadian_on called: area_id=%s", DOMAIN, area_id)

    async def handle_circadian_off(call: ServiceCall) -> None:
        area_id = call.data.get(ATTR_AREA_ID)
        _LOGGER.info("[%s] circadian_off called: area_id=%s", DOMAIN, area_id)

    async def handle_freeze_toggle(call: ServiceCall) -> None:
        area_id = call.data.get(ATTR_AREA_ID)
        _LOGGER.info("[%s] freeze_toggle called: area_id=%s", DOMAIN, area_id)

    async def handle_set(call: ServiceCall) -> None:
        area_id = call.data.get(ATTR_AREA_ID)
        preset = call.data.get(ATTR_PRESET)
        frozen_at = call.data.get(ATTR_FROZEN_AT)
        copy_from = call.data.get(ATTR_COPY_FROM)
        is_on = call.data.get(ATTR_IS_ON)
        _LOGGER.info("[%s] set called: area_id=%s, preset=%s, frozen_at=%s, copy_from=%s, is_on=%s",
                     DOMAIN, area_id, preset, frozen_at, copy_from, is_on)

    async def handle_broadcast(call: ServiceCall) -> None:
        area_id = call.data.get(ATTR_AREA_ID)
        _LOGGER.info("[%s] broadcast called: area_id=%s", DOMAIN, area_id)

    async def handle_refresh(call: ServiceCall) -> None:
        _LOGGER.info("[%s] refresh called - signaling addon to update all enabled areas", DOMAIN)

    async def handle_glo_up(call: ServiceCall) -> None:
        area_id = call.data.get(ATTR_AREA_ID)
        _LOGGER.info("[%s] glo_up called: area_id=%s", DOMAIN, area_id)

    async def handle_glo_down(call: ServiceCall) -> None:
        area_id = call.data.get(ATTR_AREA_ID)
        _LOGGER.info("[%s] glo_down called: area_id=%s", DOMAIN, area_id)

    async def handle_glo_reset(call: ServiceCall) -> None:
        area_id = call.data.get(ATTR_AREA_ID)
        _LOGGER.info("[%s] glo_reset called: area_id=%s", DOMAIN, area_id)

    async def handle_glozone_reset(call: ServiceCall) -> None:
        zone_name = call.data.get(ATTR_ZONE_NAME)
        _LOGGER.info("[%s] glozone_reset called: zone_name=%s", DOMAIN, zone_name)

    async def handle_glozone_down(call: ServiceCall) -> None:
        zone_name = call.data.get(ATTR_ZONE_NAME)
        _LOGGER.info("[%s] glozone_down called: zone_name=%s", DOMAIN, zone_name)

    async def handle_full_send(call: ServiceCall) -> None:
        area_id = call.data.get(ATTR_AREA_ID)
        _LOGGER.info("[%s] full_send called: area_id=%s", DOMAIN, area_id)

    # Schema for services - area_id can be a string or list of strings
    area_schema = vol.Schema({
        vol.Required(ATTR_AREA_ID): vol.Any(cv.string, [cv.string]),
    })

    # Schema for zone-level services
    zone_schema = vol.Schema({
        vol.Required(ATTR_ZONE_NAME): cv.string,
    })

    # Schema for set service - includes additional optional parameters
    # area_id is optional for moments (which apply to all areas)
    set_schema = vol.Schema({
        vol.Optional(ATTR_AREA_ID): vol.Any(cv.string, [cv.string]),
        vol.Optional(ATTR_PRESET): cv.string,  # nitelite, britelite, wake, bed, or moment name
        vol.Optional(ATTR_FROZEN_AT): vol.Coerce(float),
        vol.Optional(ATTR_COPY_FROM): cv.string,
        vol.Optional(ATTR_IS_ON): cv.boolean,
    })

    # Register services with area_schema
    area_services = [
        (SERVICE_STEP_UP, handle_step_up),
        (SERVICE_STEP_DOWN, handle_step_down),
        (SERVICE_BRIGHT_UP, handle_bright_up),
        (SERVICE_BRIGHT_DOWN, handle_bright_down),
        (SERVICE_COLOR_UP, handle_color_up),
        (SERVICE_COLOR_DOWN, handle_color_down),
        (SERVICE_RESET, handle_reset),
        (SERVICE_LIGHTS_ON, handle_lights_on),
        (SERVICE_LIGHTS_OFF, handle_lights_off),
        (SERVICE_LIGHTS_TOGGLE, handle_lights_toggle),
        (SERVICE_CIRCADIAN_ON, handle_circadian_on),
        (SERVICE_CIRCADIAN_OFF, handle_circadian_off),
        (SERVICE_FREEZE_TOGGLE, handle_freeze_toggle),
        (SERVICE_BROADCAST, handle_broadcast),
        (SERVICE_GLO_UP, handle_glo_up),
        (SERVICE_GLO_DOWN, handle_glo_down),
        (SERVICE_GLO_RESET, handle_glo_reset),
        (SERVICE_FULL_SEND, handle_full_send),
    ]

    for service_name, handler in area_services:
        hass.services.async_register(DOMAIN, service_name, handler, schema=area_schema)
        _LOGGER.debug("[%s] Registered service: %s.%s", DOMAIN, DOMAIN, service_name)

    # Register zone-level services
    zone_services = [
        (SERVICE_GLOZONE_RESET, handle_glozone_reset),
        (SERVICE_GLOZONE_DOWN, handle_glozone_down),
    ]

    for service_name, handler in zone_services:
        hass.services.async_register(DOMAIN, service_name, handler, schema=zone_schema)
        _LOGGER.debug("[%s] Registered service: %s.%s", DOMAIN, DOMAIN, service_name)

    # Register set service with its own schema
    hass.services.async_register(DOMAIN, SERVICE_SET, handle_set, schema=set_schema)
    _LOGGER.debug("[%s] Registered service: %s.%s", DOMAIN, DOMAIN, SERVICE_SET)

    # Register refresh service (no parameters needed)
    hass.services.async_register(DOMAIN, SERVICE_REFRESH, handle_refresh)
    _LOGGER.debug("[%s] Registered service: %s.%s", DOMAIN, DOMAIN, SERVICE_REFRESH)

    _LOGGER.info("[%s] Services registered successfully", DOMAIN)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info("[%s] async_unload_entry: id=%s title=%s", DOMAIN, entry.entry_id, entry.title)

    if entry.entry_id in hass.data.get(DOMAIN, {}):
        hass.data[DOMAIN].pop(entry.entry_id)
        _LOGGER.debug("[%s] Removed entry. Remaining keys: %s", DOMAIN, list(hass.data[DOMAIN].keys()))

    # Check if this is the last config entry
    config_entries_left = [key for key in hass.data.get(DOMAIN, {}).keys() if key != "services_registered"]
    if not config_entries_left:
        _LOGGER.info("[%s] No config entries remain; unregistering services", DOMAIN)
        services = [
            SERVICE_STEP_UP, SERVICE_STEP_DOWN,
            SERVICE_BRIGHT_UP, SERVICE_BRIGHT_DOWN,
            SERVICE_COLOR_UP, SERVICE_COLOR_DOWN,
            SERVICE_RESET,
            SERVICE_LIGHTS_ON, SERVICE_LIGHTS_OFF, SERVICE_LIGHTS_TOGGLE,
            SERVICE_CIRCADIAN_ON, SERVICE_CIRCADIAN_OFF,
            SERVICE_FREEZE_TOGGLE, SERVICE_SET, SERVICE_BROADCAST, SERVICE_REFRESH,
            SERVICE_GLO_UP, SERVICE_GLO_DOWN, SERVICE_GLO_RESET,
            SERVICE_GLOZONE_RESET, SERVICE_GLOZONE_DOWN, SERVICE_FULL_SEND,
        ]
        for service_name in services:
            hass.services.async_remove(DOMAIN, service_name)
        hass.data[DOMAIN].pop("services_registered", None)

    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    _LOGGER.info("[%s] async_reload_entry: id=%s title=%s", DOMAIN, entry.entry_id, entry.title)
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
