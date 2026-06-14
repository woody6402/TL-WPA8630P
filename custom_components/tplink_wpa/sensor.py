from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import UnitOfDataRate
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send

from .const import DOMAIN
from .TL_WPA4220 import TL_WPA4220

_LOGGER = logging.getLogger(__name__)

SIGNAL_WPA4220_UPDATED = "tplink_wpa_updated_{ip}"
SCAN_INTERVAL = timedelta(minutes=2)

PLC_DEGRADED_THRESHOLD = 100  # Mbit/s


# Global lock: the WPA8631P (and likely other models) only accept one active
# session at a time. Without this, two configured devices logging in
# simultaneously invalidate each other's session, causing empty responses
# and JSONDecodeError. All polling is serialized through this lock.
_DEVICE_POLL_LOCK: asyncio.Lock | None = None

def _get_poll_lock() -> asyncio.Lock:
    global _DEVICE_POLL_LOCK
    if _DEVICE_POLL_LOCK is None:
        _DEVICE_POLL_LOCK = asyncio.Lock()
    return _DEVICE_POLL_LOCK


async def async_setup_entry(hass: HomeAssistant, config_entry, async_add_entities):
    """Set up sensors for TP-Link WPA powerline device."""
    ip = config_entry.data["ip_address"]
    pwd = config_entry.data["password"]

    shared = {"status": None, "top_n": int((config_entry.options or {}).get("top_n", 12))}

    main = TPLinkStatusSensor(hass, "status", ip, pwd, config_entry, shared)

    entities = [
        main,
        WifiClientsTotalSensor(hass, "wifi_clients_total", ip, config_entry, shared),
        WifiClients24Sensor(hass, "wifi_clients_24", ip, config_entry, shared),
        WifiClients5Sensor(hass, "wifi_clients_5", ip, config_entry, shared),
        WifiClientsWithIpSensor(hass, "wifi_clients_with_ip", ip, config_entry, shared),
        PlcPeersCountSensor(hass, "plc_peers", ip, config_entry, shared),
        PlcMaxRxRateSensor(hass, "plc_max_rx", ip, config_entry, shared),
        PlcMaxTxRateSensor(hass, "plc_max_tx", ip, config_entry, shared),
        PlcMinRxRateSensor(hass, "plc_min_rx", ip, config_entry, shared),
        PlcMinTxRateSensor(hass, "plc_min_tx", ip, config_entry, shared),
        PlcDegradedBinary(
            hass,
            "plc_degraded",
            ip,
            config_entry,
            shared,
        ),
        WifiSsid24Sensor(hass, "wifi_ssid_24", ip, config_entry, shared),
        WifiSsid5Sensor(hass, "wifi_ssid_5", ip, config_entry, shared),
        WifiChannel24Sensor(hass, "wifi_channel_24", ip, config_entry, shared),
        WifiChannel5Sensor(hass, "wifi_channel_5", ip, config_entry, shared),
        Wifi24EnabledBinary(hass, "wifi_24_enabled", ip, config_entry, shared),
        Wifi5EnabledBinary(hass, "wifi_5_enabled", ip, config_entry, shared),
    ]

    async_add_entities(entities, update_before_add=True)

    # ---- Options wirken SOFORT: update listener ----
    @callback
    def _options_updated(_hass: HomeAssistant, entry) -> None:
        shared["top_n"] = int((entry.options or {}).get("top_n", 12))
        # Derived Entities sofort neu rechnen lassen (auch ohne 2-min Status refresh)
        async_dispatcher_send(hass, SIGNAL_WPA4220_UPDATED.format(ip=ip))

    config_entry.async_on_unload(config_entry.add_update_listener(_options_updated))


