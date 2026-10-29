"""Generated files are current, and every entity has its name and icon in place."""

from __future__ import annotations

import json
from pathlib import Path

import export_entities
import gen_translations
from custom_components.bandary_fc660_modbus.binary_sensor import BINARY_SENSORS
from custom_components.bandary_fc660_modbus.button import SYNC_CLOCK
from custom_components.bandary_fc660_modbus.number import NUMBERS
from custom_components.bandary_fc660_modbus.select import SELECTS
from custom_components.bandary_fc660_modbus.sensor import SENSORS
from custom_components.bandary_fc660_modbus.switch import SWITCHES

PACKAGE = Path(__file__).parents[2] / "custom_components" / "bandary_fc660_modbus"
PLATFORMS = {"sensor": SENSORS, "binary_sensor": BINARY_SENSORS, "number": NUMBERS,
             "select": SELECTS, "switch": SWITCHES, "button": (SYNC_CLOCK,)}


def test_translations_are_current():
    assert gen_translations.main(["--check"]) == 0


def test_entities_json_is_current():
    assert export_entities.main(["--check"]) == 0


def test_every_entity_is_named_in_both_languages():
    for lang in ("en", "uk"):
        names = json.loads((PACKAGE / "translations" / f"{lang}.json").read_text())["entity"]
        for platform, descriptions in PLATFORMS.items():
            for d in descriptions:
                assert names[platform][d.key]["name"], (lang, platform, d.key)
                for option in getattr(d, "options", None) or []:
                    if platform in ("select",) or d.device_class == "enum":
                        assert option in names[platform][d.key]["state"], (lang, d.key, option)


def test_icons_name_only_real_entities():
    icons = json.loads((PACKAGE / "icons.json").read_text())["entity"]
    for platform, keys in icons.items():
        known = {d.key for d in PLATFORMS[platform]}
        assert set(keys) <= known, (platform, set(keys) - known)
