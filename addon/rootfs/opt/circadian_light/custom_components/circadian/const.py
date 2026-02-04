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
SERVICE_CIRCADIAN_ON: Final = "circadian_on"
SERVICE_CIRCADIAN_OFF: Final = "circadian_off"
SERVICE_CIRCADIAN_TOGGLE: Final = "circadian_toggle"
SERVICE_FREEZE_TOGGLE: Final = "freeze_toggle"
SERVICE_SET: Final = "set"
SERVICE_REFRESH: Final = "refresh"

# Service attributes
ATTR_AREA_ID: Final = "area_id"
ATTR_PRESET: Final = "preset"
ATTR_FROZEN_AT: Final = "frozen_at"
ATTR_COPY_FROM: Final = "copy_from"
ATTR_ENABLE: Final = "enable"
