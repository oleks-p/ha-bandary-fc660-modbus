"""Writable numeric settings (holding registers) as number entities.

The value shown is what the unit holds, read back after every write. Ranges
and steps are the manual's (registers.WRITE_SPECS).

The degF registers are separate registers, not views of the degC ones: the
panel uses one set or the other, by its display unit (register 257), and the
other set keeps whatever it last held. They are disabled by default.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import Fc660ConfigEntry
from .entity import Fc660Entity, Fc660EntityDescription, value
from .registers import WRITE_SPECS

PARALLEL_UPDATES = 1  # one write at a time: they share one bus

CELSIUS, FAHRENHEIT = UnitOfTemperature.CELSIUS, UnitOfTemperature.FAHRENHEIT
CONFIG = EntityCategory.CONFIG


@dataclass(frozen=True, kw_only=True)
class Fc660NumberDescription(NumberEntityDescription, Fc660EntityDescription):
    """A writable numeric register."""


def _number(key: str, unit: str | None, *, device_class: NumberDeviceClass | None = None,
            mode: NumberMode = NumberMode.BOX, category: EntityCategory | None = CONFIG,
            enabled: bool = True) -> Fc660NumberDescription:
    spec = WRITE_SPECS[key]
    return Fc660NumberDescription(
        key=key,
        native_min_value=spec.minimum,
        native_max_value=spec.maximum,
        native_step=spec.step,
        native_unit_of_measurement=unit,
        device_class=device_class,
        mode=mode,
        entity_category=category,
        entity_registry_enabled_default=enabled,
        value_fn=value(key),
    )


# Offsets, dead bands and hysteresis are temperature DIFFERENCES: no device
# class, or Home Assistant would convert a 0.5 K band with the absolute formula.
# The degF registers carry no device class either, so they show as the panel
# holds them instead of converted to the system's unit.
NUMBERS: tuple[Fc660NumberDescription, ...] = (
    _number("setpoint", CELSIUS, device_class=NumberDeviceClass.TEMPERATURE, category=None),
    _number("setpoint_f", FAHRENHEIT, category=None, enabled=False),
    _number("backlight_brightness", PERCENTAGE, mode=NumberMode.SLIDER),
    _number("backlight_timeout", UnitOfTime.SECONDS, device_class=NumberDeviceClass.DURATION),
    _number("temperature_offset", CELSIUS),
    _number("temperature_offset_f", FAHRENHEIT, enabled=False),
    _number("humidity_offset", PERCENTAGE),
    _number("compressor_delay", UnitOfTime.MINUTES, device_class=NumberDeviceClass.DURATION),
    _number("dead_band", CELSIUS),
    _number("dead_band_f", FAHRENHEIT, enabled=False),
    _number("stage_hysteresis", CELSIUS),
    _number("stage_hysteresis_f", FAHRENHEIT, enabled=False),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Fc660ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities(Fc660Number(coordinator, d, "number") for d in NUMBERS)


class Fc660Number(Fc660Entity, NumberEntity):
    entity_description: Fc660NumberDescription

    @property
    def native_value(self) -> float | None:
        return self.entity_description.value_fn(self.coordinator)

    async def async_set_native_value(self, value: float) -> None:
        await self._async_write((self.entity_description.key, value))
