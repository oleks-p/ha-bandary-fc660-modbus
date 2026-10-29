"""Enumerated settings as selects: the working mode (265) and the display unit (257)."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import Fc660ConfigEntry
from .coordinator import Fc660Coordinator
from .entity import Fc660Entity, Fc660EntityDescription
from .registers import ENUMS

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class Fc660SelectDescription(SelectEntityDescription, Fc660EntityDescription):
    """An enumerated register."""


def _select(key: str, **kwargs) -> Fc660SelectDescription:
    table = ENUMS[key]

    def state(coordinator: Fc660Coordinator) -> str | None:
        raw = coordinator.data.values.get(key)
        return table.get(raw) if raw is not None else None

    return Fc660SelectDescription(key=key, options=list(table.values()), value_fn=state, **kwargs)


SELECTS: tuple[Fc660SelectDescription, ...] = (
    _select("working_mode"),
    _select("display_unit", entity_category=EntityCategory.CONFIG),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Fc660ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities(Fc660Select(coordinator, d, "select") for d in SELECTS)


class Fc660Select(Fc660Entity, SelectEntity):
    entity_description: Fc660SelectDescription

    @property
    def current_option(self) -> str | None:
        return self.entity_description.value_fn(self.coordinator)

    async def async_select_option(self, option: str) -> None:
        key = self.entity_description.key
        raw = next(n for n, name in ENUMS[key].items() if name == option)
        await self._async_write((key, raw))
