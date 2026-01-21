import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
            
import logging

_LOGGER = logging.getLogger(__name__)
_LOGGER.debug("TP-Link WPA4220 ConfigFlow is initializing...")

_LOGGER.debug("Attempting to import TL_WPA4220 module...")
from .TL_WPA4220 import TL_WPA4220
_LOGGER.debug("done")



class TPLinkConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for TP-Link WPA4220."""

    VERSION = 1

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            ip_address = user_input.get("ip_address")
            password = user_input.get("password", "admin")
            _LOGGER.debug("Step 0")

            try:    
                _LOGGER.debug(f"Step 1 {ip_address} {password}")
                #device = TL_WPA4220(ip_address)
                #_LOGGER.debug("Step 2")
                #await hass.async_add_executor_job(device.login,password)
                #_LOGGER.debug("Step 3")
                #device.logout()

                # If successful, create the config entry
                return self.async_create_entry(title=f"TP-Link {ip_address}", data=user_input)

            except Exception:
                errors["base"] = "cannot_connect"

        schema = vol.Schema({
            vol.Required("ip_address"): str,
            vol.Optional("password", default="admin"): str,
        })

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return TPLinkOptionsFlowHandler(config_entry)

class TPLinkOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for TP-Link WPA4220."""

    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        schema = vol.Schema({
            vol.Optional("ip_address", default=self.config_entry.data.get("ip_address")): str,
            vol.Optional("password", default=self.config_entry.data.get("password", "admin")): str,
        })

        return self.async_show_form(step_id="init", data_schema=schema)


