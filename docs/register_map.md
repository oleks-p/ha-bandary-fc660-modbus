# FC660 register map

Transcribed from the FC660 manual, section "Modbus communication Register"
(pages 21-23), and checked against the reference unit with
`tools/probe_fc660.py` on 2026-10-29. Addresses are the wire addresses: the
manual already numbers them from 0. The map in code is
`custom_components/bandary_fc660_modbus/registers.py` (`fc660-r1`).

## Input registers (FC4, read-only)

| Address | Key | Description | Resolution / unit | Reference unit |
|---|---|---|---|---|
| 0 | `firmware` | Firmware version, e.g. 0x1A0 | — | 0x0101 |
| 1 | `temperature` | Room temperature, 0…500 → 0…50.0 °C | 0.1 °C | 176 (17.6 °C) |
| 2 | `humidity` | Room humidity, 0…100 % | 1 %RH | 58 |
| 3 | `tvoc` | Room TVOC, 0…60000 | 1 ppb | 51 |
| 4 | `co2` | Room CO2, 400…60000 | 1 ppm | 407 |
| 5 | `equipment_type` | 0 single-stage heat pump, 1 multi-stage heat pump, 2 cooling only, 3 heating only | — | 1 |
| 6 | `y1` | Y1 status, 0 off / 1 on | — | 0 |
| 7 | `y2` | Y2 status | — | 0 |
| 8 | `w1` | W1 status | — | 1 |
| 9 | `w2` | W2 status | — | 1 |
| 10 | `fan_running` | Fan status | — | 1 |
| 11 | `reversing_valve` | O/B (reversing valve) status | — | 0 |
| 12 | `aux_heater` | Auxiliary electric heater status | — | 0 |
| 13 | `wifi` | Wi-Fi status, 0 offline / 1 online | — | 0 |
| 14 | `fault_code_raw` | Fault code, E01 = NTC sensor fault | — | 0 |

## Holding registers (FC3 to read, FC6 to write)

| Address | Key | Description | Range | Default | Reference unit |
|---|---|---|---|---|---|
| 256 | `modbus_address` | Device (Modbus) address | 1…247 | 1 | 2 |
| 257 | `display_unit` | LCD temperature unit, 0 °C / 1 °F | 0…1 | 0 | 0 |
| 258 | `backlight_brightness` | Backlight intensity | 0…100 % | 80 | 100 |
| 259 | `backlight_timeout` | Backlight on time | 1…255 s | 30 | 30 |
| 260 | `temperature_offset` | Internal sensor offset, −100…100 → −10.0…10.0 °C | 0.1 °C | 0 | 0 |
| 261 | `temperature_offset_f` | Internal sensor offset | −10…10 °F | 0 | 0 |
| 262 | `humidity_offset` | Humidity offset | −20…20 % | 0 | 0 |
| 263 | `password` | Settings password, 000 = none | 001…998 | 987 | (default) |
| 264 | `power` | Stand-by status, 0 power off / 1 power on | 0…1 | 1 | 1 |
| 265 | `working_mode` | 0 cooling, 1 heating (comfort), 2 ventilating | 0…2 | 0 | 1 |
| 266 | `away_mode` | Scene mode, 0 comfort / 1 away | 0…1 | 0 | 0 |
| 267 | `setpoint` | Setpoint, 90…380 → 9.0…38.0 °C | 0.1 °C | 210 | 240 |
| 268 | `setpoint_f` | Setpoint | 48…99 °F | 69 | 69 |
| 269 | `key_lock` | 0 unlocked / 1 locked | 0…1 | 0 | 0 |
| 270 | `compressor_delay` | Compressor start-up delay | 0…15 min | 3 | 3 |
| 271 | `dead_band` | Dead band, 5…50 → 0.5…5.0 °C | 0.1 °C | 5 | 5 |
| 272 | `dead_band_f` | Dead band | 1…10 °F | 2 | 1 |
| 273 | `stage_hysteresis` | Y2/W2 hysteresis, 10…50 → 1.0…5.0 °C | 0.1 °C | 1 (sic) | 10 |
| 274 | `stage_hysteresis_f` | Y2/W2 hysteresis | 2…10 °F | 2 | 2 |
| 275 | `clock_year` | Year | 2023…2099 | 2023 | 2026 |
| 276 | `clock_month` | Month | 1…12 | 1 | 10 |
| 277 | `clock_day` | Day | 1…31 | 1 | 29 |
| 278 | `clock_hour` | Hour | 0…23 | 0 | 21 |
| 279 | `clock_minute` | Minute | 0…59 | 0 | 46 |

The manual prints default "1" for register 273, whose range is 10…50. The
reference unit holds 10 (1.0 °C), so the "1" is presumably 1.0 °C.

The °C and °F registers are independent: the reference unit holds a 24.0 °C
setpoint in 267 and the factory 69 °F in 268, so the panel does not keep them
in step. It uses the set that matches its display unit (257).

## What the reference unit showed

Bandary FC660, firmware 0x0101, address 2, behind mbusd 0.5.3 (Modbus TCP,
9600 8N1) on a bus it shares with an Olimpia Splendid Sherpa heat pump and a
Daikin fancoil.

- Input registers 0-14 read whole in one FC4 request, and holding registers
  256-279 in one FC3 request. That is the whole map.
- A read one register past either end (`input 15`, `input 0+16`, `holding
  280`, `holding 256+25`), FC3 on the input range and FC4 on the holding range
  are all refused. Behind mbusd each one comes back as exception 4 after 1-3 s,
  which is the gateway's whole retry budget (`-N 2 -W 300`). So the unit most
  likely does not answer such a read at all; mbusd reports the silence as 4.
- In-map reads took 70-100 ms when the bus was quiet, and up to about 1.9 s
  when queued behind the other masters' requests in mbusd.
- A read of part of a block is answered too. Holding 264-268 alone (power,
  working mode, scene, both setpoints) came back in about 40 ms on a quiet bus,
  and in up to 0.9 s when queued (2026-10-30). The integration polls that slice
  on its own, between whole reads of the holding block.
- Writes are FC6 only. FC16 gets no reply. That was measured on the same unit
  by the `modbus:` YAML setup this integration replaces, which wrote 264-267
  and 269 with FC6.

## Not in the map

The manual describes three more panel functions, *Fan On/Off*, *Key
Lock/Unlock* and *ECO On/Off*, as touch settings. Key lock is register 269.
Fan on/off and ECO have no register in the Modbus table, so the integration
cannot see or set them. The weekly programme is not in the map either. Only
the clock it runs on is.
