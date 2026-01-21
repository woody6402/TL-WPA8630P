import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.entity import Entity
from homeassistant.helpers import selector


from .const import DOMAIN
            
import logging

_LOGGER = logging.getLogger(__name__)
_LOGGER.debug("TP-Link WPA4220 ConfigFlow is initializing...")

_LOGGER.debug("Attempting to import TL_WPA4220 module...")
from .TL_WPA4220 import TL_WPA4220
_LOGGER.debug("done")



class TPLinkConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for TP-Link WPA Powerline."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}

        if user_input is not None:
            return self.async_create_entry(
                title=f"TP-Link {user_input.get('ip_address')}",
                data=user_input
            )

        schema = vol.Schema({
            vol.Required("ip_address"): str,
            vol.Optional("password", default="admin"): str,
        })

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)


    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return TPLinkOptionsFlowHandler()

class TPLinkOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow."""

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
         
        data = dict(self.config_entry.data or {})
        options = dict(self.config_entry.options or {})    

        schema = vol.Schema({
            vol.Optional("ip_address", default=str(options.get("ip_address") or data.get("ip_address") or "")): str,
            vol.Optional("password",   default=str(options.get("password")   or data.get("password")   or "admin")): str,            
            vol.Optional(
                "top_n",
                default=int(options.get("top_n") or 12),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=100, step=1, mode="box")
            ),            
           
        })

        return self.async_show_form(step_id="init", data_schema=schema)


