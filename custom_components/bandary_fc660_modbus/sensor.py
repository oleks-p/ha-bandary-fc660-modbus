"""Sensor entities: the readings, the fault code, the panel clock, and read-only registers.

humidity, tvoc and co2 keep the keys and units of the `modbus:` YAML setup this
replaces (sensor.fc660_humidity, ...), so their history carries over.
entities.json pins every key, unit and class, and a test holds this file to it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import Fc660ConfigEntry
from .coordinator import Fc660Coordinator
from .entity import Fc660Entity, Fc660EntityDescription, value
from .registers import ENUMS, FAULT_DESCRIPTIONS

try:  # Home Assistant 2026.8 and later; the old constants go in 2027.8.
    from homeassistant.const import UnitOfRatio

    PPB, PPM = UnitOfRatio.PARTS_PER_BILLION, UnitOfRatio.PARTS_PER_MILLION
except ImportError:  # pragma: no cover - older releases
    from homeassistant.const import (
        CONCENTRATION_PARTS_PER_BILLION as PPB,
    )
    from homeassistant.const import (
        CONCENTRATION_PARTS_PER_MILLION as PPM,
    )

PARALLEL_UPDATES = 0  # all reads go through the coordinator

DIAGNOSTIC = EntityCategory.DIAGNOSTIC
MEASUREMENT = SensorStateClass.MEASUREMENT


@dataclass(frozen=True, kw_only=True)
class Fc660SensorDescription(SensorEntityDescription, Fc660EntityDescription):
    """A sensor and where its value comes from."""


def _enum(key: str, **kwargs: Any) -> Fc660SensorDescription:
    table = ENUMS[key]

    def state(coordinator: Fc660Coordinator) -> str | None:
        raw = coordinator.data.values.get(key)
        return table.get(raw) if raw is not None else None

    return Fc660SensorDescription(key=key, device_class=SensorDeviceClass.ENUM,
                                  options=list(table.values()), value_fn=state, **kwargs)


def _fault_attrs(coordinator: Fc660Coordinator) -> dict[str, Any]:
    values = coordinator.data.values
    code = values.get("fault_code")
    return {"raw": values.get("fault_code_raw"),
            "description": FAULT_DESCRIPTIONS.get(code, "") if code not in (None, "none") else ""}


SENSORS: tuple[Fc660SensorDescription, ...] = (
    # -- readings (input registers 1-4) ------------------------------------
    Fc660SensorDescription(
        key="temperature", native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE, state_class=MEASUREMENT,
        suggested_display_precision=1, value_fn=value("temperature")),
    Fc660SensorDescription(
        key="humidity", native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.HUMIDITY, state_class=MEASUREMENT,
        value_fn=value("humidity")),
    Fc660SensorDescription(
        key="tvoc", native_unit_of_measurement=PPB,
        device_class=SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS_PARTS,
        state_class=MEASUREMENT, value_fn=value("tvoc")),
    Fc660SensorDescription(
        key="co2", native_unit_of_measurement=PPM,
        device_class=SensorDeviceClass.CO2, state_class=MEASUREMENT, value_fn=value("co2")),
    # -- fault (input register 14) -----------------------------------------
    Fc660SensorDescription(key="fault_code", value_fn=value("fault_code"),
                           attrs_fn=_fault_attrs),
    # -- identity and read-only registers ----------------------------------
    _enum("equipment_type", entity_category=DIAGNOSTIC),
    Fc660SensorDescription(key="firmware", entity_category=DIAGNOSTIC,
                           value_fn=value("firmware")),
    # 256 and 263 are never written (registers.FORBIDDEN_WRITES).
    Fc660SensorDescription(key="modbus_address", entity_category=DIAGNOSTIC,
                           value_fn=value("modbus_address")),
    Fc660SensorDescription(key="password", entity_category=DIAGNOSTIC,
                           entity_registry_enabled_default=False, value_fn=value("password")),
    # -- the panel clock (holding registers 275-279) -----------------------
    Fc660SensorDescription(
        key="clock", device_class=SensorDeviceClass.TIMESTAMP, entity_category=DIAGNOSTIC,
        value_fn=value("clock"),
        attrs_fn=lambda c: {"drift_seconds": c.data.values.get("clock_drift"),
                            "sync_clock": c.sync_clock}),
    # -- link health -----------------------------------------------------------
    Fc660SensorDescription(
        key="last_successful_read", device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=DIAGNOSTIC, value_fn=lambda c: c.last_success_at),
    Fc660SensorDescription(
        key="read_failures", entity_category=DIAGNOSTIC, value_fn=lambda c: c.read_failures),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Fc660ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities(Fc660Sensor(coordinator, d, "sensor") for d in SENSORS)


class Fc660Sensor(Fc660Entity, SensorEntity):
    entity_description: Fc660SensorDescription

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator)
