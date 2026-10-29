"""The clock sync button: set the panel's clock (275-279) to Home Assistant's time."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import Fc660ConfigEntry
from .entity import Fc660Entity, Fc660EntityDescription

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class Fc660ButtonDescription(ButtonEntityDescription, Fc660EntityDescription):
    """A one-shot action."""


SYNC_CLOCK = Fc660ButtonDescription(key="sync_clock", entity_category=EntityCategory.CONFIG,
                                    value_fn=lambda _: None)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Fc660ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([Fc660SyncClock(entry.runtime_data.coordinator, SYNC_CLOCK, "button")])


class Fc660SyncClock(Fc660Entity, ButtonEntity):
    entity_description: Fc660ButtonDescription

    async def async_press(self) -> None:
        await self.coordinator.async_sync_clock()
