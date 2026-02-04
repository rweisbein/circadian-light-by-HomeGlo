"""Constants for the Circadian Light integration."""
from typing import Final

DOMAIN: Final = "circadian"

# Service names
SERVICE_STEP_UP: Final = "step_up"
SERVICE_STEP_DOWN: Final = "step_down"
SERVICE_BRIGHT_UP: Final = "bright_up"
SERVICE_BRIGHT_DOWN: Final = "bright_down"
SERVICE_COLOR_UP: Final = "color_up"
SERVICE_COLOR_DOWN: Final = "color_down"
SERVICE_RESET: Final = "reset"
SERVICE_LIGHTS_ON: Final = "lights_on"
SERVICE_LIGHTS_OFF: Final = "lights_off"
SERVICE_LIGHTS_TOGGLE: Final = "lights_toggle"
SERVICE_CIRCADIAN_ON: Final = "circadian_on"
SERVICE_CIRCADIAN_OFF: Final = "circadian_off"
SERVICE_FREEZE_TOGGLE: Final = "freeze_toggle"
SERVICE_SET: Final = "set"
SERVICE_BROADCAST: Final = "broadcast"
SERVICE_REFRESH: Final = "refresh"

# GloZone services (area-level)
SERVICE_GLO_UP: Final = "glo_up"
SERVICE_GLO_DOWN: Final = "glo_down"
SERVICE_GLO_RESET: Final = "glo_reset"

# GloZone services (zone-level)
SERVICE_GLOZONE_RESET: Final = "glozone_reset"
SERVICE_GLOZONE_DOWN: Final = "glozone_down"
SERVICE_FULL_SEND: Final = "full_send"

# Service attributes
ATTR_AREA_ID: Final = "area_id"
ATTR_ZONE_NAME: Final = "zone_name"
ATTR_PRESET: Final = "preset"
ATTR_FROZEN_AT: Final = "frozen_at"
ATTR_COPY_FROM: Final = "copy_from"
ATTR_IS_ON: Final = "is_on"
