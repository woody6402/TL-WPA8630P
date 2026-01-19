from homeassistant.helpers.entity import Entity
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers import device_registry as dr
from homeassistant.const import UnitOfDataRate
from homeassistant.core import callback  # optional, aber schön für Callbacks
from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass

PLC_DEGRADED_THRESHOLD = 100  # Mbit/s

from datetime import timedelta, datetime
import asyncio
from homeassistant.helpers.event import async_track_time_interval

from .const import DOMAIN

import logging
import re

from .TL_WPA4220 import TL_WPA4220

from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)

SIGNAL_WPA4220_UPDATED = "tplink_wpa4220_updated_{ip}"


_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(minutes=2)

# --------------------


# ---------

async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the TP-Link WPA4220 sensor."""
    #device = hass.data[DOMAIN]
    
    ip = config_entry.data["ip_address"]
    pwd = config_entry.data["password"]
    shared = {"status": None}  # kleiner gemeinsamer Speicher    

    main = TPLinkStatusSensor(hass, "TP-Link WPA4220 Status", ip, pwd, config_entry, shared)
    
    async_add_entities([main,
        WifiClientsTotalSensor(hass, "WLAN Clients (gesamt)", ip, config_entry, shared),
        WifiClients24Sensor(hass, "WLAN Clients 2.4 GHz", ip, config_entry, shared),
        WifiClients5Sensor(hass, "WLAN Clients 5 GHz", ip, config_entry, shared),
        PlcMaxRxRateSensor(hass, "PLC Max RX (Mbit/s)", ip, config_entry, shared),
        PlcMaxTxRateSensor(hass, "PLC Max TX (Mbit/s)", ip, config_entry, shared),
        WifiChannel24Sensor(hass, "WLAN Kanal 2.4 GHz", ip, config_entry, shared),
        WifiChannel5Sensor(hass, "WLAN Kanal 5 GHz", ip, config_entry, shared),
        
    WifiSsid24Sensor(hass, "SSID 2.4 GHz", ip, config_entry, shared),
    WifiSsid5Sensor(hass, "SSID 5 GHz", ip, config_entry, shared),
    WifiChannel24Sensor(hass, "Kanal 2.4 GHz", ip, config_entry, shared),
    WifiChannel5Sensor(hass, "Kanal 5 GHz", ip, config_entry, shared),
    Wifi24EnabledBinary(hass, "WLAN 2.4 GHz aktiv", ip, config_entry, shared),
    Wifi5EnabledBinary(hass, "WLAN 5 GHz aktiv", ip, config_entry, shared),
    PlcPeersCountSensor(hass, "PLC Peers (Anzahl)", ip, config_entry, shared),
    PlcMinRxRateSensor(hass, "PLC min RX (Mbit/s)", ip, config_entry, shared),
    PlcMinTxRateSensor(hass, "PLC min TX (Mbit/s)", ip, config_entry, shared),
    # optional:
    PlcDegradedBinary(hass, f"PLC unter {PLC_DEGRADED_THRESHOLD} Mbit/s?", ip, config_entry, shared),
    WifiClientsWithIpSensor(hass, "WLAN Clients mit IP", ip, config_entry, shared),
        
        
    ],  update_before_add=True)

    # Rufe die async_update-Funktion im festgelegten Intervall auf
    # async_track_time_interval(hass, sensor.async_update, SCAN_INTERVAL)

class TPLinkStatusSensor(SensorEntity):
    """Sensor to retrieve the full status of the TP-Link WPA4220 device."""
    
    _attr_should_poll = True   # <— hinzufügen
    # optional: kleines Icon
    _attr_icon = "mdi:access-point"

    def __init__(self, hass, name, ip, password,config_entry,shared):
        self._ip = ip
        self._name = name
        self._state = None
        self._attributes = {}
        self._hass = hass
        self._password = password
        self._config_entry = config_entry
        self._shared = shared


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
            "configuration_url": f"http://{self._ip}/",
        }        


    async def async_update(self):
        
        device=None
                
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
            self._shared["status"] = status
            
            async_dispatcher_send(self._hass, SIGNAL_WPA4220_UPDATED.format(ip=self._ip))
            
            _LOGGER.debug(f"Updated state: {self._state}, attributes: {self._attributes}")
          
            
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

                #_LOGGER.debug(f"Mac; {conn_set}")
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
                _LOGGER.debug(
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

class _DerivedBinaryBase(BinarySensorEntity):
    _attr_should_poll = False

    def __init__(self, hass, name, ip, config_entry, shared):
        self._hass = hass
        self._name = name
        self._ip = ip
        self._config_entry = config_entry
        self._shared = shared
        self._is_on = None
        self._unsub = None

    @property
    def name(self): return self._name

    @property
    def unique_id(self):
        return f"{self._config_entry.entry_id}_{self._ip}_{self.__class__.__name__.lower()}"

    @property
    def device_info(self):
        return {
            "identifiers": {("tplink_wpa4220", self._ip)},
            "name": "TP-Link WPA4220",
            "manufacturer": "TP-Link",
            "model": "WPA4220",
        }

    @property
    def is_on(self):
        return self._is_on

    @callback
    def _handle_push(self) -> None:
        self.schedule_update_ha_state(True)

    async def async_added_to_hass(self) -> None:
        # JETZT ist self.hass garantiert gesetzt
        self._unsub = async_dispatcher_connect(
            self.hass,
            SIGNAL_WPA4220_UPDATED.format(ip=self._ip),
            self._handle_push,
        )
        # automatisch beim Entfernen deregistrieren
        self.async_on_remove(self._unsub)
        # einmal initial updaten, falls wir das erste Signal verpasst haben
        self.async_schedule_update_ha_state(True)        

    async def async_update(self):
        status = self._shared.get("status") or {}
        self._compute_on(status)

    async def async_will_remove_from_hass(self) -> None:
        if getattr(self, "_unsub", None):
            self._unsub()
        self._unsub = None

    def _compute_on(self, status: dict):
        raise NotImplementedError



class _DerivedBase(SensorEntity):
    _attr_should_poll = False   # nicht pollen
    
    def __init__(self, hass, name, ip, config_entry, shared):
        self._hass = hass
        self._name = name
        self._ip = ip
        self._config_entry = config_entry
        self._shared = shared
        self._state = None
        self._unsub = None
        self._attrs = {} 


    @property
    def name(self):
        return self._name

    @property
    def unique_id(self):
        return f"{self._config_entry.entry_id}_{self._ip}_{self.__class__.__name__.lower()}"

    @property
    def device_info(self):
        # zum selben Gerät gruppieren
        return {
            "identifiers": {("tplink_wpa4220", self._ip)},
            "name": "TP-Link WPA4220",
            "manufacturer": "TP-Link",
            "model": "WPA4220",
        }

    @property
    def extra_state_attributes(self):
        return self._attrs
        
    @property
    def native_value(self):
        return self._state      

    @callback
    def _handle_push(self) -> None:
        # ruft async_update() auf und schreibt danach den State
        self.schedule_update_ha_state(True)          

    
    async def async_update(self):
        # keine I/O – nur aus Shared lesen
        status = self._shared.get("status") or {}
        self._compute_state(status)
    
    async def async_added_to_hass(self) -> None:
        # JETZT ist self.hass garantiert gesetzt
        self._unsub = async_dispatcher_connect(
            self.hass,
            SIGNAL_WPA4220_UPDATED.format(ip=self._ip),
            self._handle_push,
        )
        # automatisch beim Entfernen deregistrieren
        self.async_on_remove(self._unsub)
        # einmal initial updaten, falls wir das erste Signal verpasst haben
        self.async_schedule_update_ha_state(True)
    
    
    async def async_will_remove_from_hass(self) -> None:
        if getattr(self, "_unsub", None):
            self._unsub()
            self._unsub = None


    # ---- Generische Helfer (einmal, ohne Duplikate) ----
    @staticmethod
    def _as_list(maybe):
        if isinstance(maybe, list): return maybe
        if isinstance(maybe, dict): return [maybe]
        return []

    @staticmethod
    def _unique_sorted(seq):
        return sorted({x for x in seq if x})

    @staticmethod
    def _norm_mac(mac: str | None) -> str | None:
        if not mac: return None
        return mac.strip().lower().replace("-", ":")

    @staticmethod
    def _to_int(v):
        if isinstance(v, (int, float)): return int(v)
        try: return int(str(v).strip())
        except Exception: return 0

    @staticmethod
    def _band_str(c) -> str:
        return str((c or {}).get("type", "")).strip().lower()

    # ---- Wifi-Client-Helfer (parametrisierte Band-Filterung) ----
    def _is_band(self, client: dict, band: str | None) -> bool:
        """band: None=alle, '2.4' oder '5'"""
        t = self._band_str(client)
        if band is None:
            return True
        if band == "2.4":
            return "2.4" in t
        if band == "5":
            # robust gg. '5ghz', '5 ghz', '5g'
            return ("5" in t) and ("ghz" in t or " 5g" in t or t.endswith("5g"))
        return False

    def _clients_for(self, status: dict, band: str | None):
        clients = status.get("WifiClients")
        clients = clients if isinstance(clients, list) else []
        return [c for c in clients if isinstance(c, dict) and self._is_band(c, band)]

    def _take_top_n(self, items: list[dict], n: int) -> list[dict]:
        """Gibt die ersten n Elemente (oder weniger) zurück; robust gegen Falscheingaben."""
        if not isinstance(items, list) or n is None or n <= 0:
            return []
        return items[:n]

    def _drop_key_from_dicts(self, items: list[dict], key: str) -> list[dict]:
        """Entfernt den angegebenen Key aus jedem Dict (ohne die Liste zu verändern)."""
        if not isinstance(items, list):
            return []
        out: list[dict] = []
        for d in items:
            if isinstance(d, dict):
                out.append({k: v for k, v in d.items() if k != key})
        return out



    def _enrich_clients(self, clients: list[dict], top_n: int = 12):
        """→ (names_sorted, macs_sorted_unique, topN_by_packets)"""
        names, macs, enriched = [], [], []
        for c in clients:
            mac = self._norm_mac(c.get("mac"))
            name = (c.get("devName") or c.get("name") or mac)
            rx = self._to_int(c.get("rxpkts"))
            tx = self._to_int(c.get("txpkts"))
            enriched.append({
                "name": name,
                "mac": mac,
                "ip": c.get("ip"),
                "band": c.get("type"),
                "pkts": f"({rx/1000:.1f}k, {tx/1000:.1f}k)",
                "total_pkts": rx + tx,
            })
            if mac: names.append(name.strip() if isinstance(name, str) else name)
            if mac: macs.append(mac)
        names_sorted = sorted({n for n in names if isinstance(n, str) and n})
        macs_sorted_unique = self._unique_sorted(macs)

        top_all = sorted(enriched, key=lambda x: x["total_pkts"], reverse=True)        
        top_n_list = self._take_top_n(top_all, 12)                 # Schritt 1: Top-N nehmen
        top_sorted = self._drop_key_from_dicts(top_n_list, "total_pkts")  # Schritt 2: Key entfernen

        return names_sorted, macs_sorted_unique, top_sorted
       

    # ---- Convenience: zähle Werte & setze Attribut ----
    def _count_set_attr(self, attr_key: str, values_iterable):
        vals = self._unique_sorted(values_iterable)
        self._attrs[attr_key] = vals
        self._state = len(vals)

# --------------
    def _compute_state(self, status: dict):
        raise NotImplementedError


class WifiClientsTotalSensor(_DerivedBase):
    @property
    def icon(self): return "mdi:account-multiple"
    def _compute_state(self, status):
        clients = self._clients_for(status, None)  # None = alle Bänder
        self._state = len(clients)
        names, macs, top12 = self._enrich_clients(clients, top_n=12)
        self._attrs.update({
            "wifi_client_names": names,
            "wifi_top12_by_packets": top12,
        })  

class WifiClients24Sensor(_DerivedBase):
    @property
    def icon(self): return "mdi:wifi"

    def _compute_state(self, status):
        clients = self._clients_for(status, "2.4")
        self._state = len(clients)
        names, macs, top12 = self._enrich_clients(clients, top_n=12)
        self._attrs.update({
            "wifi_24_client_names": names,
            "wifi_24_top12_by_packets": self._drop_key_from_dicts(top12, "band"),
        })


class WifiClients5Sensor(_DerivedBase):
    @property
    def icon(self): return "mdi:wifi"

    def _compute_state(self, status):
        clients = self._clients_for(status, "5")
        self._state = len(clients)
        names, macs, top12 = self._enrich_clients(clients, top_n=12)
        self._attrs.update({
            "wifi_5_client_names": names,
            "wifi_5_top12_by_packets": self._drop_key_from_dicts(top12, "band"),
        })


class PlcMaxRxRateSensor(_DerivedBase):
    @property
    def native_unit_of_measurement(self): return UnitOfDataRate.MEGABITS_PER_SECOND
    @property
    def icon(self): return "mdi:power-plug"
    def _compute_state(self, status):
        plc = status.get("PlcDeviceStatus")
        if isinstance(plc, dict):
            plc = [plc]
        rx_vals = []
        for d in plc or []:
            v = (d or {}).get("rx_rate")
            if isinstance(v, (int, float)):
                rx_vals.append(int(v))
            elif isinstance(v, str):
                m = re.search(r"\d+", v)
                if m:
                    rx_vals.append(int(m.group(0)))
        self._state = max(rx_vals) if rx_vals else None


class PlcMaxTxRateSensor(_DerivedBase):
    @property
    def native_unit_of_measurement(self): return UnitOfDataRate.MEGABITS_PER_SECOND
    @property
    def icon(self): return "mdi:power-plug"
    def _compute_state(self, status):
        plc = status.get("PlcDeviceStatus")
        if isinstance(plc, dict):
            plc = [plc]
        tx_vals = []
        for d in plc or []:
            v = (d or {}).get("tx_rate")
            if isinstance(v, (int, float)):
                tx_vals.append(int(v))
            elif isinstance(v, str):
                m = re.search(r"\d+", v)
                if m:
                    tx_vals.append(int(m.group(0)))
        self._state = max(tx_vals) if tx_vals else None


# Optional: Kanalsensoren
class WifiChannel24Sensor(_DerivedBase):
    def _compute_state(self, status):
        wls = status.get("WlanStatus") or {}
        self._state = wls.get("wireless_2g_channel")

class WifiChannel5Sensor(_DerivedBase):
    def _compute_state(self, status):
        wls = status.get("WlanStatus") or {}
        self._state = wls.get("wireless_5g_channel")

class WifiSsid24Sensor(_DerivedBase):
    @property
    def icon(self): return "mdi:wifi"
    def _compute_state(self, status):
        wls = status.get("WlanStatus") or {}
        self._state = wls.get("wireless_2g_ssid")

class WifiSsid5Sensor(_DerivedBase):
    @property
    def icon(self): return "mdi:wifi"
    def _compute_state(self, status):
        wls = status.get("WlanStatus") or {}
        self._state = wls.get("wireless_5g_ssid")

class WifiChannel24Sensor(_DerivedBase):
    @property
    def icon(self): return "mdi:wifi-settings"
    def _compute_state(self, status):
        wls = status.get("WlanStatus") or {}
        self._state = wls.get("wireless_2g_channel")

class WifiChannel5Sensor(_DerivedBase):
    @property
    def icon(self): return "mdi:wifi-settings"
    def _compute_state(self, status):
        wls = status.get("WlanStatus") or {}
        self._state = wls.get("wireless_5g_channel")

class Wifi24EnabledBinary(_DerivedBinaryBase):
    @property
    def device_class(self): return BinarySensorDeviceClass.CONNECTIVITY
    def _compute_on(self, status):
        wls = status.get("WlanStatus") or {}
        self._is_on = str(wls.get("wireless_2g_enable", "")).lower() == "on"

class Wifi5EnabledBinary(_DerivedBinaryBase):
    @property
    def device_class(self): return BinarySensorDeviceClass.CONNECTIVITY
    def _compute_on(self, status):
        wls = status.get("WlanStatus") or {}
        self._is_on = str(wls.get("wireless_5g_enable", "")).lower() == "on"

class PlcPeersCountSensor(_DerivedBase):
    @property
    def icon(self): return "mdi:power-plug"

    def _compute_state(self, status):
        plc_items = self._as_list(status.get("PlcDeviceStatus"))
        macs = (self._norm_mac((d or {}).get("device_mac")) for d in plc_items)
        self._count_set_attr("plc_peers_macs", macs)       

class PlcMinRxRateSensor(_DerivedBase):
    @property
    def native_unit_of_measurement(self): return UnitOfDataRate.MEGABITS_PER_SECOND
    @property
    def icon(self): return "mdi:power-plug"
    def _compute_state(self, status):
        plc = status.get("PlcDeviceStatus")
        if isinstance(plc, dict): plc = [plc]
        vals = []
        for d in plc or []:
            v = (d or {}).get("rx_rate")
            if isinstance(v, (int, float)): vals.append(int(v))
            elif isinstance(v, str):
                m = re.search(r"\d+", v)
                if m: vals.append(int(m.group(0)))
        self._state = min(vals) if vals else None

class PlcMinTxRateSensor(_DerivedBase):
    @property
    def native_unit_of_measurement(self): return UnitOfDataRate.MEGABITS_PER_SECOND
    @property
    def icon(self): return "mdi:power-plug"
    def _compute_state(self, status):
        plc = status.get("PlcDeviceStatus")
        if isinstance(plc, dict): plc = [plc]
        vals = []
        for d in plc or []:
            v = (d or {}).get("tx_rate")
            if isinstance(v, (int, float)): vals.append(int(v))
            elif isinstance(v, str):
                m = re.search(r"\d+", v)
                if m: vals.append(int(m.group(0)))
        self._state = min(vals) if vals else None
        
        
class PlcDegradedBinary(_DerivedBinaryBase):
    @property
    def device_class(self): return BinarySensorDeviceClass.PROBLEM
    def _compute_on(self, status):
        plc = status.get("PlcDeviceStatus")
        if isinstance(plc, dict): plc = [plc]
        worst = None
        for d in plc or []:
            for key in ("rx_rate", "tx_rate"):
                v = (d or {}).get(key)
                if isinstance(v, (int, float)): val = int(v)
                elif isinstance(v, str):
                    m = re.search(r"\d+", v); val = int(m.group(0)) if m else None
                else:
                    val = None
                if val is not None:
                    worst = val if worst is None else min(worst, val)
        self._is_on = (worst is not None and worst < PLC_DEGRADED_THRESHOLD)


class WifiClientsWithIpSensor(_DerivedBase):
    @property
    def icon(self): return "mdi:lan-connect"
    def _compute_state(self, status):
        clients = status.get("WifiClients")
        if not isinstance(clients, list): clients = []
        def has_ip(c):
            ip = (c or {}).get("ip")
            return isinstance(ip, str) and ip.lower() != "unknown" and len(ip) > 0
        self._state = sum(1 for c in clients if has_ip(c))



