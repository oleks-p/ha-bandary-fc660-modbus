"""The transport against a real socket: pymodbus, MBAP framing, the simulator's gateway.

The other tests swap pymodbus out; these keep it, so the function codes, the
unit argument and the exception handling are checked against the real client.
"""

from __future__ import annotations

import pytest

from custom_components.bandary_fc660_modbus.registers import Table
from custom_components.bandary_fc660_modbus.transport import (
    Endpoint,
    Fc660Bus,
    Fc660TransientError,
)
from tests.sim import FakeFc660, Gateway

from .conftest import CAPTURE


@pytest.fixture
async def gateway(socket_enabled):
    units = [FakeFc660.from_capture(CAPTURE), FakeFc660.from_capture(CAPTURE, slave=3)]
    gw = Gateway(units)
    server = await gw.serve("127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    yield gw, port
    server.close()
    await server.wait_closed()


@pytest.fixture
async def bus(gateway):
    _, port = gateway
    bus = Fc660Bus(Endpoint("tcp", host="127.0.0.1", port=port), timeout=2, gap=0, resync=0)
    yield bus
    await bus.close()


async def test_reads_both_tables(gateway, bus):
    gw, _ = gateway
    inputs = await bus.read(2, 0, 15, Table.INPUT)
    holding = await bus.read(2, 256, 24, Table.HOLDING)
    assert inputs == gw.fakes[0].inputs
    assert holding == gw.fakes[0].holding
    assert gw.fakes[0].reads == [(4, 0, 15), (3, 256, 24)]


async def test_two_units_behind_one_gateway(gateway, bus):
    assert (await bus.read(3, 256, 1))[0] == 3
    assert (await bus.read(2, 256, 1))[0] == 2


async def test_writes_with_fc6(gateway, bus):
    gw, _ = gateway
    await bus.write(2, 267, 215)
    assert gw.fakes[0].writes == [(267, 215)]
    assert await bus.read(2, 267, 1) == [215]


async def test_outside_the_map_is_the_gateways_no_answer(gateway, bus):
    # mbusd reports the unit's silence as exception 4: transient, and the bus recovers.
    with pytest.raises(Fc660TransientError, match="exception 4"):
        await bus.read(2, 0, 16, Table.INPUT)
    assert bus.failures == 1
    assert len(await bus.read(2, 0, 15, Table.INPUT)) == 15


async def test_an_absent_unit(gateway, bus):
    with pytest.raises(Fc660TransientError):
        await bus.read(9, 256, 1)
