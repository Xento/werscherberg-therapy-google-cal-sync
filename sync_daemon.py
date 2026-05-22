#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

STOP = False


def _handle_stop(signum, frame):  # noqa: ANN001
    global STOP
    STOP = True


def bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def positive_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
        if value <= 0:
            raise ValueError
        return value
    except ValueError:
        logging.warning("Ungültiger Wert für %s=%r, verwende %s", name, raw, default)
        return default


def get_timezone() -> ZoneInfo:
    tz_name = os.environ.get("TZ", "Europe/Berlin").strip() or "Europe/Berlin"
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        logging.warning("Unbekannte Zeitzone TZ=%r, verwende Europe/Berlin", tz_name)
        return ZoneInfo("Europe/Berlin")


def parse_schedule_times(raw: str) -> list[dt.time]:
    values = [item.strip() for item in raw.split(",") if item.strip()]
    if not values:
        raise ValueError("SYNC_TIMES ist leer.")
    if len(values) > 4:
        logging.warning("Mehr als vier SYNC_TIMES konfiguriert. Es werden nur die ersten vier genutzt.")
        values = values[:4]

    times: list[dt.time] = []
    for value in values:
        parts = value.split(":")
        if len(parts) not in {2, 3}:
            raise ValueError(f"Ungültige Uhrzeit in SYNC_TIMES: {value!r}. Erwartet HH:MM oder HH:MM:SS.")
        try:
            hour = int(parts[0])
            minute = int(parts[1])
            second = int(parts[2]) if len(parts) == 3 else 0
            parsed = dt.time(hour=hour, minute=minute, second=second)
        except ValueError as exc:
            raise ValueError(f"Ungültige Uhrzeit in SYNC_TIMES: {value!r}") from exc
        if parsed not in times:
            times.append(parsed)

    if not times:
        raise ValueError("Keine gültigen Uhrzeiten in SYNC_TIMES gefunden.")
    times.sort()
    return times


def next_run_after(now: dt.datetime, schedule_times: list[dt.time]) -> dt.datetime:
    for schedule_time in schedule_times:
        candidate = dt.datetime.combine(now.date(), schedule_time, tzinfo=now.tzinfo)
        if candidate > now:
            return candidate
    return dt.datetime.combine(now.date() + dt.timedelta(days=1), schedule_times[0], tzinfo=now.tzinfo)


def run_sync(
    config_file: str,
    verbose: bool,
    *,
    window_start: dt.datetime | None = None,
    window_end: dt.datetime | None = None,
) -> int:
    cmd = [sys.executable, "/app/therapieplan_sync.py", "--config", config_file]
    if verbose:
        cmd.append("--verbose")
    env = os.environ.copy()
    if window_start is not None and window_end is not None and window_end > window_start:
        env["SYNC_WINDOW_START"] = window_start.isoformat()
        env["SYNC_WINDOW_END"] = window_end.isoformat()
        logging.info(
            "Sync-Fenster für Eskalationsmeldungen: %s bis %s",
            window_start.strftime("%Y-%m-%d %H:%M:%S %Z"),
            window_end.strftime("%Y-%m-%d %H:%M:%S %Z"),
        )
    logging.info("Starte Sync: %s", " ".join(cmd))
    completed = subprocess.run(cmd, check=False, env=env)
    logging.info("Sync beendet mit Exitcode %s", completed.returncode)
    return completed.returncode


def sleep_until(target: dt.datetime) -> None:
    while not STOP:
        now = dt.datetime.now(target.tzinfo)
        seconds = int((target - now).total_seconds())
        if seconds <= 0:
            return
        time.sleep(min(seconds, 60))


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    config_file = os.environ.get("CONFIG_FILE", "/app/data/config.yaml")
    schedule_raw = os.environ.get("SYNC_TIMES", "06:00,12:00,18:00,22:00")
    run_once = bool_env("RUN_ONCE", False)
    run_on_start = bool_env("RUN_ON_START", False)
    verbose = bool_env("VERBOSE", False)
    tz = get_timezone()

    if not Path(config_file).exists():
        logging.error("Config-Datei fehlt: %s", config_file)
        return 1

    try:
        schedule_times = parse_schedule_times(schedule_raw)
    except ValueError as exc:
        logging.error("Zeitplan ungültig: %s", exc)
        return 1

    logging.info("Konfigurierte Sync-Uhrzeiten (%s): %s", tz.key, ", ".join(t.strftime("%H:%M:%S") for t in schedule_times))

    last_exit = 0
    if run_once:
        now = dt.datetime.now(tz)
        return run_sync(config_file, verbose, window_start=now, window_end=next_run_after(now, schedule_times))

    if run_on_start:
        now = dt.datetime.now(tz)
        last_exit = run_sync(config_file, verbose, window_start=now, window_end=next_run_after(now, schedule_times))

    while not STOP:
        next_run = next_run_after(dt.datetime.now(tz), schedule_times)
        logging.info("Nächster Sync: %s", next_run.strftime("%Y-%m-%d %H:%M:%S %Z"))
        sleep_until(next_run)
        if STOP:
            break
        window_start = next_run
        window_end = next_run_after(next_run + dt.timedelta(seconds=1), schedule_times)
        last_exit = run_sync(config_file, verbose, window_start=window_start, window_end=window_end)

    logging.info("Container wird beendet.")
    return last_exit if last_exit in {0, 2} else 0


if __name__ == "__main__":
    raise SystemExit(main())
