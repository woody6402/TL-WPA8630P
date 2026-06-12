import asyncio
import logging
from datetime import datetime, timedelta

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_IP_ADDRESS
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import DOMAIN
from .TL_WPA4220 import TL_WPA4220

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "button"]

SERVICE_REBOOT = "reboot"
CONF_PASSWORD = "password"

DATA_ENTRIES = "entries"
DATA_SERVICE_REGISTERED = "service_registered"
DATA_REBOOTING_UNTIL = "rebooting_until"

REBOOT_LOGIN_RETRIES = 3
REBOOT_LOGIN_RETRY_DELAY = 2
REBOOT_STATUS_HOLD_SECONDS = 90

DATA_REBOOTING = "rebooting"
REBOOT_PROBE_DELAY_SECONDS = 20
REBOOT_MAX_SECONDS = 180


REBOOT_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_IP_ADDRESS): cv.string,
    }
)

def _mark_rebooting(hass: HomeAssistant, ip_address: str) -> None:
    from datetime import datetime, timedelta
    from homeassistant.helpers.dispatcher import async_dispatcher_send
    from .sensor import SIGNAL_WPA4220_UPDATED

    now = datetime.now()

    hass.data.setdefault(DOMAIN, {}).setdefault(DATA_REBOOTING, {})
    hass.data[DOMAIN][DATA_REBOOTING][ip_address] = {
        "since": now,
        "probe_after": now + timedelta(seconds=REBOOT_PROBE_DELAY_SECONDS),
    }

    async_dispatcher_send(
        hass,
        SIGNAL_WPA4220_UPDATED.format(ip=ip_address),
    )


async def _async_reboot_device(
    hass: HomeAssistant,
    ip_address: str,
    password: str,
) -> bool:
    """Reboot one TP-Link WPA device."""

    from .sensor import _get_poll_lock

    async with _get_poll_lock():
        last_error = None

        for attempt in range(1, REBOOT_LOGIN_RETRIES + 1):
            device = TL_WPA4220(ip_address)

            try:
                await hass.async_add_executor_job(
                    device.login,
                    password,
                )

                result = await hass.async_add_executor_job(
                    device.reboot
                )

                _mark_rebooting(hass, ip_address)

                return result

            except TL_WPA4220.TpError as err:
                last_error = err

                error_code = getattr(err, "error_code", None)

                if (
                    error_code != "timeout"
                    or attempt >= REBOOT_LOGIN_RETRIES
                ):
                    raise

                _LOGGER.warning(
                    "TP-Link WPA reboot login timeout for %s, retrying (%s/%s)",
                    ip_address,
                    attempt,
                    REBOOT_LOGIN_RETRIES,
                )

                await asyncio.sleep(REBOOT_LOGIN_RETRY_DELAY)

            finally:
                try:
                    if device.logged_in():
                        await hass.async_add_executor_job(
                            device.logout
                        )
                except Exception as cleanup_error:
                    _LOGGER.debug(
                        "Ignoring cleanup error for %s: %s",
                        ip_address,
                        cleanup_error,
                    )

        if last_error:
            raise last_error

        return False


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
):
    """Set up TP-Link WPA from a config entry."""

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault(DATA_ENTRIES, {})
    hass.data[DOMAIN].setdefault(DATA_REBOOTING_UNTIL, {})

    hass.data[DOMAIN][DATA_ENTRIES][entry.entry_id] = entry

    if not hass.data[DOMAIN].get(DATA_SERVICE_REGISTERED):

        async def handle_reboot(call: ServiceCall) -> None:
            requested_ip = call.data.get(CONF_IP_ADDRESS)

            entries = list(
                hass.data[DOMAIN]
                .get(DATA_ENTRIES, {})
                .values()
            )

            if requested_ip:
                entries = [
                    e
                    for e in entries
                    if e.data.get(CONF_IP_ADDRESS)
                    == requested_ip
                ]

            if not entries:
                raise ValueError(
                    f"No TP-Link WPA config entry found for "
                    f"ip_address={requested_ip!r}"
                )

            for registered_entry in entries:
                ip_address = registered_entry.data[
                    CONF_IP_ADDRESS
                ]
                password = registered_entry.data[
                    CONF_PASSWORD
                ]

                _LOGGER.info(
                    "Rebooting TP-Link WPA device at %s",
                    ip_address,
                )

                await _async_reboot_device(
                    hass,
                    ip_address,
                    password,
                )

        hass.services.async_register(
            DOMAIN,
            SERVICE_REBOOT,
            handle_reboot,
            schema=REBOOT_SERVICE_SCHEMA,
        )

        hass.data[DOMAIN][
            DATA_SERVICE_REGISTERED
        ] = True

    await hass.config_entries.async_forward_entry_setups(
        entry,
        PLATFORMS,
    )

    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
):
    """Unload config entry."""

    unload_ok = await hass.config_entries.async_unload_platforms(
        entry,
        PLATFORMS,
    )

    if unload_ok:
        hass.data.get(DOMAIN, {}).get(
            DATA_ENTRIES,
            {},
        ).pop(entry.entry_id, None)

        if not hass.data.get(DOMAIN, {}).get(DATA_ENTRIES):

            hass.services.async_remove(
                DOMAIN,
                SERVICE_REBOOT,
            )

            hass.data.get(DOMAIN, {}).pop(
                DATA_SERVICE_REGISTERED,
                None,
            )

            hass.data.pop(DOMAIN, None)    

    return unload_ok

