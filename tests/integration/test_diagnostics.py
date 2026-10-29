"""Diagnostics: raw words and decoded values, with the link and the password redacted."""

from __future__ import annotations

from custom_components.bandary_fc660_modbus.diagnostics import (
    async_get_config_entry_diagnostics,
)


async def test_diagnostics(hass, setup_integration):
    diag = await async_get_config_entry_diagnostics(hass, setup_integration)
    assert diag["entry"]["data"]["host"] == "**REDACTED**"
    assert diag["values"]["password"] == "**REDACTED**"
    assert diag["raw_registers"]["holding:256+24"][7] == "**REDACTED**"
    assert diag["raw_registers"]["input:0+15"][1] == 176
    assert diag["values"]["setpoint"] == 24.0
    assert diag["values"]["clock"] == "2026-10-29T21:46:00+02:00"
    assert diag["model"] == {"firmware": "0x0101", "equipment_type": "multi_stage_heat_pump",
                             "register_map": "fc660-r1"}
