# Bandary FC660 for Home Assistant (Modbus RTU)

A config-flow integration for the **Bandary FC660** touch-screen heat pump
thermostat. It talks to the panel over RS-485 (terminals **A/B**), either
through a Modbus TCP gateway such as [mbusd](https://github.com/3cky/mbusd) or
from a USB adapter on the Home Assistant host.

Every register in the panel's Modbus map becomes an entity, and several panels
can be added, each with its own Modbus address, on one bus or several.

## What you get

| Registers | Entity | Notes |
|---|---|---|
| — | `climate.fc660` | Power, working mode, setpoint, comfort/away preset, room temperature and humidity, and what the outputs are doing (heating, cooling, fan, idle). |
| input 1-4 | `sensor` temperature, humidity, TVOC, CO2 | Long-term statistics. |
| input 6-12 | `binary_sensor` Y1, Y2, W1, W2, fan, reversing valve (O/B), auxiliary heater | The panel's output states. |
| input 13 | `binary_sensor` Wi-Fi | Diagnostic. |
| input 14 | `sensor` fault code + `binary_sensor` fault | `none`, or `E01` (NTC sensor fault), … |
| input 0, 5 | `sensor` firmware, equipment type | Diagnostic. |
| holding 264 | `switch` power | Stand-by status. |
| holding 265 | `select` working mode | Cooling, heating, ventilation. |
| holding 266 | `switch` away mode | Scene mode: comfort / away. |
| holding 267 | `number` setpoint | 9.0–38.0 °C. |
| holding 269 | `switch` key lock | |
| holding 257 | `select` display unit | °C / °F. |
| holding 258-259 | `number` backlight brightness, backlight timeout | |
| holding 260, 262 | `number` temperature offset, humidity offset | |
| holding 270 | `number` compressor start delay | 0–15 min. |
| holding 271 | `number` dead band | 0.5–5.0 °C. |
| holding 273 | `number` stage 2 hysteresis (Y2/W2) | 1.0–5.0 °C. |
| holding 268, 261, 272, 274 | `number` the °F setpoint, offset, dead band and hysteresis | Disabled by default: the panel uses them only while it displays °F. |
| holding 275-279 | `sensor` panel clock + `button` sync clock | The panel's weekly programme runs on this clock. |
| holding 256 | `sensor` Modbus address | Read-only: writing it would cut this entry off. |
| holding 263 | `sensor` panel password | Read-only, disabled by default, redacted in diagnostics. |
| — | `sensor` last successful read, read failures | Link health. |

Entity ids are `<domain>.<prefix>_<key>`, and the climate is `climate.<prefix>`.
The prefix is the slug of the name given at setup: `FC660` gives
`climate.fc660` and `sensor.fc660_humidity`, `FC660 Bedroom` gives
`climate.fc660_bedroom`. Ids don't depend on Home Assistant's language. The
full list, with units and classes, is in [entities.json](entities.json).

Names are translated into English and Ukrainian.

### Writes

Every holding register except the address and the password is writable, within
the ranges in the manual. Writes are **FC6**, one register at a time: the
FC660 does not answer FC16. After each write the integration reads the settings
back, so an entity shows what the panel holds rather than what was asked for.
A value the panel does not keep is reported as an error.

The climate entity writes the working mode first and then power on, so the
panel never starts in its old mode.

## Install

**HACS:** *HACS → ⋮ → Custom repositories*, add
`https://github.com/oleks-p/ha-bandary-fc660-modbus` as an *Integration*,
install **Bandary FC660 (Modbus)**, and restart Home Assistant.

**Manually:** copy `custom_components/bandary_fc660_modbus` into your Home
Assistant `config/custom_components/` and restart.

## Configure

*Settings → Devices & services → Add integration → Bandary FC660*, then:

- **Network gateway**: host and port, and the gateway type. mbusd and other
  Modbus TCP gateways are *Modbus TCP gateway*. A transparent serial server
  that passes raw RTU frames is *RTU over TCP*.
- **USB / RS-485 adapter**: the serial port (prefer `/dev/serial/by-id/...`),
  baud rate (9600 on the reference unit), 8N1.

Then give the panel's **Modbus address** (holding register 256, factory
default 1) and a **name**. Add more panels the same way. Panels behind the
same gateway or on the same serial port share one connection, and their
requests queue instead of colliding.

