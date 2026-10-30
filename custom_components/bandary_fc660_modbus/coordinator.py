"""Polling coordinator: makes each read on its own interval, decodes, writes.

Three reads, each on an interval from the entry's options: power, mode and
setpoint (holding 264-268, every 5 s by default), the readings and outputs
(input 0-14, 15 s) and every setting with the clock (holding 256-279, 30 s).
The first is a slice of the last, so it is skipped when both are due.

Writes are FC6, one register at a time (the unit answers nothing else), and
every write is followed by one read of the settings block: the value shown is
the one the unit holds, not the one that was asked for.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CLOCK_MAX_DRIFT,
    CLOCK_SYNC_INTERVAL,
    CONF_CONTROL_INTERVAL,
    CONF_SETTINGS_INTERVAL,
    CONF_STATE_INTERVAL,
    CONF_SYNC_CLOCK,
    CONF_UNAVAILABLE_AFTER,
    DEFAULT_UNAVAILABLE_AFTER,
    DOMAIN,
    POLL_INTERVALS,
)
from .model import ModelInfo
from .registers import (
    BLOCKS,
    BY_KEY,
    CLOCK_KEYS,
    HOLDING_BLOCK,
    POLLED,
    REGISTERS,
    WRITE_SPECS,
    Block,
    Reg,
    Tier,
    decode,
    encode,
    fault_code,
    firmware_text,
    on_step,
)
from .transport import Fc660Bus, Fc660Error, Fc660IllegalError

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

#: Which option sets each tier's interval.
INTERVAL_OPTIONS: dict[Tier, str] = {
    Tier.CONTROL: CONF_CONTROL_INTERVAL,
    Tier.STATE: CONF_STATE_INTERVAL,
    Tier.SETTINGS: CONF_SETTINGS_INTERVAL,
}
#: The clock sync starts no later than this second of the minute: its six writes
#: must land inside the minute they write.
CLOCK_LATEST_SECOND = 45


async def _wait(seconds: float) -> None:
    """The clock sync's only wait, in one place (tests move the clock instead)."""
    await asyncio.sleep(seconds)


def poll_intervals(options: Mapping[str, Any]) -> dict[Tier, int]:
    """Seconds between reads, per tier, from an entry's options."""
    return {tier: int(options.get(key, POLL_INTERVALS[key][0]))
            for tier, key in INTERVAL_OPTIONS.items()}


def _registers_in(block: Block) -> tuple[Reg, ...]:
    return tuple(r for r in REGISTERS
                 if r.table is block.table and block.address <= r.address <= block.end)


def panel_clock(values: dict[str, Any]) -> datetime | None:
    """Registers 275-279 as an aware datetime, in Home Assistant's time zone."""
    parts = [values.get(key) for key in CLOCK_KEYS]
    if any(p is None for p in parts):
        return None
    try:
        return datetime(*parts, tzinfo=dt_util.get_default_time_zone())
    except ValueError:
        return None


@dataclass
class Fc660Data:
    """One poll's worth of decoded state."""

    values: dict[str, Any] = field(default_factory=dict)
    #: Raw words per block key, for diagnostics.
    raw: dict[str, list[int]] = field(default_factory=dict)
    #: True when this cycle's reads failed and the values are the last good ones.
    stale: bool = False

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)