class TPLinkStatusSensor(SensorEntity):
    """Sensor to retrieve the full status of the device."""

    _attr_should_poll = True
    _attr_icon = "mdi:access-point"

    def __init__(self, hass, name, ip, password, config_entry, shared):
        self._ip = ip
        self._attr_translation_key = name
        self._attr_has_entity_name = True
        self._state = None
        self._attributes = {}
        self._hass = hass
        self._password = password
        self._config_entry = config_entry
        self._shared = shared


    @property
    def state(self):
        return self._state

    @property
    def extra_state_attributes(self):
        return self._attributes

    @property
    def unique_id(self):
        return f"tplink_wpa_{self._ip}"

    @property
    def device_info(self):
        return {
            "identifiers": {("tplink_wpa", self._ip)},
            "name": "TP-Link WPA",
            "manufacturer": "TP-Link",
            "model": "WPA",
            "configuration_url": f"http://{self._ip}/",
        }

    @callback
    def _handle_push(self) -> None:
        self.schedule_update_ha_state(True)

    async def async_added_to_hass(self) -> None:
        self._unsub = async_dispatcher_connect(
            self.hass,
            SIGNAL_WPA4220_UPDATED.format(ip=self._ip),
            self._handle_push,
        )
        self.async_on_remove(self._unsub)

    async def async_update(self):
        async with _get_poll_lock():
            await self._do_update()

    async def _do_update(self):
        device = None

        rebooting = (
            self._hass.data
            .get(DOMAIN, {})
            .get("rebooting", {})
            .get(self._ip)
        )

        if rebooting:
            now = datetime.now()

            self._state = "rebooting"
            self._attributes["rebooting"] = True
            self._attributes["rebooting_since"] = (
                rebooting["since"].isoformat()
            )

            if now < rebooting["probe_after"]:
                return

        try:
            device = TL_WPA4220(self._ip)

            _LOGGER.debug(
                "Logging in to the device... %s",
                self._ip,
            )

            await self._hass.async_add_executor_job(
                device.login,
                self._password,
            )

            async def _fetch_all():
                f = await self._hass.async_add_executor_job(
                    device.get_firmware_info
                )
                p = await self._hass.async_add_executor_job(
                    device.get_plc_device_status
                )
                w = await self._hass.async_add_executor_job(
                    device.get_wlan_status
                )
                wc = await self._hass.async_add_executor_job(
                    device.get_wifi_clients
                )
                return f, p, w, wc

            fw_data, plc_list, wls_data, wic_list = (
                await asyncio.wait_for(
                    _fetch_all(),
                    timeout=60,
                )
            )

            now_str = datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )

            if isinstance(wls_data, dict):
                wls_data["wireless_2g_pwd"] = (
                    f"hidden ({now_str})"
                )
                wls_data["wireless_5g_pwd"] = (
                    f"hidden ({now_str})"
                )

        except TL_WPA4220.TpError as e:

            if rebooting:
                _LOGGER.debug(
                    "Device %s still rebooting: %s",
                    self._ip,
                    e,
                )
                return

            ignore_codes = {
                "decode-error",
                "empty-decrypted-response",
                "missing-data",
            }

            if getattr(e, "error_code", None) in ignore_codes:
                self._attributes["last_error"] = str(e)

                _LOGGER.debug(
                    "Ignoring transient TP-Link error on %s: %s",
                    self._ip,
                    e,
                )
                return

            self._state = "error"
            self._attributes = {"error": str(e)}

            _LOGGER.error(
                "Error during data retrieval: %s",
                e,
            )

        except Exception as e:

            if rebooting:
                _LOGGER.debug(
                    "Device %s still rebooting: %s",
                    self._ip,
                    e,
                )
                return

            self._state = "error"
            self._attributes = {"error": str(e)}

            _LOGGER.error(
                "Error during data retrieval: %s",
                e,
            )

        else:

            if rebooting:
                self._hass.data.get(
                    DOMAIN,
                    {},
                ).get(
                    "rebooting",
                    {},
                ).pop(
                    self._ip,
                    None,
                )

            status = {
                "FirmwareInfo": fw_data,
                "WlanStatus": wls_data,
                "WifiClients": wic_list,
                "PlcDeviceStatus": plc_list,
            }

            self._state = "connected"

            self._attributes = status
            self._attributes["rebooting"] = False

            self._attributes.pop(
                "last_error",
                None,
            )

            self._shared["status"] = status

            async_dispatcher_send(
                self._hass,
                SIGNAL_WPA4220_UPDATED.format(
                    ip=self._ip
                ),
            )

            try:

                def _norm(mac):
                    if not mac:
                        return None
                    return (
                        mac.strip()
                        .lower()
                        .replace("-", ":")
                    )

                mac_24 = _norm(
                    (wls_data or {}).get(
                        "wireless_2g_macaddr"
                    )
                )

                mac_5 = _norm(
                    (wls_data or {}).get(
                        "wireless_5g_macaddr"
                    )
                )

                conn_set = {
                    ("mac", m)
                    for m in (mac_24, mac_5)
                    if m
                }

                device_registry = dr.async_get(
                    self._hass
                )

                dev = (
                    device_registry.async_get_or_create(
                        config_entry_id=self._config_entry.entry_id,
                        identifiers={
                            ("tplink_wpa", self._ip)
                        },
                        manufacturer="TP-Link",
                        name="TP-Link WPA",
                        connections=(
                            conn_set
                            if conn_set
                            else None
                        ),
                    )
                )

                device_registry.async_update_device(
                    device_id=dev.id,
                    model=(
                        (fw_data or {}).get("model")
                        or "WPA"
                    ),
                    sw_version=(
                        fw_data or {}
                    ).get(
                        "firmware_version"
                    ),
                    hw_version=(
                        fw_data or {}
                    ).get(
                        "hardware_version"
                    ),
                )

            except Exception as reg_err:
                _LOGGER.debug(
                    "Device registry update skipped/failed: %s",
                    reg_err,
                )

        finally:
            try:
                if device:
                    await self._hass.async_add_executor_job(
                        device.logout
                    )
            except Exception as logout_error:
                _LOGGER.error(
                    "Logout error: %s",
                    logout_error,
                )





