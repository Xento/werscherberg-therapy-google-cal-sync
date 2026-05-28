# Therapieplan → Google Kalender Sync

Docker-basierter Sync für Werscherberg-Therapiepläne in Google Kalender. Das Projekt ruft die JSON-Schnittstelle der Therapieplan-Webseite ab, schreibt Termine in einen oder mehrere Google-Kalender, aktualisiert Änderungen und kann entfernte Termine als abgesagt behandeln. Optional werden Pushbenachrichtigungen über Pushover oder Home Assistant versendet.

## Konfigurationsprinzip

Die Konfiguration ist bewusst getrennt:

| Datei | Zweck |
|---|---|
| `.env` | Nur technische Containerwerte, OAuth-Port und geheime Tokens |
| `data/config.yaml` | Fachliche Konfiguration: Therapiepläne, Kalender, Zeiten, Retries, Pushregeln, Farben, Erinnerungen |

Damit muss man für den normalen Betrieb fast alles in **einer Datei** pflegen: `data/config.yaml`. In `.env` gehören nur Secrets und wenige Docker-/OAuth-Werte.

## Funktionsumfang

- mehrere Therapieplan-URLs / Personen in einem Container
- ein oder mehrere Zielkalender pro Plan oder global
- Party-Filter für Eltern-/Kind-/Mehrpersonen-JSON
- Google-Event-Farben pro Plan
- Google-Kalender-Erinnerungen pro Termin
- konfigurierbare Sichtbarkeit, z. B. `default` statt `private`
- Sync zu festen Uhrzeiten, konfiguriert in `data/config.yaml`
- automatische Retries nach geplanten Sync-Zeitpunkten
- Pushbenachrichtigung bei neuen, geänderten und entfernten Terminen
- dreistufige Pushover-Intensität:
  - Stufe 0: Änderungen für spätere Tage
  - Stufe 1: Änderungen am gleichen Tag
  - Stufe 2: Änderungen im nächsten Abschnitt bis zum nächsten Sync-Zeitpunkt
- Fehlerdiagnose für Google `token.json`
- einmaliger Google-OAuth-Login, danach automatischer Betrieb mit `token.json`

## Schnellstart

```bash
git clone <repository-url> therapieplan-calendar-sync
cd therapieplan-calendar-sync

cp .env.example .env
cp data/config.example.yaml data/config.yaml
```

Dann bearbeiten:

```bash
nano .env              # nur Tokens/OAuth/Containerwerte
nano data/config.yaml  # Therapiepläne, Kalender, Zeiten, Pushregeln
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
./scripts/start.sh
```

Logs anzeigen:

```bash
./scripts/logs.sh
```

## Minimale `.env`

```env
TZ=Europe/Berlin
VERBOSE=0

PUSHOVER_TOKEN=dein_application_api_token
PUSHOVER_USER=dein_user_key
PUSHOVER_DEVICE=

GOOGLE_AUTH_HOST=localhost
GOOGLE_AUTH_BIND_ADDR=0.0.0.0
GOOGLE_AUTH_PORT=6080
GOOGLE_AUTH_PUBLISH_ADDR=127.0.0.1
```

## Beispiel `data/config.yaml`

```yaml
scheduler:
  sync_times:
    - "07:30"
    - "10:00"
    - "12:00"
    - "18:00"
  run_on_start: false
  retry:
    enabled: true
    max_attempts: 15
    delay_seconds: 60
    when_no_changes: true
    when_errors: true
    stats_file: "last_sync_stats.json"

therapy:
  request_timeout_seconds: 30
  verify_tls: true
  user_agent: "therapieplan-calendar-sync/2.0"

therapy_plans:
  - id: "person-1"
    name: "Person 1"
    url: "https://rehaklinik-werscherberg.ssint-online.de:996/ipp/app/DEIN_TOKEN/"
    birth_date: "TT.MM.JJJJ"
    color_id: "6"
    party_filter: "all"
    calendar_ids:
      - "primary"

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
  include_sync_timestamps_in_description: true
  match_existing_events: true
  match_time_tolerance_minutes: 90
  match_min_score: 8
  visibility: "default"
  transparency: "opaque"
  reminders:
    use_default: false
    overrides:
      - method: "popup"
        minutes: 20
      - method: "popup"
        minutes: 10

notifications:
  enabled: true
  title_prefix: "Therapieplan"
  notify_on:
    changes: true
    errors: true
    success_no_changes: true
  include_change_details: true
  max_change_items: 12
  max_message_chars: 950
  intense_same_day_changes: true
  intense_next_sync_window_changes: true
  providers:
    pushover:
      enabled: true
      token: ""     # besser in .env: PUSHOVER_TOKEN
      user: ""      # besser in .env: PUSHOVER_USER
      device: ""    # optional in .env: PUSHOVER_DEVICE
      priority: 0
      sound: "pushover"
  pushover_levels:
    level0_future:
      priority: 0
      sound: "incoming"
      retry: 60
      expire: 1800
    level1_same_day:
      priority: 1
      sound: "echo"
      retry: 60
      expire: 1800
    level2_next_window:
      priority: 2
      sound: "echo"
      retry: 60
      expire: 1800
```

## Party-Filter

Falls eine Therapieplan-URL mehrere Parteien enthält, kann pro Quelle gefiltert werden:

```yaml
therapy_plans:
  - id: "eltern"
    name: "Eltern"
    url: "https://rehaklinik-werscherberg.ssint-online.de:996/ipp/app/DEIN_TOKEN/"
    birth_date: "TT.MM.JJJJ"
    party_filter: "empty"

  - id: "person-1"
    name: "Person 1"
    url: "https://rehaklinik-werscherberg.ssint-online.de:996/ipp/app/DEIN_TOKEN/"
    birth_date: "TT.MM.JJJJ"
    party_filter:
      include:
        - "Person 1"
```

## Geplante Neuversuche

Retries werden jetzt in `data/config.yaml` unter `scheduler.retry` konfiguriert:

```yaml
scheduler:
  retry:
    enabled: true
    max_attempts: 15
    delay_seconds: 60
    when_no_changes: true
    when_errors: true
```

Bei Retry-Läufen wegen „keine Änderungen“ wird die Pushmeldung für „keine Änderungen“ automatisch unterdrückt. Push kommt bei Retry nur bei echten Änderungen oder Fehlern.

## Dokumentation

Für eine vollständige Einrichtung lies die Dokumentation in dieser Reihenfolge:

1. [Installation](docs/INSTALLATION.md)
2. [Google Calendar API und OAuth einrichten](docs/GOOGLE_SETUP.md)
3. [Konfiguration](docs/CONFIGURATION.md)
4. [Migration auf vereinfachte Config](docs/MIGRATION_CONFIG_V2.md)
5. [Betrieb, Tests und Updates](docs/OPERATIONS.md)
6. [Fehlerbehebung](docs/TROUBLESHOOTING.md)
7. [Sicherheit und Datenschutz](docs/SECURITY.md)

## Wichtige Hinweise

- `data/credentials.json`, `data/token.json`, `data/state.json`, `.env` und echte Therapieplan-URLs enthalten sensible Daten und gehören nicht in Git.
- Der Google-Account, mit dem OAuth durchgeführt wird, muss Schreibrechte auf alle Zielkalender haben.
- Wenn `delete_missing_future: true` gesetzt ist, werden zukünftige Kalendertermine gelöscht, die in der jeweiligen Therapieplan-Quelle nicht mehr vorhanden sind. Nur so kann eine Entfernung als „Abgesagt“ gemeldet werden.
- Für Pushover `priority=2` sind `retry` und `expire` Pflicht.
