"""Config flow: pick the link and the address, check it is an FC660, done.

One entry per panel. The name becomes the device name, and its slug the entity
id prefix: "FC660" gives climate.fc660 and sensor.fc660_humidity, "FC660
Bedroom" gives climate.fc660_bedroom. Two panels cannot share a prefix.
"""

from __future__ import annotations

import glob
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
from homeassistant.util import slugify

from . import bus_registry
from .const import (
    CONF_BAUDRATE,
    CONF_ENTITY_PREFIX,
    CONF_SERIAL_PORT,
    CONF_SLAVE,
    CONF_SYNC_CLOCK,
    CONF_TRANSPORT,
    CONF_UNAVAILABLE_AFTER,
    DEFAULT_BAUDRATE,
    DEFAULT_NAME,
    DEFAULT_SLAVE,
    DEFAULT_TCP_PORT,
    DEFAULT_UNAVAILABLE_AFTER,
    DOMAIN,
    MAX_UNAVAILABLE_AFTER,
    MIN_UNAVAILABLE_AFTER,
    TRANSPORT_RTU_OVER_TCP,
    TRANSPORT_SERIAL,
    TRANSPORT_TCP,
)
from .model import ModelInfo, NotAnFc660, async_identify
from .transport import Endpoint, Fc660TransientError

BAUDRATES = ["2400", "4800", "9600", "19200", "38400"]
SLAVE = vol.All(vol.Coerce(int), vol.Range(min=1, max=247))


def _list_serial_ports() -> list[str]:
    """Stable by-id paths first; then whatever pyserial sees (in a container the
    by-id links may not exist, only the mapped device)."""
    from serial.tools import list_ports

    ports = sorted(glob.glob("/dev/serial/by-id/*"))
    ports += sorted(p.device for p in list_ports.comports() if p.device not in ports)
    return ports


def _serial_schema(defaults: dict[str, Any], ports: list[str], *, with_name: bool) -> vol.Schema:
    fields: dict[Any, Any] = {}
    if with_name:
        fields[vol.Required(CONF_NAME, default=DEFAULT_NAME)] = str
    fields.update({
        vol.Required(CONF_SERIAL_PORT, default=defaults.get(CONF_SERIAL_PORT, vol.UNDEFINED)):
            selector.SelectSelector(selector.SelectSelectorConfig(
                options=ports, custom_value=True, mode=selector.SelectSelectorMode.DROPDOWN)),
        vol.Required(CONF_BAUDRATE, default=str(defaults.get(CONF_BAUDRATE, DEFAULT_BAUDRATE))):
            selector.SelectSelector(selector.SelectSelectorConfig(
                options=BAUDRATES, mode=selector.SelectSelectorMode.DROPDOWN)),
        vol.Required(CONF_SLAVE, default=defaults.get(CONF_SLAVE, DEFAULT_SLAVE)): SLAVE,
    })
    return vol.Schema(fields)


def _network_schema(defaults: dict[str, Any], *, with_name: bool) -> vol.Schema:
    fields: dict[Any, Any] = {}
    if with_name:
        fields[vol.Required(CONF_NAME, default=DEFAULT_NAME)] = str
    fields.update({
        vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, vol.UNDEFINED)): str,
        vol.Required(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_TCP_PORT)):
            vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
        vol.Required(CONF_TRANSPORT, default=defaults.get(CONF_TRANSPORT, TRANSPORT_TCP)):
            selector.SelectSelector(selector.SelectSelectorConfig(
                options=[TRANSPORT_TCP, TRANSPORT_RTU_OVER_TCP], translation_key="framing",
                mode=selector.SelectSelectorMode.LIST)),
        vol.Required(CONF_SLAVE, default=defaults.get(CONF_SLAVE, DEFAULT_SLAVE)): SLAVE,
    })
    return vol.Schema(fields)


async def _identify(hass: HomeAssistant, data: dict[str, Any]
                    ) -> tuple[ModelInfo | None, dict[str, str], dict[str, str]]:
    """Check the unit through the shared bus registry.

    Going through the registry matters: if another entry already polls this
    port, the check queues on the same bus instead of opening the port a
    second time.
    """
    endpoint = Endpoint.from_config(data)
    registry = bus_registry(hass)
    bus = registry.acquire(endpoint)
    try:
        return await async_identify(bus, data[CONF_SLAVE]), {}, {}
    except Fc660TransientError:
        return None, {"base": "cannot_connect"}, {}
    except NotAnFc660 as err:
        return None, {"base": "not_an_fc660"}, {"reason": str(err)}
    finally:
        await registry.release(endpoint)


def _unique_id(data: dict[str, Any]) -> str:
    return f"{Endpoint.from_config(data).key}#{data[CONF_SLAVE]}"


