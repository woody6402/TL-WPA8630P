import logging
from datetime import timedelta

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD, CONF_HOST
from homeassistant.helpers.event import async_track_time_interval

from .const import DOMAIN
from .technicolor_cga import TechnicolorCGA

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=300)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the Technicolor CGA sensor from a config entry."""
    _LOGGER.debug("Setting up Technicolor CGA sensor")

    username = config_entry.data[CONF_USERNAME]
    password = config_entry.data[CONF_PASSWORD]
    host = config_entry.data[CONF_HOST]

    try:
        technicolor_cga = TechnicolorCGA(username, password, host)
        await hass.async_add_executor_job(technicolor_cga.login)
    except Exception as e:
        _LOGGER.error(f"Failed to log in to Technicolor CGA: {e}")
        return

    sensors = []

    # Add system sensor
    try:
        system_data = await hass.async_add_executor_job(technicolor_cga.system)
        sensors.append(
            TechnicolorCGASystemSensor(
                technicolor_cga,
                hass,
                config_entry.entry_id,
                host,
                "Technicolor CGA System Status",
                system_data,
            )
        )
    except Exception as e:
        _LOGGER.error(f"Failed to fetch system data from Technicolor CGA: {e}")

    # Add DHCP sensors
    try:
        dhcp_data = await hass.async_add_executor_job(technicolor_cga.dhcp)
        for key in dhcp_data.keys():
            sensors.append(
                TechnicolorCGADHCPSensor(
                    technicolor_cga,
                    hass,
                    config_entry.entry_id,
                    host,
                    f"Technicolor CGA DHCP {key}",
                    key,
                )
            )
    except Exception as e:
        _LOGGER.error(f"Failed to fetch DHCP data from Technicolor CGA: {e}")

    # Add host sensor
    try:
        sensors.append(
            TechnicolorCGAHostSensor(
                technicolor_cga,
                hass,
                config_entry.entry_id,
                host,
                "Technicolor CGA Host List",
            )
        )
    except Exception as e:
        _LOGGER.error(f"Failed to fetch host data from Technicolor CGA: {e}")

    # Delta sensor for missing devices
    try:
        sensors.append(
            TechnicolorCGAHostDeltaSensor(
                technicolor_cga,
                hass,
                config_entry.entry_id,
                host,
                "Technicolor CGA Missing Devices",
            )
        )
    except Exception as e:
        _LOGGER.error(f"Failed to create Delta sensor: {e}")

    async_add_entities(sensors, True)
    _LOGGER.debug("Technicolor CGA sensors added (with device_info)")

    # Call async_update at a fixed interval
    for sensor in sensors:
        async_track_time_interval(hass, sensor.async_update, SCAN_INTERVAL)

    # Also perform a bulk refresh on the same schedule (kept from original behavior)
    async_track_time_interval(
        hass, lambda _: [sensor.async_update() for sensor in sensors], SCAN_INTERVAL
    )


class TechnicolorCGABaseSensor(SensorEntity):
    """Base class for Technicolor CGA sensors with device_info."""

    def __init__(self, technicolor_cga, hass, config_entry_id, host, name):
        """Initialize the sensor."""
        self.technicolor_cga = technicolor_cga
        self.hass = hass
        self._config_entry_id = config_entry_id
        self._host = host
        self._attr_name = name
        self._state = None
        self._attributes = {}
        # Optional fields that the system sensor may fill later
        self._model = None
        self._sw_version = None
        _LOGGER.debug(f"{name} Sensor initialized (host: {host})")

    @property
    def unique_id(self):
        """Return a unique ID."""
        return f"{self._config_entry_id}_{self._attr_name.replace(' ', '_').lower()}"

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._attr_name

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def extra_state_attributes(self):
        """Return the state attributes of the sensor."""
        return self._attributes

    @property
    def device_info(self):
        """Return device registry information for the Technicolor gateway.

        Keeping it simple: identifiers by (DOMAIN, host), a friendly name,
        manufacturer, and a configuration URL.
        The system sensor may enrich model and sw_version after its first fetch.
        """
        info = {
            "identifiers": {(DOMAIN, self._host)},
            "name": "Technicolor CGA Gateway",
            "manufacturer": "Technicolor",
            "configuration_url": f"http://{self._host}/",
        }
        if self._model:
            info["model"] = self._model
        if self._sw_version:
            info["sw_version"] = self._sw_version
        return info

    async def async_update(self):
        """Fetch new state data for the sensor."""
        raise NotImplementedError("Subclasses must implement async_update")


class TechnicolorCGASystemSensor(TechnicolorCGABaseSensor):
    """System sensor for Technicolor CGA."""

    def __init__(self, technicolor_cga, hass, config_entry_id, host, name, system_data):
        super().__init__(technicolor_cga, hass, config_entry_id, host, name)
        self._apply_system_data(system_data)

    def _apply_system_data(self, system_data: dict):
        self._state = system_data.get("CMStatus", "Unknown")
        # Pick common keys for model / firmware if available
        self._model = system_data.get("ModelName") or system_data.get("Model")
        self._sw_version = (
            system_data.get("SoftwareVersion")
            or system_data.get("SWVersion")
            or system_data.get("FirmwareVersion")
        )
        self._attributes = {k: v for k, v in system_data.items() if k != "CMStatus"}

    async def async_update(self):
        try:
            system_data = await self.hass.async_add_executor_job(self.technicolor_cga.system)
            self._apply_system_data(system_data)
        except Exception as e:
            _LOGGER.error(f"Error updating {self.name}: {e}")


class TechnicolorCGADHCPSensor(TechnicolorCGABaseSensor):
    """DHCP sensor for Technicolor CGA."""

    def __init__(self, technicolor_cga, hass, config_entry_id, host, name, attribute):
        super().__init__(technicolor_cga, hass, config_entry_id, host, name)
        self._attribute = attribute

    async def async_update(self):
        try:
            dhcp_data = await self.hass.async_add_executor_job(self.technicolor_cga.dhcp)
            self._state = dhcp_data.get(self._attribute, "Unknown")
        except Exception as e:
            _LOGGER.error(f"Error updating {self.name}: {e}")


class TechnicolorCGAHostSensor(TechnicolorCGABaseSensor):
    """Host sensor for Technicolor CGA."""

    def __init__(self, technicolor_cga, hass, config_entry_id, host, name):
        super().__init__(technicolor_cga, hass, config_entry_id, host, name)

    async def async_update(self):
        try:
            host_data = await self.hass.async_add_executor_job(self.technicolor_cga.aDev)
            self._state = len(host_data.get("hostTbl", []))
            self._attributes = host_data
        except Exception as e:
            _LOGGER.error(f"Error updating {self.name}: {e}")


class TechnicolorCGAHostDeltaSensor(SensorEntity):
    """Sensor to calculate missing or inactive devices and track known devices.

    Not inheriting from the base class originally; we still provide device_info
    here to group this entity under the same device in the registry.
    """

    def __init__(self, technicolor_cga, hass, config_entry_id, host, name):
        """Initialize the sensor."""
        self.technicolor_cga = technicolor_cga
        self.hass = hass
        self._config_entry_id = config_entry_id
        self._host = host
        self._attr_name = name
        self._state = None
        self._missing_devices = []
        self._known_devices = {}  # dynamically learned known devices
        _LOGGER.debug(f"{name} Sensor initialized (host: {host})")

    @property
    def unique_id(self):
        """Return a unique ID."""
        return f"{self._config_entry_id}_{self._attr_name.replace(' ', '_').lower()}"

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._attr_name

    @property
    def state(self):
        """Return the state of the sensor."""
        return len(self._missing_devices)

    @property
    def extra_state_attributes(self):
        """Return the state attributes of the sensor."""
        return {
            "missing_devices": sorted(
                self._missing_devices, key=lambda x: self._ip_sort_key(x["last_ip"])
            ),
            "known_devices": sorted(
                [
                    {"mac": mac, "last_ip": details["ip"], "hostname": details["hostname"]}
                    for mac, details in self._known_devices.items()
                ],
                key=lambda x: self._ip_sort_key(x["last_ip"]),
            ),
        }

    @property
    def device_info(self):
        """Match device registry info used by the other sensors."""
        return {
            "identifiers": {(DOMAIN, self._host)},
            "name": "Technicolor CGA Gateway",
            "manufacturer": "Technicolor",
            "configuration_url": f"http://{self._host}/",
        }

    def _ip_sort_key(self, ip):
        """Convert an IP address into a tuple of integers for correct sorting."""
        try:
            return tuple(map(int, ip.split('.')))
        except ValueError:
            # Handle invalid IPs gracefully by placing them at the end
            return (999, 999, 999, 999)

    async def async_update(self):
        """Fetch new state data for the sensor."""
        _LOGGER.debug(f"Updating {self._attr_name} sensor")
        try:
            # Fetch host table
            host_data = await self.hass.async_add_executor_job(self.technicolor_cga.aDev)
            current_devices = {
                host["physaddress"]: {
                    "ip": host.get("ipaddress", "Unknown"),
                    "hostname": host.get("hostname", "Unknown"),
                    "active": host.get("active", "false"),
                }
                for host in host_data.get("hostTbl", [])
            }

            # Update known devices
            for mac, details in current_devices.items():
                self._known_devices[mac] = details

            # Determine missing or inactive devices
            self._missing_devices = []
            for mac, details in self._known_devices.items():
                if mac not in current_devices:
                    self._missing_devices.append(
                        {
                            "mac": mac,
                            "last_ip": details["ip"],
                            "hostname": details["hostname"],
                            "status": "missing",
                        }
                    )
                elif current_devices[mac]["active"] == "false":
                    self._missing_devices.append(
                        {
                            "mac": mac,
                            "last_ip": current_devices[mac]["ip"],
                            "hostname": current_devices[mac]["hostname"],
                            "status": "inactive",
                        }
                    )

            _LOGGER.debug(f"{self._attr_name} sensor state updated: {self._missing_devices}")
        except Exception as e:
            _LOGGER.error(f"Error updating {self._attr_name} sensor: {e}")
