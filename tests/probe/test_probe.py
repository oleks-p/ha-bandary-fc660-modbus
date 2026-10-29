"""The probe and the register map without Home Assistant: Python 3.11, pymodbus only.

The probe runs on the Home Assistant host, outside Home Assistant, and loads
registers.py on its own; these tests hold both to the reference capture.
"""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

import pytest

import probe_fc660
from sim_fc660 import FakeFc660, Gateway

CAPTURE = Path(__file__).parents[1] / "fixtures" / "fc660_reference.json"
REG = probe_fc660.load_registers()


def test_the_map_is_two_blocks_and_nothing_else():
    assert [(b.table, b.address, b.count) for b in REG.BLOCKS] == [
        ("input", 0, 15), ("holding", 256, 24)]
    assert len(REG.REGISTERS) == 39


@pytest.mark.parametrize(("key", "raw", "value"), [
    ("temperature", 176, 17.6),
    ("setpoint", 240, 24.0),
    ("temperature_offset", 0x10000 - 15, -1.5),
    ("humidity_offset", 0x10000 - 20, -20),
    ("dead_band", 5, 0.5),
    ("stage_hysteresis", 10, 1.0),
    ("co2", 407, 407),
])
def test_decode_and_encode_round_trip(key, raw, value):
    reg = REG.BY_KEY[key]
    assert REG.decode(reg, raw) == value
    assert REG.encode(reg, value) == raw


def test_an_insane_reading_is_none():
    assert REG.decode(REG.BY_KEY["humidity"], 655) is None


def test_the_capture_decodes():
    blocks = json.loads(CAPTURE.read_text())["blocks"]
    holding = blocks["holding:256+24"]
    assert holding[0] == json.loads(CAPTURE.read_text())["slave"]
    assert REG.ENUMS["working_mode"][holding[265 - 256]] == "heating"
    assert REG.fault_code(blocks["input:0+15"][14]) == "none"
    assert REG.firmware_text(blocks["input:0+15"][0]) == "0x0101"


def test_every_writable_register_has_a_range_inside_16_bits():
    for key, spec in REG.WRITE_SPECS.items():
        reg = REG.BY_KEY[key]
        for value in (spec.minimum, spec.maximum):
            assert 0 <= REG.encode(reg, value) <= 0xFFFF, key
    assert not {REG.BY_KEY[k].address for k in REG.WRITE_SPECS} & REG.FORBIDDEN_WRITES


def test_the_fake_keeps_the_units_rules():
    fake = FakeFc660.from_capture(CAPTURE)
    assert fake.read(2, 4, 0, 15) == fake.inputs
    assert fake.read(2, 4, 0, 16) is None           # past the end: no answer
    assert fake.read(2, 3, 0, 1) is None            # FC3 on the input range
    assert fake.read(3, 3, 256, 1) is None          # not its address
    assert fake.write(2, 267, 215) is True
    assert fake.get_holding(267) == 215


@pytest.fixture
def gateway_port():
    """The simulated gateway on its own loop and thread: the probe runs asyncio.run()."""
    loop = asyncio.new_event_loop()
    gateway = Gateway([FakeFc660.from_capture(CAPTURE)])
    server = loop.run_until_complete(gateway.serve("127.0.0.1", 0))
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    yield server.sockets[0].getsockname()[1], gateway
    loop.call_soon_threadsafe(loop.stop)
    thread.join(5)
    server.close()
    loop.run_until_complete(server.wait_closed())
    loop.close()


def test_the_probe_captures_what_the_unit_holds(gateway_port, tmp_path, capsys):
    port, gateway = gateway_port
    out = tmp_path / "capture.json"
    assert probe_fc660.main(["--host", "127.0.0.1", "--port", str(port), "--slave", "2",
                             "--edges", "--timeout", "2", "--out", str(out)]) == 0
    capture = json.loads(out.read_text())
    reference = json.loads(CAPTURE.read_text())
    assert capture["blocks"] == reference["blocks"]
    assert {key: edge.get("exception") for key, edge in capture["edges"].items()} == {
        "input:15+1": 4, "input:0+16": 4, "holding:280+1": 4, "holding:256+25": 4}
    # Read-only: nothing written, whatever it read.
    assert gateway.fakes[0].writes == []
    assert "setpoint" in capsys.readouterr().out
