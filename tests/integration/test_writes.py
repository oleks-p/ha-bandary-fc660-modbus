"""Writes: FC6 only, inside the manual's ranges, and shown as the unit read them back."""

from __future__ import annotations

import pytest
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from custom_components.bandary_fc660_modbus.transport import Endpoint, Fc660Bus

HOLDING_READ = (3, 256, 24)


async def _set_number(hass, entity_id: str, value: float) -> None:
    await hass.services.async_call("number", "set_value",
                                   {"entity_id": entity_id, "value": value}, blocking=True)


async def test_a_number_is_written_then_read_back(hass, fake, setup_integration):
    fake.reads.clear()
    await _set_number(hass, "number.fc660_setpoint", 22.5)
    assert fake.writes == [(267, 225)]
    # One read of the settings block after the write, and the state is what it says.
    assert fake.reads == [HOLDING_READ]
    assert hass.states.get("number.fc660_setpoint").state == "22.5"
    assert hass.states.get("climate.fc660").attributes["temperature"] == 22.5


async def test_a_negative_offset_is_sent_as_a_signed_word(hass, fake, setup_integration):
    await _set_number(hass, "number.fc660_temperature_offset", -1.5)
    assert fake.writes == [(260, 0x10000 - 15)]
    assert hass.states.get("number.fc660_temperature_offset").state == "-1.5"


@pytest.mark.parametrize(("entity_id", "value"), [
    ("number.fc660_setpoint", 38.5),          # above the manual's 38.0
    ("number.fc660_dead_band", 0.4),          # below 0.5
])
async def test_a_value_outside_the_range_is_never_sent(hass, fake, setup_integration,
                                                       entity_id, value):
    # Home Assistant checks the entity's own min/max first; either way nothing is sent.
    with pytest.raises(ServiceValidationError):
        await _set_number(hass, entity_id, value)
    assert fake.writes == []


async def test_a_value_off_the_step_is_refused_before_sending(hass, fake, setup_integration):
    coordinator = setup_integration.runtime_data.coordinator
    with pytest.raises(ServiceValidationError) as err:
        await coordinator.async_write([("setpoint", 22.55)])
    assert err.value.translation_key == "out_of_range"
    assert fake.writes == []


async def test_a_register_without_a_spec_is_not_writable(hass, fake, setup_integration):
    coordinator = setup_integration.runtime_data.coordinator
    with pytest.raises(ServiceValidationError) as err:
        await coordinator.async_write([("temperature", 20)])
    assert err.value.translation_key == "not_writable"
    assert fake.writes == []


@pytest.mark.parametrize(("service", "entity_id", "expected"), [
    ("turn_on", "switch.fc660_key_lock", (269, 1)),
    ("turn_on", "switch.fc660_away_mode", (266, 1)),
    ("turn_off", "switch.fc660_power", (264, 0)),
])
async def test_switches(hass, fake, setup_integration, service, entity_id, expected):
    await hass.services.async_call("switch", service, {"entity_id": entity_id}, blocking=True)
    assert fake.writes == [expected]
    assert hass.states.get(entity_id).state == ("on" if expected[1] else "off")


@pytest.mark.parametrize(("entity_id", "option", "expected"), [
    ("select.fc660_working_mode", "cooling", (265, 0)),
    ("select.fc660_working_mode", "ventilation", (265, 2)),
    ("select.fc660_display_unit", "fahrenheit", (257, 1)),
])
async def test_selects(hass, fake, setup_integration, entity_id, option, expected):
    await hass.services.async_call("select", "select_option",
                                   {"entity_id": entity_id, "option": option}, blocking=True)
    assert fake.writes == [expected]
    assert hass.states.get(entity_id).state == option


async def test_a_value_the_unit_does_not_keep_is_reported(hass, fake, setup_integration):
    fake.keeps[267] = 230
    with pytest.raises(HomeAssistantError) as err:
        await _set_number(hass, "number.fc660_setpoint", 22.5)
    assert err.value.translation_key == "write_not_applied"
    # What the unit holds is what is shown.
    assert hass.states.get("number.fc660_setpoint").state == "23.0"


async def test_a_refused_write(hass, fake, setup_integration):
    fake.refuses[269] = 3
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call("switch", "turn_on",
                                       {"entity_id": "switch.fc660_key_lock"}, blocking=True)
    assert err.value.translation_key == "write_refused"
    assert hass.states.get("switch.fc660_key_lock").state == "off"


async def test_a_write_on_a_dead_link(hass, fake, setup_integration):
    fake.offline = True
    with pytest.raises(HomeAssistantError) as err:
        await _set_number(hass, "number.fc660_setpoint", 22.5)
    assert err.value.translation_key == "write_failed"
    assert fake.writes == []


@pytest.mark.parametrize("address", [256, 263])
async def test_the_address_and_the_password_are_never_written(address):
    bus = Fc660Bus(Endpoint("tcp", host="127.0.0.1"))
    with pytest.raises(ValueError, match="never written"):
        await bus.write(2, address, 1)
