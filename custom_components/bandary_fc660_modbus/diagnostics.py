"""Diagnostics: raw register words alongside the decoded view, for bug reports.

The raw words matter most: they let a decoding problem be reproduced against
the simulator without access to the unit. The panel password (263) is redacted.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import REDACTED, async_redact_data
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from . import Fc660ConfigEntry
from .const import CONF_SERIAL_PORT
from .registers import BLOCKS, BY_KEY, HOLDING_BLOCK, REGISTER_MAP_VERSION

TO_REDACT = {CONF_HOST, CONF_SERIAL_PORT}
PASSWORD = BY_KEY["password"].address - HOLDING_BLOCK.address


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: Fc660ConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data.coordinator
    model = coordinator.model
    data = coordinator.data
    values = {k: (v.isoformat() if hasattr(v, "isoformat") else v)
              for k, v in sorted(data.values.items())}
    if "password" in values:
        values["password"] = REDACTED
    raw = {key: list(words) for key, words in data.raw.items()}
    if HOLDING_BLOCK.key in raw:
        raw[HOLDING_BLOCK.key][PASSWORD] = REDACTED
    return {
        "entry": {
            "title": entry.title,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "model": {
            "firmware": model.firmware,
            "equipment_type": model.equipment,
            "register_map": REGISTER_MAP_VERSION,
        },
        "link": coordinator.link_stats(),
        "blocks": [str(block) for block in BLOCKS],
        "recent_writes": list(coordinator.write_log),
        "stale": data.stale,
        "values": values,
        "raw_registers": raw,
    }
