"""Polling: three reads on their intervals, and an outage that does not flap entities."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.components.climate import HVACMode
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE

from custom_components.bandary_fc660_modbus.const import (
    CONF_CONTROL_INTERVAL,
    CONF_SETTINGS_INTERVAL,
    CONF_STATE_INTERVAL,
)

CONTROL_READ = (3, 264, 5)
INPUT_READ = (4, 0, 15)
HOLDING_READ = (3, 256, 24)


async def test_setup_reads_each_block_whole(hass, fake, setup_integration):
    # The identity check, then the first poll: one request per block, nothing else.
    assert fake.reads == [INPUT_READ, HOLDING_READ, INPUT_READ, HOLDING_READ]


async def test_by_default_control_every_5_s_state_15_s_settings_30_s(
        hass, fake, setup_integration, advance):
    fake.reads.clear()
    await advance(15)
    assert fake.reads == [CONTROL_READ, CONTROL_READ, CONTROL_READ, INPUT_READ]
    fake.reads.clear()
    await advance(15)
    # At 30 s the settings read brings power, mode and setpoint with it.
    assert fake.reads == [CONTROL_READ, CONTROL_READ, INPUT_READ, HOLDING_READ]


async def test_a_change_on_the_panel_shows_up(hass, fake, setup_integration, advance):
    fake.set_holding(264, 0)        # switched off on the panel
    fake.set_holding(267, 220)      # setpoint changed to 22.0
    fake.set_holding(271, 10)       # dead band changed to 1.0
    fake.set_input(1, 205)          # room at 20.5 degC
    await advance(5)
    assert hass.states.get("climate.fc660").state == HVACMode.OFF
    assert hass.states.get("number.fc660_setpoint").state == "22.0"
    assert hass.states.get("sensor.fc660_temperature").state == "17.6"  # not read yet
    assert hass.states.get("number.fc660_dead_band").state == "0.5"     # nor this
    await advance(10)
    assert hass.states.get("sensor.fc660_temperature").state == "20.5"
    await advance(15)
    assert hass.states.get("number.fc660_dead_band").state == "1.0"


async def test_intervals_come_from_the_options(hass, fake, kyiv, config_entry, modbus_clients,
                                               advance):
    hass.config_entries.async_update_entry(config_entry, options={
        CONF_CONTROL_INTERVAL: 2, CONF_STATE_INTERVAL: 10, CONF_SETTINGS_INTERVAL: 60})
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.runtime_data.coordinator.update_interval == timedelta(seconds=2)
    fake.reads.clear()
    await advance(60, step=2)
    assert fake.reads.count(INPUT_READ) == 6
    assert fake.reads.count(HOLDING_READ) == 1
    assert fake.reads.count(CONTROL_READ) == 29     # not at 60 s: the settings read has it
    assert fake.reads[-2:] == [INPUT_READ, HOLDING_READ]


async def test_an_interval_rounds_to_the_nearest_cycle(hass, fake, kyiv, config_entry,
                                                       modbus_clients, advance):
    # 15 s from a 2 s loop: the seventh cycle, 14 s.
    hass.config_entries.async_update_entry(config_entry, options={
        CONF_CONTROL_INTERVAL: 2, CONF_STATE_INTERVAL: 15})
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    fake.reads.clear()
    await advance(12, step=2)
    assert INPUT_READ not in fake.reads
    await advance(2, step=2)
    assert fake.reads[-1] == INPUT_READ


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
