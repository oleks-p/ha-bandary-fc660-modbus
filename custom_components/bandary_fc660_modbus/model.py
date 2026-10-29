"""Whether the unit at an address is an FC660, and what it reports about itself.

The FC660 has no identify code. What it does have is a map that answers whole
-- input registers 0-14 and holding registers 256-279, and nothing else -- and
holding register 256, which holds the unit's own Modbus address. A unit that
answers both blocks and reports the address it was asked at is an FC660 at
that address; a heat pump or a fancoil on the same bus is refused, as is a
gateway that forwards to some other address than the one configured.
"""

from __future__ import annotations

from dataclasses import dataclass

from .registers import BY_KEY, ENUMS, HOLDING_BLOCK, INPUT_BLOCK, firmware_text
from .transport import Fc660Bus, Fc660IllegalError


class NotAnFc660(Exception):
    """The address answered, but not like an FC660."""

    def __init__(self, reason: str, reported: int | None = None) -> None:
        super().__init__(reason)
        self.reported = reported


@dataclass(frozen=True, slots=True)
class ModelInfo:
    firmware_raw: int
    equipment_type: int

    @property
    def firmware(self) -> str:
        return firmware_text(self.firmware_raw) or ""

    @property
    def equipment(self) -> str:
        return ENUMS["equipment_type"].get(self.equipment_type, str(self.equipment_type))


async def async_identify(bus: Fc660Bus, slave: int) -> ModelInfo:
    """Read both blocks and check the address register. Raises NotAnFc660.

    Link failures propagate as Fc660TransientError: the caller decides between
    "try again later" (setup) and "cannot connect" (config flow).
    """
    try:
        inputs = await bus.read(slave, INPUT_BLOCK.address, INPUT_BLOCK.count, INPUT_BLOCK.table)
        holding = await bus.read(slave, HOLDING_BLOCK.address, HOLDING_BLOCK.count,
                                 HOLDING_BLOCK.table)
    except Fc660IllegalError as err:
        raise NotAnFc660(str(err)) from err
    reported = holding[BY_KEY["modbus_address"].address - HOLDING_BLOCK.address]
    if reported != slave:
        raise NotAnFc660(f"register 256 reports address {reported}", reported)
    equipment = inputs[BY_KEY["equipment_type"].address]
    if equipment not in ENUMS["equipment_type"]:
        raise NotAnFc660(f"equipment type {equipment} is not one the FC660 has")
    return ModelInfo(firmware_raw=inputs[BY_KEY["firmware"].address], equipment_type=equipment)