class _DerivedBinaryBase(BinarySensorEntity):
    _attr_should_poll = False

    def __init__(self, hass, name, ip, config_entry, shared):
        self._hass = hass
        self._attr_translation_key = name
        self._attr_has_entity_name = True
        self._ip = ip
        self._config_entry = config_entry
        self._shared = shared
        self._is_on = None
        self._unsub = None


    @property
    def unique_id(self):
        return f"{self._config_entry.entry_id}_{self._ip}_{self.__class__.__name__.lower()}"

    @property
    def device_info(self):
        return {
            "identifiers": {("tplink_wpa", self._ip)},
            "name": "TP-Link WPA",
            "manufacturer": "TP-Link",
            "model": "WPA",
        }

    @property
    def is_on(self):
        return self._is_on

    @callback
    def _handle_push(self) -> None:
        self.schedule_update_ha_state(True)

    async def async_added_to_hass(self) -> None:
        self._unsub = async_dispatcher_connect(
            self.hass,
            SIGNAL_WPA4220_UPDATED.format(ip=self._ip),
            self._handle_push,
        )
        self.async_on_remove(self._unsub)
        self.async_schedule_update_ha_state(True)

    async def async_update(self):
        status = self._shared.get("status") or {}
        self._compute_on(status)

    def _compute_on(self, status: dict):
        raise NotImplementedError


class _DerivedBase(SensorEntity):
    _attr_should_poll = False

    def __init__(self, hass, name, ip, config_entry, shared):
        self._hass = hass
        self._attr_translation_key = name
        self._attr_has_entity_name = True
        self._ip = ip
        self._config_entry = config_entry
        self._shared = shared
        self._state = None
        self._unsub = None
        self._attrs = {}


    @property
    def unique_id(self):
        return f"{self._config_entry.entry_id}_{self._ip}_{self.__class__.__name__.lower()}"

    @property
    def device_info(self):
        return {
            "identifiers": {("tplink_wpa", self._ip)},
            "name": "TP-Link WPA",
            "manufacturer": "TP-Link",
            "model": "WPA",
        }

    @property
    def extra_state_attributes(self):
        return self._attrs

    @property
    def native_value(self):
        return self._state

    @callback
    def _handle_push(self) -> None:
        self.schedule_update_ha_state(True)

    async def async_update(self):
        status = self._shared.get("status") or {}
        self._compute_state(status)

    async def async_added_to_hass(self) -> None:
        self._unsub = async_dispatcher_connect(
            self.hass,
            SIGNAL_WPA4220_UPDATED.format(ip=self._ip),
            self._handle_push,
        )
        self.async_on_remove(self._unsub)
        self.async_schedule_update_ha_state(True)

    # ---- Helpers ----
    @staticmethod
    def _as_list(maybe):
        if isinstance(maybe, list):
            return maybe
        if isinstance(maybe, dict):
            return [maybe]
        return []

    @staticmethod
    def _unique_sorted(seq):
        return sorted({x for x in seq if x})

    @staticmethod
    def _norm_mac(mac: str | None) -> str | None:
        if not mac:
            return None
        return mac.strip().lower().replace("-", ":")

    @staticmethod
    def _to_int(v):
        if isinstance(v, (int, float)):
            return int(v)
        try:
            return int(str(v).strip())
        except Exception:
            return 0

    @staticmethod
    def _band_str(c) -> str:
        return str((c or {}).get("type", "")).strip().lower()

    def _is_band(self, client: dict, band: str | None) -> bool:
        t = self._band_str(client)
        if band is None:
            return True
        if band == "2.4":
            return "2.4" in t
        if band == "5":
            return ("5" in t) and ("ghz" in t or " 5g" in t or t.endswith("5g"))
        return False

    def _clients_for(self, status: dict, band: str | None):
        clients = status.get("WifiClients")
        clients = clients if isinstance(clients, list) else []
        return [c for c in clients if isinstance(c, dict) and self._is_band(c, band)]

    def _take_top_n(self, items, n: int):
        if not isinstance(items, list) or not isinstance(n, int) or n <= 0:
            return []
        return items[:n]

    def _drop_key_from_dicts(self, items, key: str):
        if not isinstance(items, list):
            return []
        out = []
        for d in items:
            if isinstance(d, dict):
                out.append({k: v for k, v in d.items() if k != key})
        return out

    def _enrich_clients(self, clients: list[dict], top_n: int = 12):
        names, macs, enriched = [], [], []
        for c in clients:
            mac = self._norm_mac(c.get("mac"))
            name = (c.get("devName") or c.get("name") or mac)
            rx = self._to_int(c.get("rxpkts"))
            tx = self._to_int(c.get("txpkts"))
            enriched.append(
                {
                    "name": name,
                    "mac": mac,
                    "ip": c.get("ip"),
                    "band": c.get("type"),
                    "pkts": f"({rx/1000:.1f}k, {tx/1000:.1f}k)",
                    "total_pkts": rx + tx,
                }
            )
            if mac:
                if isinstance(name, str) and name.strip():
                    names.append(name.strip())
                macs.append(mac)

        names_sorted = sorted(set(names))
        macs_sorted_unique = self._unique_sorted(macs)

        top_all = sorted(enriched, key=lambda x: x["total_pkts"], reverse=True)
        top_n_list = self._take_top_n(top_all, top_n)
        top_sorted = self._drop_key_from_dicts(top_n_list, "total_pkts")

        return names_sorted, macs_sorted_unique, top_sorted

    def _count_set_attr(self, attr_key: str, values_iterable):
        vals = self._unique_sorted(values_iterable)
        self._attrs[attr_key] = vals
        self._state = len(vals)

    def _compute_state(self, status: dict):
        raise NotImplementedError


