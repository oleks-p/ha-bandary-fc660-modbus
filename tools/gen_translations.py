#!/usr/bin/env python3
"""Write strings.json and translations/{en,uk}.json from one table.

English and Ukrainian sit side by side here, so a string cannot be added to one
language and forgotten in the other, and strings.json and en.json stay equal.
A test fails if the committed files fall behind this script.

    .venv/bin/python tools/gen_translations.py            # rewrite the three files
    .venv/bin/python tools/gen_translations.py --check    # exit 1 if any is stale
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "custom_components" / "bandary_fc660_modbus"

# platform -> key -> (en, uk[, {state: (en, uk)}])
ENTITIES: dict[str, dict[str, tuple]] = {
    "sensor": {
        "temperature": ("Temperature", "Температура"),
        "humidity": ("Humidity", "Вологість"),
        "tvoc": ("TVOC", "TVOC"),
        "co2": ("CO2", "CO2"),
        "fault_code": ("Fault code", "Код несправності"),
        "equipment_type": ("Equipment type", "Тип обладнання", {
            "single_stage_heat_pump": ("Heat pump, single stage", "Тепловий насос, один ступінь"),
            "multi_stage_heat_pump": ("Heat pump, multi-stage", "Тепловий насос, кілька ступенів"),
            "cooling_only": ("Cooling only", "Лише охолодження"),
            "heating_only": ("Heating only", "Лише опалення"),
        }),
        "firmware": ("Firmware", "Прошивка"),
        "modbus_address": ("Modbus address", "Адреса Modbus"),
        "password": ("Panel password", "Пароль панелі"),
        "clock": ("Panel clock", "Годинник панелі"),
        "last_successful_read": ("Last successful read", "Останнє успішне читання"),
        "read_failures": ("Read failures", "Помилки читання"),
    },
    "binary_sensor": {
        "y1": ("Y1 (cooling stage 1)", "Y1 (ступінь охолодження 1)"),
        "y2": ("Y2 (cooling stage 2)", "Y2 (ступінь охолодження 2)"),
        "w1": ("W1 (heating stage 1)", "W1 (ступінь опалення 1)"),
        "w2": ("W2 (heating stage 2)", "W2 (ступінь опалення 2)"),
        "fan_running": ("Fan", "Вентилятор"),
        "reversing_valve": ("Reversing valve (O/B)", "Чотириходовий клапан (O/B)"),
        "aux_heater": ("Auxiliary heater", "Додатковий нагрівач"),
        "wifi": ("Wi-Fi", "Wi-Fi"),
        "fault": ("Fault", "Несправність"),
    },
    "number": {
        "setpoint": ("Setpoint", "Уставка"),
        "setpoint_f": ("Setpoint (°F)", "Уставка (°F)"),
        "backlight_brightness": ("Backlight brightness", "Яскравість підсвічування"),
        "backlight_timeout": ("Backlight timeout", "Тривалість підсвічування"),
        "temperature_offset": ("Temperature offset", "Корекція температури"),
        "temperature_offset_f": ("Temperature offset (°F)", "Корекція температури (°F)"),
        "humidity_offset": ("Humidity offset", "Корекція вологості"),
        "compressor_delay": ("Compressor start delay", "Затримка запуску компресора"),
        "dead_band": ("Dead band", "Мертва зона"),
        "dead_band_f": ("Dead band (°F)", "Мертва зона (°F)"),
        "stage_hysteresis": ("Stage 2 hysteresis (Y2/W2)", "Гістерезис 2-го ступеня (Y2/W2)"),
        "stage_hysteresis_f": ("Stage 2 hysteresis (Y2/W2, °F)",
                               "Гістерезис 2-го ступеня (Y2/W2, °F)"),
    },
    "select": {
        "working_mode": ("Working mode", "Режим роботи", {
            "cooling": ("Cooling", "Охолодження"),
            "heating": ("Heating", "Опалення"),
            "ventilation": ("Ventilation", "Вентиляція"),
        }),
        "display_unit": ("Display unit", "Одиниця на дисплеї", {
            "celsius": ("°C", "°C"),
            "fahrenheit": ("°F", "°F"),
        }),
    },
    "switch": {
        "power": ("Power", "Живлення"),
        "away_mode": ("Away mode", "Режим «Відсутність»"),
        "key_lock": ("Key lock", "Блокування кнопок"),
    },
    "button": {
        "sync_clock": ("Sync clock", "Синхронізувати годинник"),
    },
}

# key: (en, uk)
T: dict[str, tuple[str, str]] = {
    "menu_title": ("How is the FC660 connected?", "Як підключено FC660?"),
    "menu_desc": (
        "One entry per panel. Panels on one RS-485 bus are added one at a time, each with its "
        "own Modbus address, and share the connection.",
        "Один запис на панель. Панелі на одній шині RS-485 додаються по одній, кожна зі своєю "
        "адресою Modbus, і користуються одним з'єднанням."),
    "network": ("Network gateway (mbusd, …)", "Мережевий шлюз (mbusd, …)"),
    "serial": ("USB / RS-485 adapter", "Адаптер USB / RS-485"),
    "network_title": ("Network gateway", "Мережевий шлюз"),
    "network_desc": (
        "A Modbus TCP gateway such as mbusd, or a transparent serial server (RTU over TCP). "
        "Use a gateway when other devices share the bus and something else polls them: "
        "RS-485 allows one master.",
        "Шлюз Modbus TCP, як-от mbusd, або прозорий послідовний сервер (RTU через TCP). "
        "Використовуйте шлюз, коли шиною користуються інші пристрої і їх опитує ще хтось: "
        "RS-485 допускає лише одного майстра."),
    "serial_title": ("RS-485 adapter", "Адаптер RS-485"),
    "serial_desc": (
        "Terminals A/B on the panel, 8N1. Prefer a /dev/serial/by-id path: it survives reboots "
        "and replugging. Nothing else may open this port.",
        "Клеми A/B на панелі, 8N1. Обирайте шлях /dev/serial/by-id: він не змінюється після "
        "перезавантаження чи перепідключення. Ніщо інше не повинно відкривати цей порт."),
    "reconf_title": ("Change the connection", "Змінити підключення"),
    "reconf_desc": ("Same panel, different link. Entity ids and history are kept.",
                    "Та сама панель, інше підключення. Ідентифікатори сутностей та історія "
                    "зберігаються."),
    "name": ("Name", "Назва"),
    "name_desc": (
        "The device name. Its slug starts every entity id: \"FC660\" gives climate.fc660 and "
        "sensor.fc660_humidity, \"FC660 Bedroom\" gives climate.fc660_bedroom.",
        "Назва пристрою. З неї починається кожен ідентифікатор сутності: «FC660» дає "
        "climate.fc660 і sensor.fc660_humidity, «FC660 Bedroom» — climate.fc660_bedroom."),
    "serial_port": ("Serial port", "Послідовний порт"),
    "baudrate": ("Baud rate", "Швидкість"),
    "slave": ("Modbus address", "Адреса Modbus"),
    "slave_desc": ("Set on the panel (holding register 256); factory default 1.",
                   "Задається на панелі (регістр 256); заводське значення 1."),
    "host": ("Host", "Хост"),
    "port": ("Port", "Порт"),
    "transport": ("Gateway type", "Тип шлюзу"),
    "tcp": ("Modbus TCP gateway (mbusd, …)", "Шлюз Modbus TCP (mbusd, …)"),
    "rtu_over_tcp": ("Transparent serial server (RTU over TCP)",
                     "Прозорий послідовний сервер (RTU через TCP)"),
    "e_cannot": (
        "No answer. Check the host and port or the serial port, the Modbus address, and the "
        "wiring on A/B.",
        "Немає відповіді. Перевірте хост і порт або послідовний порт, адресу Modbus та "
        "підключення на A/B."),
    "e_not": ("Something answered, but not like an FC660 at this address: {reason}.",
              "Щось відповіло, але не як FC660 за цією адресою: {reason}."),
    "e_invalid_name": ("Use a name with at least one letter or digit.",
                       "Назва має містити хоча б одну літеру або цифру."),
    "e_name_in_use": ("Another FC660 already uses the entity id prefix {prefix}. "
                      "Choose another name.",
                      "Інша FC660 вже використовує префікс {prefix}. Оберіть іншу назву."),
    "a_already": ("This panel is already set up.", "Цю панель уже налаштовано."),
    "a_reconf": ("The connection was changed.", "Підключення змінено."),
    "opt_title": ("FC660 options", "Параметри FC660"),
    "opt_desc": (
        "The panel is polled at the shortest of the three read intervals, and each read is "
        "made on the cycle nearest its own, so the other two round to a multiple of it. "
        "After a change from Home Assistant the settings are read back at once.",
        "Панель опитується з найкоротшим із трьох інтервалів читання, і кожне читання "
        "робиться в найближчому до свого інтервалу циклі, тож два інші округлюються до "
        "кратного йому. Після зміни з Home Assistant налаштування зчитуються одразу."),
    "control_interval": ("Read power, mode and setpoint every",
                         "Читати живлення, режим і уставку кожні"),
    "control_interval_desc": (
        "Power, working mode, comfort/away and the setpoint (registers 264-268): what people "
        "change on the panel. One short read; 2 s is fine on a shared bus.",
        "Живлення, режим роботи, комфорт/відсутність і уставка (регістри 264-268): те, що "
        "змінюють на панелі. Одне коротке читання; 2 с — нормально і для спільної шини."),
    "state_interval": ("Read readings and outputs every", "Читати показники й виходи кожні"),
    "state_interval_desc": (
        "Temperature, humidity, TVOC, CO2, the outputs (Y1, Y2, W1, W2, fan, …) and the fault "
        "code (registers 0-14).",
        "Температура, вологість, TVOC, CO2, виходи (Y1, Y2, W1, W2, вентилятор, …) і код "
        "несправності (регістри 0-14)."),
    "settings_interval": ("Read all settings every", "Читати всі налаштування кожні"),
    "settings_interval_desc": (
        "Every setting and the panel clock (registers 256-279). Power, mode and setpoint come "
        "with it, so this read replaces that one when both are due.",
        "Усі налаштування й годинник панелі (регістри 256-279). Живлення, режим і уставка "
        "входять у нього, тож коли обидва читання припадають на один цикл, робиться лише це."),
    "unavailable_after": ("Unavailable after", "Недоступно через"),
    "unavailable_after_desc": (
        "How long reads may fail before the entities show as unavailable. Short stalls on a "
        "shared bus are normal.",
        "Скільки часу читання може не вдаватися, перш ніж сутності стануть недоступними. "
        "Короткі затримки на спільній шині — це норма."),
    "sync_clock": ("Keep the panel clock in sync", "Синхронізувати годинник панелі"),
    "sync_clock_desc": (
        "Set the panel's clock to Home Assistant's time whenever it is more than 2 minutes off "
        "(at most once an hour), daylight saving included. The panel's weekly programme runs on "
        "this clock.",
        "Встановлювати годинник панелі за часом Home Assistant, щойно він відхиляється більш "
        "ніж на 2 хвилини (не частіше ніж раз на годину), з урахуванням літнього часу. За цим "
        "годинником працює тижнева програма панелі."),
    "x_cannot": ("Cannot reach the FC660 at address {slave} on {endpoint}.",
                 "Не вдається зв'язатися з FC660 за адресою {slave} через {endpoint}."),
    "x_not": ("The unit at Modbus address {slave} does not answer like an FC660: {reason}.",
              "Пристрій за адресою Modbus {slave} відповідає не як FC660: {reason}."),
    "x_not_writable": ("{key} cannot be written.", "{key} не можна записати."),
    "x_out_of_range": ("{value} is not a valid {key}: it takes {minimum} to {maximum} in steps "
                       "of {step}.",
                       "{value} — недопустиме значення {key}: від {minimum} до {maximum} з "
                       "кроком {step}."),
    "x_write_refused": ("The FC660 refused {key} = {value} ({error}).",
                        "FC660 відхилила {key} = {value} ({error})."),
    "x_write_failed": ("Could not write {key}: {error}. Nothing was changed on the panel, or "
                       "the next poll will show it.",
                       "Не вдалося записати {key}: {error}. Панель не змінилася, або це покаже "
                       "наступне опитування."),
    "x_not_applied": ("The FC660 accepted {key} but holds {held}, not {wanted}.",
                      "FC660 прийняла {key}, але зберігає {held}, а не {wanted}."),
    "x_clock": ("The panel clock reads {clock} after the sync.",
                "Після синхронізації годинник панелі показує {clock}."),
}


#: The options form's fields, in the order the flow shows them.
OPTIONS = ("control_interval", "state_interval", "settings_interval", "unavailable_after",
           "sync_clock")


def entities(lang: str) -> dict:
    i = 0 if lang == "en" else 1
    out: dict = {}
    for platform, rows in ENTITIES.items():
        out[platform] = {}
        for key, row in rows.items():
            item: dict = {"name": row[i]}
            if len(row) > 2:
                item["state"] = {state: names[i] for state, names in row[2].items()}
            out[platform][key] = item
    return out


def doc(lang: str) -> dict:
    i = 0 if lang == "en" else 1
    t = {k: v[i] for k, v in T.items()}
    serial = {"serial_port": t["serial_port"], "baudrate": t["baudrate"], "slave": t["slave"]}
    network = {"host": t["host"], "port": t["port"], "transport": t["transport"],
               "slave": t["slave"]}
    with_name = {"name": t["name_desc"], "slave": t["slave_desc"]}
    return {
        "config": {
            "step": {
                "user": {"title": t["menu_title"], "description": t["menu_desc"],
                         "menu_options": {"network": t["network"], "serial": t["serial"]}},
                "network": {"title": t["network_title"], "description": t["network_desc"],
                            "data": {"name": t["name"], **network}, "data_description": with_name},
                "serial": {"title": t["serial_title"], "description": t["serial_desc"],
                           "data": {"name": t["name"], **serial}, "data_description": with_name},
                "reconfigure": {"title": t["reconf_title"], "description": t["reconf_desc"],
                                "menu_options": {"reconfigure_network": t["network"],
                                                 "reconfigure_serial": t["serial"]}},
                "reconfigure_network": {"title": t["network_title"],
                                        "description": t["network_desc"], "data": network,
                                        "data_description": {"slave": t["slave_desc"]}},
                "reconfigure_serial": {"title": t["serial_title"], "description": t["serial_desc"],
                                       "data": serial,
                                       "data_description": {"slave": t["slave_desc"]}},
            },
            "error": {"cannot_connect": t["e_cannot"], "not_an_fc660": t["e_not"],
                      "invalid_name": t["e_invalid_name"], "name_in_use": t["e_name_in_use"]},
            "abort": {"already_configured": t["a_already"], "reconfigure_successful": t["a_reconf"]},
        },
        "options": {"step": {"init": {
            "title": t["opt_title"],
            "description": t["opt_desc"],
            "data": {key: t[key] for key in OPTIONS},
            "data_description": {key: t[f"{key}_desc"] for key in OPTIONS}}}},
        "selector": {"framing": {"options": {"tcp": t["tcp"], "rtu_over_tcp": t["rtu_over_tcp"]}}},
        "entity": entities(lang),
        "exceptions": {
            "cannot_connect": {"message": t["x_cannot"]},
            "not_an_fc660": {"message": t["x_not"]},
            "not_writable": {"message": t["x_not_writable"]},
            "out_of_range": {"message": t["x_out_of_range"]},
            "write_refused": {"message": t["x_write_refused"]},
            "write_failed": {"message": t["x_write_failed"]},
            "write_not_applied": {"message": t["x_not_applied"]},
            "clock_not_applied": {"message": t["x_clock"]},
        },
    }


OUTPUTS = (("strings.json", "en"), ("translations/en.json", "en"), ("translations/uk.json", "uk"))


def render(lang: str) -> str:
    return json.dumps(doc(lang), indent=2, ensure_ascii=False) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="fail if a file is stale")
    args = ap.parse_args(argv)
    stale = []
    for name, lang in OUTPUTS:
        path, text = PACKAGE / name, render(lang)
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(name)
            continue
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path.relative_to(ROOT)}")
    if stale:
        print(f"stale: {', '.join(stale)}; run tools/gen_translations.py", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
