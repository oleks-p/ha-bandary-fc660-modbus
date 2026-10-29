"""The panel clock: shown as a timestamp, set by the button, kept in step by an option."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from homeassistant.util import dt as dt_util

from custom_components.bandary_fc660_modbus.const import CONF_SYNC_CLOCK

from .conftest import PACKAGE


async def _press(hass) -> None:
    await hass.services.async_call("button", "press", {"entity_id": "button.fc660_sync_clock"},
                                   blocking=True)


async def test_the_button_sets_the_clock_day_1_first(hass, fake, setup_integration, freezer):
    freezer.move_to("2026-10-31 08:15:10+00:00")       # 10:15 in Kyiv
    fake.set_holding(276, 9)                           # the panel still thinks it is September
    await _press(hass)
    assert fake.writes == [(277, 1), (275, 2026), (276, 10), (277, 31), (278, 10), (279, 15)]
    state = hass.states.get("sensor.fc660_clock")
    assert state.state == "2026-10-31T08:15:00+00:00"
    assert state.attributes["drift_seconds"] == 0


async def test_late_in_the_minute_it_waits_for_the_next(hass, fake, setup_integration, freezer):
    freezer.move_to("2026-10-29 19:59:50+00:00")       # 21:59:50 in Kyiv

    async def wait(seconds: float) -> None:
        freezer.tick(timedelta(seconds=seconds))

    with patch(f"{PACKAGE}.coordinator._wait", side_effect=wait) as waited:
        await _press(hass)
    waited.assert_called_once()
    assert fake.writes[-2:] == [(278, 22), (279, 0)]


async def test_with_the_option_a_drifted_clock_is_set_once_an_hour(
        hass, fake, kyiv, config_entry, modbus_clients, advance, freezer):
    hass.config_entries.async_update_entry(config_entry, options={CONF_SYNC_CLOCK: True})
    fake.set_holding(278, 20)                          # an hour behind: summer time ended
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert [a for a, _ in fake.writes] == [277, 275, 276, 277, 278, 279]
    assert fake.get_holding(278) == 21
    # The panel loses it again: not written again within the hour ...
    fake.writes.clear()
    fake.set_holding(278, 20)
    await advance(600)
    assert fake.writes == []
    # ... and set again after it.
    await advance(3000)
    assert fake.get_holding(278) == dt_util.as_local(dt_util.now()).hour


async def test_without_the_option_nothing_is_written(hass, fake, kyiv, config_entry,
                                                    modbus_clients, advance):
    fake.set_holding(278, 20)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    await advance(60)
    assert fake.writes == []
    assert hass.states.get("sensor.fc660_clock").attributes["drift_seconds"] < -3000
