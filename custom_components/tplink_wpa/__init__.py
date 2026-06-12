import logging
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_IP_ADDRESS
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .TL_WPA4220 import TL_WPA4220

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "button"]
SERVICE_REBOOT = "reboot"
CONF_PASSWORD = "password"
DATA_ENTRIES = "entries"
DATA_SERVICE_REGISTERED = "service_registered"

REBOOT_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_IP_ADDRESS): cv.string,
    }
)


async def _async_reboot_device(hass: HomeAssistant, ip_address: str, password: str) -> bool:
    """Reboot one TP-Link WPA device."""
    from .sensor import _get_poll_lock

    async with _get_poll_lock():
        device = TL_WPA4220(ip_address)
        await hass.async_add_executor_job(device.login, password)
        return await hass.async_add_executor_job(device.reboot)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up TP-Link WPA from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault(DATA_ENTRIES, {})
    hass.data[DOMAIN][DATA_ENTRIES][entry.entry_id] = entry

    if not hass.data[DOMAIN].get(DATA_SERVICE_REGISTERED):
        async def handle_reboot(call: ServiceCall) -> None:
            """Handle tplink_wpa.reboot service calls."""
            requested_ip = call.data.get(CONF_IP_ADDRESS)
            entries = list(hass.data[DOMAIN].get(DATA_ENTRIES, {}).values())

            if requested_ip:
                entries = [
                    registered_entry
                    for registered_entry in entries
                    if registered_entry.data.get(CONF_IP_ADDRESS) == requested_ip
                ]

            if not entries:
                raise ValueError(
                    f"No TP-Link WPA config entry found for ip_address={requested_ip!r}"
                )

            for registered_entry in entries:
                ip_address = registered_entry.data[CONF_IP_ADDRESS]
                password = registered_entry.data[CONF_PASSWORD]
                _LOGGER.info("Rebooting TP-Link WPA device at %s", ip_address)
                await _async_reboot_device(hass, ip_address, password)

        hass.services.async_register(
            DOMAIN,
            SERVICE_REBOOT,
            handle_reboot,
            schema=REBOOT_SERVICE_SCHEMA,
        )
        hass.data[DOMAIN][DATA_SERVICE_REGISTERED] = True

    try:
        _LOGGER.info("Connected to TP-Link WPA")
    except Exception as e:
        _LOGGER.error("Error connecting to TP-Link WPA: %s", e)
        return False

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data.get(DOMAIN, {}).get(DATA_ENTRIES, {}).pop(entry.entry_id, None)

        if not hass.data.get(DOMAIN, {}).get(DATA_ENTRIES):
            hass.services.async_remove(DOMAIN, SERVICE_REBOOT)
            hass.data.get(DOMAIN, {}).pop(DATA_SERVICE_REGISTERED, None)
            hass.data.pop(DOMAIN, None)

    return unload_ok
