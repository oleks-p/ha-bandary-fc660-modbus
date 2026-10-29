"""On/off settings as switches: power (264), away mode (266) and key lock (269).

away_mode and key_lock keep the keys of the `modbus:` YAML setup this replaces.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import Fc660ConfigEntry
from .entity import Fc660Entity, Fc660EntityDescription, value

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class Fc660SwitchDescription(SwitchEntityDescription, Fc660EntityDescription):
    """A 0/1 register."""


SWITCHES: tuple[Fc660SwitchDescription, ...] = (
    # Stand-by status: 0 power off, 1 power on.
    Fc660SwitchDescription(key="power", value_fn=value("power")),
    # Scene mode: 0 comfort, 1 away.
    Fc660SwitchDescription(key="away_mode", value_fn=value("away_mode")),
    Fc660SwitchDescription(key="key_lock", entity_category=EntityCategory.CONFIG,
                           value_fn=value("key_lock")),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Fc660ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities(Fc660Switch(coordinator, d, "switch") for d in SWITCHES)


class Fc660Switch(Fc660Entity, SwitchEntity):
    entity_description: Fc660SwitchDescription

    @property
    def is_on(self) -> bool | None:
        return {0: False, 1: True}.get(self.entity_description.value_fn(self.coordinator))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_write((self.entity_description.key, 1))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_write((self.entity_description.key, 0))