**RS-485 has one master.** If other devices share the bus and something else
polls them, put a gateway such as mbusd on the bus and point everything at the
gateway. A serial port opened by two programs at once fails for both.

Options:

- **Poll intervals**: how often to read power, mode and setpoint (default 5 s),
  the readings and outputs (15 s), and all settings (30 s). Each goes down to
  2 s; see [Polling](#polling).
- **Unavailable after** (default 120 s): how long reads may fail before the
  entities show as unavailable. Short stalls on a shared bus are normal.
- **Keep the panel clock in sync** (default off): sets the panel's clock to
  Home Assistant's time whenever it is more than 2 minutes off, at most once an
  hour. Daylight saving is included.

*Reconfigure* changes the connection (serial ↔ gateway) and keeps the entity
ids and history.

### Coming from a `modbus:` YAML setup

With the default name `FC660`, the integration uses the same entity ids as a
YAML setup that named its entities `FC660 …`. Those ids are `climate.fc660`,
`sensor.fc660_humidity`, `sensor.fc660_tvoc`, `sensor.fc660_co2`,
`binary_sensor.fc660_fan_running`, `binary_sensor.fc660_reversing_valve`,
`binary_sensor.fc660_aux_heater`, `switch.fc660_key_lock` and
`switch.fc660_away_mode`, and their history carries over. Remove the FC660
entries from the YAML **first** and restart. While the YAML entities exist,
their ids are taken, and the integration's entities would get `_2` ids instead.

## Polling

| Read | Request | Default | Option |
|---|---|---|---|
| Holding registers 264-268 (power, working mode, comfort/away, setpoint) | one FC3 | 5 s | *Read power, mode and setpoint every* |
| Input registers 0-14 (readings, outputs, fault) | one FC4 | 15 s | *Read readings and outputs every* |
| Holding registers 256-279 (every setting, the clock) | one FC3 | 30 s | *Read all settings every* |

Each interval can be set from 2 s up. The integration polls at the shortest of
the three and makes each read on the cycle nearest its own interval, so the
other two round to a multiple of it: with power, mode and setpoint at 2 s, a
15 s interval becomes 14 s. When the settings read is due it brings power, mode
and setpoint with it, and the short read is skipped. After a change from Home
Assistant the settings are read back at once, whatever the intervals.

With the defaults that is eight requests per 30 s per panel. The short read
took about 40 ms on the reference unit's quiet bus, and up to 0.9 s when queued
behind the other devices' requests in mbusd. The map is exactly the two whole
blocks, and the unit answers nothing outside them; see
[docs/register_map.md](docs/register_map.md).

## Tools

- `tools/probe_fc660.py`: read-only capture of a panel's whole map, decoded.
  It needs only Python 3.11+ and pymodbus, so it runs on the Home Assistant
  host or inside the Home Assistant container:

  ```
  python3 tools/probe_fc660.py --host 127.0.0.1 --port 10502 --slave 2 --edges --out capture.json
  ```

- `tools/sim_fc660.py`: serves a capture as a Modbus TCP gateway, with the
  unit's rules, at one or more addresses. `docker compose up -d` starts it
  alongside a development Home Assistant. Open http://localhost:8123, add the
  integration with host `sim`, port 5020, *Modbus TCP gateway*, and address 2
  or 3.

## Development

```
python3.14 -m venv .venv && .venv/bin/pip install -r requirements_test.txt
.venv/bin/ruff check custom_components tools tests
.venv/bin/pytest -q
.venv/bin/python tools/gen_translations.py     # after changing any string
.venv/bin/python tools/export_entities.py      # after changing any entity
```

The tests run the integration against a fake built from the reference unit's
capture (`tests/fixtures/fc660_reference.json`). `tests/probe` runs without
Home Assistant, on Python 3.11.

Releases are published from tags (`v0.1.0`, …). The tag must match the
manifest version, and HACS offers the newest release.

## License

MIT. The Bandary name and logo belong to their owner.
