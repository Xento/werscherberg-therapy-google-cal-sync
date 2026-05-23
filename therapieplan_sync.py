#!/usr/bin/env python3
"""
Therapieplan -> Google Calendar Sync

Liest den Therapieplan über die von der Web-App genutzte JSON-Schnittstelle aus
und synchronisiert Termine in einen Google Kalender.

Wichtige Eigenschaften:
- läuft headless unter Linux, sobald Google OAuth einmalig autorisiert wurde
- speichert nur Access-Token der Therapieplan-Webseite und Google Refresh-Token lokal
- aktualisiert Termine bei geänderten Inhalten
- löscht zukünftige Termine, die nicht mehr im Therapieplan enthalten sind
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import json
import logging
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

import requests
import yaml
from dateutil import parser as date_parser
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
SYNC_VERSION = "1.4"
SUPPORTED_FORMS = {"V", "A", "E", "C", "G"}
HIDDEN_FLAG = 0x20000000


@dataclasses.dataclass(frozen=True)
class TherapyConfig:
    plan_id: str
    display_name: str
    source_name: str
    event_prefix: Optional[str]
    color_id: str
    calendar_ids: Tuple[str, ...]
    reminder_minutes: Optional[int]
    reminder_method: Optional[str]
    url: str
    birth_date: str
    access_token: str
    request_timeout_seconds: int
    verify_tls: bool
    user_agent: str


@dataclasses.dataclass(frozen=True)
class GoogleConfig:
    credentials_file: Path
    token_file: Path
    calendar_id: str
    calendar_ids: Tuple[str, ...]
    timezone: str


@dataclasses.dataclass(frozen=True)
class SyncConfig:
    state_file: Path
    source_name: str
    event_prefix: str
    include_past_days: int
    delete_missing_future: bool
    dry_run: bool
    include_details_in_description: bool
    visibility: str
    transparency: str
    reminders: Dict[str, Any]
    reminder_minutes: Optional[int]
    reminder_method: str


@dataclasses.dataclass(frozen=True)
class NotificationConfig:
    enabled: bool
    notify_on_changes: bool
    notify_on_errors: bool
    notify_on_success_no_changes: bool
    include_change_details: bool
    max_change_items: int
    max_message_chars: int
    title_prefix: str
    intense_same_day_changes: bool
    intense_next_sync_window_changes: bool
    # Drei Pushover-Eskalationsstufen für Terminänderungen:
    # 0 = Änderungen für spätere Tage, 1 = Änderungen am gleichen Tag,
    # 2 = Änderungen im nächsten Abschnitt zwischen zwei Sync-Zeitpunkten.
    level0_priority: int
    level0_sound: str
    level0_retry: int
    level0_expire: int
    level1_priority: int
    level1_sound: str
    level1_retry: int
    level1_expire: int
    level2_priority: int
    level2_sound: str
    level2_retry: int
    level2_expire: int
    # Legacy aliases retained for older configs/env files.
    intense_priority: int
    intense_sound: str
    intense_retry: int
    intense_expire: int
    intense_same_day_priority: int
    intense_same_day_sound: str
    intense_same_day_retry: int
    intense_same_day_expire: int
    pushover: Dict[str, Any]
    homeassistant: Dict[str, Any]


@dataclasses.dataclass(frozen=True)
class AppConfig:
    therapy: TherapyConfig
    plans: Tuple[TherapyConfig, ...]
    google: GoogleConfig
    sync: SyncConfig
    notifications: NotificationConfig
    base_dir: Path


@dataclasses.dataclass(frozen=True)
class CalendarEventCandidate:
    source_key: str
    source_signature: str
    google_body: Dict[str, Any]
    begin: dt.datetime
    end: dt.datetime


def load_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config ist kein YAML-Objekt: {path}")
    return data


def resolve_path(base_dir: Path, value: str) -> Path:
    p = Path(value).expanduser()
    return p if p.is_absolute() else base_dir / p


def env_or_config(env_name: str, mapping: Dict[str, Any], key: str, default: Any = "") -> Any:
    value = os.environ.get(env_name)
    if value is not None:
        return value
    return mapping.get(key, default)


def env_or_config_multi(env_names: Iterable[str], mapping: Dict[str, Any], keys: Iterable[str], default: Any = "") -> Any:
    for env_name in env_names:
        value = os.environ.get(env_name)
        if value is not None:
            return value
    for key in keys:
        if key in mapping:
            return mapping.get(key)
    return default


def env_bool_or_config(env_name: str, mapping: Dict[str, Any], key: str, default: bool = False) -> bool:
    value = os.environ.get(env_name)
    if value is not None:
        return str(value).strip().lower() in {"1", "true", "yes", "on"}
    return bool(mapping.get(key, default))


def slugify_plan_id(value: str, fallback: str) -> str:
    raw = (value or fallback or "plan").strip().lower()
    slug = re.sub(r"[^a-z0-9_.-]+", "-", raw)
    slug = slug.strip("-_.")
    return slug or fallback or "plan"


COLOR_NAME_MAP = {
    # Google Calendar event color IDs. Die Namen entsprechen weitgehend den Google-Farbnamen.
    "lavender": "1",
    "lavendel": "1",
    "sage": "2",
    "salbei": "2",
    "grape": "3",
    "traube": "3",
    "flamingo": "4",
    "banana": "5",
    "banane": "5",
    "tangerine": "6",
    "orange": "6",
    "peacock": "7",
    "pfau": "7",
    "graphite": "8",
    "graphit": "8",
    "blueberry": "9",
    "blaubeere": "9",
    "basil": "10",
    "basilikum": "10",
    "tomato": "11",
    "tomate": "11",
}


def normalize_color_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.isdigit() and 1 <= int(text) <= 11:
        return text
    mapped = COLOR_NAME_MAP.get(text.lower())
    if mapped:
        return mapped
    raise ValueError(
        f"Ungültige Event-Farbe '{text}'. Zulässig sind Google Calendar color_id 1 bis 11 "
        "oder Namen wie lavender, sage, grape, flamingo, banana, tangerine, peacock, graphite, blueberry, basil, tomato."
    )




def normalize_calendar_ids(value: Any, *, default: Optional[Iterable[str]] = None) -> Tuple[str, ...]:
    """Normalisiert Kalender-Konfiguration.

    Unterstützt:
    - calendar_id: "primary"
    - calendar_ids: ["primary", "abc@group.calendar.google.com"]
    - calendar_ids: "primary,abc@group.calendar.google.com"
    """
    raw_items: List[Any]
    if value is None:
        raw_items = list(default or [])
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        text = str(value or "").strip()
        if not text:
            raw_items = list(default or [])
        else:
            raw_items = [part.strip() for part in text.split(",")]

    result: List[str] = []
    seen: set[str] = set()
    for item in raw_items:
        calendar_id = str(item or "").strip()
        if not calendar_id:
            continue
        if calendar_id not in seen:
            result.append(calendar_id)
            seen.add(calendar_id)
    return tuple(result)


def first_calendar_id(calendar_ids: Tuple[str, ...]) -> str:
    return calendar_ids[0] if calendar_ids else "primary"

def parse_optional_int(value: Any, *, field_name: str) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"", "none", "null", "default", "calendar_default", "calendar-default"}:
            return None
        value = text
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} muss eine ganze Zahl in Minuten sein oder leer bleiben.") from exc
    if parsed < 0 or parsed > 40320:
        raise ValueError(f"{field_name} muss zwischen 0 und 40320 Minuten liegen.")
    return parsed


def parse_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "ja"}:
        return True
    if text in {"0", "false", "no", "off", "nein"}:
        return False
    return default


def normalize_reminder_method(value: Any, *, default: str = "popup") -> str:
    method = str(value or default).strip().lower()
    if method not in {"popup", "email"}:
        raise ValueError("reminder_method muss 'popup' oder 'email' sein.")
    return method


def normalize_reminders(value: Any) -> Dict[str, Any]:
    """Normalisiert YAML-Schreibweise auf das Google-Calendar-API-Format.

    Unterstützt sowohl die ältere snake_case-Konfiguration:
      use_default: true
    als auch das direkte Google-Format:
      useDefault: true
    """
    if value is None or value == "":
        return {"useDefault": True}
    if not isinstance(value, dict):
        raise ValueError("sync.reminders muss ein YAML-Objekt sein.")

    use_default_raw = value.get("useDefault", value.get("use_default", True))
    use_default = parse_bool(use_default_raw, default=True)
    result: Dict[str, Any] = {"useDefault": use_default}

    if use_default:
        return result

    overrides_raw = value.get("overrides") or []
    if not isinstance(overrides_raw, list):
        raise ValueError("sync.reminders.overrides muss eine Liste sein.")

    overrides: List[Dict[str, Any]] = []
    for index, item in enumerate(overrides_raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"sync.reminders.overrides[{index}] muss ein YAML-Objekt sein.")
        method = normalize_reminder_method(item.get("method", "popup"), default="popup")
        minutes = parse_optional_int(item.get("minutes"), field_name=f"sync.reminders.overrides[{index}].minutes")
        if minutes is None:
            raise ValueError(f"sync.reminders.overrides[{index}].minutes darf nicht leer sein.")
        overrides.append({"method": method, "minutes": minutes})

    result["overrides"] = overrides
    return result


def effective_reminders(cfg: "AppConfig") -> Dict[str, Any]:
    minutes = cfg.therapy.reminder_minutes if cfg.therapy.reminder_minutes is not None else cfg.sync.reminder_minutes
    if minutes is None:
        return cfg.sync.reminders
    method = cfg.therapy.reminder_method or cfg.sync.reminder_method
    return {"useDefault": False, "overrides": [{"method": normalize_reminder_method(method), "minutes": minutes}]}


def _merged_plan_mapping(base_therapy: Dict[str, Any], item: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base_therapy)
    for key, value in item.items():
        if value is not None:
            merged[key] = value
    return merged


def build_therapy_sources(data: Dict[str, Any], base_source_name: str) -> Tuple[TherapyConfig, ...]:
    base_therapy = data.get("therapy") or {}
    raw_plans = data.get("therapy_plans")
    env_birth_date = os.environ.get("THERAPIEPLAN_BIRTH_DATE")
    env_access_token = os.environ.get("THERAPIEPLAN_ACCESS_TOKEN")

    if raw_plans is None:
        # Rückwärtskompatible Einzelplan-Konfiguration.
        raw_plans = [base_therapy]
    if not isinstance(raw_plans, list) or not raw_plans:
        raise ValueError("therapy_plans muss eine nicht-leere Liste sein oder legacy therapy.url muss gesetzt sein.")

    sources: List[TherapyConfig] = []
    seen_ids: set[str] = set()
    multi_plan = len(raw_plans) > 1 or "therapy_plans" in data

    for index, item in enumerate(raw_plans, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"therapy_plans[{index}] ist kein YAML-Objekt.")
        merged = _merged_plan_mapping(base_therapy, item)

        display_name = str(merged.get("name") or merged.get("display_name") or f"Therapieplan {index}").strip()
        requested_id = str(merged.get("id") or merged.get("plan_id") or display_name or f"plan{index}")
        plan_id = slugify_plan_id(requested_id, f"plan{index}")
        original_plan_id = plan_id
        suffix = 2
        while plan_id in seen_ids:
            plan_id = f"{original_plan_id}-{suffix}"
            suffix += 1
        seen_ids.add(plan_id)

        # Env-Overrides werden nur bei der legacy Einzelplan-Konfiguration angewendet.
        birth_date = merged.get("birth_date", "")
        access_token = merged.get("access_token", "")
        if not multi_plan:
            if env_birth_date is not None:
                birth_date = env_birth_date
            if env_access_token is not None:
                access_token = env_access_token

        source_name = str(merged.get("source_name") or f"{base_source_name}:{plan_id}" if multi_plan else base_source_name)
        event_prefix = merged.get("event_prefix", None)
        if event_prefix is not None:
            event_prefix = str(event_prefix)

        source = TherapyConfig(
            plan_id=plan_id,
            display_name=display_name,
            source_name=source_name,
            event_prefix=event_prefix,
            color_id=normalize_color_id(merged.get("color_id", merged.get("color", ""))),
            calendar_ids=normalize_calendar_ids(merged.get("calendar_ids", merged.get("calendar_id", None))),
            reminder_minutes=parse_optional_int(merged.get("reminder_minutes"), field_name=f"therapy_plans[{index}].reminder_minutes"),
            reminder_method=normalize_reminder_method(merged.get("reminder_method"), default="popup") if merged.get("reminder_method") not in (None, "") else None,
            url=str(merged.get("url", "")).strip(),
            birth_date=str(birth_date or "").strip(),
            access_token=str(access_token or "").strip(),
            request_timeout_seconds=int(merged.get("request_timeout_seconds", 30)),
            verify_tls=bool(merged.get("verify_tls", True)),
            user_agent=str(merged.get("user_agent", "therapieplan-calendar-sync/1.2")),
        )
        if not source.url.startswith("http"):
            raise ValueError(f"therapy_plans[{index}].url fehlt oder ist ungültig.")
        if not source.url.endswith("/"):
            raise ValueError(f"therapy_plans[{index}].url muss mit / enden, da die Web-App POST auf dieselbe URL macht.")
        sources.append(source)

    return tuple(sources)


def load_config(path: Path) -> AppConfig:
    base_dir = path.resolve().parent
    data = load_yaml(path)

    google = data.get("google") or {}
    sync = data.get("sync") or {}
    notifications = data.get("notifications") or {}
    notify_on = notifications.get("notify_on") or {}
    providers = notifications.get("providers") or {}
    pushover = providers.get("pushover") or {}
    homeassistant = providers.get("homeassistant") or {}
    pushover_levels = notifications.get("pushover_levels") or notifications.get("levels") or {}
    if not isinstance(pushover_levels, dict):
        pushover_levels = {}

    po_priority = int(env_or_config("PUSHOVER_PRIORITY", pushover, "priority", 0) or 0)
    po_sound = str(env_or_config("PUSHOVER_SOUND", pushover, "sound", "") or "").strip()

    def level_mapping(*names: str) -> Dict[str, Any]:
        for name in names:
            value = pushover_levels.get(name)
            if isinstance(value, dict):
                return value
        return {}

    level0_map = level_mapping("level0", "level0_future", "future", "normal")
    level1_map = level_mapping("level1", "level1_same_day", "same_day", "today")
    level2_map = level_mapping("level2", "level2_next_window", "next_window", "emergency")

    def level_value(env_names: Iterable[str], mapping: Dict[str, Any], keys: Iterable[str], default: Any) -> Any:
        return env_or_config_multi(env_names, mapping, keys, default)

    level0_priority = int(level_value(("PUSHOVER_LEVEL0_PRIORITY",), level0_map, ("priority",), po_priority) or 0)
    level0_sound = str(level_value(("PUSHOVER_LEVEL0_SOUND",), level0_map, ("sound",), po_sound) or "").strip()
    level0_retry = int(level_value(("PUSHOVER_LEVEL0_RETRY",), level0_map, ("retry",), 60) or 60)
    level0_expire = int(level_value(("PUSHOVER_LEVEL0_EXPIRE",), level0_map, ("expire",), 1800) or 1800)

    level1_priority = int(level_value(("PUSHOVER_LEVEL1_PRIORITY", "PUSHOVER_SAME_DAY_PRIORITY"), level1_map, ("priority", "same_day_priority"), notifications.get("intense_same_day_priority", 1)) or 1)
    level1_sound = str(level_value(("PUSHOVER_LEVEL1_SOUND", "PUSHOVER_SAME_DAY_SOUND"), level1_map, ("sound", "same_day_sound"), notifications.get("intense_same_day_sound", "persistent")) or "").strip()
    level1_retry = int(level_value(("PUSHOVER_LEVEL1_RETRY", "PUSHOVER_SAME_DAY_RETRY"), level1_map, ("retry", "same_day_retry"), notifications.get("intense_same_day_retry", 60)) or 60)
    level1_expire = int(level_value(("PUSHOVER_LEVEL1_EXPIRE", "PUSHOVER_SAME_DAY_EXPIRE"), level1_map, ("expire", "same_day_expire"), notifications.get("intense_same_day_expire", 1800)) or 1800)

    level2_priority = int(level_value(("PUSHOVER_LEVEL2_PRIORITY", "PUSHOVER_INTENSE_PRIORITY"), level2_map, ("priority", "intense_priority"), notifications.get("intense_priority", 2)) or 2)
    level2_sound = str(level_value(("PUSHOVER_LEVEL2_SOUND", "PUSHOVER_INTENSE_SOUND"), level2_map, ("sound", "intense_sound"), notifications.get("intense_sound", "persistent")) or "").strip()
    level2_retry = int(level_value(("PUSHOVER_LEVEL2_RETRY", "PUSHOVER_INTENSE_RETRY"), level2_map, ("retry", "intense_retry"), notifications.get("intense_retry", 60)) or 60)
    level2_expire = int(level_value(("PUSHOVER_LEVEL2_EXPIRE", "PUSHOVER_INTENSE_EXPIRE"), level2_map, ("expire", "intense_expire"), notifications.get("intense_expire", 1800)) or 1800)

    base_source_name = str(sync.get("source_name", "therapieplan-sync"))
    plans = build_therapy_sources(data, base_source_name)
    google_calendar_ids = normalize_calendar_ids(google.get("calendar_ids", google.get("calendar_id", "primary")), default=("primary",))

    cfg = AppConfig(
        base_dir=base_dir,
        therapy=plans[0],
        plans=plans,
        google=GoogleConfig(
            credentials_file=resolve_path(base_dir, str(google.get("credentials_file", "credentials.json"))),
            token_file=resolve_path(base_dir, str(google.get("token_file", "token.json"))),
            calendar_id=first_calendar_id(google_calendar_ids),
            calendar_ids=google_calendar_ids,
            timezone=str(google.get("timezone", "Europe/Berlin")),
        ),
        sync=SyncConfig(
            state_file=resolve_path(base_dir, str(sync.get("state_file", "state.json"))),
            source_name=base_source_name,
            event_prefix=str(sync.get("event_prefix", "Therapie: ")),
            include_past_days=int(sync.get("include_past_days", 0)),
            delete_missing_future=bool(sync.get("delete_missing_future", True)),
            dry_run=bool(sync.get("dry_run", False)),
            include_details_in_description=bool(sync.get("include_details_in_description", True)),
            visibility=str(sync.get("visibility", "private")),
            transparency=str(sync.get("transparency", "opaque")),
            reminders=normalize_reminders(sync.get("reminders", {"use_default": True, "overrides": []})),
            reminder_minutes=parse_optional_int(sync.get("reminder_minutes"), field_name="sync.reminder_minutes"),
            reminder_method=normalize_reminder_method(sync.get("reminder_method", "popup"), default="popup"),
        ),
        notifications=NotificationConfig(
            enabled=env_bool_or_config("NOTIFICATIONS_ENABLED", notifications, "enabled", False),
            notify_on_changes=env_bool_or_config("NOTIFY_ON_CHANGES", notify_on, "changes", True),
            notify_on_errors=env_bool_or_config("NOTIFY_ON_ERRORS", notify_on, "errors", True),
            notify_on_success_no_changes=env_bool_or_config("NOTIFY_ON_SUCCESS_NO_CHANGES", notify_on, "success_no_changes", False),
            include_change_details=env_bool_or_config("NOTIFY_INCLUDE_CHANGE_DETAILS", notifications, "include_change_details", True),
            max_change_items=int(env_or_config("NOTIFY_MAX_CHANGE_ITEMS", notifications, "max_change_items", 12) or 12),
            max_message_chars=int(env_or_config("NOTIFY_MAX_MESSAGE_CHARS", notifications, "max_message_chars", 950) or 950),
            title_prefix=str(env_or_config("NOTIFICATION_TITLE_PREFIX", notifications, "title_prefix", "Therapieplan")),
            intense_same_day_changes=env_bool_or_config("NOTIFY_INTENSE_SAME_DAY_CHANGES", notifications, "intense_same_day_changes", True),
            intense_next_sync_window_changes=env_bool_or_config("NOTIFY_INTENSE_NEXT_SYNC_WINDOW_CHANGES", notifications, "intense_next_sync_window_changes", True),
            level0_priority=level0_priority,
            level0_sound=level0_sound,
            level0_retry=level0_retry,
            level0_expire=level0_expire,
            level1_priority=level1_priority,
            level1_sound=level1_sound,
            level1_retry=level1_retry,
            level1_expire=level1_expire,
            level2_priority=level2_priority,
            level2_sound=level2_sound,
            level2_retry=level2_retry,
            level2_expire=level2_expire,
            intense_priority=level2_priority,
            intense_sound=level2_sound,
            intense_retry=level2_retry,
            intense_expire=level2_expire,
            intense_same_day_priority=level1_priority,
            intense_same_day_sound=level1_sound,
            intense_same_day_retry=level1_retry,
            intense_same_day_expire=level1_expire,
            pushover={
                "enabled": env_bool_or_config("PUSHOVER_ENABLED", pushover, "enabled", False),
                "token": str(env_or_config("PUSHOVER_TOKEN", pushover, "token", "")).strip(),
                "user": str(env_or_config("PUSHOVER_USER", pushover, "user", "")).strip(),
                "device": str(env_or_config("PUSHOVER_DEVICE", pushover, "device", "")).strip(),
                "priority": po_priority,
                "sound": po_sound,
            },
            homeassistant={
                "enabled": env_bool_or_config("HOMEASSISTANT_ENABLED", homeassistant, "enabled", False),
                "url": str(env_or_config("HOMEASSISTANT_URL", homeassistant, "url", "")).rstrip("/"),
                "token": str(env_or_config("HOMEASSISTANT_TOKEN", homeassistant, "token", "")).strip(),
                "notify_service": str(env_or_config("HOMEASSISTANT_NOTIFY_SERVICE", homeassistant, "notify_service", "")).strip(),
            },
        ),
    )

    if cfg.sync.visibility not in {"default", "public", "private", "confidential"}:
        raise ValueError("sync.visibility muss default, public, private oder confidential sein.")
    if cfg.sync.transparency not in {"opaque", "transparent"}:
        raise ValueError("sync.transparency muss opaque oder transparent sein.")
    return cfg

def read_json_file(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logging.warning("Konnte JSON-Datei nicht lesen: %s: %s", path, exc)
    return default


def write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
    finally:
        try:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        except OSError:
            pass


def therapy_password_hash(value: str) -> str:
    """Implementiert exakt die Hash-Funktion aus script.js der Webseite."""
    a = 0
    b = 0
    for ch in value:
        c = b
        b = a
        a = ((c % 509) + 1) * 127 + ord(ch)
    if b >= 32768:
        b -= 65536
    return str(b * 65536 + a)


class TherapyPlanError(RuntimeError):
    pass


class TherapyPlanClient:
    def __init__(self, cfg: AppConfig, state: Dict[str, Any]) -> None:
        self.cfg = cfg
        self.state = state
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Content-Type": "application/json; charset=UTF-8",
                "Accept": "application/json",
                "User-Agent": cfg.therapy.user_agent,
            }
        )

    def _plan_state(self) -> Dict[str, Any]:
        plans_state = self.state.setdefault("therapy_plans", {})
        if not isinstance(plans_state, dict):
            plans_state = {}
            self.state["therapy_plans"] = plans_state
        plan_state = plans_state.setdefault(self.cfg.therapy.plan_id, {})
        if not isinstance(plan_state, dict):
            plan_state = {}
            plans_state[self.cfg.therapy.plan_id] = plan_state
        return plan_state

    def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        logging.debug("Therapieplan request: %s", {k: ("***" if "token" in k.lower() else v) for k, v in payload.items()})
        response = self.session.post(
            self.cfg.therapy.url,
            json=payload,
            timeout=self.cfg.therapy.request_timeout_seconds,
            verify=self.cfg.therapy.verify_tls,
        )
        response.raise_for_status()
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise TherapyPlanError(f"Antwort ist kein JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise TherapyPlanError("Antwort ist kein JSON-Objekt.")
        return data

    def _get_access_token(self, force_login: bool = False) -> str:
        plan_state = self._plan_state()
        legacy_token = self.state.get("therapy_access_token", "") if self.cfg.therapy.plan_id in {"therapieplan-1", "plan1", "therapieplan-sync"} else ""
        token = "" if force_login else (self.cfg.therapy.access_token or plan_state.get("therapy_access_token", "") or legacy_token)
        if token:
            return str(token)

        if not self.cfg.therapy.birth_date:
            raise TherapyPlanError(
                f"Kein Therapieplan-Access-Token für '{self.cfg.therapy.display_name}' vorhanden und kein Geburtsdatum für logon1 konfiguriert. "
                "birth_date im jeweiligen therapy_plans-Eintrag setzen."
            )

        password_hash = therapy_password_hash(self.cfg.therapy.birth_date)
        rp = self._post({"select": "logon1", "passwordhash": password_hash})
        if rp.get("code") != 0:
            raise TherapyPlanError(f"logon1 fehlgeschlagen für '{self.cfg.therapy.display_name}': {rp.get('description', rp)}")
        token = rp.get("accesstoken")
        if not token:
            raise TherapyPlanError(f"logon1 erfolgreich für '{self.cfg.therapy.display_name}', aber accesstoken fehlt.")
        plan_state["therapy_access_token"] = token
        logging.info("Therapieplan Access-Token für '%s' erhalten und in state.json gespeichert.", self.cfg.therapy.display_name)
        return str(token)

    def fetch_plan(self) -> Dict[str, Any]:
        access_token = self._get_access_token()
        rp = self._post({"select": "logon2", "accesstoken": access_token})

        if rp.get("code") != 0:
            logging.warning("logon2 mit gespeichertem Token fehlgeschlagen: %s", rp.get("description", rp))
            if self.cfg.therapy.birth_date:
                access_token = self._get_access_token(force_login=True)
                rp = self._post({"select": "logon2", "accesstoken": access_token})

        if rp.get("code") != 0:
            raise TherapyPlanError(f"logon2 fehlgeschlagen: {rp.get('description', rp)}")

        session_token = rp.get("sessiontoken")
        if not session_token:
            raise TherapyPlanError("logon2 erfolgreich, aber sessiontoken fehlt.")

        plan = self._post({"select": "plan", "sessiontoken": session_token})
        if plan.get("code") != 0:
            raise TherapyPlanError(f"plan fehlgeschlagen: {plan.get('description', plan)}")

        plan_state = self._plan_state()
        if "sessiontoken" in plan:
            plan_state["therapy_session_token_last"] = plan.get("sessiontoken")
        plan_state["therapy_last_fetch_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        return plan


def parse_datetime(value: Any, local_tz: ZoneInfo) -> dt.datetime:
    if not value:
        raise ValueError("Leeres Datum")
    parsed = date_parser.parse(str(value))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=local_tz)
    else:
        parsed = parsed.astimezone(local_tz)
    return parsed


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())


def first_non_empty(mapping: Dict[str, Any], keys: Iterable[str]) -> str:
    for key in keys:
        value = clean_text(mapping.get(key))
        if value:
            return value
    return ""


def canonical_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_short(value: str, length: int = 32) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def build_description(bok: Dict[str, Any], include_details: bool) -> str:
    if not include_details:
        return "Automatisch aus dem Therapieplan synchronisiert."

    lines: List[str] = []
    for label, keys in [
        ("Mitarbeiter", ["employee"]),
        ("Raum", ["location"]),
        ("Hinweis", ["serviceremark", "serviceinstruction"]),
        ("Patientenhinweis", ["patientremark"]),
        ("Gruppenhinweis", ["groupremark"]),
        ("Co-Therapie", ["coservice"]),
        ("Co-Mitarbeiter", ["coemployee"]),
        ("Co-Hinweis", ["coserviceremark"]),
    ]:
        values = [clean_text(bok.get(k)) for k in keys if clean_text(bok.get(k))]
        if values:
            lines.append(f"{label}: " + " | ".join(values))

    lines.append("")
    lines.append("Automatisch aus dem Therapieplan synchronisiert.")
    return "\n".join(lines).strip()


def booking_explicit_id(bok: Dict[str, Any]) -> str:
    # Falls die Backend-JSON künftig eine echte Termin-ID enthält, wird sie automatisch genutzt.
    return first_non_empty(
        bok,
        [
            "id",
            "uid",
            "uuid",
            "bookingid",
            "bookingId",
            "booking_id",
            "appointmentid",
            "appointmentId",
            "eventid",
            "eventId",
            "bokid",
            "bokId",
        ],
    )


def make_candidates(plan: Dict[str, Any], cfg: AppConfig) -> List[CalendarEventCandidate]:
    local_tz = ZoneInfo(cfg.google.timezone)
    bookings = plan.get("bookings") or []
    if not isinstance(bookings, list):
        raise TherapyPlanError("plan.bookings ist keine Liste.")

    today_local = dt.datetime.now(local_tz).date()
    min_date = today_local - dt.timedelta(days=cfg.sync.include_past_days)

    # Für Termine ohne echte ID erzeugen wir pro Tag/Leistung/Raum/Mitarbeiter eine laufende Nummer.
    weak_key_counter: Dict[str, int] = {}
    candidates: List[CalendarEventCandidate] = []

    for bok in bookings:
        if not isinstance(bok, dict):
            continue
        form = clean_text(bok.get("form"))
        if form not in SUPPORTED_FORMS:
            continue
        try:
            flags = int(bok.get("flags", 0) or 0)
        except Exception:
            flags = 0
        if flags & HIDDEN_FLAG:
            continue
        if not bok.get("beg") or not bok.get("end"):
            continue

        try:
            begin = parse_datetime(bok["beg"], local_tz)
            end = parse_datetime(bok["end"], local_tz)
        except Exception as exc:
            logging.warning("Überspringe Termin mit ungültigem Datum: %s (%s)", bok, exc)
            continue

        if end <= begin:
            logging.warning("Überspringe Termin mit end <= beg: %s", bok)
            continue
        if begin.date() < min_date:
            continue

        service = clean_text(bok.get("service")) or "Therapieplan"
        location = clean_text(bok.get("location"))
        employee = clean_text(bok.get("employee"))
        coservice = clean_text(bok.get("coservice"))
        coemployee = clean_text(bok.get("coemployee"))

        explicit_id = booking_explicit_id(bok)
        if explicit_id:
            stable_material = f"plan={cfg.therapy.plan_id}|explicit|{explicit_id}"
        else:
            weak_base = "|".join(
                [
                    f"plan={cfg.therapy.plan_id}",
                    "weak",
                    begin.date().isoformat(),
                    form,
                    service.lower(),
                    location.lower(),
                    employee.lower(),
                    coservice.lower(),
                    coemployee.lower(),
                ]
            )
            weak_key_counter[weak_base] = weak_key_counter.get(weak_base, 0) + 1
            stable_material = f"{weak_base}|occurrence={weak_key_counter[weak_base]}"

        source_key = sha256_short(stable_material, 32)

        event_reminders = effective_reminders(cfg)

        signature_material = {
            "version": SYNC_VERSION,
            "source_key": source_key,
            "begin": begin.isoformat(),
            "end": end.isoformat(),
            "form": form,
            "service": service,
            "location": location,
            "employee": employee,
            "description": build_description(bok, cfg.sync.include_details_in_description),
            "coservice": coservice,
            "coemployee": coemployee,
            "visibility": cfg.sync.visibility,
            "transparency": cfg.sync.transparency,
            "reminders": event_reminders,
            "plan_id": cfg.therapy.plan_id,
            "plan_name": cfg.therapy.display_name,
            "color_id": cfg.therapy.color_id,
        }
        signature = sha256_short(canonical_json(signature_material), 64)

        body: Dict[str, Any] = {
            "summary": f"{cfg.sync.event_prefix}{service}" if cfg.sync.event_prefix else service,
            "location": location,
            "description": signature_material["description"],
            "start": {"dateTime": begin.isoformat(), "timeZone": cfg.google.timezone},
            "end": {"dateTime": end.isoformat(), "timeZone": cfg.google.timezone},
            "visibility": cfg.sync.visibility,
            "transparency": cfg.sync.transparency,
            "extendedProperties": {
                "private": {
                    "source": cfg.sync.source_name,
                    "sourceKey": source_key,
                    "sourceSignature": signature,
                    "syncVersion": SYNC_VERSION,
                    "planId": cfg.therapy.plan_id,
                    "planName": cfg.therapy.display_name,
                }
            },
        }
        if event_reminders:
            body["reminders"] = event_reminders
        if cfg.therapy.color_id:
            body["colorId"] = cfg.therapy.color_id
        candidates.append(CalendarEventCandidate(source_key, signature, body, begin, end))

    candidates.sort(key=lambda item: (item.begin, item.google_body.get("summary", "")))
    return candidates


def get_google_service(
    cfg: AppConfig,
    *,
    auth_host: str = "localhost",
    auth_bind_addr: Optional[str] = None,
    auth_port: int = 0,
    open_browser: bool = True,
):
    token_file = cfg.google.token_file
    creds: Optional[Credentials] = None

    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(GoogleRequest())
        else:
            if not cfg.google.credentials_file.exists():
                raise FileNotFoundError(
                    f"Google credentials_file fehlt: {cfg.google.credentials_file}. "
                    "OAuth-Client-JSON aus Google Cloud Console dort ablegen."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(cfg.google.credentials_file), SCOPES)
            # Im Container wird host=localhost als Redirect-URI verwendet, aber an 0.0.0.0 gebunden,
            # damit der Port über Docker nach außen erreichbar ist.
            run_kwargs = {
                "host": auth_host,
                "port": auth_port,
                "open_browser": open_browser,
            }
            if auth_bind_addr:
                run_kwargs["bind_addr"] = auth_bind_addr
            creds = flow.run_local_server(**run_kwargs)
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(creds.to_json(), encoding="utf-8")
        os.chmod(token_file, 0o600)

    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def rfc3339_z(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def list_existing_events(service: Any, cfg: AppConfig, candidates: List[CalendarEventCandidate], calendar_id: str) -> Dict[str, Dict[str, Any]]:
    local_tz = ZoneInfo(cfg.google.timezone)
    now = dt.datetime.now(local_tz)
    if candidates:
        min_begin = min(c.begin for c in candidates)
        max_end = max(c.end for c in candidates)
    else:
        min_begin = now - dt.timedelta(days=cfg.sync.include_past_days)
        max_end = now + dt.timedelta(days=90)

    time_min = min(min_begin, now - dt.timedelta(days=cfg.sync.include_past_days, hours=1))
    time_max = max_end + dt.timedelta(days=14)

    existing_by_key: Dict[str, Dict[str, Any]] = {}
    page_token = None
    while True:
        result = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=rfc3339_z(time_min),
                timeMax=rfc3339_z(time_max),
                singleEvents=True,
                showDeleted=False,
                privateExtendedProperty=f"source={cfg.sync.source_name}",
                pageToken=page_token,
                maxResults=2500,
            )
            .execute()
        )
        for event in result.get("items", []):
            private_props = (event.get("extendedProperties") or {}).get("private") or {}
            source_key = private_props.get("sourceKey")
            if source_key:
                existing_by_key[str(source_key)] = event
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    return existing_by_key


def event_signature(event: Dict[str, Any]) -> str:
    return str(((event.get("extendedProperties") or {}).get("private") or {}).get("sourceSignature", ""))


def insert_event(service: Any, cfg: AppConfig, candidate: CalendarEventCandidate, calendar_id: str) -> Dict[str, Any]:
    return (
        service.events()
        .insert(calendarId=calendar_id, body=candidate.google_body, sendUpdates="none")
        .execute()
    )


def patch_event(service: Any, cfg: AppConfig, event_id: str, candidate: CalendarEventCandidate, calendar_id: str) -> Dict[str, Any]:
    return (
        service.events()
        .patch(calendarId=calendar_id, eventId=event_id, body=candidate.google_body, sendUpdates="none")
        .execute()
    )


def delete_event(service: Any, cfg: AppConfig, event_id: str, calendar_id: str) -> None:
    service.events().delete(calendarId=calendar_id, eventId=event_id, sendUpdates="none").execute()


def _event_datetime_from_body(value: Dict[str, Any], tz: ZoneInfo) -> Optional[dt.datetime]:
    raw = (value or {}).get("dateTime") or (value or {}).get("date")
    if not raw:
        return None
    try:
        return parse_datetime(raw, tz)
    except Exception:
        return None


def _format_event_range(begin: Optional[dt.datetime], end: Optional[dt.datetime], timezone: str) -> str:
    if begin is None:
        return "Zeit unbekannt"
    local_tz = ZoneInfo(timezone)
    begin_local = begin.astimezone(local_tz)
    if end is not None:
        end_local = end.astimezone(local_tz)
    else:
        end_local = None
    date_part = begin_local.strftime("%d.%m.")
    start_part = begin_local.strftime("%H:%M")
    if end_local is None:
        return f"{date_part} {start_part}"
    if begin_local.date() == end_local.date():
        return f"{date_part} {start_part}-{end_local.strftime('%H:%M')}"
    return f"{date_part} {start_part}-{end_local.strftime('%d.%m. %H:%M')}"


def _event_detail_from_candidate(cfg: AppConfig, change_type: str, candidate: CalendarEventCandidate) -> Dict[str, Any]:
    body = candidate.google_body
    return {
        "type": change_type,
        "plan_id": cfg.therapy.plan_id,
        "plan_name": cfg.therapy.display_name,
        "title": str(body.get("summary") or "Therapieplan"),
        "location": str(body.get("location") or ""),
        "begin": candidate.begin.isoformat(),
        "end": candidate.end.isoformat(),
    }


def _event_detail_from_existing(cfg: AppConfig, change_type: str, event: Dict[str, Any]) -> Dict[str, Any]:
    local_tz = ZoneInfo(cfg.google.timezone)
    begin = _event_datetime_from_body(event.get("start") or {}, local_tz)
    end = _event_datetime_from_body(event.get("end") or {}, local_tz)
    private_props = (event.get("extendedProperties") or {}).get("private") or {}
    return {
        "type": change_type,
        "plan_id": str(private_props.get("planId") or cfg.therapy.plan_id),
        "plan_name": str(private_props.get("planName") or cfg.therapy.display_name),
        "title": str(event.get("summary") or "Therapieplan"),
        "location": str(event.get("location") or ""),
        "begin": begin.isoformat() if begin else "",
        "end": end.isoformat() if end else "",
    }


def _append_change_detail(stats: Dict[str, Any], detail: Dict[str, Any]) -> None:
    details = stats.setdefault("change_details", [])
    if isinstance(details, list):
        details.append(detail)


def _change_detail_dedupe_key(detail: Dict[str, Any]) -> Tuple[Any, ...]:
    return (
        detail.get("type"),
        detail.get("plan_id"),
        detail.get("title"),
        detail.get("begin"),
        detail.get("end"),
        detail.get("old_begin"),
        detail.get("old_end"),
        detail.get("old_title"),
        detail.get("old_location"),
    )


def _append_change_detail_once(stats: Dict[str, Any], detail: Dict[str, Any], seen: set[Tuple[Any, ...]]) -> None:
    key = _change_detail_dedupe_key(detail)
    if key in seen:
        return
    seen.add(key)
    _append_change_detail(stats, detail)


def _add_update_diff(detail: Dict[str, Any], existing: Dict[str, Any], candidate: CalendarEventCandidate, cfg: AppConfig) -> Dict[str, Any]:
    local_tz = ZoneInfo(cfg.google.timezone)
    old_begin = _event_datetime_from_body(existing.get("start") or {}, local_tz)
    old_end = _event_datetime_from_body(existing.get("end") or {}, local_tz)
    old_title = str(existing.get("summary") or "")
    old_location = str(existing.get("location") or "")
    new_title = str(candidate.google_body.get("summary") or "")
    new_location = str(candidate.google_body.get("location") or "")

    if old_begin and old_begin != candidate.begin:
        detail["old_begin"] = old_begin.isoformat()
    if old_end and old_end != candidate.end:
        detail["old_end"] = old_end.isoformat()
    if old_title and old_title != new_title:
        detail["old_title"] = old_title
    if old_location != new_location:
        detail["old_location"] = old_location
    return detail


def target_calendar_ids(cfg: AppConfig) -> Tuple[str, ...]:
    return cfg.google.calendar_ids or (cfg.google.calendar_id or "primary",)


def sync_to_google(plan: Dict[str, Any], cfg: AppConfig, state: Dict[str, Any]) -> Dict[str, Any]:
    candidates = make_candidates(plan, cfg)
    calendar_ids = target_calendar_ids(cfg)
    logging.info("Therapieplan-Termine nach Filter: %s", len(candidates))
    logging.info("Zielkalender: %s", ", ".join(calendar_ids))

    stats: Dict[str, Any] = {
        "created": 0,
        "updated": 0,
        "unchanged": 0,
        "deleted": 0,
        "errors": 0,
        "change_details": [],
        "calendar_ids": list(calendar_ids),
        "calendars": [],
    }
    if cfg.sync.dry_run:
        for calendar_id in calendar_ids:
            logging.info("DRY-RUN Zielkalender: %s", calendar_id)
        for c in candidates:
            logging.info("DRY-RUN candidate: %s %s %s", c.begin.isoformat(), c.end.isoformat(), c.google_body.get("summary"))
        return stats

    service = get_google_service(cfg)
    current_keys = {c.source_key for c in candidates}
    seen_change_details: set[Tuple[Any, ...]] = set()

    for calendar_id in calendar_ids:
        calendar_stats = {"calendar_id": calendar_id, "created": 0, "updated": 0, "unchanged": 0, "deleted": 0, "errors": 0}
        logging.info("Synchronisiere Kalender '%s'", calendar_id)
        try:
            existing_by_key = list_existing_events(service, cfg, candidates, calendar_id)
        except HttpError as exc:
            stats["errors"] = int(stats.get("errors", 0)) + 1
            calendar_stats["errors"] = int(calendar_stats.get("errors", 0)) + 1
            logging.error("Google-Listenfehler für Kalender '%s': %s", calendar_id, exc)
            stats["calendars"].append(calendar_stats)
            continue

        for candidate in candidates:
            existing = existing_by_key.get(candidate.source_key)
            try:
                if existing is None:
                    created = insert_event(service, cfg, candidate, calendar_id)
                    existing_by_key[candidate.source_key] = created
                    stats["created"] = int(stats.get("created", 0)) + 1
                    calendar_stats["created"] = int(calendar_stats.get("created", 0)) + 1
                    detail = _event_detail_from_candidate(cfg, "created", candidate)
                    detail.setdefault("calendar_ids", []).append(calendar_id)
                    _append_change_detail_once(stats, detail, seen_change_details)
                    logging.info("Erstellt in %s: %s", calendar_id, candidate.google_body.get("summary"))
                else:
                    if event_signature(existing) == candidate.source_signature:
                        stats["unchanged"] = int(stats.get("unchanged", 0)) + 1
                        calendar_stats["unchanged"] = int(calendar_stats.get("unchanged", 0)) + 1
                    else:
                        detail = _event_detail_from_candidate(cfg, "updated", candidate)
                        _add_update_diff(detail, existing, candidate, cfg)
                        detail.setdefault("calendar_ids", []).append(calendar_id)
                        patched = patch_event(service, cfg, existing["id"], candidate, calendar_id)
                        existing_by_key[candidate.source_key] = patched
                        stats["updated"] = int(stats.get("updated", 0)) + 1
                        calendar_stats["updated"] = int(calendar_stats.get("updated", 0)) + 1
                        _append_change_detail_once(stats, detail, seen_change_details)
                        logging.info("Aktualisiert in %s: %s", calendar_id, candidate.google_body.get("summary"))
            except HttpError as exc:
                stats["errors"] = int(stats.get("errors", 0)) + 1
                calendar_stats["errors"] = int(calendar_stats.get("errors", 0)) + 1
                logging.error("Google-Sync-Fehler bei %s in Kalender '%s': %s", candidate.google_body.get("summary"), calendar_id, exc)

        if cfg.sync.delete_missing_future:
            now = dt.datetime.now(ZoneInfo(cfg.google.timezone))
            for source_key, event in list(existing_by_key.items()):
                if source_key in current_keys:
                    continue
                start_value = (event.get("start") or {}).get("dateTime") or (event.get("start") or {}).get("date")
                try:
                    event_start = parse_datetime(start_value, ZoneInfo(cfg.google.timezone))
                except Exception:
                    event_start = now
                if event_start < now - dt.timedelta(days=cfg.sync.include_past_days):
                    continue
                try:
                    delete_detail = _event_detail_from_existing(cfg, "deleted", event)
                    delete_detail.setdefault("calendar_ids", []).append(calendar_id)
                    delete_event(service, cfg, event["id"], calendar_id)
                    stats["deleted"] = int(stats.get("deleted", 0)) + 1
                    calendar_stats["deleted"] = int(calendar_stats.get("deleted", 0)) + 1
                    _append_change_detail_once(stats, delete_detail, seen_change_details)
                    logging.info("Gelöscht aus %s, nicht mehr im Therapieplan: %s", calendar_id, event.get("summary"))
                except HttpError as exc:
                    stats["errors"] = int(stats.get("errors", 0)) + 1
                    calendar_stats["errors"] = int(calendar_stats.get("errors", 0)) + 1
                    logging.error("Google-Löschfehler bei %s in Kalender '%s': %s", event.get("summary"), calendar_id, exc)
        stats["calendars"].append(calendar_stats)

    state["google_last_sync_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    state["google_last_stats"] = stats
    return stats


def dump_plan(plan: Dict[str, Any], path: Path) -> None:
    write_json_atomic(path, plan)
    logging.info("Plan gespeichert: %s", path)




def should_notify(cfg: AppConfig, *, stats: Optional[Dict[str, int]] = None, error: Optional[str] = None, force: bool = False) -> bool:
    if not cfg.notifications.enabled and not force:
        return False
    if force:
        return True
    if error:
        return cfg.notifications.notify_on_errors
    if not stats:
        return False
    changes = int(stats.get("created", 0)) + int(stats.get("updated", 0)) + int(stats.get("deleted", 0))
    errors = int(stats.get("errors", 0))
    if errors > 0:
        return cfg.notifications.notify_on_errors
    if changes > 0:
        return cfg.notifications.notify_on_changes
    return cfg.notifications.notify_on_success_no_changes


def _parse_iso_datetime(value: Any, timezone: str) -> Optional[dt.datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return parse_datetime(text, ZoneInfo(timezone))
    except Exception:
        return None


def _format_change_detail(detail: Dict[str, Any], timezone: str) -> str:
    change_type = str(detail.get("type") or "").lower()
    marker = {"created": "Neu", "updated": "Geändert", "deleted": "Abgesagt"}.get(change_type, "Änderung")
    plan_name = str(detail.get("plan_name") or detail.get("plan_id") or "Plan")
    title = str(detail.get("title") or "Therapieplan")
    location = str(detail.get("location") or "").strip()
    begin = _parse_iso_datetime(detail.get("begin"), timezone)
    end = _parse_iso_datetime(detail.get("end"), timezone)
    when = _format_event_range(begin, end, timezone)

    line = f"- {marker}: {plan_name}: {when} {title}"
    if location:
        line += f" ({location})"

    if change_type == "updated":
        old_begin = _parse_iso_datetime(detail.get("old_begin"), timezone)
        old_end = _parse_iso_datetime(detail.get("old_end"), timezone)
        old_title = str(detail.get("old_title") or "").strip()
        old_location = str(detail.get("old_location") or "").strip()
        diff_parts: List[str] = []
        if old_begin:
            diff_parts.append(f"vorher { _format_event_range(old_begin, old_end, timezone) }")
        if old_title:
            diff_parts.append(f"vorher Titel '{old_title}'")
        if old_location:
            diff_parts.append(f"vorher Ort '{old_location}'")
        if diff_parts:
            line += " [" + "; ".join(diff_parts) + "]"
    return line


def _limit_message(message: str, max_chars: int) -> str:
    if max_chars <= 0 or len(message) <= max_chars:
        return message
    suffix = "\n… gekürzt. Details stehen im Container-Log."
    keep = max(0, max_chars - len(suffix))
    return message[:keep].rstrip() + suffix


def _parse_sync_time_values(raw: str) -> List[dt.time]:
    values = [item.strip() for item in str(raw or "").split(",") if item.strip()]
    result: List[dt.time] = []
    for value in values:
        parts = value.split(":")
        if len(parts) not in {2, 3}:
            continue
        try:
            parsed = dt.time(
                hour=int(parts[0]),
                minute=int(parts[1]),
                second=int(parts[2]) if len(parts) == 3 else 0,
            )
        except ValueError:
            continue
        if parsed not in result:
            result.append(parsed)
    result.sort()
    return result


def _next_boundary_after(now: dt.datetime, times: List[dt.time]) -> Optional[dt.datetime]:
    if not times:
        return None
    for value in times:
        candidate = dt.datetime.combine(now.date(), value, tzinfo=now.tzinfo)
        if candidate > now:
            return candidate
    return dt.datetime.combine(now.date() + dt.timedelta(days=1), times[0], tzinfo=now.tzinfo)


def _notification_next_sync_window(cfg: AppConfig) -> Optional[Tuple[dt.datetime, dt.datetime]]:
    local_tz = ZoneInfo(cfg.google.timezone)
    env_start = os.environ.get("SYNC_WINDOW_START") or os.environ.get("SYNC_WINDOW_START_ISO")
    env_end = os.environ.get("SYNC_WINDOW_END") or os.environ.get("SYNC_WINDOW_END_ISO")
    if env_start and env_end:
        start = _parse_iso_datetime(env_start, cfg.google.timezone)
        end = _parse_iso_datetime(env_end, cfg.google.timezone)
        if start and end and end > start:
            return start.astimezone(local_tz), end.astimezone(local_tz)

    now = dt.datetime.now(local_tz)
    raw_times = os.environ.get("SYNC_TIMES", "06:00,12:00,18:00,22:00")
    times = _parse_sync_time_values(raw_times)
    end = _next_boundary_after(now, times)
    if end is None:
        return None
    return now, end


def _detail_interval(detail: Dict[str, Any], timezone: str, *, old: bool = False) -> Tuple[Optional[dt.datetime], Optional[dt.datetime]]:
    begin_key = "old_begin" if old else "begin"
    end_key = "old_end" if old else "end"
    begin = _parse_iso_datetime(detail.get(begin_key), timezone)
    end = _parse_iso_datetime(detail.get(end_key), timezone)
    if begin and (end is None or end <= begin):
        end = begin + dt.timedelta(minutes=1)
    return begin, end


def _interval_overlaps(begin: Optional[dt.datetime], end: Optional[dt.datetime], window_start: dt.datetime, window_end: dt.datetime) -> bool:
    if begin is None:
        return False
    if end is None or end <= begin:
        end = begin + dt.timedelta(minutes=1)
    begin = begin.astimezone(window_start.tzinfo)
    end = end.astimezone(window_start.tzinfo)
    return begin < window_end and end > window_start


def _next_sync_window_change_details(cfg: AppConfig, stats: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not stats or not cfg.notifications.intense_next_sync_window_changes:
        return []
    details = stats.get("change_details")
    if not isinstance(details, list):
        return []
    window = _notification_next_sync_window(cfg)
    if window is None:
        return []
    window_start, window_end = window

    result: List[Dict[str, Any]] = []
    for detail in details:
        if not isinstance(detail, dict):
            continue
        change_type = str(detail.get("type") or "").lower()
        if change_type not in {"created", "updated", "deleted"}:
            continue
        begin, end = _detail_interval(detail, cfg.google.timezone)
        if _interval_overlaps(begin, end, window_start, window_end):
            result.append(detail)
            continue
        # Bei verschobenen Terminen auch die alte Zeit prüfen, damit eine Änderung
        # aus dem nächsten Fenster heraus ebenfalls eskaliert wird.
        if change_type == "updated":
            old_begin, old_end = _detail_interval(detail, cfg.google.timezone, old=True)
            if _interval_overlaps(old_begin, old_end, window_start, window_end):
                result.append(detail)
    return result


def _same_day_change_details(cfg: AppConfig, stats: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not stats or not cfg.notifications.intense_same_day_changes:
        return []
    details = stats.get("change_details")
    if not isinstance(details, list):
        return []

    local_tz = ZoneInfo(cfg.google.timezone)
    today = dt.datetime.now(local_tz).date()
    result: List[Dict[str, Any]] = []
    for detail in details:
        if not isinstance(detail, dict):
            continue
        change_type = str(detail.get("type") or "").lower()
        if change_type not in {"created", "updated", "deleted"}:
            continue
        begin, _end = _detail_interval(detail, cfg.google.timezone)
        old_begin, _old_end = _detail_interval(detail, cfg.google.timezone, old=True)
        if begin and begin.astimezone(local_tz).date() == today:
            result.append(detail)
        elif old_begin and old_begin.astimezone(local_tz).date() == today:
            result.append(detail)
    return result


def _notification_intensity(
    cfg: AppConfig,
    stats: Optional[Dict[str, Any]],
) -> Tuple[int, str, List[Dict[str, Any]], Optional[Tuple[dt.datetime, dt.datetime]]]:
    """Ermittelt die Pushover-Eskalationsstufe für Terminänderungen.

    Stufe 2 gewinnt vor Stufe 1, Stufe 1 gewinnt vor Stufe 0.
    - 2: Terminänderung im nächsten Abschnitt zwischen zwei Sync-Zeitpunkten
    - 1: Terminänderung am gleichen Kalendertag
    - 0: sonstige neue/geänderte/abgesagte Termine
    """
    if not stats:
        return 0, "none", [], None

    details_raw = stats.get("change_details")
    details = [item for item in details_raw if isinstance(item, dict)] if isinstance(details_raw, list) else []
    changed_details = [
        item
        for item in details
        if str(item.get("type") or "").lower() in {"created", "updated", "deleted"}
    ]
    if not changed_details:
        return 0, "none", [], None

    next_window = _notification_next_sync_window(cfg) if cfg.notifications.intense_next_sync_window_changes else None
    next_window_details = _next_sync_window_change_details(cfg, stats)
    if next_window_details:
        return 2, "next_window", next_window_details, next_window

    same_day_details = _same_day_change_details(cfg, stats)
    if same_day_details:
        return 1, "same_day", same_day_details, None

    return 0, "future", changed_details, None


def _intense_change_details(cfg: AppConfig, stats: Optional[Dict[str, Any]]) -> Tuple[str, List[Dict[str, Any]], Optional[Tuple[dt.datetime, dt.datetime]]]:
    # Rückwärtskompatibler Wrapper: früher hieß alles oberhalb von Normal "intense".
    level, reason, details, window = _notification_intensity(cfg, stats)
    if level >= 1:
        return reason, details, window
    return "", [], None


def notification_intensity_level(cfg: AppConfig, stats: Optional[Dict[str, Any]]) -> int:
    level, _reason, _details, _window = _notification_intensity(cfg, stats)
    return level


def has_intense_changes(cfg: AppConfig, stats: Optional[Dict[str, Any]]) -> bool:
    return notification_intensity_level(cfg, stats) >= 1


def has_same_day_changes(cfg: AppConfig, stats: Optional[Dict[str, Any]]) -> bool:
    level, reason, _details, _window = _notification_intensity(cfg, stats)
    return level >= 1 and reason in {"same_day", "next_window"}


def _format_window_label(window: Optional[Tuple[dt.datetime, dt.datetime]]) -> str:
    if window is None:
        return "nächster Sync-Abschnitt"
    start, end = window
    if start.date() == end.date():
        return f"{start.strftime('%H:%M')}-{end.strftime('%H:%M')}"
    return f"{start.strftime('%d.%m. %H:%M')}-{end.strftime('%d.%m. %H:%M')}"


def build_notification_text(
    cfg: AppConfig,
    stats: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
    test: bool = False,
) -> Tuple[str, str]:
    if test:
        return "Testbenachrichtigung", "Die Pushbenachrichtigung aus dem Therapieplan-Sync funktioniert."
    if error:
        return "Sync-Fehler", f"Der Therapieplan-Sync ist fehlgeschlagen:\n{error}"
    stats = stats or {}
    created = int(stats.get("created", 0))
    updated = int(stats.get("updated", 0))
    deleted = int(stats.get("deleted", 0))
    unchanged = int(stats.get("unchanged", 0))
    errors = int(stats.get("errors", 0))
    changes = created + updated + deleted
    level, level_reason, level_details, level_window = _notification_intensity(cfg, stats)
    level_changes = len(level_details)

    if errors > 0:
        title = "Sync mit Fehlern"
    elif level_reason == "next_window":
        title = "Nächster Abschnitt geändert"
    elif level_reason == "same_day":
        title = "HEUTE geändert"
    elif changes > 0:
        title = "Therapieplan geändert"
    else:
        title = "Therapieplan unverändert"

    lines = [
        f"Neu: {created}",
        f"Geändert: {updated}",
        f"Abgesagt: {deleted}",
        f"Unverändert: {unchanged}",
        f"Fehler: {errors}",
    ]
    if changes > 0:
        lines.append(f"Meldungsstufe: {level}")
    if level_changes > 0:
        if level_reason == "next_window":
            lines.append(f"Nächster Abschnitt betroffen: {level_changes} ({_format_window_label(level_window)})")
        elif level_reason == "same_day":
            lines.append(f"Heute betroffen: {level_changes}")
        elif level_reason == "future":
            lines.append(f"Weitere Tage betroffen: {level_changes}")

    change_details = stats.get("change_details")
    if cfg.notifications.include_change_details and isinstance(change_details, list) and change_details:
        max_items = max(0, int(cfg.notifications.max_change_items))
        shown = change_details[:max_items]
        lines.append("")
        lines.append("Termine:")
        for detail in shown:
            if isinstance(detail, dict):
                lines.append(_format_change_detail(detail, cfg.google.timezone))
        remaining = len(change_details) - len(shown)
        if remaining > 0:
            lines.append(f"… {remaining} weitere Änderung(en).")

    plan_rows = stats.get("plans")
    if isinstance(plan_rows, list) and plan_rows:
        lines.append("")
        lines.append("Pro Quelle:")
        for row in plan_rows[:10]:
            if not isinstance(row, dict):
                continue
            lines.append(
                f"- {row.get('name', row.get('id', 'Plan'))}: "
                f"+{int(row.get('created', 0))} / "
                f"~{int(row.get('updated', 0))} / "
                f"-{int(row.get('deleted', 0))} / "
                f"Fehler {int(row.get('errors', 0))}"
            )

    error_messages = stats.get("error_messages")
    if isinstance(error_messages, list) and error_messages:
        lines.append("")
        lines.append("Fehlerdetails:")
        for msg in error_messages[:5]:
            lines.append(f"- {str(msg)[:300]}")

    message = "\n".join(lines)
    message = _limit_message(message, int(cfg.notifications.max_message_chars))
    return title, message


def _masked(value: str) -> str:
    value = str(value or "")
    if len(value) <= 8:
        return "***" if value else "<leer>"
    return f"{value[:4]}...{value[-4:]}"


def _pushover_response_error(response: requests.Response) -> str:
    try:
        data = response.json()
    except Exception:
        body = response.text.strip()
        return f"HTTP {response.status_code}: {body[:500]}"
    errors = data.get("errors")
    if isinstance(errors, list):
        err_text = "; ".join(str(item) for item in errors)
    else:
        err_text = str(errors or data)
    request_id = data.get("request")
    if request_id:
        return f"HTTP {response.status_code}: {err_text} (request={request_id})"
    return f"HTTP {response.status_code}: {err_text}"


def _pushover_level_options(cfg: AppConfig, level: int) -> Tuple[int, str, int, int]:
    level = max(0, min(2, int(level)))
    if level == 2:
        priority = cfg.notifications.level2_priority
        sound = cfg.notifications.level2_sound
        retry = cfg.notifications.level2_retry
        expire = cfg.notifications.level2_expire
    elif level == 1:
        priority = cfg.notifications.level1_priority
        sound = cfg.notifications.level1_sound
        retry = cfg.notifications.level1_retry
        expire = cfg.notifications.level1_expire
    else:
        priority = cfg.notifications.level0_priority
        sound = cfg.notifications.level0_sound
        retry = cfg.notifications.level0_retry
        expire = cfg.notifications.level0_expire

    priority = max(-2, min(2, int(priority)))
    retry = max(30, int(retry))
    expire = min(10800, max(retry, int(expire)))
    return priority, str(sound or "").strip(), retry, expire


def send_pushover(cfg: AppConfig, title: str, message: str, *, level: int = 0, intense: bool = False) -> bool:
    po = cfg.notifications.pushover
    if not po.get("enabled"):
        logging.debug("Pushover ist deaktiviert.")
        return False
    if not po.get("token") or not po.get("user"):
        raise ValueError("Pushover ist aktiviert, aber PUSHOVER_TOKEN oder PUSHOVER_USER fehlt.")
    if intense and level < 1:
        level = 1
    priority, sound, retry, expire = _pushover_level_options(cfg, level)

    payload: Dict[str, Any] = {
        "token": po["token"],
        "user": po["user"],
        "title": title,
        "message": message,
        "priority": priority,
    }
    if po.get("device"):
        payload["device"] = po["device"]
    if sound:
        payload["sound"] = sound
    if priority == 2:
        payload["retry"] = retry
        payload["expire"] = expire

    logging.info(
        "Sende Pushover-Test/Push: token=%s user=%s device=%s priority=%s level=%s",
        _masked(str(po.get("token", ""))),
        _masked(str(po.get("user", ""))),
        po.get("device") or "<alle>",
        priority,
        level,
    )
    response = requests.post("https://api.pushover.net/1/messages.json", data=payload, timeout=20)
    if response.status_code >= 400:
        raise RuntimeError(f"Pushover-API-Fehler: {_pushover_response_error(response)}")
    try:
        data = response.json()
    except Exception as exc:
        raise RuntimeError(f"Pushover lieferte keine gültige JSON-Antwort: {response.text[:500]}") from exc
    if int(data.get("status", 0)) != 1:
        raise RuntimeError(f"Pushover hat die Nachricht abgelehnt: {data}")
    logging.info("Pushover-Benachrichtigung gesendet. request=%s", data.get("request", "<unbekannt>"))
    return True


def send_homeassistant(cfg: AppConfig, title: str, message: str, *, intense: bool = False) -> bool:
    ha = cfg.notifications.homeassistant
    if not ha.get("enabled"):
        logging.debug("Home Assistant ist deaktiviert.")
        return False
    url = str(ha.get("url") or "").rstrip("/")
    token = str(ha.get("token") or "")
    service = str(ha.get("notify_service") or "").strip()
    if service.startswith("notify."):
        service = service.split(".", 1)[1]
    if not url or not token or not service:
        raise ValueError("Home Assistant ist aktiviert, aber HOMEASSISTANT_URL, HOMEASSISTANT_TOKEN oder HOMEASSISTANT_NOTIFY_SERVICE fehlt.")
    endpoint = f"{url}/api/services/notify/{service}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"title": title, "message": message}
    if intense:
        payload["data"] = {"priority": "high"}
    response = requests.post(endpoint, headers=headers, json=payload, timeout=20)
    if response.status_code >= 400:
        raise RuntimeError(f"Home-Assistant-API-Fehler: HTTP {response.status_code}: {response.text[:500]}")
    logging.info("Home-Assistant-Benachrichtigung gesendet.")
    return True


def send_notifications(cfg: AppConfig, *, stats: Optional[Dict[str, int]] = None, error: Optional[str] = None, test: bool = False) -> None:
    if not should_notify(cfg, stats=stats, error=error, force=test):
        return
    raw_title, message = build_notification_text(cfg, stats=stats, error=error, test=test)
    level = notification_intensity_level(cfg, stats) if (stats and not error and not test) else 0
    intense = level >= 1
    prefix = cfg.notifications.title_prefix.strip()
    title = f"{prefix}: {raw_title}" if prefix else raw_title

    enabled_providers = []
    if cfg.notifications.pushover.get("enabled"):
        enabled_providers.append("Pushover")
    if cfg.notifications.homeassistant.get("enabled"):
        enabled_providers.append("Home Assistant")
    if not enabled_providers:
        raise RuntimeError(
            "Keine Push-Provider aktiviert. Setze mindestens PUSHOVER_ENABLED=1 "
            "oder HOMEASSISTANT_ENABLED=1 in .env."
        )

    notify_errors = 0
    sent_count = 0
    for sender in (send_pushover, send_homeassistant):
        try:
            if sender is send_pushover:
                sent = sender(cfg, title, message, level=level)
            else:
                sent = sender(cfg, title, message, intense=intense)
            if sent:
                sent_count += 1
        except Exception as exc:
            notify_errors += 1
            logging.error("Benachrichtigung fehlgeschlagen: %s", exc)
    if notify_errors:
        raise RuntimeError("Mindestens eine Benachrichtigung konnte nicht gesendet werden.")
    if sent_count == 0:
        raise RuntimeError("Kein aktivierter Push-Provider hat eine Nachricht gesendet.")


def config_for_plan(cfg: AppConfig, therapy: TherapyConfig) -> AppConfig:
    effective_prefix = therapy.event_prefix if therapy.event_prefix is not None else cfg.sync.event_prefix
    effective_sync = dataclasses.replace(
        cfg.sync,
        source_name=therapy.source_name,
        event_prefix=effective_prefix,
    )
    if therapy.calendar_ids:
        effective_google = dataclasses.replace(
            cfg.google,
            calendar_id=first_calendar_id(therapy.calendar_ids),
            calendar_ids=therapy.calendar_ids,
        )
    else:
        effective_google = cfg.google
    return dataclasses.replace(cfg, therapy=therapy, google=effective_google, sync=effective_sync)


def empty_stats() -> Dict[str, Any]:
    return {
        "created": 0,
        "updated": 0,
        "unchanged": 0,
        "deleted": 0,
        "errors": 0,
        "plans": [],
        "error_messages": [],
        "change_details": [],
    }


def add_stats(target: Dict[str, Any], source: Dict[str, Any]) -> None:
    for key in ("created", "updated", "unchanged", "deleted", "errors"):
        target[key] = int(target.get(key, 0)) + int(source.get(key, 0))
    source_details = source.get("change_details")
    if isinstance(source_details, list):
        target.setdefault("change_details", []).extend(source_details)


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def write_stats_if_requested(base_dir: Path, stats_file_arg: Optional[str], stats: Dict[str, Any]) -> None:
    if not stats_file_arg:
        return
    stats_path = resolve_path(base_dir, stats_file_arg)
    payload = dict(stats)
    payload["written_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    write_json_atomic(stats_path, payload)
    logging.debug("Stats-Datei geschrieben: %s", stats_path)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Therapieplan in Google Kalender synchronisieren")
    parser.add_argument("--config", default="config.yaml", help="Pfad zur config.yaml")
    parser.add_argument("--dry-run", action="store_true", help="Keine Google-Änderungen durchführen")
    parser.add_argument("--dump-plan", help="Roh-JSON des Therapieplans in Datei speichern")
    parser.add_argument("--verbose", action="store_true", help="Debug-Logging aktivieren")
    parser.add_argument("--auth-only", action="store_true", help="Nur Google OAuth durchführen und token.json speichern")
    parser.add_argument("--auth-host", default=os.environ.get("GOOGLE_AUTH_HOST", "localhost"), help="OAuth Redirect-Host, normalerweise localhost")
    parser.add_argument("--auth-bind-addr", default=os.environ.get("GOOGLE_AUTH_BIND_ADDR", "0.0.0.0"), help="OAuth Bind-Adresse im Container")
    parser.add_argument("--auth-port", type=int, default=int(os.environ.get("GOOGLE_AUTH_PORT", "6080")), help="OAuth Port")
    parser.add_argument("--test-notification", action="store_true", help="Test-Pushbenachrichtigung senden und beenden")
    parser.add_argument("--stats-file", help="Schreibt die Gesamtstatistik des Laufs als JSON-Datei")
    args = parser.parse_args(argv)

    setup_logging(args.verbose)

    cfg = load_config(Path(args.config))
    if args.dry_run:
        cfg = dataclasses.replace(cfg, sync=dataclasses.replace(cfg.sync, dry_run=True))

    state = read_json_file(cfg.sync.state_file, {})
    if not isinstance(state, dict):
        state = {}

    try:
        if args.test_notification:
            send_notifications(cfg, test=True)
            return 0

        if args.auth_only:
            get_google_service(
                cfg,
                auth_host=args.auth_host,
                auth_bind_addr=args.auth_bind_addr,
                auth_port=args.auth_port,
                open_browser=False,
            )
            logging.info("Google OAuth abgeschlossen. Token-Datei: %s", cfg.google.token_file)
            return 0

        if len(cfg.plans) > 1:
            logging.info("Mehrquellen-Sync aktiv: %s Quellen in Kalender(n): %s", len(cfg.plans), ", ".join(cfg.google.calendar_ids))

        total_stats = empty_stats()
        dumped_plans: List[Dict[str, Any]] = []

        for therapy_source in cfg.plans:
            plan_cfg = config_for_plan(cfg, therapy_source)
            logging.info(
                "Synchronisiere Quelle '%s' (id=%s, source=%s, colorId=%s, Kalender=%s, reminder=%s)",
                therapy_source.display_name,
                therapy_source.plan_id,
                therapy_source.source_name,
                therapy_source.color_id or "<Standard>",
                ", ".join(config_for_plan(cfg, therapy_source).google.calendar_ids),
                (f"{therapy_source.reminder_minutes} min" if therapy_source.reminder_minutes is not None else (f"{cfg.sync.reminder_minutes} min" if cfg.sync.reminder_minutes is not None else "Kalenderstandard")),
            )
            try:
                client = TherapyPlanClient(plan_cfg, state)
                plan = client.fetch_plan()
                if args.dump_plan:
                    dumped_plans.append({"id": therapy_source.plan_id, "name": therapy_source.display_name, "plan": plan})
                stats = sync_to_google(plan, plan_cfg, state)
                add_stats(total_stats, stats)
                plan_row = {
                    "id": therapy_source.plan_id,
                    "name": therapy_source.display_name,
                    "created": int(stats.get("created", 0)),
                    "updated": int(stats.get("updated", 0)),
                    "unchanged": int(stats.get("unchanged", 0)),
                    "deleted": int(stats.get("deleted", 0)),
                    "errors": int(stats.get("errors", 0)),
                    "calendar_ids": list(plan_cfg.google.calendar_ids),
                    "calendars": stats.get("calendars", []),
                }
                total_stats["plans"].append(plan_row)
            except Exception as exc:
                logging.exception("Quelle '%s' fehlgeschlagen: %s", therapy_source.display_name, exc)
                total_stats["errors"] = int(total_stats.get("errors", 0)) + 1
                total_stats["plans"].append(
                    {
                        "id": therapy_source.plan_id,
                        "name": therapy_source.display_name,
                        "created": 0,
                        "updated": 0,
                        "unchanged": 0,
                        "deleted": 0,
                        "errors": 1,
                    }
                )
                total_stats["error_messages"].append(f"{therapy_source.display_name}: {exc}")

        if args.dump_plan:
            dump_path = resolve_path(cfg.base_dir, args.dump_plan)
            if len(dumped_plans) == 1:
                dump_plan(dumped_plans[0]["plan"], dump_path)
            else:
                write_json_atomic(
                    dump_path,
                    {
                        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                        "plans": dumped_plans,
                    },
                )
                logging.info("Plan-Dump für %s Quellen gespeichert: %s", len(dumped_plans), dump_path)

        state["google_last_sync_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        state["google_last_stats"] = total_stats
        write_json_atomic(cfg.sync.state_file, state)
        write_stats_if_requested(cfg.base_dir, args.stats_file, total_stats)
        send_notifications(cfg, stats=total_stats)
        logging.info("Fertig. Gesamtstatistik: %s", total_stats)
        return 0 if int(total_stats.get("errors", 0)) == 0 else 2
    except Exception as exc:
        logging.exception("Abbruch: %s", exc)
        error_stats = empty_stats()
        error_stats["errors"] = 1
        error_stats["error_messages"] = [str(exc)]
        try:
            write_stats_if_requested(cfg.base_dir, args.stats_file, error_stats)
        except Exception:
            logging.exception("Stats-Datei konnte nicht geschrieben werden.")
        try:
            send_notifications(cfg, error=str(exc))
        except Exception:
            logging.exception("Fehlerbenachrichtigung konnte nicht gesendet werden.")
        try:
            state["google_last_stats"] = error_stats
            write_json_atomic(cfg.sync.state_file, state)
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
