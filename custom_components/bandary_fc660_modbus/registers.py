"""The FC660 register map: addresses, encodings, ranges and the reads that cover it.

Protocol only, and free of Home Assistant imports: tools/probe_fc660.py uses
it on a host without Home Assistant. What an entity shows -- unit, device
class, name -- lives with the entity descriptions.

Sources: the FC660 manual, "Modbus communication Register" (pages 21-23), for
meanings, ranges and defaults; and the reference unit (slave 2, firmware
0x0101, behind mbusd), read by tools/probe_fc660.py on 2026-10-29
(tests/fixtures/fc660_reference.json). The manual's addresses are already the
wire addresses (0-based), and the unit confirmed every one of them:

* input registers 0-14 read whole in one FC4 request, and holding registers
  256-279 in one FC3 request;
* a read of part of a block answers too: holding 264-268 alone came back in
  40 ms on a quiet bus, and in up to 0.9 s behind the other masters' requests
  in mbusd (2026-10-30);
* one register past either end, or FC3 on the input range and FC4 on the
  holding range, is refused: behind mbusd it comes back as exception 4 after
  the gateway's whole retry budget (1-3 s), so the unit most likely does not
  answer such a read at all;
* writes are FC6 only. FC16 gets no reply at all (measured on the same unit by
  the `modbus:` YAML setup this integration replaces).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

REGISTER_MAP_VERSION = "fc660-r1"


class Table(StrEnum):
    """Which Modbus table a register lives in."""

    #: FC4, read-only: readings and output states.
    INPUT = "input"
    #: FC3 to read, FC6 to write: the settings.
    HOLDING = "holding"


class Kind(StrEnum):
    U16 = "u16"
    I16 = "i16"


class Tier(StrEnum):
    """What a block holds. How often each tier is read is an option of the entry."""

    #: Power, working mode, scene and setpoint: what people change on the panel.
    CONTROL = "control"
    #: Readings and outputs: they change on their own.
    STATE = "state"
    #: Every setting and the clock.
    SETTINGS = "settings"


@dataclass(frozen=True, slots=True)
class Reg:
    """One register in the map."""

    key: str
    address: int
    table: Table
    kind: Kind = Kind.U16
    scale: float = 1.0
    #: Values outside this band are noise, not readings, and decode to None.
    sane: tuple[float, float] | None = None


@dataclass(frozen=True, slots=True)
class Block:
    """One read request: ``count`` registers from ``address`` in ``table``."""

    table: Table
    address: int
    count: int
    tier: Tier

    @property
    def end(self) -> int:
        return self.address + self.count - 1

    @property
    def key(self) -> str:
        return f"{self.table}:{self.address}+{self.count}"

    def covers(self, other: Block) -> bool:
        """True if every register of ``other`` is in this block (itself included)."""
        return (self.table is other.table and self.address <= other.address
                and other.end <= self.end)

    def __str__(self) -> str:
        return f"{self.table} {self.address}..{self.end}"


#: The whole map, two reads. Nothing else answers (see the module docstring).
INPUT_BLOCK = Block(Table.INPUT, 0, 15, Tier.STATE)
HOLDING_BLOCK = Block(Table.HOLDING, 256, 24, Tier.SETTINGS)
BLOCKS: tuple[Block, ...] = (INPUT_BLOCK, HOLDING_BLOCK)
#: Power, working mode, scene and both setpoints (264-268): a slice of the
#: settings block, read on its own between whole reads of it.
CONTROL_BLOCK = Block(Table.HOLDING, 264, 5, Tier.CONTROL)
#: Every read the coordinator polls, in the order it makes them.
POLLED: tuple[Block, ...] = (CONTROL_BLOCK, INPUT_BLOCK, HOLDING_BLOCK)

_IN = {"table": Table.INPUT}
_HOLD = {"table": Table.HOLDING}
_TENTHS = {"kind": Kind.I16, "scale": 0.1}


def _inputs() -> list[Reg]:
    return [
        # "e.g. 0x1A0"; the reference unit reports 0x0101. Shown as hex.
        Reg("firmware", 0, **_IN),
        Reg("temperature", 1, sane=(-40.0, 100.0), **_IN, **_TENTHS),   # 0..500 -> 0..50.0 degC
        Reg("humidity", 2, sane=(0, 100), **_IN),
        Reg("tvoc", 3, sane=(0, 60000), **_IN),                         # ppb
        Reg("co2", 4, sane=(0, 60000), **_IN),                          # ppm, 400..60000
        Reg("equipment_type", 5, **_IN),
        # Output states, 0 off / 1 on. Y = cooling (compressor) stages,
        # W = heating stages, O/B = the heat pump's reversing valve.
        Reg("y1", 6, **_IN),
        Reg("y2", 7, **_IN),
        Reg("w1", 8, **_IN),
        Reg("w2", 9, **_IN),
        Reg("fan_running", 10, **_IN),
        Reg("reversing_valve", 11, **_IN),
        Reg("aux_heater", 12, **_IN),
        Reg("wifi", 13, **_IN),                                         # 0 offline, 1 online
        Reg("fault_code_raw", 14, **_IN),                               # E01 = NTC sensor fault
    ]


def _holding() -> list[Reg]:
    return [
        Reg("modbus_address", 256, **_HOLD),                            # 1..247, default 1
        Reg("display_unit", 257, **_HOLD),                              # 0 degC, 1 degF
        Reg("backlight_brightness", 258, **_HOLD),                      # 0..100 %, default 80
        Reg("backlight_timeout", 259, **_HOLD),                         # 1..255 s, default 30
        Reg("temperature_offset", 260, **_HOLD, **_TENTHS),             # -100..100 -> +/-10.0 degC
        Reg("temperature_offset_f", 261, kind=Kind.I16, **_HOLD),       # -10..10 degF
        Reg("humidity_offset", 262, kind=Kind.I16, **_HOLD),            # -20..20 %
        Reg("password", 263, **_HOLD),                                  # 1..998, 0 = none
        Reg("power", 264, **_HOLD),                                     # stand-by: 0 off, 1 on
        Reg("working_mode", 265, **_HOLD),
        Reg("away_mode", 266, **_HOLD),                                 # scene: 0 comfort, 1 away
        Reg("setpoint", 267, **_HOLD, **_TENTHS),                       # 90..380 -> 9.0..38.0 degC
        Reg("setpoint_f", 268, **_HOLD),                                # 48..99 degF
        Reg("key_lock", 269, **_HOLD),
        Reg("compressor_delay", 270, **_HOLD),                          # 0..15 min, default 3
        Reg("dead_band", 271, **_HOLD, **_TENTHS),                      # 5..50 -> 0.5..5.0 degC
        Reg("dead_band_f", 272, **_HOLD),                               # 1..10 degF
        Reg("stage_hysteresis", 273, **_HOLD, **_TENTHS),               # Y2/W2, 10..50 -> 1..5 degC
        Reg("stage_hysteresis_f", 274, **_HOLD),                        # Y2/W2, 2..10 degF
        Reg("clock_year", 275, **_HOLD),                                # 2023..2099
        Reg("clock_month", 276, **_HOLD),
        Reg("clock_day", 277, **_HOLD),
        Reg("clock_hour", 278, **_HOLD),
        Reg("clock_minute", 279, **_HOLD),
    ]


REGISTERS: tuple[Reg, ...] = (*_inputs(), *_holding())
BY_KEY: dict[str, Reg] = {reg.key: reg for reg in REGISTERS}

assert all(
    any(b.table is r.table and b.address <= r.address <= b.end for b in BLOCKS)
    for r in REGISTERS
), "every register is inside a block"
assert sum(b.count for b in BLOCKS) == len(REGISTERS), "the blocks hold nothing else"
assert all(any(b.covers(p) for b in BLOCKS) for p in POLLED), "a polled read is inside the map"
assert [r.key for r in REGISTERS if r.table is CONTROL_BLOCK.table
        and CONTROL_BLOCK.address <= r.address <= CONTROL_BLOCK.end] == [
    "power", "working_mode", "away_mode", "setpoint", "setpoint_f"], "what the control read holds"


def decode(reg: Reg, raw: int) -> float | int | None:
    """One raw word -> the register's value, or None if insane."""
    value: float | int = raw - 0x10000 if reg.kind is Kind.I16 and raw & 0x8000 else raw
    if reg.scale != 1.0:
        value = round(value * reg.scale, 3)
    if reg.sane and not reg.sane[0] <= value <= reg.sane[1]:
        return None
    return value


