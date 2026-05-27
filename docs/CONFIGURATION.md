# Konfiguration

Die Konfiguration besteht aus zwei Dateien:

```text
.env
 data/config.yaml
```

`.env` enthält Betriebsparameter und Secrets für Pushdienste. `data/config.yaml` enthält Therapieplanquellen, Kalenderziele und Sync-Verhalten.

## 1. `.env`

### Zeitsteuerung

```env
TZ=Europe/Berlin
SYNC_TIMES=06:00,12:00,18:00,22:00
RUN_ON_START=0
```

`SYNC_TIMES` definiert bis zu vier Sync-Zeitpunkte pro Tag. Format:

```text
HH:MM
HH:MM:SS
```

Beispiele:

```env
SYNC_TIMES=07:00,11:30,16:00,21:00
SYNC_TIMES=06:15,12:15,18:15,22:15
```

`RUN_ON_START=1` führt direkt beim Containerstart zusätzlich einen Sync aus.

### Neuversuche nach Sync-Zeitpunkten

```env
SYNC_RETRY_ENABLED=1
SYNC_RETRY_MAX_ATTEMPTS=3
SYNC_RETRY_DELAY_SECONDS=300
SYNC_RETRY_WHEN_NO_CHANGES=1
SYNC_RETRY_WHEN_ERRORS=1
SYNC_STATS_FILE=/app/data/last_sync_stats.json
```

Bedeutung:

| Variable | Bedeutung | Standard |
|---|---|---:|
| `SYNC_RETRY_ENABLED` | Neuversuche aktivieren/deaktivieren | `1` |
| `SYNC_RETRY_MAX_ATTEMPTS` | Anzahl zusätzlicher Versuche nach dem ersten Lauf | `3` |
| `SYNC_RETRY_DELAY_SECONDS` | Abstand zwischen den Neuversuchen in Sekunden | `300` |
| `SYNC_RETRY_WHEN_NO_CHANGES` | Neuversuch, wenn keine Kalenderänderung erkannt wurde | `1` |
| `SYNC_RETRY_WHEN_ERRORS` | Neuversuch bei Fehlern oder Teilfehlern | `1` |
| `SYNC_STATS_FILE` | interne JSON-Statistik für den Daemon | `/app/data/last_sync_stats.json` |

Beispiel: Bei `SYNC_TIMES=06:00,12:00,18:00,22:00` und den Standardwerten läuft ein geplanter Sync um 06:00. Wenn keine neuen/geänderten/gelöschten Termine erkannt wurden oder ein Fehler auftrat, folgen bis zu drei Neuversuche um 06:05, 06:10 und 06:15.

### Google OAuth Redirect

Browser auf demselben Host:

```env
GOOGLE_AUTH_HOST=localhost
GOOGLE_AUTH_BIND_ADDR=0.0.0.0
GOOGLE_AUTH_PORT=6080
GOOGLE_AUTH_PUBLISH_ADDR=127.0.0.1
```

Browser auf anderem Rechner im LAN:

```env
GOOGLE_AUTH_HOST=192.0.2.10
GOOGLE_AUTH_BIND_ADDR=0.0.0.0
GOOGLE_AUTH_PORT=6080
GOOGLE_AUTH_PUBLISH_ADDR=0.0.0.0
```

### Pushbenachrichtigung allgemein

```env
NOTIFICATIONS_ENABLED=1
NOTIFY_ON_CHANGES=1
NOTIFY_ON_ERRORS=1
NOTIFY_ON_SUCCESS_NO_CHANGES=1
NOTIFICATION_TITLE_PREFIX=Therapieplan
NOTIFY_INCLUDE_CHANGE_DETAILS=1
NOTIFY_MAX_CHANGE_ITEMS=12
NOTIFY_MAX_MESSAGE_CHARS=950
```

### Drei Pushover-Stufen

```env
NOTIFY_INTENSE_SAME_DAY_CHANGES=1
NOTIFY_INTENSE_NEXT_SYNC_WINDOW_CHANGES=1
```

| Stufe | Bedeutung |
|---:|---|
| 0 | Änderung betrifft spätere Tage |
| 1 | Änderung betrifft den aktuellen Kalendertag |
| 2 | Änderung betrifft das nächste Zeitfenster bis zum nächsten Sync-Zeitpunkt |

Beispiel bei `SYNC_TIMES=06:00,12:00,18:00,22:00`:

