from homeassistant.helpers.entity import Entity
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers import device_registry as dr

from datetime import timedelta, datetime
import asyncio
from homeassistant.helpers.event import async_track_time_interval

from .const import DOMAIN

import logging

from .TL_WPA4220 import TL_WPA4220

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(minutes=1)

async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the TP-Link WPA4220 sensor."""
    #device = hass.data[DOMAIN]
    sensor = TPLinkStatusSensor(hass, "TP-Link WPA4220 Status", config_entry.data["ip_address"], config_entry.data["password"], config_entry)
    async_add_entities([sensor],  update_before_add=True)

    # Rufe die async_update-Funktion im festgelegten Intervall auf
    # async_track_time_interval(hass, sensor.async_update, SCAN_INTERVAL)

class TPLinkStatusSensor(SensorEntity):
    """Sensor to retrieve the full status of the TP-Link WPA4220 device."""

    def __init__(self, hass, name, ip, password,config_entry):
        self._ip = ip
        self._name = name
        self._state = None
        self._attributes = {}
        self._hass = hass
        self._password = password
        self._config_entry = config_entry

    @property
    def name(self):
        return self._name

    @property
    def state(self):
        return self._state

    @property
    def extra_state_attributes(self):
        return self._attributes
    
    @property
    def unique_id(self):
        return f"tplink_wpa4220_{self._ip}"
        
    @property
    def device_info(self):
           
        return {
            "identifiers": {("tplink_wpa4220", self._ip)},  # eindeutige ID
            "name": "TP-Link WPA4220",
            "manufacturer": "TP-Link",
            "model": "WPA4220", 
        }        


    async def async_update(self):
        try:
            device = TL_WPA4220(self._ip)
            _LOGGER.debug(f"Logging in to the device... {self._password}")
            
            await self._hass.async_add_executor_job(device.login, self._password)
            _LOGGER.debug("Fetching data...")

            # Asynchronous calls with `asyncio.gather`
            fw_data, plc_list, wls_data, wic_list = await asyncio.gather(
               self._hass.async_add_executor_job(device.get_firmware_info),
               self._hass.async_add_executor_job(device.get_plc_device_status),
               self._hass.async_add_executor_job(device.get_wlan_status),
               self._hass.async_add_executor_job(device.get_wifi_clients)
            )
            
            # Passwort maskieren und aktuelle Zeit ergänzen
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            wls_data['wireless_2g_pwd'] = f"hidden ({now_str})"
            wls_data['wireless_5g_pwd'] = f"hidden ({now_str})"

         
        except Exception as e:
            self._state = "error"
            self._attributes = {"error": str(e)}
            _LOGGER.error(f"An error occurred during data retrieval: {e}")
        else:
            status = {
                "FirmwareInfo": fw_data,
                "WlanStatus": wls_data,
                "WifiClients": wic_list,
                "PlcDeviceStatus": plc_list
            }
            self._state = "connected"
            self._attributes = status
            _LOGGER.debug(f"Updated state: {self._state}, attributes: {self._attributes}")
           
            device = None
            
            # --- Device-Register-Update JETZT, mit den frischen Variablen ---
            try:
                def _norm(mac):
                    if not mac:
                        return None
                    return mac.strip().lower().replace("-", ":")

                # 2.4G/5G MACs aus den frischen Daten
                mac_24 = _norm((wls_data or {}).get("wireless_2g_macaddr"))
                mac_5  = _norm((wls_data or {}).get("wireless_5g_macaddr"))

                # nur die beiden WLAN-MACs setzen
                conn_set = {("mac", m) for m in (mac_24, mac_5) if m}

                #device_registry = dr.async_get(self._hass)
                #deviceR = device_registry.async_get_device(identifiers={("tplink_wpa4220", self._ip)})
                _LOGGER.error(f"Mac; {conn_set}")
                device_registry = dr.async_get(self._hass)

                dev = device_registry.async_get_or_create(
                    config_entry_id=self._config_entry.entry_id,
                    identifiers={("tplink_wpa4220", self._ip)},
                    manufacturer="TP-Link",
                    name="TP-Link WPA4220",
                    connections=conn_set if conn_set else None,
                )

                device_registry.async_update_device(
                    device_id=dev.id,
                    model=fw_data.get("model") or "WPA4220",
                    sw_version=fw_data.get("firmware_version"),
                    hw_version=fw_data.get("hardware_version"),
                )
                
                dev_after = device_registry.async_get_device(identifiers={("tplink_wpa4220", self._ip)})
                _LOGGER.error(
                    f"DR check -> connections={getattr(dev_after, 'connections', None)}, "
                    f"model={getattr(dev_after, 'model', None)}, sw={getattr(dev_after, 'sw_version', None)}, "
                    f"hw={getattr(dev_after, 'hw_version', None)}"
                )

            except Exception as reg_err:
                _LOGGER.debug(f"Device registry MAC/version update skipped/failed: {reg_err}")
            # --- Ende Device-Register-Update ---
                    
            
            
        finally:
            try:
                _LOGGER.debug("Logging out from the device...")
                if device:
                    await self._hass.async_add_executor_job(device.logout)
                device = None
                _LOGGER.debug("Logout successful.")
            except Exception as logout_error:
                _LOGGER.error(f"An error occurred during logout: {logout_error} - {device}")
            

