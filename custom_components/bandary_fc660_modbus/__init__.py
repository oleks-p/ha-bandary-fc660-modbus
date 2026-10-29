"""The Bandary FC660 integration (Modbus RTU).

One config entry per panel. Panels on the same pair of wires -- or behind the
same gateway -- share one bus (transport.BusRegistry), so their requests queue
instead of colliding.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.util.hass_dict import HassKey

from .const import CONF_SLAVE, DOMAIN, PLATFORMS
from .coordinator import Fc660Coordinator
from .model import NotAnFc660, async_identify
from .transport import BusRegistry, Endpoint, Fc660Bus, Fc660TransientError

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

#: One bus per physical link, shared by every entry and config flow using it.
BUSES: HassKey[BusRegistry] = HassKey(DOMAIN)


@dataclass
class Fc660Runtime:
    endpoint: Endpoint
    bus: Fc660Bus
    coordinator: Fc660Coordinator


Fc660ConfigEntry = ConfigEntry[Fc660Runtime]


def bus_registry(hass: HomeAssistant) -> BusRegistry:
    return hass.data.setdefault(BUSES, BusRegistry())


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    return True


async def async_setup_entry(hass: HomeAssistant, entry: Fc660ConfigEntry) -> bool:
    """Check the unit is an FC660 at its address, then start polling it."""
    endpoint = Endpoint.from_config(entry.data)
    registry = bus_registry(hass)
    bus = registry.acquire(endpoint)
    slave = entry.data[CONF_SLAVE]
    try:
        model = await async_identify(bus, slave)
    except NotAnFc660 as err:
        await registry.release(endpoint)
        raise ConfigEntryError(translation_domain=DOMAIN, translation_key="not_an_fc660",
                               translation_placeholders={"slave": str(slave),
                                                         "reason": str(err)}) from err
    except Fc660TransientError as err:
        await registry.release(endpoint)
        raise ConfigEntryNotReady(translation_domain=DOMAIN, translation_key="cannot_connect",
                                  translation_placeholders={"endpoint": str(endpoint),
                                                            "slave": str(slave)}) from err

    coordinator = Fc660Coordinator(hass, entry, bus, slave, model)
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        await registry.release(endpoint)
        raise

    entry.runtime_data = Fc660Runtime(endpoint, bus, coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: Fc660ConfigEntry) -> bool:
    """Stop polling and let the bus go if nothing else uses it."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await bus_registry(hass).release(entry.runtime_data.endpoint)
    return unloaded