| Lauf | Stufe-2-Zeitfenster |
|---|---|
| 06:00 | 06:00 bis 12:00 |
| 12:00 | 12:00 bis 18:00 |
| 18:00 | 18:00 bis 22:00 |
| 22:00 | 22:00 bis 06:00 am Folgetag |

Pushover je Stufe:

```env
PUSHOVER_LEVEL0_PRIORITY=0
PUSHOVER_LEVEL0_SOUND=pushover
PUSHOVER_LEVEL0_RETRY=60
PUSHOVER_LEVEL0_EXPIRE=1800

PUSHOVER_LEVEL1_PRIORITY=1
PUSHOVER_LEVEL1_SOUND=persistent
PUSHOVER_LEVEL1_RETRY=60
PUSHOVER_LEVEL1_EXPIRE=1800

PUSHOVER_LEVEL2_PRIORITY=2
PUSHOVER_LEVEL2_SOUND=echo
PUSHOVER_LEVEL2_RETRY=60
PUSHOVER_LEVEL2_EXPIRE=1800
```

Pushover `priority=2` ist Emergency und benötigt `retry` und `expire`. Die Pushover-API beschreibt diese Parameter hier: <https://pushover.net/api>

### Pushover Zugangsdaten

```env
PUSHOVER_ENABLED=1
PUSHOVER_TOKEN=dein_application_api_token
PUSHOVER_USER=dein_user_key
PUSHOVER_DEVICE=
```

- `PUSHOVER_TOKEN`: Application/API Token
- `PUSHOVER_USER`: User Key
- `PUSHOVER_DEVICE`: optional; leer = alle Geräte

### Home Assistant

```env
HOMEASSISTANT_ENABLED=0
HOMEASSISTANT_URL=http://homeassistant.local:8123
HOMEASSISTANT_TOKEN=
HOMEASSISTANT_NOTIFY_SERVICE=mobile_app_dein_handy
```

Bei Home Assistant Companion App heißen Notify-Services typischerweise `notify.mobile_app_<device_id>` oder im Skript kurz `mobile_app_<device_id>`.

## 2. `data/config.yaml`

### Globale Therapieplan-Defaults

```yaml
therapy:
  request_timeout_seconds: 30
  verify_tls: true
  user_agent: "therapieplan-calendar-sync/1.5"
```

### Mehrere Therapiepläne

```yaml
therapy_plans:
  - id: "person-1"
    name: "Person 1"
    url: "https://rehaklinik-werscherberg.ssint-online.de:996/ipp/app/DEIN_TOKEN_1/"
    birth_date: "TT.MM.JJJJ"
    access_token: ""
    color_id: "6"
    event_prefix: ""

  - id: "person-2"
    name: "Person 2"
    url: "https://rehaklinik-werscherberg.ssint-online.de:996/ipp/app/DEIN_TOKEN_2/"
    birth_date: "TT.MM.JJJJ"
    access_token: ""
    color_id: "10"
    event_prefix: ""
```

`id` muss stabil bleiben. Wenn du die `id` änderst, erkennt der Sync alte Termine nicht mehr als eigene Termine und kann Duplikate erzeugen.

### Party-Filter

Neuere Therapieplan-JSONs können mehrere Parteien in derselben Antwort enthalten. Das Feld `party` unterscheidet dabei die Zuordnung:

- `party: ""` = Termine ohne benannte Party, typischerweise Eltern-/Begleitpersonen-Termine
- `party: "Person 1"` = Termine dieser benannten Party

Ohne Filter werden alle passenden Termine übernommen:

```yaml
party_filter: "all"
```

Nur Eltern-/Begleitpersonen-Termine mit leerer `party` übernehmen:

```yaml
party_filter: "empty"
```

Nur Termine mit gesetzter Party übernehmen:

```yaml
party_filter: "non_empty"
```

Nur eine konkrete Party übernehmen:

```yaml
party_filter:
  include: ["Person 1"]
```

Mehrere Parteien übernehmen, inklusive leerer Party:

```yaml
party_filter:
  include:
    - ""
    - "Person 1"
```

Alles außer einer bestimmten Party übernehmen:

```yaml
party_filter:
  exclude: ["Person 1"]
```

Kurzformen sind ebenfalls möglich:

```yaml
party: "Person 1"
parties: ["", "Person 1"]
```

### Farben

```yaml
color_id: "6"
```

