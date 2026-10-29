"""The panel as a climate entity: power, working mode, setpoint and scene.

Its id is ``climate.<prefix>`` -- with the default prefix ``climate.fc660``, the
id of the `modbus:` YAML climate this replaces -- and its name the device's.

Power is register 264 and the working mode 265, two registers: OFF is power
off (the mode is kept), and HEAT, COOL and FAN_ONLY write the mode, then power
on. The target is the degC setpoint (267) while the panel displays degC, and
the degF one (268) while it displays degF: the panel uses whichever matches its
display unit (257). The presets are the scene (266): comfort and away. What it
is doing comes from the output states (input registers 6-12).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    PRESET_AWAY,
    PRESET_COMFORT,
    ClimateEntity,
    ClimateEntityDescription,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, PRECISION_TENTHS, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import Fc660ConfigEntry
from .const import CONF_ENTITY_PREFIX
from .coordinator import Fc660Coordinator
from .entity import Fc660Entity, Fc660EntityDescription, value
from .registers import WRITE_SPECS

PARALLEL_UPDATES = 1  # one write at a time: they share one bus

#: Register 265 <-> HVAC mode.
MODES: dict[int, HVACMode] = {0: HVACMode.COOL, 1: HVACMode.HEAT, 2: HVACMode.FAN_ONLY}
MODE_VALUES: dict[HVACMode, int] = {mode: raw for raw, mode in MODES.items()}
#: Register 266 <-> preset.
PRESETS: dict[int, str] = {0: PRESET_COMFORT, 1: PRESET_AWAY}
#: Register 5 (equipment type) -> the modes that equipment has.
EQUIPMENT_MODES: dict[int, list[HVACMode]] = {
    2: [HVACMode.OFF, HVACMode.COOL, HVACMode.FAN_ONLY],    # cooling only
    3: [HVACMode.OFF, HVACMode.HEAT, HVACMode.FAN_ONLY],    # heating only
}
ALL_MODES = [HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL, HVACMode.FAN_ONLY]


@dataclass(frozen=True, kw_only=True)
class Fc660ClimateDescription(ClimateEntityDescription, Fc660EntityDescription):
    """The one climate entity."""


THERMOSTAT = Fc660ClimateDescription(key="thermostat", value_fn=value("power"))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Fc660ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([Fc660Climate(entry.runtime_data.coordinator, THERMOSTAT)])


def hvac_action(values: dict[str, Any]) -> HVACAction | None:
    """What the outputs say the panel is calling for.

    W1, W2 and the auxiliary heater only ever heat. Y1 and Y2 are the
    compressor stages: on a heat pump they heat or cool, by the working mode.
    """
    power = values.get("power")
    if power is None:
        return None
    if power == 0:
        return HVACAction.OFF
    if any(values.get(key) == 1 for key in ("w1", "w2", "aux_heater")):
        return HVACAction.HEATING
    if any(values.get(key) == 1 for key in ("y1", "y2")):
        return HVACAction.HEATING if values.get("working_mode") == 1 else HVACAction.COOLING
    if values.get("fan_running") == 1:
        return HVACAction.FAN
    return HVACAction.IDLE


class Fc660Climate(Fc660Entity, ClimateEntity):
    entity_description: Fc660ClimateDescription
    _attr_name = None
    _attr_precision = PRECISION_TENTHS
    _attr_preset_modes = list(PRESETS.values())
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
    )

    def __init__(self, coordinator: Fc660Coordinator,
                 description: Fc660ClimateDescription) -> None:
        super().__init__(coordinator, description, "climate")
        self.entity_id = f"climate.{coordinator.config_entry.data[CONF_ENTITY_PREFIX]}"

    @property
    def _values(self) -> dict[str, Any]:
        return self.coordinator.data.values

    @property
    def _fahrenheit(self) -> bool:
        return self._values.get("fahrenheit") is True

    @property
    def _setpoint_key(self) -> str:
        return "setpoint_f" if self._fahrenheit else "setpoint"

    @property
    def temperature_unit(self) -> str:
        return UnitOfTemperature.FAHRENHEIT if self._fahrenheit else UnitOfTemperature.CELSIUS

    @property
    def current_temperature(self) -> float | None:
        # Register 1 is degC whatever the panel displays.
        celsius = self._values.get("temperature")
        if celsius is None or not self._fahrenheit:
            return celsius
        return round(celsius * 9 / 5 + 32, 1)

    @property
    def current_humidity(self) -> float | None:
        return self._values.get("humidity")

    @property
    def target_temperature(self) -> float | None:
        return self._values.get(self._setpoint_key)

    @property
    def target_temperature_step(self) -> float:
        return 1.0 if self._fahrenheit else 0.5

    @property
    def min_temp(self) -> float:
        return WRITE_SPECS[self._setpoint_key].minimum

    @property
    def max_temp(self) -> float:
        return WRITE_SPECS[self._setpoint_key].maximum

    @property
    def hvac_modes(self) -> list[HVACMode]:
        equipment = self._values.get("equipment_type", self.coordinator.model.equipment_type)
        return EQUIPMENT_MODES.get(equipment, ALL_MODES)

    @property
    def hvac_mode(self) -> HVACMode | None:
        power = self._values.get("power")
        if power is None:
            return None
        if power == 0:
            return HVACMode.OFF
        return MODES.get(self._values.get("working_mode"))

    @property
    def hvac_action(self) -> HVACAction | None:
        return hvac_action(self._values)

    @property
    def preset_mode(self) -> str | None:
        return PRESETS.get(self._values.get("away_mode"))

    def _mode_changes(self, hvac_mode: HVACMode) -> list[tuple[str, float]]:
        if hvac_mode is HVACMode.OFF:
            return [("power", 0)]
        # The mode first: powering on into the old mode, even for a second,
        # would start the wrong outputs.
        return [("working_mode", MODE_VALUES[hvac_mode]), ("power", 1)]

    async def async_set_temperature(self, **kwargs: Any) -> None:
        changes: list[tuple[str, float]] = []
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is not None:
            target = round(temperature) if self._fahrenheit else round(temperature, 1)
            changes.append((self._setpoint_key, target))
        if (hvac_mode := kwargs.get(ATTR_HVAC_MODE)) is not None:
            changes.extend(self._mode_changes(HVACMode(hvac_mode)))
        if changes:
            await self._async_write(*changes)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        await self._async_write(*self._mode_changes(hvac_mode))

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        raw = next(n for n, name in PRESETS.items() if name == preset_mode)
        await self._async_write(("away_mode", raw))

    async def async_turn_on(self) -> None:
        await self._async_write(("power", 1))

    async def async_turn_off(self) -> None:
        await self._async_write(("power", 0))
