#!/usr/bin/env python3
"""A simulated FC660, built from a probe capture, served as a Modbus TCP gateway.

The fake keeps the rules the reference unit showed: the input block (FC4, 0-14)
and the holding block (FC3, 256-279) answer, and anything else gets no answer;
writes are FC6 to the holding block, and FC16 gets no answer either. It answers
only at its own address, as register 256 says. The gateway in front reports
"no answer" as exception 4, as mbusd does.

    python3 tools/sim_fc660.py --capture tests/fixtures/fc660_reference.json \
        --listen 0.0.0.0:5020 --slaves 2,3

serves the captured unit at address 2 and a copy of it at 3: two panels on one
"bus", for trying several entries against one gateway.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import struct
from dataclasses import dataclass, field

INPUT_FIRST, INPUT_COUNT = 0, 15
HOLDING_FIRST, HOLDING_COUNT = 256, 24
#: What mbusd sends back when the unit does not answer.
GATEWAY_NO_ANSWER = 4
ADDRESS_REGISTER = 256


@dataclass
class FakeFc660:
    """One panel's registers and the unit's rules. Tests drive it directly."""

    inputs: list[int]
    holding: list[int]
    #: Every (address, value) written, in order.
    writes: list[tuple[int, int]] = field(default_factory=list)
    #: Every (function, address, count) read, in order.
    reads: list[tuple[int, int, int]] = field(default_factory=list)
    #: True: nothing answers, as with a cut cable.
    offline: bool = False
    #: address -> raw: the unit acknowledges a write but holds this instead.
    keeps: dict[int, int] = field(default_factory=dict)
    #: address -> exception code a write to it gets.
    refuses: dict[int, int] = field(default_factory=dict)
    #: Answer at this address whatever register 256 says (a gateway that remaps).
    answer_at: int | None = None

    @property
    def slave(self) -> int:
        if self.answer_at is not None:
            return self.answer_at
        return self.holding[ADDRESS_REGISTER - HOLDING_FIRST]

    @classmethod
    def from_capture(cls, path: pathlib.Path | str, slave: int | None = None) -> FakeFc660:
        blocks = json.loads(pathlib.Path(path).read_text())["blocks"]
        fake = cls(list(blocks[f"input:{INPUT_FIRST}+{INPUT_COUNT}"]),
                   list(blocks[f"holding:{HOLDING_FIRST}+{HOLDING_COUNT}"]))
        if slave is not None:
            fake.holding[ADDRESS_REGISTER - HOLDING_FIRST] = slave
        return fake

    def set_input(self, address: int, value: int) -> None:
        self.inputs[address - INPUT_FIRST] = value

    def set_holding(self, address: int, value: int) -> None:
        self.holding[address - HOLDING_FIRST] = value

    def get_holding(self, address: int) -> int:
        return self.holding[address - HOLDING_FIRST]

    def read(self, slave: int, function: int, address: int, count: int) -> list[int] | int | None:
        """Words, an exception code, or None for no reply."""
        if self.offline or slave != self.slave:
            return None
        self.reads.append((function, address, count))
        if function == 4:
            bank, first = self.inputs, INPUT_FIRST
        elif function == 3:
            bank, first = self.holding, HOLDING_FIRST
        else:
            return 1
        start = address - first
        if start < 0 or count < 1 or start + count > len(bank):
            return None
        return list(bank[start:start + count])

    def write(self, slave: int, address: int, value: int) -> bool | int | None:
        """FC6: True, an exception code, or None for no reply."""
        if self.offline or slave != self.slave:
            return None
        if not HOLDING_FIRST <= address < HOLDING_FIRST + HOLDING_COUNT:
            return None
        if address in self.refuses:
            return self.refuses[address]
        self.writes.append((address, value))
        self.set_holding(address, self.keeps.get(address, value))
        return True


class Gateway:
    """Several fakes behind one Modbus TCP endpoint, as behind mbusd."""

    def __init__(self, fakes: list[FakeFc660]) -> None:
        self.fakes = fakes

    def _unit(self, slave: int) -> FakeFc660 | None:
        return next((f for f in self.fakes if f.slave == slave and not f.offline), None)

    def respond(self, unit: int, pdu: bytes) -> bytes:
        function = pdu[0] if pdu else 0
        fake = self._unit(unit)
        result: list[int] | bool | int | None = None
        if fake is not None and len(pdu) >= 5:
            address, operand = struct.unpack(">HH", pdu[1:5])
            if function in (3, 4):
                result = fake.read(unit, function, address, operand)
            elif function == 6:
                result = fake.write(unit, address, operand)
            # FC16 and the rest: the reference unit does not reply at all.
        if isinstance(result, list):
            return bytes([function, 2 * len(result)]) + struct.pack(f">{len(result)}H", *result)
        if result is True:
            return pdu[:5]
        code = GATEWAY_NO_ANSWER if result is None else result
        return bytes([function | 0x80, code])

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                header = await reader.readexactly(7)
                tid, pid, length, unit = struct.unpack(">HHHB", header)
                pdu = await reader.readexactly(length - 1)
                reply = self.respond(unit, pdu)
                writer.write(struct.pack(">HHHB", tid, pid, len(reply) + 1, unit) + reply)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()

    async def serve(self, host: str, port: int) -> asyncio.Server:
        return await asyncio.start_server(self.handle, host, port)


async def _main(args: argparse.Namespace) -> None:
    slaves = [int(s) for s in args.slaves.split(",")] if args.slaves else [None]
    gateway = Gateway([FakeFc660.from_capture(args.capture, slave) for slave in slaves])
    host, _, port = args.listen.rpartition(":")
    server = await gateway.serve(host or "0.0.0.0", int(port))
    print(f"FC660 at {', '.join(str(f.slave) for f in gateway.fakes)} on {args.listen}",
          flush=True)
    async with server:
        await server.serve_forever()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--capture", required=True, help="a tools/probe_fc660.py capture")
    ap.add_argument("--listen", default="127.0.0.1:5020", help="host:port")
    ap.add_argument("--slaves", help="comma-separated addresses (default: the capture's)")
    asyncio.run(_main(ap.parse_args(argv)))


if __name__ == "__main__":
    main()