def encode(reg: Reg, value: float) -> int:
    """A value in the register's units -> the raw word FC6 sends."""
    raw = round(value / reg.scale)
    return raw & 0xFFFF if reg.kind is Kind.I16 else raw


# -- enumerations -------------------------------------------------------------

#: Register value -> state key.
ENUMS: dict[str, dict[int, str]] = {
    "equipment_type": {0: "single_stage_heat_pump", 1: "multi_stage_heat_pump",
                       2: "cooling_only", 3: "heating_only"},
    "display_unit": {0: "celsius", 1: "fahrenheit"},
    "working_mode": {0: "cooling", 1: "heating", 2: "ventilation"},
}

#: Register 14. The manual lists one code; the rest are shown as E<nn>.
FAULT_DESCRIPTIONS: dict[str, str] = {"E01": "NTC sensor fault"}


def fault_code(raw: int | None) -> str | None:
    if raw is None:
        return None
    return "none" if raw == 0 else f"E{raw:02d}"


def firmware_text(raw: int | None) -> str | None:
    return None if raw is None else f"0x{raw:04X}"


# -- writes ----------------------------------------------------------------------

#: Never written, whatever a later WriteSpec says. 256 is the address this entry
#: talks to: writing it cuts the entry off. 263 is the panel's settings password:
#: changing it from here could lock a person out of their own panel.
FORBIDDEN_WRITES: frozenset[int] = frozenset({256, 263})


