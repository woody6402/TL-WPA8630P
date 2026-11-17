"""Home Assistant wrapper for the upstream TP-Link client."""

from __future__ import annotations

import logging

from .TL_WPA4220 import TL_WPA4220


def create_device(ip_address: str) -> TL_WPA4220:
    """Create a client without adding another console log handler.

    The upstream client adds a new ``StreamHandler`` to its process-wide logger
    for every instance. Home Assistant already configures logging, so remove
    only the handler created during this construction. Existing handlers,
    including ones explicitly configured by a user, are left untouched.
    """
    logger = logging.getLogger(TL_WPA4220.__name__)
    existing_handlers = set(logger.handlers)

    device = TL_WPA4220(ip_address)

    for handler in set(logger.handlers) - existing_handlers:
        logger.removeHandler(handler)
        handler.close()

    return device