class WifiClientsTotalSensor(_DerivedBase):
    @property
    def icon(self):
        return "mdi:account-multiple"

    def _compute_state(self, status):
        clients = self._clients_for(status, None)
        self._state = len(clients)

        n = int(self._shared.get("top_n", 12))
        names, macs, topN = self._enrich_clients(clients, top_n=n)
        self._attrs.update(
            {
                "wifi_client_names": names,
                f"wifi_top{n}_by_packets": topN,
            }
        )


class WifiClients24Sensor(_DerivedBase):
    @property
    def icon(self):
        return "mdi:wifi"

    def _compute_state(self, status):
        clients = self._clients_for(status, "2.4")
        self._state = len(clients)

        n = int(self._shared.get("top_n", 12))
        names, macs, topN = self._enrich_clients(clients, top_n=n)
        self._attrs.update(
            {
                "wifi_24_client_names": names,
                f"wifi_24_top{n}_by_packets": self._drop_key_from_dicts(topN, "band"),
            }
        )


class WifiClients5Sensor(_DerivedBase):
    @property
    def icon(self):
        return "mdi:wifi"

    def _compute_state(self, status):
        clients = self._clients_for(status, "5")
        self._state = len(clients)

        n = int(self._shared.get("top_n", 12))
        names, macs, topN = self._enrich_clients(clients, top_n=n)
        self._attrs.update(
            {
                "wifi_5_client_names": names,
                f"wifi_5_top{n}_by_packets": self._drop_key_from_dicts(topN, "band"),
            }
        )


class WifiClientsWithIpSensor(_DerivedBase):
    @property
    def icon(self):
        return "mdi:lan-connect"

    def _compute_state(self, status):
        clients = status.get("WifiClients")
        clients = clients if isinstance(clients, list) else []

        def has_ip(c):
            ip = (c or {}).get("ip")
            return isinstance(ip, str) and ip.lower() != "unknown" and len(ip) > 0

        self._state = sum(1 for c in clients if isinstance(c, dict) and has_ip(c))


class PlcPeersCountSensor(_DerivedBase):
    @property
    def icon(self):
        return "mdi:power-plug"

    def _compute_state(self, status):
        plc_items = self._as_list(status.get("PlcDeviceStatus"))
        macs = (self._norm_mac((d or {}).get("device_mac")) for d in plc_items)
        self._count_set_attr("plc_peers_macs", macs)