| ID | Name | Farbe |
|---:|---|---|
| 1 | lavender | Lavendel / helles Lila |
| 2 | sage | Salbei / helles Grün |
| 3 | grape | Violett |
| 4 | flamingo | Rosa / Pink |
| 5 | banana | Gelb |
| 6 | tangerine | Orange |
| 7 | peacock | Türkis / Cyan |
| 8 | graphite | Grau |
| 9 | blueberry | Blau |
| 10 | basil | Grün |
| 11 | tomato | Rot |

Auch Namen sind möglich:

```yaml
color_id: "blueberry"
```

### Zielkalender global

Ein Kalender:

```yaml
google:
  calendar_ids:
    - "primary"
```

Mehrere Kalender:

```yaml
google:
  calendar_ids:
    - "primary"
    - "abcdef1234567890@group.calendar.google.com"
```

### Zielkalender pro Plan

Wenn ein Plan eigene `calendar_ids` hat, überschreibt diese Liste die globale Google-Liste:

```yaml
therapy_plans:
  - id: "person-1"
    name: "Person 1"
    calendar_ids:
      - "person-1-kalender@group.calendar.google.com"

  - id: "person-2"
    name: "Person 2"
    calendar_ids:
      - "primary"
      - "person-2-kalender@group.calendar.google.com"
```

### Sync-Verhalten

```yaml
sync:
  state_file: "state.json"
  source_name: "therapieplan-sync"
  include_past_days: 0
  delete_missing_future: true
  dry_run: false
  include_details_in_description: true
  include_sync_timestamps_in_description: true
  visibility: "default"
  transparency: "opaque"
```

Wichtige Werte:

| Option | Bedeutung |
|---|---|
| `include_past_days` | wie viele vergangene Tage berücksichtigt werden |
| `delete_missing_future` | zukünftige Termine löschen, wenn sie nicht mehr im Plan stehen |
| `include_details_in_description` | Details in Terminbeschreibung übernehmen |
| `include_sync_timestamps_in_description` | Sync-Erstell-/Änderungszeit in der Terminbeschreibung anzeigen |
| `visibility` | `default`, `public`, `private`, `confidential` |
| `transparency` | `opaque` = blockt Zeit, `transparent` = blockt nicht |

Für nicht vertrauliche normale Einträge:

```yaml
visibility: "default"
```

Sync-Zeitstempel in der Beschreibung:

```yaml
include_sync_timestamps_in_description: true
```

Damit schreibt der Sync in den Google-Termin z. B.:

```text
Sync-Informationen:
Erstellt durch Sync: 27.05.2026 21:55:00 CEST
Zuletzt geändert durch Sync: 28.05.2026 07:35:00 CEST
```

Die Zeitstempel werden nicht in die fachliche Änderungs-Signatur aufgenommen. Dadurch erzeugt ein unveränderter Termin nicht bei jedem Lauf erneut eine Änderung.

### Erinnerungen

Zwei Popup-Erinnerungen 20 und 10 Minuten vorher:

```yaml
sync:
  reminders:
    use_default: false
    overrides:
      - method: "popup"
        minutes: 20
      - method: "popup"
        minutes: 10
```

Mögliche Methoden:

```yaml
method: "popup"
method: "email"
```

Google Calendar API unterstützt Reminder-Overrides mit `email` und `popup` sowie Minutenwerten zwischen 0 und 40320. Siehe Event-Resource-Dokumentation: <https://developers.google.com/workspace/calendar/api/v3/reference/events>

### Benachrichtigungskonfiguration in YAML

```yaml
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
```

Werte aus `.env` überschreiben die meisten Provider-/Betriebswerte und sind für Secrets vorzuziehen.

## Terminart

Wenn `sync.include_details_in_description: true` gesetzt ist, schreibt der Sync die Terminart zusätzlich in die Google-Terminbeschreibung, z. B.:

```text
Terminart: Gruppentermin (G)
```

Zusätzlich werden nur diese maschinenlesbaren Werte in `extendedProperties.private` des Google-Termins gespeichert:

| Feld | Bedeutung |
|---|---|
| `form` | Rohwert aus dem Therapieplan, z. B. `E`, `G`, `C` |
| `formLabel` | lesbare Terminart, z. B. `Gruppentermin` |

Unterstützte Terminformen:

| Form | Bedeutung |
|---|---|
| `V` | Termin |
| `A` | allgemeiner Termin |
| `E` | Einzeltermin |
| `C` | kombinierter Termin / Co-Therapie |
| `G` | Gruppentermin |

`form: 1` wird als Hinweis-/Leereintrag behandelt und nicht importiert. Einträge mit gesetztem Hidden-Flag `0x20000000` werden ebenfalls nicht importiert.
