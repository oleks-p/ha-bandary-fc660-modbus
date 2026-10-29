#!/usr/bin/env python3
"""Read an FC660's whole register map, show it decoded, and save a capture.

Read-only: it sends FC3 and FC4 and nothing else. It needs only Python 3.11+
and pymodbus, so it runs on the Home Assistant host or inside the Home
Assistant container (which has pymodbus) without Home Assistant itself:

    # behind mbusd or another Modbus TCP gateway
    python3 tools/probe_fc660.py --host 127.0.0.1 --port 10502 --slave 2 --out capture.json
    # on a serial adapter nothing else has open
    python3 tools/probe_fc660.py --serial /dev/ttyUSB0 --slave 1

--edges also reads one register past each end of the map, to confirm the unit
refuses them (the integration relies on the map being exactly what it is).
RS-485 has one master: on a bare serial port, stop whatever else polls the bus
first. Behind a gateway that is not needed; the gateway queues the requests.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import inspect
import json
import pathlib
import sys
import time
from datetime import UTC, datetime
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parent.parent
REGISTERS = ROOT / "custom_components" / "bandary_fc660_modbus" / "registers.py"


def load_registers() -> Any:
    """registers.py on its own: importing the package would import Home Assistant."""
    spec = importlib.util.spec_from_file_location("fc660_registers", REGISTERS)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module      # dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


def make_client(args: argparse.Namespace) -> Any:
    from pymodbus import FramerType
    from pymodbus.client import AsyncModbusSerialClient, AsyncModbusTcpClient

    if args.serial:
        return AsyncModbusSerialClient(args.serial, framer=FramerType.RTU, baudrate=args.baudrate,
                                       bytesize=8, parity="N", stopbits=1, timeout=args.timeout,
                                       retries=0)
    framer = FramerType.RTU if args.rtu_over_tcp else FramerType.SOCKET
    return AsyncModbusTcpClient(args.host, port=args.port, framer=framer, timeout=args.timeout,
                                retries=0)


async def read(client: Any, table: str, address: int, count: int, slave: int) -> dict[str, Any]:
    method = client.read_input_registers if table == "input" else client.read_holding_registers
    unit = "device_id" if "device_id" in inspect.signature(method).parameters else "slave"
    started = time.monotonic()
    try:
        result = await method(address, count=count, **{unit: slave})
    except Exception as err:  # noqa: BLE001 - a probe reports, it does not stop
        return {"error": f"{type(err).__name__}: {err}"}
    ms = round((time.monotonic() - started) * 1000)
    if result.isError():
        return {"exception": getattr(result, "exception_code", None), "ms": ms}
    return {"words": list(result.registers), "ms": ms}


def show(registers: Any, blocks: dict[str, list[int]]) -> None:
    for block in registers.BLOCKS:
        words = blocks.get(block.key)
        if words is None:
            print(f"{block}: not read")
            continue
        print(f"-- {block}")
        for reg in registers.REGISTERS:
            if reg.table is not block.table:
                continue
            raw = words[reg.address - block.address]
            decoded = registers.decode(reg, raw)
            enum = registers.ENUMS.get(reg.key, {}).get(raw)
            extra = f"  ({enum})" if enum else ""
            print(f"  {reg.address:>3}  {reg.key:<22} raw {raw:>5}  -> {decoded}{extra}")


async def probe(args: argparse.Namespace) -> int:
    registers = load_registers()
    client = make_client(args)
    if not await client.connect():
        print("cannot connect", file=sys.stderr)
        return 2
    capture: dict[str, Any] = {
        "tool": "probe_fc660",
        "register_map": registers.REGISTER_MAP_VERSION,
        "captured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "slave": args.slave,
        "blocks": {},
        "timings_ms": {},
    }
    try:
        for block in registers.BLOCKS:
            result = await read(client, block.table, block.address, block.count, args.slave)
            if "words" not in result:
                print(f"{block}: {result}", file=sys.stderr)
                return 1
            capture["blocks"][block.key] = result["words"]
            capture["timings_ms"][block.key] = result["ms"]
        if args.edges:
            edges = {}
            for block in registers.BLOCKS:
                edges[f"{block.table}:{block.end + 1}+1"] = await read(
                    client, block.table, block.end + 1, 1, args.slave)
                edges[f"{block.table}:{block.address}+{block.count + 1}"] = await read(
                    client, block.table, block.address, block.count + 1, args.slave)
            capture["edges"] = edges
    finally:
        client.close()

    show(registers, capture["blocks"])
    if args.edges:
        print("-- edges (expected: refused)")
        for key, result in capture["edges"].items():
            print(f"  {key}: {result}")
    if args.out:
        pathlib.Path(args.out).write_text(json.dumps(capture, indent=1) + "\n")
        print(f"wrote {args.out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    link = ap.add_mutually_exclusive_group(required=True)
    link.add_argument("--host", help="Modbus TCP gateway (or serial server) host")
    link.add_argument("--serial", help="serial port, e.g. /dev/ttyUSB0")
    ap.add_argument("--port", type=int, default=502)
    ap.add_argument("--rtu-over-tcp", action="store_true",
                    help="raw RTU frames over TCP (a transparent serial server)")
    ap.add_argument("--baudrate", type=int, default=9600)
    ap.add_argument("--slave", type=int, required=True)
    ap.add_argument("--timeout", type=float, default=5.0)
    ap.add_argument("--edges", action="store_true", help="also read past the ends of the map")
    ap.add_argument("--out", help="write the capture to this JSON file")
    return asyncio.run(probe(ap.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