class Fc660ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up one FC660."""

    VERSION = 1

    def __init__(self) -> None:
        self._errors: dict[str, str] = {}
        self._placeholders: dict[str, str] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None
                              ) -> ConfigFlowResult:
        return self.async_show_menu(step_id="user", menu_options=["network", "serial"])

    async def async_step_serial(self, user_input: dict[str, Any] | None = None
                                ) -> ConfigFlowResult:
        if user_input is not None:
            data = {**user_input, CONF_TRANSPORT: TRANSPORT_SERIAL,
                    CONF_BAUDRATE: int(user_input[CONF_BAUDRATE])}
            result = await self._async_create(data)
            if result is not None:
                return result
        ports = await self.hass.async_add_executor_job(_list_serial_ports)
        return self.async_show_form(
            step_id="serial", errors=self._errors, description_placeholders=self._placeholders,
            data_schema=self.add_suggested_values_to_schema(
                _serial_schema({}, ports, with_name=True), user_input or {}))

    async def async_step_network(self, user_input: dict[str, Any] | None = None
                                 ) -> ConfigFlowResult:
        if user_input is not None:
            result = await self._async_create(dict(user_input))
            if result is not None:
                return result
        return self.async_show_form(
            step_id="network", errors=self._errors, description_placeholders=self._placeholders,
            data_schema=self.add_suggested_values_to_schema(
                _network_schema({}, with_name=True), user_input or {}))

    async def _async_create(self, data: dict[str, Any]) -> ConfigFlowResult | None:
        self._errors, self._placeholders = {}, {}
        name = data.pop(CONF_NAME).strip()
        prefix = slugify(name)
        # slugify() turns a name with nothing to keep into "unknown", not "".
        if not any(ch.isalnum() for ch in name):
            self._errors = {CONF_NAME: "invalid_name"}
            return None
        if any(e.data.get(CONF_ENTITY_PREFIX) == prefix for e in self._async_current_entries()):
            self._errors = {CONF_NAME: "name_in_use"}
            self._placeholders = {"prefix": prefix}
            return None
        data[CONF_ENTITY_PREFIX] = prefix
        await self.async_set_unique_id(_unique_id(data))
        self._abort_if_unique_id_configured()
        info, self._errors, self._placeholders = await _identify(self.hass, data)
        if info is None:
            return None
        return self.async_create_entry(title=name, data=data)

    # -- reconfigure: same panel, different link --------------------------------

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None
                                     ) -> ConfigFlowResult:
        """Offer both link types, not only the one currently in use.

        Every entity's unique_id is derived from the entry_id, so removing and
        re-adding the integration orphans all of them along with their history;
        a panel moved behind a gateway has to be re-linked in place.
        """
        self._errors, self._placeholders = {}, {}
        return self.async_show_menu(
            step_id="reconfigure",
            menu_options=["reconfigure_network", "reconfigure_serial"])

    async def async_step_reconfigure_serial(
            self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._async_relink(user_input, serial=True)

    async def async_step_reconfigure_network(
            self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._async_relink(user_input, serial=False)

    async def _async_relink(self, user_input: dict[str, Any] | None, *,
                            serial: bool) -> ConfigFlowResult:
        """Rewrite one entry's link, keeping the entry itself."""
        entry = self._get_reconfigure_entry()
        step = "reconfigure_serial" if serial else "reconfigure_network"
        if user_input is not None:
            # Drop the other link's keys, so the stored data says only what is used.
            kept = {k: v for k, v in entry.data.items()
                    if k not in (CONF_SERIAL_PORT, CONF_BAUDRATE, CONF_HOST, CONF_PORT)}
            data = {**kept, **user_input}
            if serial:
                data[CONF_TRANSPORT] = TRANSPORT_SERIAL
                data[CONF_BAUDRATE] = int(user_input[CONF_BAUDRATE])
            unique_id = _unique_id(data)
            if unique_id != entry.unique_id and any(
                    e.unique_id == unique_id for e in self._async_current_entries()):
                return self.async_abort(reason="already_configured")
            info, self._errors, self._placeholders = await _identify(self.hass, data)
            if info is not None:
                return self.async_update_reload_and_abort(entry, unique_id=unique_id, data=data)
        defaults = {**entry.data, **(user_input or {})}
        if serial:
            ports = await self.hass.async_add_executor_job(_list_serial_ports)
            schema = _serial_schema(defaults, ports, with_name=False)
        else:
            schema = _network_schema(defaults, with_name=False)
        return self.async_show_form(step_id=step, data_schema=schema,
                                    errors=self._errors,
                                    description_placeholders=self._placeholders)

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> Fc660OptionsFlow:
        return Fc660OptionsFlow()


class Fc660OptionsFlow(OptionsFlowWithReload):
    """Link tolerance, and whether to keep the panel's clock in step."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None
                              ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data={
                CONF_UNAVAILABLE_AFTER: int(user_input[CONF_UNAVAILABLE_AFTER]),
                CONF_SYNC_CLOCK: bool(user_input.get(CONF_SYNC_CLOCK, False)),
            })
        options = self.config_entry.options
        schema = vol.Schema({
            vol.Required(CONF_UNAVAILABLE_AFTER,
                         default=options.get(CONF_UNAVAILABLE_AFTER, DEFAULT_UNAVAILABLE_AFTER)):
                selector.NumberSelector(selector.NumberSelectorConfig(
                    min=MIN_UNAVAILABLE_AFTER, max=MAX_UNAVAILABLE_AFTER, step=10,
                    unit_of_measurement="s", mode=selector.NumberSelectorMode.BOX)),
            vol.Required(CONF_SYNC_CLOCK, default=options.get(CONF_SYNC_CLOCK, False)):
                selector.BooleanSelector(),
        })
        return self.async_show_form(step_id="init", data_schema=schema)
