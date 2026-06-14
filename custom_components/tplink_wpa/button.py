from __future__ import annotations

import logging

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_IP_ADDRESS
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from . import _async_reboot_device

_LOGGER = logging.getLogger(__name__)
CONF_PASSWORD = "password"


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities,
) -> None:
    """Set up TP-Link WPA button entities."""
    ip_address = config_entry.data[CONF_IP_ADDRESS]
    password = config_entry.data[CONF_PASSWORD]

    async_add_entities(
        [TPLinkWPARebootButton(hass, config_entry, ip_address, password)]
    )


class TPLinkWPARebootButton(ButtonEntity):
    """Button entity to reboot the TP-Link WPA device."""

    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_icon = "mdi:restart"
    _attr_has_entity_name = True
    _attr_translation_key = "reboot"

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        ip_address: str,
        password: str,
    ) -> None:
        self._hass = hass
        self._config_entry = config_entry
        self._ip_address = ip_address
        self._password = password
        self._attr_unique_id = f"{config_entry.entry_id}_{ip_address}_reboot"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._ip_address)},
            "name": "TP-Link WPA",
            "manufacturer": "TP-Link",
            "model": "WPA",
            "configuration_url": f"http://{self._ip_address}/",
        }

    async def async_press(self) -> None:
        """Reboot the TP-Link WPA device."""
        _LOGGER.info("Reboot button pressed for TP-Link WPA device at %s", self._ip_address)
        await _async_reboot_device(self._hass, self._ip_address, self._password)
