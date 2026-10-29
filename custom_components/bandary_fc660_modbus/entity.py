"""Shared entity base for the FC660 integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ENTITY_PREFIX, DEFAULT_NAME, DOMAIN, MANUFACTURER, MODEL
from .coordinator import Fc660Coordinator


@dataclass(frozen=True, kw_only=True)
class Fc660EntityDescription(EntityDescription):
    """Where an entity's value comes from."""

    value_fn: Callable[[Fc660Coordinator], Any]
    attrs_fn: Callable[[Fc660Coordinator], dict[str, Any]] | None = None


def value(key: str) -> Callable[[Fc660Coordinator], Any]:
    return lambda coordinator: coordinator.data.values.get(key)


def device_info(coordinator: Fc660Coordinator) -> DeviceInfo:
    entry = coordinator.config_entry
    model = coordinator.model
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        manufacturer=MANUFACTURER,
        model=MODEL,
        name=entry.title or DEFAULT_NAME,
        sw_version=model.firmware,
    )


class Fc660Entity(CoordinatorEntity[Fc660Coordinator]):
    """Wires every entity to its panel's device and coordinator."""

    _attr_has_entity_name = True
    entity_description: Fc660EntityDescription

    def __init__(self, coordinator: Fc660Coordinator, description: Fc660EntityDescription,
                 domain: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self.entity_description = description
        self._attr_translation_key = description.translation_key or description.key
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        # Suggest the entity id from the prefix and the key, not from the
        # (translated) name: `sensor.fc660_humidity` whatever language Home
        # Assistant runs in. With the default prefix these are the ids of the
        # `modbus:` YAML setup this replaces, so its history carries over.
        self.entity_id = f"{domain}.{entry.data[CONF_ENTITY_PREFIX]}_{description.key}"
        self._attr_device_info = device_info(coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        attrs_fn = self.entity_description.attrs_fn
        return attrs_fn(self.coordinator) if attrs_fn else None

    async def _async_write(self, *changes: tuple[str, float]) -> None:
        await self.coordinator.async_write(changes)
