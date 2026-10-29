"""Constants for the Bandary FC660 integration."""

from __future__ import annotations

from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "bandary_fc660_modbus"
MANUFACTURER: Final = "Bandary"
MODEL: Final = "FC660"
DEFAULT_NAME: Final = "FC660"

PLATFORMS: Final = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.CLIMATE, Platform.NUMBER,
                    Platform.SELECT, Platform.SWITCH, Platform.BUTTON]

# -- connection ---------------------------------------------------------------

CONF_TRANSPORT: Final = "transport"
CONF_SERIAL_PORT: Final = "serial_port"
CONF_BAUDRATE: Final = "baudrate"
CONF_SLAVE: Final = "slave"
CONF_ENTITY_PREFIX: Final = "entity_prefix"

TRANSPORT_SERIAL: Final = "serial"
# A transparent serial server: raw RTU frames over a TCP socket.
TRANSPORT_RTU_OVER_TCP: Final = "rtu_over_tcp"
# A Modbus-TCP gateway (mbusd, for one): MBAP framing, the gateway speaks RTU on the bus.
TRANSPORT_TCP: Final = "tcp"
TRANSPORTS: Final = (TRANSPORT_SERIAL, TRANSPORT_RTU_OVER_TCP, TRANSPORT_TCP)

DEFAULT_BAUDRATE: Final = 9600
DEFAULT_TCP_PORT: Final = 502
# Holding register 256; the manual's factory default.
DEFAULT_SLAVE: Final = 1

#: Response timeout. Behind mbusd, on a bus shared with a heat pump and a
#: fancoil, the reference unit answers in 0.15-1.9 s (the gateway queues and
#: retries); 5 s matches the `modbus:` YAML setup that ran on it before.
REQUEST_TIMEOUT: Final = 5.0
#: Quiet time between frames on a serial link.
FRAME_GAP: Final = 0.050
#: Pause after a failed exchange before the link is used again. RTU has no
#: transaction id, so a late reply must be given time to arrive and be thrown
#: away rather than read as the answer to the next request.
RESYNC_DELAY: Final = 1.0

# -- options ------------------------------------------------------------------

#: How long the link may fail before entities go unavailable. A shared RS-485
#: bus stalls now and then; that must not flap entities.
CONF_UNAVAILABLE_AFTER: Final = "unavailable_after"
DEFAULT_UNAVAILABLE_AFTER: Final = 120
MIN_UNAVAILABLE_AFTER: Final = 30
MAX_UNAVAILABLE_AFTER: Final = 900

#: Keep the panel's clock (its weekly programme runs on it) on Home Assistant's
#: time, daylight saving included. Off by default: it writes to the unit.
CONF_SYNC_CLOCK: Final = "sync_clock"
#: The panel has minutes, not seconds: a drift below this is not one.
CLOCK_MAX_DRIFT: Final = 120
#: At most one automatic sync per this many seconds, whatever the drift: a panel
#: that does not keep the time it is given must not be written every poll.
CLOCK_SYNC_INTERVAL: Final = 3600
