"""Binary sensors: the output states (input registers 6-13) and the fault flag.

fan_running, reversing_valve and aux_heater keep the keys of the `modbus:` YAML
setup this replaces.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import Fc660ConfigEntry
from .coordinator import Fc660Coordinator
from .entity import Fc660Entity, Fc660EntityDescription

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class Fc660BinaryDescription(BinarySensorEntityDescription, Fc660EntityDescription):
    """A binary sensor and where its value comes from."""


def _flag(key: str, **kwargs) -> Fc660BinaryDescription:
    """A 0/1 register; anything else (or nothing read) is unknown."""

    def state(coordinator: Fc660Coordinator) -> bool | None:
        raw = coordinator.data.values.get(key)
        return {0: False, 1: True}.get(raw)

    return Fc660BinaryDescription(key=key, value_fn=state, **kwargs)


RUNNING = BinarySensorDeviceClass.RUNNING

BINARY_SENSORS: tuple[Fc660BinaryDescription, ...] = (
    # Y = cooling (compressor) stages, W = heating stages.
    _flag("y1", device_class=RUNNING),
    _flag("y2", device_class=RUNNING),
    _flag("w1", device_class=RUNNING),
    _flag("w2", device_class=RUNNING),
    _flag("fan_running", device_class=RUNNING),
    # A valve position, not something that runs: plain on/off.
    _flag("reversing_valve"),
    _flag("aux_heater", device_class=RUNNING),
    _flag("wifi", device_class=BinarySensorDeviceClass.CONNECTIVITY,
          entity_category=EntityCategory.DIAGNOSTIC),
    Fc660BinaryDescription(key="fault", device_class=BinarySensorDeviceClass.PROBLEM,
                           value_fn=lambda c: c.data.values.get("fault")),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Fc660ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities(Fc660BinarySensor(coordinator, d, "binary_sensor") for d in BINARY_SENSORS)


class Fc660BinarySensor(Fc660Entity, BinarySensorEntity):
    entity_description: Fc660BinaryDescription

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.coordinator)
