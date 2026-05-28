# Konfiguration

## Grundprinzip

Die Konfiguration ist in zwei Dateien getrennt:

| Datei | Zweck |
|---|---|
| `.env` | Container-/OAuth-Werte und Secrets |
| `data/config.yaml` | Fachliche Sync-Konfiguration |

In `.env` sollen nur Werte stehen, die nicht sinnvoll in Git gehören oder schon vor dem Start des Containers benötigt werden, z. B. Pushover-Token und OAuth-Port. Alles andere gehört in `data/config.yaml`.

## `.env`

Minimale `.env`:

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

## `data/config.yaml`

### Scheduler und Retries

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
```

`sync_times` steuert den dauerhaft laufenden Container. `run-once.sh` nutzt weiterhin einen manuellen Einmallauf.

Bei Retry-Läufen wegen „keine Änderungen“ wird die „keine Änderungen“-Pushmeldung unterdrückt. Eine Pushmeldung kommt bei Retry nur bei echten Änderungen oder Fehlern.

### Therapiepläne

```yaml
therapy_plans:
  - id: "person-1"
    name: "Person 1"
    url: "https://rehaklinik-werscherberg.ssint-online.de:996/ipp/app/REPLACE_ME/"
    birth_date: "TT.MM.JJJJ"
    color_id: "6"
    event_prefix: ""
    party_filter: "all"
    calendar_ids:
      - "primary"
```

Wichtige Felder:

| Feld | Bedeutung |
|---|---|
| `id` | stabile technische ID für Sync-Zuordnung |
| `name` | Anzeigename in Logs/Pushmeldungen |
| `url` | vollständige Therapieplan-URL inklusive abschließendem `/` |
| `birth_date` | Geburtsdatum im Format `TT.MM.JJJJ` |
| `color_id` | Google-Event-Farbe |
| `party_filter` | Filter für Mehrpersonen-JSON |
| `calendar_ids` | Zielkalender nur für diesen Plan |

### Party-Filter

```yaml
party_filter: "all"
```

Importiert alle Termine.

```yaml
party_filter: "empty"
```

Importiert nur Termine mit leerer `party`, typischerweise Eltern-/Begleitpersonen-Termine.

```yaml
party_filter: "non_empty"
```

Importiert nur Termine mit gesetzter `party`.

```yaml
party_filter:
  include:
    - "Person 1"
```

Importiert nur Termine dieser Party.

```yaml
party_filter:
  exclude:
    - "Person 1"
```

Importiert alles außer dieser Party.

### Zielkalender

Globaler Fallback:

```yaml
google:
  calendar_ids:
    - "primary"
```

Plan-spezifisch:

```yaml
therapy_plans:
  - id: "person-1"
    calendar_ids:
      - "abcdef1234567890@group.calendar.google.com"
```

Wenn `therapy_plans[].calendar_ids` gesetzt ist, überschreibt es `google.calendar_ids` für diesen Plan.

### Darstellung der Google-Termine

```yaml
sync:
  visibility: "default"
  transparency: "opaque"
  include_details_in_description: true
  include_sync_timestamps_in_description: true
```

`visibility: "default"` legt Termine nicht als vertraulich an.

### Matching vorhandener Termine

Wenn das Backend keine echte Termin-ID liefert, erzeugt der Sync eine eigene interne Kennung. Damit Änderungen an Raum oder Mitarbeiter nicht als neuer Termin plus gelöschter Termin erscheinen, gibt es eine zweite Matching-Stufe:

```yaml
sync:
  match_existing_events: true
  match_time_tolerance_minutes: 90
  match_min_score: 8
```

Die Logik prüft mehrere Kriterien, u. a. Tag, Uhrzeit, Dauer, Titel, Terminart, Party und Ort. Wenn genug Kriterien übereinstimmen, wird der vorhandene Google-Termin aktualisiert und bekommt den neuen `sourceKey`.

Wichtig: Raum und Mitarbeiter sind Teil der Änderungsprüfung, aber nicht mehr Teil der stabilen Termin-Identität. Dadurch werden Änderungen an diesen Feldern korrekt als `updated` erkannt.

### Erinnerungen

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

Mögliche Methoden sind `popup` und `email`.

### Benachrichtigungen

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
```

### Pushover

```yaml
notifications:
  providers:
    pushover:
      enabled: true
      token: ""   # besser in .env: PUSHOVER_TOKEN
      user: ""    # besser in .env: PUSHOVER_USER
      device: ""  # optional in .env: PUSHOVER_DEVICE
      priority: 0
      sound: "pushover"
```

### Drei Pushover-Stufen

```yaml
notifications:
  intense_same_day_changes: true
  intense_next_sync_window_changes: true
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

Stufe 2 gewinnt vor Stufe 1, Stufe 1 gewinnt vor Stufe 0.

## Legacy `.env`-Variablen

Aus Kompatibilitätsgründen werden alte `.env`-Variablen wie `SYNC_TIMES`, `NOTIFICATIONS_ENABLED` oder `PUSHOVER_LEVEL2_SOUND` weiterhin gelesen, wenn die entsprechenden neuen Werte in `data/config.yaml` fehlen.

Für neue Installationen sollten diese Werte aber in `data/config.yaml` stehen.
