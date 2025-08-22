import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

from .TL_WPA4220 import TL_WPA4220


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up TP-Link WPA4220 from a config entry."""
    #ip_address = entry.data["ip_address"]
    #password = entry.data["password"]

    #device = TL_WPA4220(ip_address)

    try:
        #await hass.async_add_executor_job(device.login,password)
        #hass.data[DOMAIN] = device
        _LOGGER.info("Connected to TP-Link WPA4220")
    except Exception as e:
        _LOGGER.error(f"Error connecting to TP-Link WPA4220: {e}")
        return False

    hass.async_create_task(
        hass.config_entries.async_forward_entry_setups(entry, ["sensor"])
    )
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    #device = hass.data.pop(DOMAIN, None)
    #if device:
    #    await hass.async_add_executor_job(device.logout)

    await hass.config_entries.async_forward_entry_unload(entry, "sensor")
    return True