@dataclass(frozen=True, slots=True)
class WriteSpec:
    """A writable register and the values it may take, in its own units.

    The ranges are the manual's. They are checked before anything is sent:
    what the unit does with a value outside them is not documented.
    """

    key: str
    minimum: float
    maximum: float
    step: float = 1.0


WRITE_SPECS: dict[str, WriteSpec] = {spec.key: spec for spec in (
    WriteSpec("display_unit", 0, 1),
    WriteSpec("backlight_brightness", 0, 100),
    WriteSpec("backlight_timeout", 1, 255),
    WriteSpec("temperature_offset", -10.0, 10.0, 0.1),
    WriteSpec("temperature_offset_f", -10, 10),
    WriteSpec("humidity_offset", -20, 20),
    WriteSpec("power", 0, 1),
    WriteSpec("working_mode", 0, 2),
    WriteSpec("away_mode", 0, 1),
    WriteSpec("setpoint", 9.0, 38.0, 0.1),
    WriteSpec("setpoint_f", 48, 99),
    WriteSpec("key_lock", 0, 1),
    WriteSpec("compressor_delay", 0, 15),
    WriteSpec("dead_band", 0.5, 5.0, 0.1),
    WriteSpec("dead_band_f", 1, 10),
    WriteSpec("stage_hysteresis", 1.0, 5.0, 0.1),
    WriteSpec("stage_hysteresis_f", 2, 10),
    # The clock: written only together, by the clock sync.
    WriteSpec("clock_year", 2023, 2099),
    WriteSpec("clock_month", 1, 12),
    WriteSpec("clock_day", 1, 31),
    WriteSpec("clock_hour", 0, 23),
    WriteSpec("clock_minute", 0, 59),
)}
CLOCK_KEYS: tuple[str, ...] = ("clock_year", "clock_month", "clock_day", "clock_hour",
                               "clock_minute")

# A forbidden register can never acquire a write spec, whatever is edited above.
assert not {BY_KEY[key].address for key in WRITE_SPECS} & FORBIDDEN_WRITES
assert all(BY_KEY[key].table is Table.HOLDING for key in WRITE_SPECS)


def on_step(spec: WriteSpec, value: float) -> bool:
    steps = (value - spec.minimum) / spec.step
    return spec.minimum <= value <= spec.maximum and abs(steps - round(steps)) < 1e-6
