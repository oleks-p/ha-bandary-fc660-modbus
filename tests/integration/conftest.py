"""Home Assistant fixtures: the integration against fake reference units.

The fake is built from the probe's capture of the real panel -- the same two
blocks, the same silence outside them -- so decoding and the entity set are
exercised against what the hardware answers, not against what the code assumes.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.util import dt as dt_util
from pymodbus.exceptions import ConnectionException, ModbusIOException
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.bandary_fc660_modbus.const import (
    CONF_ENTITY_PREFIX,
    CONF_SLAVE,
    CONF_TRANSPORT,
    DOMAIN,
    TRANSPORT_TCP,
)
from custom_components.bandary_fc660_modbus.registers import FORBIDDEN_WRITES
from tests.sim import FakeFc660

CAPTURE = Path(__file__).parents[1] / "fixtures" / "fc660_reference.json"
PACKAGE = "custom_components.bandary_fc660_modbus"
#: The capture's panel clock reads 21:46 on 29 October 2026, in Kyiv (UTC+2).
TIME_ZONE = "Europe/Kyiv"
CAPTURED_AT = datetime(2026, 10, 29, 19, 46, 20, tzinfo=dt_util.UTC)

NETWORK_DATA = {
    CONF_TRANSPORT: TRANSPORT_TCP,
    CONF_HOST: "127.0.0.1",
    CONF_PORT: 10502,
    CONF_SLAVE: 2,
    CONF_ENTITY_PREFIX: "fc660",
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


class FakeResponse:
    def __init__(self, registers: list[int] | None = None, code: int | None = None) -> None:
        self.registers = registers or []
        self.exception_code = code

    def isError(self) -> bool:  # noqa: N802 - pymodbus spelling
        return self.exception_code is not None


class FakeModbusClient:
    """The slice of pymodbus the transport uses, answering from the fakes on the wire."""

    def __init__(self, units: list[FakeFc660], *args, **kwargs) -> None:
        self.units = units
        self.args, self.kwargs = args, kwargs
        self.connected = False
        self.closes = 0

    def _unit(self, slave: int) -> FakeFc660 | None:
        return next((u for u in self.units if u.slave == slave), None)

    async def connect(self) -> bool:
        if all(u.offline for u in self.units):
            return False
        self.connected = True
        return True

    def close(self) -> None:
        self.connected = False
        self.closes += 1

    async def _read(self, function: int, address: int, count: int, device_id: int):
        if not self.connected:
            raise ConnectionException("not connected")
        unit = self._unit(device_id)
        result = None if unit is None else unit.read(device_id, function, address, count)
        if result is None:
            raise ModbusIOException("no response")
        if isinstance(result, int):
            return FakeResponse(code=result)
        return FakeResponse(registers=result)

    async def read_holding_registers(self, address, *, count=1, device_id=1,
                                     no_response_expected=False):
        return await self._read(3, address, count, device_id)

    async def read_input_registers(self, address, *, count=1, device_id=1,
                                   no_response_expected=False):
        return await self._read(4, address, count, device_id)

    async def write_register(self, address, value, *, device_id=1, no_response_expected=False):
        if not self.connected:
            raise ConnectionException("not connected")
        unit = self._unit(device_id)
        outcome = None if unit is None else unit.write(device_id, address, value)
        if outcome is None:
            raise ModbusIOException("no response")
        if outcome is True:
            return FakeResponse(registers=[value])
        return FakeResponse(code=outcome)


@pytest.fixture
def fake() -> FakeFc660:
    fake = FakeFc660.from_capture(CAPTURE)
    yield fake
    # No test may ever make the integration write the address or the password.
    assert not {a for a, _ in fake.writes} & FORBIDDEN_WRITES, fake.writes


@pytest.fixture
def units(fake) -> list[FakeFc660]:
    """Every panel on the fake bus; a test appends more to add panels."""
    return [fake]


@pytest.fixture
def modbus_clients(units):
    """Every pymodbus client the integration creates, in order."""
    clients: list[FakeModbusClient] = []

    def factory(*args, **kwargs):
        client = FakeModbusClient(units, *args, **kwargs)
        clients.append(client)
        return client

    with (
        patch(f"{PACKAGE}.transport.AsyncModbusSerialClient", side_effect=factory),
        patch(f"{PACKAGE}.transport.AsyncModbusTcpClient", side_effect=factory),
        patch(f"{PACKAGE}.transport.FRAME_GAP", 0),
        patch(f"{PACKAGE}.transport.RESYNC_DELAY", 0),
    ):
        yield clients


@pytest.fixture
async def kyiv(hass, freezer):
    """Home Assistant in the panel's time zone, at the moment of the capture."""
    await hass.config.async_set_time_zone(TIME_ZONE)
    freezer.move_to(CAPTURED_AT)


@pytest.fixture
def config_entry(hass) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="FC660",
        unique_id="tcp:127.0.0.1:10502#2",
        data=dict(NETWORK_DATA),
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
async def setup_integration(hass, kyiv, config_entry, modbus_clients):
    # The clock is frozen before the first poll, so the coordinator's tier and
    # outage timing (time.monotonic) and the tests' time travel share one clock.
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry


@pytest.fixture
def advance(hass, freezer):
    """Move time forward in ``step`` s steps, letting each poll complete."""

    async def run(seconds: float, step: float = 5) -> None:
        remaining = seconds
        while remaining > 0:
            tick = min(step, remaining)
            freezer.tick(timedelta(seconds=tick))
            async_fire_time_changed(hass, dt_util.utcnow())
            await hass.async_block_till_done()
            remaining -= tick

    return run
