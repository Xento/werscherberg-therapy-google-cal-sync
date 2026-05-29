# Migration auf die vereinfachte Konfiguration

## Ziel

Die alte Konfiguration war auf `.env` und `data/config.yaml` verteilt. Die neue Struktur ist:

| Datei | Inhalt |
|---|---|
| `.env` | Secrets, OAuth-Port, Containerwerte |
| `data/config.yaml` | alles Fachliche: Zeitplan, Retry, Pushregeln, Kalender, Therapiepläne |

## Was aus `.env` nach `data/config.yaml` wandert

| Alter `.env`-Wert | Neuer Ort in `data/config.yaml` |
|---|---|
| `SYNC_TIMES` | `scheduler.sync_times` |
| `RUN_ON_START` | `scheduler.run_on_start` |
| `SYNC_RETRY_*` | `scheduler.retry.*` |
| `NOTIFICATIONS_ENABLED` | `notifications.enabled` |
| `NOTIFY_ON_*` | `notifications.notify_on.*` |
| `NOTIFY_INCLUDE_CHANGE_DETAILS` | `notifications.include_change_details` |
| `NOTIFY_MAX_CHANGE_ITEMS` | `notifications.max_change_items` |
| `NOTIFY_MAX_MESSAGE_CHARS` | `notifications.max_message_chars` |
| `NOTIFY_INTENSE_*` | `notifications.intense_*` |
| `PUSHOVER_ENABLED` | `notifications.providers.pushover.enabled` |
| `PUSHOVER_PRIORITY/SOUND` | `notifications.providers.pushover.priority/sound` |
| `PUSHOVER_LEVEL*` | `notifications.pushover_levels.*` |
| `HOMEASSISTANT_ENABLED/URL/NOTIFY_SERVICE` | `notifications.providers.homeassistant.*` |

## Was in `.env` bleiben soll

```env
TZ=Europe/Berlin
VERBOSE=0

PUSHOVER_TOKEN=
PUSHOVER_USER=
PUSHOVER_DEVICE=
HOMEASSISTANT_TOKEN=

GOOGLE_AUTH_HOST=localhost
GOOGLE_AUTH_BIND_ADDR=0.0.0.0
GOOGLE_AUTH_PORT=6080
GOOGLE_AUTH_PUBLISH_ADDR=127.0.0.1
```

## Vorgehen

1. Aktuelle Dateien sichern:

```bash
cp .env .env.bak
cp data/config.yaml data/config.yaml.bak
```

2. Neue Vorlage übernehmen:

```bash
cp .env.example .env.new
cp data/config.example.yaml data/config.yaml.new
```

3. Aus `.env.bak` nur die Secrets in `.env` übernehmen:

```env
PUSHOVER_TOKEN=...
PUSHOVER_USER=...
PUSHOVER_DEVICE=...
```

4. Therapieplan-URLs, Geburtsdaten, Kalender-IDs und Party-Filter in `data/config.yaml` übernehmen.

5. Prüfen:

```bash
./scripts/diagnose-pushover.sh
./scripts/dry-run.sh
./scripts/run-once.sh
```

6. Dauerbetrieb neu starten:

```bash
./scripts/stop.sh
./scripts/start.sh
```
