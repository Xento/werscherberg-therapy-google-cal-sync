# Migration auf die vereinfachte Konfiguration

Die Konfiguration ist jetzt klar getrennt:

| Datei | Inhalt |
|---|---|
| `.env` | Secrets, OAuth-Port, Containerwerte |
| `data/config.yaml` | Sync-Zeiten, Retries, Benachrichtigungen, Kalender und Therapiepläne |

## In `.env` behalten

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

## Nach `data/config.yaml` verschieben

- `SYNC_TIMES` -> `scheduler.sync_times`
- `RUN_ON_START` -> `scheduler.run_on_start`
- `SYNC_RETRY_*` -> `scheduler.retry.*`
- `NOTIFICATIONS_ENABLED` -> `notifications.enabled`
- `NOTIFY_ON_*` -> `notifications.notify_on.*`
- `PUSHOVER_LEVEL*` -> `notifications.pushover_levels.*`
- `PUSHOVER_ENABLED` -> `notifications.providers.pushover.enabled`
- `HOMEASSISTANT_ENABLED` -> `notifications.providers.homeassistant.enabled`

## Vorgehen

```bash
cp .env .env.bak
cp data/config.yaml data/config.yaml.bak
cp .env.example .env
cp data/config.example.yaml data/config.yaml
```

Danach die echten Therapieplan-URLs, Geburtsdaten, Kalender-IDs und Secrets aus den Sicherungen übernehmen.
