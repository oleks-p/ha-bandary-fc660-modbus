# Changelog

## 0.2.0 — 2026-10-30

- **Poll intervals are options.** Power, working mode, comfort/away and the
  setpoint (holding 264-268) are read on their own, every 5 s by default, so a
  change on the panel shows up within seconds. The readings and outputs (15 s)
  and all settings (30 s) have their own intervals too. Each goes down to 2 s.
- Diagnostics show the intervals in use.

## 0.1.0 — 2026-10-29

First release: every register in the FC660's Modbus map, read and (but for two)
written, verified against a reference unit (firmware 0x0101) behind mbusd.

- **Config flow**: Modbus TCP gateway (mbusd, …), RTU over TCP, or a serial
  adapter. One entry per panel; several panels share one connection per bus.
  The name sets the device name and the entity id prefix (`FC660` →
  `climate.fc660`, the ids of a `modbus:` YAML setup).
- **Climate**: power, working mode (heat, cool, fan only), setpoint, comfort
  and away presets, room temperature and humidity, and what the outputs are
  doing. Follows the panel's display unit: the °F setpoint while it shows °F.
- **Sensors**: temperature, humidity, TVOC, CO2, fault code, equipment type,
  firmware, Modbus address, panel password (disabled), panel clock, link health.
- **Binary sensors**: Y1, Y2, W1, W2, fan, reversing valve, auxiliary heater,
  Wi-Fi, fault.
- **Numbers, selects, switches**: every writable setting, inside the manual's
  ranges. Writes are FC6 and read back. The °F registers are disabled by default.
- **Clock**: a sync button, and an option to keep the panel's clock on Home
  Assistant's time (daylight saving included).
- The Modbus address (256) and the password (263) are never written.
- English and Ukrainian.
- `tools/probe_fc660.py` (read-only capture) and `tools/sim_fc660.py` (a
  simulated gateway with one or more panels).