class Fc660Coordinator(DataUpdateCoordinator[Fc660Data]):
    """Reads one FC660 on its poll intervals and writes its settings."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        bus: Fc660Bus,
        slave: int,
        model: ModelInfo,
    ) -> None:
        self.intervals = poll_intervals(entry.options)
        # The loop runs at the shortest interval; each read is made on the cycle
        # nearest its own (see _async_update_data).
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {slave}",
            update_interval=timedelta(seconds=min(self.intervals.values())),
        )
        self.bus = bus
        self.slave = slave
        self.model = model
        self.unavailable_after = float(
            entry.options.get(CONF_UNAVAILABLE_AFTER, DEFAULT_UNAVAILABLE_AFTER))
        self.sync_clock = bool(entry.options.get(CONF_SYNC_CLOCK, False))
        self._registers = {block.key: _registers_in(block) for block in BLOCKS}
        self._cache: dict[str, list[int]] = {}
        self._last_read: dict[Tier, float] = {}
        #: When the settings block (and with it the panel clock) was last read.
        self._settings_read_at: datetime | None = None
        # A clock sync is six writes; nothing else may write in between.
        self._write_lock = asyncio.Lock()
        self.last_clock_sync: float | None = None
        # Link health, surfaced as diagnostic entities and in diagnostics.
        self.last_success: float | None = None
        self.last_success_at: datetime | None = None
        self.consecutive_failures = 0
        self.read_failures = 0
        self.write_log: deque[dict[str, Any]] = deque(maxlen=20)
        self.data = Fc660Data()

    # -- polling ---------------------------------------------------------

    async def _async_update_data(self) -> Fc660Data:
        now = time.monotonic()
        # Due on the cycle nearest the interval: 30 s from a 5 s loop is the
        # sixth cycle, 15 s from a 2 s loop the seventh (14 s). Home Assistant
        # starts a cycle no earlier than the interval after the last one ended.
        slack = self.update_interval.total_seconds() / 2
        due = [
            block for block in POLLED
            if now - self._last_read.get(block.tier, float("-inf"))
            >= self.intervals[block.tier] - slack
        ]
        # A read inside another due read comes with it.
        due = [block for block in due
               if not any(other is not block and other.covers(block) for other in due)]
        try:
            for block in due:
                await self._fetch(block)
        except Fc660Error as err:
            # A refusal of a block the unit answered at setup is no more
            # actionable than a timeout: both are retried next cycle.
            self.consecutive_failures += 1
            self.read_failures += 1
            # A stall is normal on a shared bus. Keep showing the last good
            # values until the outage has lasted `unavailable_after`; the tiers
            # that were not read stay due and are retried next cycle.
            if self.last_success is None or now - self.last_success > self.unavailable_after:
                raise UpdateFailed(f"No answer from the FC660: {err}") from err
            _LOGGER.debug("Read failed (%s); keeping the last values", err)
            data = self._build()
            data.stale = True
            return data

        self._mark_read(due, now)
        self.last_success = now
        self.last_success_at = dt_util.utcnow()
        self.consecutive_failures = 0
        data = self._build()
        if HOLDING_BLOCK in due:
            self._maybe_sync_clock(data)
        return data

    async def _fetch(self, block: Block) -> None:
        words = await self.bus.read(self.slave, block.address, block.count, block.table)
        if block in BLOCKS:
            self._cache[block.key] = words
        else:
            # A slice of a whole block: patch it into that block's words. The
            # whole block was read by the first refresh, or setup failed.
            whole = next(b for b in BLOCKS if b.covers(block))
            start = block.address - whole.address
            self._cache[whole.key][start:start + block.count] = words
        if block is HOLDING_BLOCK:
            self._settings_read_at = dt_util.now()

    def _mark_read(self, blocks: Sequence[Block], now: float) -> None:
        """Every polled read covered by ``blocks`` is fresh as of ``now``."""
        for block in POLLED:
            if any(read.covers(block) for read in blocks):
                self._last_read[block.tier] = now

    # -- decoding --------------------------------------------------------

    def _build(self) -> Fc660Data:
        """Decode the whole cache, not just this cycle's reads.

        Each read is made on its own interval; what the others read must
        survive the cycles in between.
        """
        values: dict[str, Any] = {}
        for block in BLOCKS:
            words = self._cache.get(block.key)
            if words is None:
                continue
            for reg in self._registers[block.key]:
                values[reg.key] = decode(reg, words[reg.address - block.address])

        raw_fault = values.get("fault_code_raw")
        values["fault_code"] = fault_code(raw_fault)
        values["fault"] = None if raw_fault is None else raw_fault != 0
        values["firmware"] = firmware_text(values.get("firmware"))
        unit = values.get("display_unit")
        values["fahrenheit"] = None if unit is None else unit == 1
        clock = values["clock"] = panel_clock(values)
        values["clock_drift"] = None
        if clock is not None and self._settings_read_at is not None:
            # The panel has no seconds: in step means the same minute.
            read_at = self._settings_read_at.replace(second=0, microsecond=0)
            values["clock_drift"] = (clock - read_at).total_seconds()
        return Fc660Data(values=values,
                         raw={key: list(words) for key, words in self._cache.items()})

    # -- writes ------------------------------------------------------------

    async def async_write(self, changes: Sequence[tuple[str, float]], *,
                          verify: bool = True) -> None:
        """Write each ``(key, value)`` in order with FC6, then read the settings
        back once and publish what the unit holds.

        Raises ServiceValidationError for a value outside the manual's range
        (nothing is sent then), and HomeAssistantError when the unit refuses a
        write, the link fails, or -- with ``verify`` -- the unit holds something
        other than what was written.
        """
        plan: list[tuple[Reg, int, float]] = []
        for key, value in changes:
            spec = WRITE_SPECS.get(key)
            if spec is None:
                raise ServiceValidationError(translation_domain=DOMAIN,
                                             translation_key="not_writable",
                                             translation_placeholders={"key": key})
            if not on_step(spec, value):
                raise ServiceValidationError(
                    translation_domain=DOMAIN, translation_key="out_of_range",
                    translation_placeholders={"key": key, "value": str(value),
                                              "minimum": str(spec.minimum),
                                              "maximum": str(spec.maximum),
                                              "step": str(spec.step)})
            reg = BY_KEY[key]
            plan.append((reg, encode(reg, value), value))

        written: list[tuple[Reg, int]] = []
        async with self._write_lock:
            try:
                for reg, raw, value in plan:
                    try:
                        await self.bus.write(self.slave, reg.address, raw)
                    except Fc660IllegalError as err:
                        raise HomeAssistantError(
                            translation_domain=DOMAIN, translation_key="write_refused",
                            translation_placeholders={"key": reg.key, "value": str(value),
                                                      "error": str(err)}) from err
                    except Fc660Error as err:
                        raise HomeAssistantError(
                            translation_domain=DOMAIN, translation_key="write_failed",
                            translation_placeholders={"key": reg.key,
                                                      "error": str(err)}) from err
                    written.append((reg, raw))
                    self.write_log.append({"at": dt_util.utcnow().isoformat(), "key": reg.key,
                                           "address": reg.address, "raw": raw})
                    _LOGGER.debug("Wrote %s (%s) = %s", reg.key, reg.address, raw)
            finally:
                held = await self._read_back(written) if written else None

        if not verify or held is None:
            return
        wrong = [(reg, raw) for reg, raw in written if held.get(reg.address) != raw]
        if wrong:
            reg, raw = wrong[0]
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="write_not_applied",
                translation_placeholders={"key": reg.key, "wanted": str(raw),
                                          "held": str(held.get(reg.address))})

    async def _read_back(self, written: list[tuple[Reg, int]]) -> dict[int, int] | None:
        """Re-read the settings block after a write and publish it.

        If the read fails, the written words go into the cache as they are:
        the unit acknowledged each one, and the next poll corrects anything it
        did not keep. Returns address -> word held, or None if not read.
        """
        try:
            await self._fetch(HOLDING_BLOCK)
        except Fc660Error as err:
            _LOGGER.debug("Read-back after a write failed (%s); showing what was written", err)
            words = self._cache.get(HOLDING_BLOCK.key)
            if words is not None:
                for reg, raw in written:
                    words[reg.address - HOLDING_BLOCK.address] = raw
            held = None
        else:
            self._mark_read([HOLDING_BLOCK], time.monotonic())
            words = self._cache[HOLDING_BLOCK.key]
            held = {HOLDING_BLOCK.address + i: word for i, word in enumerate(words)}
        self.async_set_updated_data(self._build())
        return held

    # -- the clock ----------------------------------------------------------

    async def async_sync_clock(self) -> None:
        """Set the panel's clock to Home Assistant's local time.

        Day 1 goes first: moving 31 October to November one field at a time
        would pass through 31 November, which the panel may well refuse. The
        clock is checked by its drift afterwards, not word by word: the panel
        may tick over a minute while the six writes go out.
        """
        now = dt_util.now()
        if now.second > CLOCK_LATEST_SECOND:
            await _wait(60 - now.second + 0.5)
            now = dt_util.now()
        self.last_clock_sync = time.monotonic()
        await self.async_write([
            ("clock_day", 1), ("clock_year", now.year), ("clock_month", now.month),
            ("clock_day", now.day), ("clock_hour", now.hour), ("clock_minute", now.minute),
        ], verify=False)
        drift = self.data.values.get("clock_drift")
        if self.data.values.get("clock") is None or (
                drift is not None and abs(drift) > CLOCK_MAX_DRIFT):
            raise HomeAssistantError(translation_domain=DOMAIN,
                                     translation_key="clock_not_applied",
                                     translation_placeholders={"clock": str(
                                         self.data.values.get("clock"))})

    def _maybe_sync_clock(self, data: Fc660Data) -> None:
        if not self.sync_clock:
            return
        drift = data.values.get("clock_drift")
        if data.values.get("clock") is not None and drift is not None \
                and abs(drift) <= CLOCK_MAX_DRIFT:
            return
        if self.last_clock_sync is not None \
                and time.monotonic() - self.last_clock_sync < CLOCK_SYNC_INTERVAL:
            return
        self.last_clock_sync = time.monotonic()
        _LOGGER.info("The FC660 at %s shows %s (drift %s s); setting its clock",
                     self.slave, data.values.get("clock"), drift)
        self.config_entry.async_create_background_task(
            self.hass, self._async_auto_sync(), f"{DOMAIN} {self.slave} clock sync")

    async def _async_auto_sync(self) -> None:
        try:
            await self.async_sync_clock()
        except HomeAssistantError as err:
            _LOGGER.warning("Could not set the FC660's clock: %s", err)

    # -- diagnostics -----------------------------------------------------

    def link_stats(self) -> dict[str, Any]:
        return {
            "last_success": self.last_success_at.isoformat() if self.last_success_at else None,
            "consecutive_failures": self.consecutive_failures,
            "read_failures": self.read_failures,
            "requests": self.bus.requests,
            "bus_failures": self.bus.failures,
            "last_error": self.bus.last_error,
            "poll_intervals": {str(block): self.intervals[block.tier] for block in POLLED},
        }