class PlcMaxRxRateSensor(_DerivedBase):
    @property
    def native_unit_of_measurement(self):
        return UnitOfDataRate.MEGABITS_PER_SECOND

    @property
    def icon(self):
        return "mdi:power-plug"

    def _compute_state(self, status):
        plc = status.get("PlcDeviceStatus")
        plc = [plc] if isinstance(plc, dict) else (plc if isinstance(plc, list) else [])
        rx_vals = []
        for d in plc:
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
    def native_unit_of_measurement(self):
        return UnitOfDataRate.MEGABITS_PER_SECOND

    @property
    def icon(self):
        return "mdi:power-plug"

    def _compute_state(self, status):
        plc = status.get("PlcDeviceStatus")
        plc = [plc] if isinstance(plc, dict) else (plc if isinstance(plc, list) else [])
        tx_vals = []
        for d in plc:
            v = (d or {}).get("tx_rate")
            if isinstance(v, (int, float)):
                tx_vals.append(int(v))
            elif isinstance(v, str):
                m = re.search(r"\d+", v)
                if m:
                    tx_vals.append(int(m.group(0)))
        self._state = max(tx_vals) if tx_vals else None


class PlcMinRxRateSensor(_DerivedBase):
    @property
    def native_unit_of_measurement(self):
        return UnitOfDataRate.MEGABITS_PER_SECOND

    @property
    def icon(self):
        return "mdi:power-plug"

    def _compute_state(self, status):
        plc = status.get("PlcDeviceStatus")
        plc = [plc] if isinstance(plc, dict) else (plc if isinstance(plc, list) else [])
        vals = []
        for d in plc:
            v = (d or {}).get("rx_rate")
            if isinstance(v, (int, float)):
                vals.append(int(v))
            elif isinstance(v, str):
                m = re.search(r"\d+", v)
                if m:
                    vals.append(int(m.group(0)))
        self._state = min(vals) if vals else None


class PlcMinTxRateSensor(_DerivedBase):
    @property
    def native_unit_of_measurement(self):
        return UnitOfDataRate.MEGABITS_PER_SECOND

    @property
    def icon(self):
        return "mdi:power-plug"

    def _compute_state(self, status):
        plc = status.get("PlcDeviceStatus")
        plc = [plc] if isinstance(plc, dict) else (plc if isinstance(plc, list) else [])
        vals = []
        for d in plc:
            v = (d or {}).get("tx_rate")
            if isinstance(v, (int, float)):
                vals.append(int(v))
            elif isinstance(v, str):
                m = re.search(r"\d+", v)
                if m:
                    vals.append(int(m.group(0)))
        self._state = min(vals) if vals else None


class PlcDegradedBinary(_DerivedBinaryBase):
    @property
    def device_class(self):
        return BinarySensorDeviceClass.PROBLEM

    def _compute_on(self, status):
        plc = status.get("PlcDeviceStatus")
        plc = [plc] if isinstance(plc, dict) else (plc if isinstance(plc, list) else [])
        worst = None
        for d in plc:
            for key in ("rx_rate", "tx_rate"):
                v = (d or {}).get(key)
                if isinstance(v, (int, float)):
                    val = int(v)
                elif isinstance(v, str):
                    m = re.search(r"\d+", v)
                    val = int(m.group(0)) if m else None
                else:
                    val = None
                if val is not None:
                    worst = val if worst is None else min(worst, val)
        self._is_on = worst is not None and worst < PLC_DEGRADED_THRESHOLD


class WifiSsid24Sensor(_DerivedBase):
    @property
    def icon(self):
        return "mdi:wifi"

    def _compute_state(self, status):
        wls = status.get("WlanStatus") or {}
        self._state = wls.get("wireless_2g_ssid")


class WifiSsid5Sensor(_DerivedBase):
    @property
    def icon(self):
        return "mdi:wifi"

    def _compute_state(self, status):
        wls = status.get("WlanStatus") or {}
        self._state = wls.get("wireless_5g_ssid")


class WifiChannel24Sensor(_DerivedBase):
    @property
    def icon(self):
        return "mdi:wifi-settings"

    def _compute_state(self, status):
        wls = status.get("WlanStatus") or {}
        self._state = wls.get("wireless_2g_channel")


class WifiChannel5Sensor(_DerivedBase):
    @property
    def icon(self):
        return "mdi:wifi-settings"

    def _compute_state(self, status):
        wls = status.get("WlanStatus") or {}
        self._state = wls.get("wireless_5g_channel")


class Wifi24EnabledBinary(_DerivedBinaryBase):
    @property
    def device_class(self):
        return BinarySensorDeviceClass.CONNECTIVITY

    def _compute_on(self, status):
        wls = status.get("WlanStatus") or {}
        self._is_on = str(wls.get("wireless_2g_enable", "")).lower() == "on"


class Wifi5EnabledBinary(_DerivedBinaryBase):
    @property
    def device_class(self):
        return BinarySensorDeviceClass.CONNECTIVITY

    def _compute_on(self, status):
        wls = status.get("WlanStatus") or {}
        self._is_on = str(wls.get("wireless_5g_enable", "")).lower() == "on"

