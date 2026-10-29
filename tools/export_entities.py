#!/usr/bin/env python3
"""Write entities.json: every entity this release creates, and what it is.

Dashboard tooling can vendor this file per release and check what it binds
against it, so a dashboard only names entities the pinned release really
provides. A test fails if the committed file falls behind the code.

    .venv/bin/python tools/export_entities.py            # rewrite entities.json
    .venv/bin/python tools/export_entities.py --check    # exit 1 if it is stale
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "entities.json"


def build() -> dict:
    from custom_components.bandary_fc660_modbus.binary_sensor import BINARY_SENSORS
    from custom_components.bandary_fc660_modbus.button import SYNC_CLOCK
    from custom_components.bandary_fc660_modbus.climate import THERMOSTAT
    from custom_components.bandary_fc660_modbus.const import DEFAULT_NAME, DOMAIN
    from custom_components.bandary_fc660_modbus.number import NUMBERS
    from custom_components.bandary_fc660_modbus.registers import BY_KEY
    from custom_components.bandary_fc660_modbus.select import SELECTS
    from custom_components.bandary_fc660_modbus.sensor import SENSORS
    from custom_components.bandary_fc660_modbus.switch import SWITCHES

    manifest = json.loads((ROOT / "custom_components" / DOMAIN / "manifest.json").read_text())

    def record(domain: str, d) -> dict:
        rec = {"domain": domain, "key": d.key}
        if d.key in BY_KEY:
            rec["register"] = f"{BY_KEY[d.key].table} {BY_KEY[d.key].address}"
        for field in ("native_unit_of_measurement", "device_class", "state_class",
                      "entity_category"):
            val = getattr(d, field, None)
            if val is not None:
                name = "unit_of_measurement" if field == "native_unit_of_measurement" else field
                rec[name] = str(val.value if hasattr(val, "value") else val)
        if getattr(d, "options", None):
            rec["options"] = list(d.options)
        if not d.entity_registry_enabled_default:
            rec["enabled_by_default"] = False
        return rec

    entities = [
        {"domain": "climate", "key": THERMOSTAT.key, "entity_id": "climate.<entity_prefix>",
         "registers": "holding 264-268"},
        *(record("sensor", d) for d in SENSORS),
        *(record("binary_sensor", d) for d in BINARY_SENSORS),
        *(record("number", d) for d in NUMBERS),
        *(record("select", d) for d in SELECTS),
        *(record("switch", d) for d in SWITCHES),
        record("button", SYNC_CLOCK),
    ]
    return {
        "domain": DOMAIN,
        "version": manifest["version"],
        "default_entity_prefix": DEFAULT_NAME.lower(),
        "entity_id": "<domain>.<entity_prefix>_<key>",
        "entities": entities,
    }


def render() -> str:
    return json.dumps(build(), indent=1, ensure_ascii=False) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="fail if entities.json is stale")
    args = ap.parse_args(argv)
    text = render()
    if args.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print("entities.json is stale; run tools/export_entities.py", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
