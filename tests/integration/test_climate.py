"""The climate entity: what it shows, and the writes behind each action."""

from __future__ import annotations

import pytest
from homeassistant.components.climate import HVACAction, HVACMode

from custom_components.bandary_fc660_modbus.climate import hvac_action

CLIMATE = "climate.fc660"


async def _call(hass, service: str, **data) -> None:
    await hass.services.async_call("climate", service, {"entity_id": CLIMATE, **data},
                                   blocking=True)


async def test_state_from_the_capture(hass, setup_integration):
    state = hass.states.get(CLIMATE)
    assert state.state == HVACMode.HEAT
    attrs = state.attributes
    assert attrs["hvac_action"] == HVACAction.HEATING       # W1 and W2 are on
    assert attrs["current_temperature"] == 17.6
    assert attrs["temperature"] == 24.0
    assert attrs["current_humidity"] == 58
    assert attrs["preset_mode"] == "comfort"
    assert attrs["min_temp"] == 9.0 and attrs["max_temp"] == 38.0
    assert attrs["friendly_name"] == "FC660"
    assert set(attrs["hvac_modes"]) == {"off", "heat", "cool", "fan_only"}


@pytest.mark.parametrize(("mode", "writes"), [
    ("cool", [(265, 0), (264, 1)]),
    ("fan_only", [(265, 2), (264, 1)]),
    ("heat", [(265, 1), (264, 1)]),
    ("off", [(264, 0)]),
])
async def test_set_hvac_mode(hass, fake, setup_integration, mode, writes):
    await _call(hass, "set_hvac_mode", hvac_mode=mode)
    assert fake.writes == writes
    assert hass.states.get(CLIMATE).state == mode


async def test_set_temperature(hass, fake, setup_integration):
    await _call(hass, "set_temperature", temperature=21.5)
    assert fake.writes == [(267, 215)]
    assert hass.states.get(CLIMATE).attributes["temperature"] == 21.5


async def test_set_temperature_with_a_mode(hass, fake, setup_integration):
    await _call(hass, "set_temperature", temperature=23, hvac_mode="cool")
    assert fake.writes == [(267, 230), (265, 0), (264, 1)]


async def test_presets_are_the_scene(hass, fake, setup_integration):
    await _call(hass, "set_preset_mode", preset_mode="away")
    assert fake.writes == [(266, 1)]
    assert hass.states.get(CLIMATE).attributes["preset_mode"] == "away"


async def test_turn_off_and_on_is_the_power_register(hass, fake, setup_integration):
    await _call(hass, "turn_off")
    await _call(hass, "turn_on")
    assert fake.writes == [(264, 0), (264, 1)]
    assert hass.states.get(CLIMATE).state == HVACMode.HEAT     # the mode was kept


async def test_a_panel_in_fahrenheit_uses_the_fahrenheit_setpoint(hass, fake, kyiv,
                                                                  config_entry, modbus_clients):
    fake.set_holding(257, 1)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    attrs = hass.states.get(CLIMATE).attributes
    # Home Assistant shows it in the system's unit: 69 degF is 20.6 degC.
    assert attrs["temperature"] == 20.6
    assert attrs["current_temperature"] == 17.6
    # The service takes degC here; the panel gets the nearest whole degF.
    await _call(hass, "set_temperature", temperature=21)
    assert fake.writes == [(268, 70)]


async def test_cooling_only_equipment_offers_no_heating(hass, fake, kyiv, config_entry,
                                                        modbus_clients):
    fake.set_input(5, 2)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert set(hass.states.get(CLIMATE).attributes["hvac_modes"]) == {"off", "cool", "fan_only"}


@pytest.mark.parametrize(("values", "action"), [
    ({}, None),
    ({"power": 0, "w1": 1}, HVACAction.OFF),
    ({"power": 1, "aux_heater": 1}, HVACAction.HEATING),
    ({"power": 1, "y1": 1, "working_mode": 0}, HVACAction.COOLING),
    # a heat pump's compressor stage heats in heating mode
    ({"power": 1, "y2": 1, "working_mode": 1}, HVACAction.HEATING),
    ({"power": 1, "fan_running": 1, "working_mode": 2}, HVACAction.FAN),
    ({"power": 1}, HVACAction.IDLE),
])
def test_hvac_action_from_the_outputs(values, action):
    assert hvac_action(values) == action
