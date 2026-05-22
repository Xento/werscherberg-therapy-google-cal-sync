# Therapieplan → Google Kalender Sync

Docker-basierter Sync für Therapiepläne der Werscherberg-Webseite in Google Kalender. Das Projekt ruft die Therapieplan-JSON-Schnittstelle ab, schreibt Termine in einen oder mehrere Google-Kalender, aktualisiert geänderte Termine und kann entfernte Termine als abgesagt behandeln. Optional werden Pushbenachrichtigungen über Pushover oder Home Assistant versendet.

## Funktionsumfang

- mehrere Therapieplan-URLs / Personen in einem Container
- ein oder mehrere Zielkalender pro Plan oder global
- getrennte Sync-Kennungen pro Plan und Kalender
- Google-Event-Farben pro Plan
- Google-Kalender-Erinnerungen pro Termin
- konfigurierbare Sichtbarkeit, z. B. `default` statt `private`
- Sync zu festen Uhrzeiten, z. B. `06:00,12:00,18:00,22:00`
- Pushbenachrichtigung bei neuen, geänderten und entfernten Terminen
- dreistufige Pushover-Intensität:
  - Stufe 0: Änderungen für spätere Tage
  - Stufe 1: Änderungen am gleichen Tag
  - Stufe 2: Änderungen im nächsten Abschnitt bis zum nächsten Sync-Zeitpunkt
- einmaliger Google-OAuth-Login, danach automatischer Betrieb mit `token.json`

## Dokumentation

Für eine vollständige Einrichtung lies die Dokumentation in dieser Reihenfolge:

1. [Installation](docs/INSTALLATION.md)
2. [Google Calendar API und OAuth einrichten](docs/GOOGLE_SETUP.md)
3. [Konfiguration](docs/CONFIGURATION.md)
4. [Betrieb, Tests und Updates](docs/OPERATIONS.md)
5. [Fehlerbehebung](docs/TROUBLESHOOTING.md)
6. [Sicherheit und Datenschutz](docs/SECURITY.md)

## Schnellstart

```bash
git clone <repository-url> therapieplan-calendar-sync
cd therapieplan-calendar-sync

cp .env.example .env
cp data/config.example.yaml data/config.yaml
```

Danach anpassen:

```bash
nano .env
nano data/config.yaml
```

Google-OAuth-Datei ablegen:

```bash
cp ~/Downloads/client_secret_*.json data/credentials.json
```

Initialen Google-Login ausführen:

```bash
./scripts/init-google-auth.sh
```

Testlauf ohne Kalenderänderungen:

```bash
./scripts/dry-run.sh
```

Einmaliger echter Sync:

```bash
./scripts/run-once.sh
```

Dauerbetrieb starten:

```bash
docker compose up -d --build therapieplan-sync
```

Logs anzeigen:

```bash
./scripts/logs.sh
```

## Minimale Beispielkonfiguration

`data/config.yaml`:

```yaml
therapy:
  request_timeout_seconds: 30
  verify_tls: true
  user_agent: "therapieplan-calendar-sync/1.3"

therapy_plans:
  - id: "person-1"
    name: "Person 1"
    url: "https://rehaklinik-werscherberg.ssint-online.de:996/ipp/app/DEIN_TOKEN/"
    birth_date: "TT.MM.JJJJ"
    color_id: "6"
    event_prefix: ""

google:
  credentials_file: "credentials.json"
  token_file: "token.json"
  calendar_ids:
    - "primary"
  timezone: "Europe/Berlin"

sync:
  state_file: "state.json"
  source_name: "therapieplan-sync"
  include_past_days: 0
  delete_missing_future: true
  dry_run: false
  include_details_in_description: true
  visibility: "default"
  transparency: "opaque"
  reminders:
    use_default: false
    overrides:
      - method: "popup"
        minutes: 20
      - method: "popup"
        minutes: 10
```

`.env`:

```env
TZ=Europe/Berlin
SYNC_TIMES=06:00,12:00,18:00,22:00
RUN_ON_START=0

NOTIFICATIONS_ENABLED=1
NOTIFY_ON_CHANGES=1
NOTIFY_ON_ERRORS=1
NOTIFY_ON_SUCCESS_NO_CHANGES=0
NOTIFY_INCLUDE_CHANGE_DETAILS=1

PUSHOVER_ENABLED=1
PUSHOVER_TOKEN=dein_application_api_token
PUSHOVER_USER=dein_user_key
PUSHOVER_DEVICE=

PUSHOVER_LEVEL0_PRIORITY=0
PUSHOVER_LEVEL0_SOUND=pushover
PUSHOVER_LEVEL1_PRIORITY=1
PUSHOVER_LEVEL1_SOUND=persistent
PUSHOVER_LEVEL2_PRIORITY=2
PUSHOVER_LEVEL2_SOUND=echo
PUSHOVER_LEVEL2_RETRY=60
PUSHOVER_LEVEL2_EXPIRE=1800

GOOGLE_AUTH_HOST=localhost
GOOGLE_AUTH_BIND_ADDR=0.0.0.0
GOOGLE_AUTH_PORT=6080
GOOGLE_AUTH_PUBLISH_ADDR=127.0.0.1
```

## Repository-Struktur

```text
.
├── Dockerfile
├── docker-compose.yml
├── README.md
├── requirements.txt
├── sync_daemon.py
├── therapieplan_sync.py
├── .env.example
├── data/
│   ├── README.md
│   ├── config.example.yaml
│   └── config.example.yaml
├── docs/
│   ├── INSTALLATION.md
│   ├── GOOGLE_SETUP.md
│   ├── CONFIGURATION.md
│   ├── OPERATIONS.md
│   ├── TROUBLESHOOTING.md
│   └── SECURITY.md
└── scripts/
    ├── init-google-auth.sh
    ├── dry-run.sh
    ├── run-once.sh
    ├── start.sh
    ├── stop.sh
    ├── logs.sh
    ├── test-notification.sh
    ├── diagnose-pushover.sh
    └── test-pushover-levels.sh
```

## Wichtige Hinweise

- `data/credentials.json`, `data/token.json`, `data/state.json` und echte Therapieplan-URLs enthalten sensible Daten und gehören nicht in Git.
- Der Google-Account, mit dem OAuth durchgeführt wird, muss Schreibrechte auf alle Zielkalender haben.
- Wenn `delete_missing_future: true` gesetzt ist, werden zukünftige Kalendertermine gelöscht, die in der jeweiligen Therapieplan-Quelle nicht mehr vorhanden sind. Nur so kann eine Entfernung als „Abgesagt“ gemeldet werden.
- Für Pushover `priority=2` sind `retry` und `expire` Pflicht.
