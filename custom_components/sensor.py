from homeassistant.helpers.entity import Entity
from datetime import timedelta

from .const import DOMAIN

import logging

from .TL_WPA4220 import TL_WPA4220

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(minutes=3)

async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the TP-Link WPA4220 sensor."""
    #device = hass.data[DOMAIN]
    sensor = TPLinkStatusSensor(hass, "TP-Link WPA4220 Status", config_entry.data["ip_address"], config_entry.data["password"])
    async_add_entities([sensor])

    # Rufe die async_update-Funktion im festgelegten Intervall auf
    async_track_time_interval(hass, sensor.async_update, SCAN_INTERVAL)

class TPLinkStatusSensor(Entity):
    """Sensor to retrieve the full status of the TP-Link WPA4220 device."""

    def __init__(self, hass, name, ip, password):
        self._ip = ip
        self._name = name
        self._state = None
        self._attributes = {}
        self._hass = hass
        self._password = password

    @property
    def name(self):
        return self._name

    @property
    def state(self):
        return self._state

    @property
    def extra_state_attributes(self):
        return self._attributes


    async def async_update(self):
        try:
            device = TL_WPA4220(self._ip)
            _LOGGER.debug(f"Logging in to the device... {self._password}")
            
            await self._hass.async_add_executor_job(device.login, self._password)
            _LOGGER.debug("Fetching data...")
            fw = await self._hass.async_add_executor_job(device.get_firmware_info)
            plc = await self._hass.async_add_executor_job(device.get_plc_device_status)
            wls = await self._hass.async_add_executor_job(device.get_wlan_status)
            wic = await self._hass.async_add_executor_job(device.get_wifi_clients)
        except Exception as e:
            self._state = "error"
            self._attributes = {"error": str(e)}
            _LOGGER.error(f"An error occurred during data retrieval: {e}")
        else:
            status = {
                "FirmwareInfo": fw,
                "WlanStatus": wls,
                "WifiClients": wic,
                "PlcDeviceStatus": plc
            }
            self._state = "connected"
            self._attributes = status
            _LOGGER.debug(f"Updated state: {self._state}, attributes: {self._attributes}")
        finally:
            try:
                _LOGGER.debug("Logging out from the device...")
                await self._hass.async_add_executor_job(device.logout)
                _LOGGER.debug("Logout successful.")
            except Exception as logout_error:
                _LOGGER.error(f"An error occurred during logout: {logout_error}")
            

