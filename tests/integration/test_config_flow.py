"""The config flow, several panels on one bus, reconfigure and options."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er

from custom_components.bandary_fc660_modbus import bus_registry
from custom_components.bandary_fc660_modbus.const import (
    CONF_SYNC_CLOCK,
    CONF_UNAVAILABLE_AFTER,
    DOMAIN,
)
from custom_components.bandary_fc660_modbus.transport import Endpoint
from tests.sim import FakeFc660

from .conftest import CAPTURE, PACKAGE

NETWORK = {"host": "127.0.0.1", "port": 10502, "transport": "tcp"}


async def _network_flow(hass, **fields):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.flow.async_configure(result["flow_id"],
                                                            {"next_step_id": "network"})
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "FC660", **NETWORK, "slave": 2, **fields})


async def test_network_creates_an_entry(hass, kyiv, modbus_clients):
    result = await _network_flow(hass)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "FC660"
    assert result["data"] == {**NETWORK, "slave": 2, "entity_prefix": "fc660"}
    assert result["result"].unique_id == "tcp:127.0.0.1:10502#2"
    await hass.async_block_till_done()
    assert hass.states.get("climate.fc660") is not None


async def test_two_panels_on_one_bus(hass, kyiv, units, modbus_clients):
    units.append(FakeFc660.from_capture(CAPTURE, slave=3))
    await _network_flow(hass)
    result = await _network_flow(hass, name="FC660 Bedroom", slave=3)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["entity_prefix"] == "fc660_bedroom"
    await hass.async_block_till_done()

    entries = hass.config_entries.async_entries(DOMAIN)
    assert [e.state for e in entries] == [ConfigEntryState.LOADED] * 2
    # Both on one bus, through one client.
    assert bus_registry(hass).users(Endpoint.from_config(entries[0].data)) == 2
    assert hass.states.get("climate.fc660") is not None
    assert hass.states.get("climate.fc660_bedroom") is not None
    assert hass.states.get("sensor.fc660_bedroom_humidity").state == "58"

    # A write goes to its own panel only.
    await hass.services.async_call("switch", "turn_on",
                                   {"entity_id": "switch.fc660_bedroom_key_lock"}, blocking=True)
    assert units[0].writes == []
    assert units[1].writes == [(269, 1)]
    registry = er.async_get(hass)
    assert len(er.async_entries_for_config_entry(registry, entries[1].entry_id)) > 30


async def test_a_name_whose_prefix_is_taken(hass, kyiv, units, modbus_clients):
    units.append(FakeFc660.from_capture(CAPTURE, slave=3))
    await _network_flow(hass)
    result = await _network_flow(hass, name="fc660", slave=3)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"name": "name_in_use"}


async def test_a_name_with_no_letters(hass, kyiv, modbus_clients):
    result = await _network_flow(hass, name=" -- ")
    assert result["errors"] == {"name": "invalid_name"}


async def test_the_same_panel_twice(hass, kyiv, modbus_clients):
    await _network_flow(hass)
    result = await _network_flow(hass, name="Again")
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_no_answer(hass, kyiv, fake, modbus_clients):
    fake.offline = True
    result = await _network_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_something_else_at_the_address(hass, kyiv, fake, modbus_clients):
    fake.answer_at = 2
    fake.set_holding(256, 7)
    result = await _network_flow(hass)
    assert result["errors"] == {"base": "not_an_fc660"}
    assert "reports address 7" in result["description_placeholders"]["reason"]


async def test_serial(hass, kyiv, modbus_clients):
    with patch(f"{PACKAGE}.config_flow._list_serial_ports", return_value=["/dev/ttyUSB0"]):
        result = await hass.config_entries.flow.async_init(DOMAIN,
                                                           context={"source": SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(result["flow_id"],
                                                                {"next_step_id": "serial"})
        assert result["type"] is FlowResultType.FORM
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {
            "name": "FC660", "serial_port": "/dev/ttyUSB0", "baudrate": "9600", "slave": 2})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"serial_port": "/dev/ttyUSB0", "baudrate": 9600, "slave": 2,
                              "transport": "serial", "entity_prefix": "fc660"}
    assert modbus_clients[0].kwargs["baudrate"] == 9600


async def test_reconfigure_moves_the_panel_to_a_serial_port(hass, setup_integration):
    entry = setup_integration
    with patch(f"{PACKAGE}.config_flow._list_serial_ports", return_value=["/dev/ttyUSB0"]):
        result = await entry.start_reconfigure_flow(hass)
        assert result["type"] is FlowResultType.MENU
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "reconfigure_serial"})
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {
            "serial_port": "/dev/ttyUSB0", "baudrate": "9600", "slave": 2})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.unique_id == "serial:/dev/ttyUSB0#2"
    assert "host" not in entry.data and entry.data["transport"] == "serial"
    assert entry.data["entity_prefix"] == "fc660"


async def test_options(hass, setup_integration):
    result = await hass.config_entries.options.async_init(setup_integration.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_UNAVAILABLE_AFTER: 300, CONF_SYNC_CLOCK: True})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert setup_integration.options == {CONF_UNAVAILABLE_AFTER: 300, CONF_SYNC_CLOCK: True}
    await hass.async_block_till_done()
    assert setup_integration.runtime_data.coordinator.sync_clock is True
