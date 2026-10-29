"""The entity set: ids, values decoded right, and every register covered."""

from __future__ import annotations

import pytest
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.bandary_fc660_modbus.binary_sensor import BINARY_SENSORS
from custom_components.bandary_fc660_modbus.const import DOMAIN
from custom_components.bandary_fc660_modbus.number import NUMBERS
from custom_components.bandary_fc660_modbus.registers import REGISTERS
from custom_components.bandary_fc660_modbus.select import SELECTS
from custom_components.bandary_fc660_modbus.sensor import SENSORS
from custom_components.bandary_fc660_modbus.switch import SWITCHES

#: Registers shown through an entity of another key.
SHOWN_AS = {
    "fault_code_raw": "fault_code",
    **{f"clock_{part}": "clock" for part in ("year", "month", "day", "hour", "minute")},
}
#: The YAML `modbus:` setup's entity ids: taken over exactly, with the default prefix.
LEGACY_IDS = [
    "climate.fc660",
    "sensor.fc660_humidity",
    "sensor.fc660_tvoc",
    "sensor.fc660_co2",
    "binary_sensor.fc660_fan_running",
    "binary_sensor.fc660_reversing_valve",
    "binary_sensor.fc660_aux_heater",
    "switch.fc660_key_lock",
    "switch.fc660_away_mode",
]


def test_every_register_has_an_entity():
    keys = {d.key for group in (SENSORS, BINARY_SENSORS, NUMBERS, SELECTS, SWITCHES)
            for d in group}
    # The climate covers power, mode, scene and setpoint too; each also has its own.
    missing = [r.key for r in REGISTERS if SHOWN_AS.get(r.key, r.key) not in keys]
    assert missing == []


async def test_entity_ids_are_prefix_and_key(hass, setup_integration):
    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, setup_integration.entry_id)
    assert entries
    prefix = f"{setup_integration.entry_id}_"
    for entry in entries:
        key = entry.unique_id.removeprefix(prefix)
        expected = "climate.fc660" if key == "thermostat" else f"{entry.domain}.fc660_{key}"
        assert entry.entity_id == expected


async def test_the_yaml_setups_ids_are_taken_over(hass, setup_integration):
    registry = er.async_get(hass)
    for entity_id in LEGACY_IDS:
        assert registry.async_get(entity_id) is not None, entity_id


@pytest.mark.parametrize(
    ("entity_id", "expected"),
    [
        ("sensor.fc660_temperature", "17.6"),
        ("sensor.fc660_humidity", "58"),
        ("sensor.fc660_tvoc", "51"),
        ("sensor.fc660_co2", "407"),
        ("sensor.fc660_fault_code", "none"),
        ("sensor.fc660_equipment_type", "multi_stage_heat_pump"),
        ("sensor.fc660_firmware", "0x0101"),
        ("sensor.fc660_modbus_address", "2"),
        # 21:46 in Kyiv, UTC+2 since the end of summer time on 25 October
        ("sensor.fc660_clock", "2026-10-29T19:46:00+00:00"),
        ("sensor.fc660_read_failures", "0"),
        ("binary_sensor.fc660_y1", "off"),
        ("binary_sensor.fc660_y2", "off"),
        ("binary_sensor.fc660_w1", "on"),
        ("binary_sensor.fc660_w2", "on"),
        ("binary_sensor.fc660_fan_running", "on"),
        ("binary_sensor.fc660_reversing_valve", "off"),
        ("binary_sensor.fc660_aux_heater", "off"),
        ("binary_sensor.fc660_wifi", "off"),
        ("binary_sensor.fc660_fault", "off"),
        ("number.fc660_setpoint", "24.0"),
        ("number.fc660_backlight_brightness", "100"),
        ("number.fc660_backlight_timeout", "30"),
        ("number.fc660_temperature_offset", "0.0"),
        ("number.fc660_humidity_offset", "0"),
        ("number.fc660_compressor_delay", "3"),
        ("number.fc660_dead_band", "0.5"),
        ("number.fc660_stage_hysteresis", "1.0"),
        ("select.fc660_working_mode", "heating"),
        ("select.fc660_display_unit", "celsius"),
        ("switch.fc660_power", "on"),
        ("switch.fc660_away_mode", "off"),
        ("switch.fc660_key_lock", "off"),
        ("button.fc660_sync_clock", "unknown"),
    ],
)
async def test_values_decode_from_the_capture(hass, setup_integration, entity_id, expected):
    state = hass.states.get(entity_id)
    assert state is not None, entity_id
    assert state.state == expected


@pytest.mark.parametrize("entity_id", [
    "sensor.fc660_password",
    "number.fc660_setpoint_f",
    "number.fc660_temperature_offset_f",
    "number.fc660_dead_band_f",
    "number.fc660_stage_hysteresis_f",
])
async def test_rarely_needed_registers_are_disabled_by_default(hass, setup_integration,
                                                                entity_id):
    entry = er.async_get(hass).async_get(entity_id)
    assert entry is not None
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert hass.states.get(entity_id) is None


async def test_fault_code_shows_the_code_and_its_description(hass, fake, setup_integration,
                                                             advance):
    fake.set_input(14, 1)
    await advance(15)
    state = hass.states.get("sensor.fc660_fault_code")
    assert state.state == "E01"
    assert state.attributes["description"] == "NTC sensor fault"
    assert hass.states.get("binary_sensor.fc660_fault").state == "on"


async def test_one_device_per_panel(hass, setup_integration):
    device = dr.async_get(hass).async_get_device({(DOMAIN, setup_integration.entry_id)})
    assert device is not None
    assert (device.manufacturer, device.model, device.name, device.sw_version) == (
        "Bandary", "FC660", "FC660", "0x0101")
