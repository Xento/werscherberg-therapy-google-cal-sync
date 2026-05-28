#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import signal
import subprocess
import sys

import yaml
import time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

STOP = False

_MISSING = object()


def _config_value(mapping: dict[str, Any], key: str, default: Any = None) -> Any:
    if isinstance(mapping, dict) and key in mapping:
        return mapping.get(key)
    return default


def _env_value(name: str, default: Any = _MISSING) -> Any:
    value = os.environ.get(name)
    if value is None:
        if default is _MISSING:
            return None
        return default
    return value


def _bool_value(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _int_value(value: Any, default: int, *, minimum: int | None = None) -> int:
    if value is None or str(value).strip() == "":
        return default
    try:
        result = int(value)
    except (TypeError, ValueError):
        return default
    if minimum is not None and result < minimum:
        return default
    return result


def _read_yaml_file(path: Path) -> dict[str, Any]:
    try:
        if not path.exists():
            return {}
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except Exception as exc:  # noqa: BLE001
        logging.warning("Config-Datei konnte nicht gelesen werden: %s (%s)", path, exc)
        return {}


def _runtime_settings(config_file: str) -> dict[str, Any]:
    """Load scheduler/runtime settings.

    New config model:
      - scheduler.* in config.yaml is the primary source for scheduler/retry behavior.
      - .env remains for technical container values, secrets, and backward compatibility.
    """
    data = _read_yaml_file(Path(config_file))
    scheduler = data.get("scheduler") or {}
    if not isinstance(scheduler, dict):
        scheduler = {}
    retry = scheduler.get("retry") or {}
    if not isinstance(retry, dict):
        retry = {}

    raw_times = _config_value(scheduler, "sync_times")
    if raw_times is None:
        raw_times = _env_value("SYNC_TIMES", "07:30,10:00,12:00,18:00")
    if isinstance(raw_times, (list, tuple)):
        schedule_raw = ",".join(str(item).strip() for item in raw_times if str(item).strip())
    else:
        schedule_raw = str(raw_times or "").strip()

    # Environment values are retained as fallback only when scheduler.* is absent.
    run_on_start = _bool_value(_config_value(scheduler, "run_on_start", _env_value("RUN_ON_START")), False)
    retry_enabled = _bool_value(_config_value(retry, "enabled", _env_value("SYNC_RETRY_ENABLED")), True)
    retry_max_attempts = _int_value(_config_value(retry, "max_attempts", _env_value("SYNC_RETRY_MAX_ATTEMPTS")), 3, minimum=0)
    retry_delay_seconds = _int_value(_config_value(retry, "delay_seconds", _env_value("SYNC_RETRY_DELAY_SECONDS")), 300, minimum=1)
    retry_when_no_changes = _bool_value(_config_value(retry, "when_no_changes", _env_value("SYNC_RETRY_WHEN_NO_CHANGES")), True)
    retry_when_errors = _bool_value(_config_value(retry, "when_errors", _env_value("SYNC_RETRY_WHEN_ERRORS")), True)
    stats_file_raw = _config_value(retry, "stats_file", _env_value("SYNC_STATS_FILE", "/app/data/last_sync_stats.json"))
    stats_file = Path(str(stats_file_raw))
    if not stats_file.is_absolute():
        stats_file = Path(config_file).resolve().parent / stats_file

    return {
        "schedule_raw": schedule_raw,
        "run_on_start": run_on_start,
        "retry_enabled": retry_enabled,
        "retry_max_attempts": retry_max_attempts,
        "retry_delay_seconds": retry_delay_seconds,
        "retry_when_no_changes": retry_when_no_changes,
        "retry_when_errors": retry_when_errors,
        "stats_file": stats_file,
    }



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


def non_negative_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
        if value < 0:
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


def _read_json_file(path: Path) -> dict[str, Any] | None:
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception as exc:  # noqa: BLE001
        logging.warning("Stats-Datei konnte nicht gelesen werden: %s (%s)", path, exc)
    return None


def _change_count(stats: dict[str, Any] | None) -> int:
    if not stats:
        return 0
    return int(stats.get("created", 0) or 0) + int(stats.get("updated", 0) or 0) + int(stats.get("deleted", 0) or 0)


def _error_count(stats: dict[str, Any] | None, exit_code: int) -> int:
    if stats:
        return int(stats.get("errors", 0) or 0)
    return 1 if exit_code != 0 else 0


def _format_retry_reason(exit_code: int, stats: dict[str, Any] | None, *, retry_when_no_changes: bool, retry_when_errors: bool) -> str | None:
    errors = _error_count(stats, exit_code)
    changes = _change_count(stats)
    if retry_when_errors and (exit_code != 0 or errors > 0):
        return f"Fehler erkannt (Exitcode={exit_code}, errors={errors})"
    if retry_when_no_changes and errors == 0 and changes == 0:
        unchanged = int(stats.get("unchanged", 0) or 0) if stats else 0
        return f"keine Kalenderänderungen erkannt (unchanged={unchanged})"
    return None


def run_sync(
    config_file: str,
    verbose: bool,
    *,
    window_start: dt.datetime | None = None,
    window_end: dt.datetime | None = None,
    stats_file: Path | None = None,
    retry_attempt: int = 0,
    suppress_no_change_notification: bool = False,
) -> tuple[int, dict[str, Any] | None]:
    cmd = [sys.executable, "/app/therapieplan_sync.py", "--config", config_file]
    if verbose:
        cmd.append("--verbose")
    if stats_file is not None:
        try:
            stats_file.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
        cmd.extend(["--stats-file", str(stats_file)])

    env = os.environ.copy()
    if retry_attempt > 0:
        env["SYNC_IS_RETRY"] = "1"
        env["SYNC_RETRY_ATTEMPT"] = str(retry_attempt)
    else:
        env.pop("SYNC_IS_RETRY", None)
        env.pop("SYNC_RETRY_ATTEMPT", None)

    if suppress_no_change_notification:
        env["SYNC_SUPPRESS_NO_CHANGE_NOTIFICATION"] = "1"
    else:
        env.pop("SYNC_SUPPRESS_NO_CHANGE_NOTIFICATION", None)

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
    stats = _read_json_file(stats_file) if stats_file is not None else None
    if stats:
        logging.info(
            "Sync-Statistik: created=%s updated=%s deleted=%s unchanged=%s errors=%s",
            stats.get("created", 0),
            stats.get("updated", 0),
            stats.get("deleted", 0),
            stats.get("unchanged", 0),
            stats.get("errors", 0),
        )
    logging.info("Sync beendet mit Exitcode %s", completed.returncode)
    return completed.returncode, stats


def sleep_seconds(seconds: int) -> None:
    end = time.monotonic() + seconds
    while not STOP:
        remaining = int(end - time.monotonic())
        if remaining <= 0:
            return
        time.sleep(min(remaining, 60))


def sleep_until(target: dt.datetime) -> None:
    while not STOP:
        now = dt.datetime.now(target.tzinfo)
        seconds = int((target - now).total_seconds())
        if seconds <= 0:
            return
        time.sleep(min(seconds, 60))


def run_sync_with_retries(
    config_file: str,
    verbose: bool,
    *,
    window_start: dt.datetime,
    window_end: dt.datetime,
    stats_file: Path,
    retry_enabled: bool,
    retry_max_attempts: int,
    retry_delay_seconds: int,
    retry_when_no_changes: bool,
    retry_when_errors: bool,
) -> int:
    attempts_total = 1 + (retry_max_attempts if retry_enabled else 0)
    last_exit = 0
    last_stats: dict[str, Any] | None = None

    for attempt in range(1, attempts_total + 1):
        if attempt == 1:
            logging.info("Starte geplanten Sync-Lauf.")
        else:
            logging.info("Starte Sync-Neuversuch %s/%s.", attempt - 1, retry_max_attempts)

        last_exit, last_stats = run_sync(
            config_file,
            verbose,
            window_start=window_start,
            window_end=window_end,
            stats_file=stats_file,
            retry_attempt=attempt - 1,
            suppress_no_change_notification=(attempt > 1),
        )

        reason = _format_retry_reason(
            last_exit,
            last_stats,
            retry_when_no_changes=retry_when_no_changes,
            retry_when_errors=retry_when_errors,
        )
        if not retry_enabled or reason is None:
            return last_exit

        if attempt >= attempts_total:
            logging.info("Keine weiteren Neuversuche. Letzter Grund: %s", reason)
            return last_exit

        logging.info(
            "Neuversuch geplant in %s Sekunden: %s",
            retry_delay_seconds,
            reason,
        )
        sleep_seconds(retry_delay_seconds)
        if STOP:
            return last_exit

    return last_exit


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    config_file = os.environ.get("CONFIG_FILE", "/app/data/config.yaml")
    runtime = _runtime_settings(config_file)
    schedule_raw = runtime["schedule_raw"]
    run_once = bool_env("RUN_ONCE", False)
    run_on_start = bool(runtime["run_on_start"])
    verbose = bool_env("VERBOSE", False)
    tz = get_timezone()

    retry_enabled = bool(runtime["retry_enabled"])
    retry_max_attempts = int(runtime["retry_max_attempts"])
    retry_delay_seconds = int(runtime["retry_delay_seconds"])
    retry_when_no_changes = bool(runtime["retry_when_no_changes"])
    retry_when_errors = bool(runtime["retry_when_errors"])
    stats_file = runtime["stats_file"]

    if not Path(config_file).exists():
        logging.error("Config-Datei fehlt: %s", config_file)
        return 1

    try:
        schedule_times = parse_schedule_times(schedule_raw)
    except ValueError as exc:
        logging.error("Zeitplan ungültig: %s", exc)
        return 1

    logging.info("Konfigurierte Sync-Uhrzeiten (%s): %s", tz.key, ", ".join(t.strftime("%H:%M:%S") for t in schedule_times))
    logging.info(
        "Sync-Neuversuche: enabled=%s max=%s delay=%ss when_no_changes=%s when_errors=%s",
        retry_enabled,
        retry_max_attempts,
        retry_delay_seconds,
        retry_when_no_changes,
        retry_when_errors,
    )

    last_exit = 0
    if run_once:
        now = dt.datetime.now(tz)
        exit_code, _stats = run_sync(config_file, verbose, window_start=now, window_end=next_run_after(now, schedule_times), stats_file=stats_file)
        return exit_code

    if run_on_start:
        now = dt.datetime.now(tz)
        last_exit, _stats = run_sync(config_file, verbose, window_start=now, window_end=next_run_after(now, schedule_times), stats_file=stats_file)

    while not STOP:
        next_run = next_run_after(dt.datetime.now(tz), schedule_times)
        logging.info("Nächster Sync: %s", next_run.strftime("%Y-%m-%d %H:%M:%S %Z"))
        sleep_until(next_run)
        if STOP:
            break
        window_start = next_run
        window_end = next_run_after(next_run + dt.timedelta(seconds=1), schedule_times)
        last_exit = run_sync_with_retries(
            config_file,
            verbose,
            window_start=window_start,
            window_end=window_end,
            stats_file=stats_file,
            retry_enabled=retry_enabled,
            retry_max_attempts=retry_max_attempts,
            retry_delay_seconds=retry_delay_seconds,
            retry_when_no_changes=retry_when_no_changes,
            retry_when_errors=retry_when_errors,
        )

    logging.info("Container wird beendet.")
    return last_exit if last_exit in {0, 2} else 0


if __name__ == "__main__":
    raise SystemExit(main())
