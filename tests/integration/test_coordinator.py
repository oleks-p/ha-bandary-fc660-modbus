"""Polling: two reads, on their tiers, and an outage that does not flap entities."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE

INPUT_READ = (4, 0, 15)
HOLDING_READ = (3, 256, 24)


async def test_setup_reads_each_block_whole(hass, fake, setup_integration):
    # The identity check, then the first poll: one request per block, nothing else.
    assert fake.reads == [INPUT_READ, HOLDING_READ, INPUT_READ, HOLDING_READ]


async def test_state_every_15_s_settings_every_30_s(hass, fake, setup_integration, advance):
    fake.reads.clear()
    await advance(15)
    assert fake.reads == [INPUT_READ]
    await advance(15)
    assert fake.reads == [INPUT_READ, INPUT_READ, HOLDING_READ]


async def test_a_change_on_the_panel_shows_up(hass, fake, setup_integration, advance):
    fake.set_input(1, 205)          # room at 20.5 degC
    fake.set_holding(267, 220)      # setpoint changed to 22.0 on the panel
    await advance(15)
    assert hass.states.get("sensor.fc660_temperature").state == "20.5"
    assert hass.states.get("number.fc660_setpoint").state == "24.0"     # not read yet
    await advance(15)
    assert hass.states.get("number.fc660_setpoint").state == "22.0"


async def test_an_outage_keeps_the_last_values_then_goes_unavailable(
        hass, fake, setup_integration, advance):
    fake.offline = True
    await advance(60)
    assert hass.states.get("sensor.fc660_temperature").state == "17.6"
    assert hass.states.get("sensor.fc660_read_failures").state != "0"
    await advance(75)               # past the default 120 s
    assert hass.states.get("sensor.fc660_temperature").state == STATE_UNAVAILABLE
    fake.offline = False
    await advance(15)
    assert hass.states.get("sensor.fc660_temperature").state == "17.6"


async def test_setup_waits_for_a_unit_that_does_not_answer(hass, fake, kyiv, config_entry,
                                                           modbus_clients):
    fake.offline = True
    await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_refuses_a_unit_that_reports_another_address(hass, fake, kyiv, config_entry,
                                                                 modbus_clients):
    # It answers at 2 but says it is 5: not the panel this entry is for.
    fake.answer_at = 2
    fake.set_holding(256, 5)
    await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_ERROR


async def test_unload_lets_the_bus_go(hass, setup_integration, modbus_clients):
    assert await hass.config_entries.async_unload(setup_integration.entry_id)
    assert modbus_clients[-1].closes == 1
