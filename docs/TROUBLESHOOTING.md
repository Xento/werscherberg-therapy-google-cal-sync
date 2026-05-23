# Fehlerbehebung

## OAuth-Link zeigt auf falschen Port

Prüfen:

```bash
grep -R "8080\|6080" .
```

In `.env` sollte stehen:

```env
GOOGLE_AUTH_PORT=6080
```

In `docker-compose.yml` muss der `google-auth`-Service `${GOOGLE_AUTH_PORT:-6080}` verwenden.

Alte Auth-Container entfernen:

```bash
docker rm -f therapieplan-calendar-auth werscherberg-google-auth 2>/dev/null || true
docker compose build google-auth
./scripts/init-google-auth.sh
```

## Port ist bereits belegt

```bash
sudo ss -ltnp | grep ':6080'
docker ps --format "table {{.Names}}\t{{.Ports}}" | grep 6080
```

Dann entweder den belegenden Dienst stoppen oder in `.env` einen anderen Port setzen, z. B.:

```env
GOOGLE_AUTH_PORT=6081
GOOGLE_AUTH_HOST=localhost
GOOGLE_AUTH_PUBLISH_ADDR=127.0.0.1
```

Danach:

```bash
docker compose build google-auth
./scripts/init-google-auth.sh
```

## `access_denied` beim Google-Login

Mögliche Ursachen:

- OAuth Consent Screen ist `External` und dein Konto ist kein Test User.
- Falsches Google-Konto verwendet.
- App wurde nicht korrekt konfiguriert.

Lösung:

1. Google Cloud Console öffnen.
2. `Google Auth Platform` → `Audience`.
3. Deine Google-Adresse als Test User eintragen.
4. Login erneut ausführen.

## `redirect_uri_mismatch`

In der Regel wurde der OAuth-Client falsch angelegt.

Lösung:

- OAuth Client neu erstellen.
- Typ: `Desktop application`.
- JSON neu herunterladen.
- Als `data/credentials.json` speichern.
- `data/token.json` löschen.
- `./scripts/init-google-auth.sh` erneut ausführen.

## `credentials.json not found`

Prüfen:

```bash
ls -l data/credentials.json
```

Die Datei muss exakt so heißen:

```text
data/credentials.json
```

## `token.json` wird nicht erzeugt

Prüfen:

- OAuth-Link wurde geöffnet?
- Browser konnte zurück auf `http://<host>:6080/`?
- Port im Netzwerk erreichbar?
- Container läuft noch?

Logs:

```bash
docker logs -f therapieplan-calendar-auth
```

## Google Calendar API nicht aktiviert

Fehlerbild:

```text
Google Calendar API has not been used in project ... before or it is disabled
```

Lösung:

- Google Cloud Projekt öffnen.
- Google Calendar API aktivieren.
- Einige Minuten warten.
- Sync erneut ausführen.

## 403 / insufficient permissions

Mögliche Ursachen:

- Zielkalender-ID falsch.
- Der OAuth-Account hat keine Schreibrechte.
- `token.json` stammt von falschem Google-Konto.

Lösung:

```bash
rm data/token.json
./scripts/init-google-auth.sh
```

Dann mit dem korrekten Konto anmelden.

## Termine werden nicht in den erwarteten Kalender geschrieben

Prüfen:

```yaml
google:
  calendar_ids:
    - "..."
```

Wenn bei einem Plan eigene Kalender gesetzt sind, überschreiben diese die globale Liste:

```yaml
therapy_plans:
  - id: "person-1"
    calendar_ids:
      - "..."
```

## Termine sind privat/vertraulich

Setze:

```yaml
sync:
  visibility: "default"
```

Danach:

```bash
./scripts/run-once.sh
```

## Abgesagte Termine werden nicht gemeldet

Setze:

```yaml
sync:
  delete_missing_future: true
```

Nur dann löscht der Sync Termine, die nicht mehr in der Quelle vorhanden sind, und kann sie als `Abgesagt` melden.

## Pushover sendet nicht

Prüfen:

```bash
./scripts/diagnose-pushover.sh
./scripts/test-notification.sh
```

Wichtige Werte:

```env
NOTIFICATIONS_ENABLED=1
PUSHOVER_ENABLED=1
PUSHOVER_TOKEN=...
PUSHOVER_USER=...
```

`PUSHOVER_TOKEN` ist der Application/API Token. `PUSHOVER_USER` ist der User Key.

## Pushover Emergency schlägt fehl

Für `priority=2` braucht Pushover zwingend:

```env
PUSHOVER_LEVEL2_RETRY=60
PUSHOVER_LEVEL2_EXPIRE=1800
```

`retry` muss mindestens 30 Sekunden betragen.

## Home Assistant sendet nicht

Prüfen:

```env
HOMEASSISTANT_ENABLED=1
HOMEASSISTANT_URL=http://homeassistant.local:8123
HOMEASSISTANT_TOKEN=...
HOMEASSISTANT_NOTIFY_SERVICE=mobile_app_dein_handy
```

In Home Assistant kann der korrekte Notify-Service unter Entwicklerwerkzeuge → Aktionen/Dienste geprüft werden. Die Companion-App-Dokumentation beschreibt `notify.mobile_app_<device_id>` als typisches Serviceformat: <https://companion.home-assistant.io/docs/notifications/notifications-basic/>

## Der erste Lauf erzeugt viele „Neu“-Meldungen

Das ist erwartbar, wenn der Kalender vorher leer war oder sich `source_name` / `therapy_plans[].id` geändert hat. Danach werden nur echte Änderungen gemeldet.

## Termine doppelt vorhanden

Ursachen:

- `therapy_plans[].id` wurde geändert.
- `sync.source_name` wurde geändert.
- Migration von alter Einzel-URL-Version auf Multi-URL-Version.
- Zielkalender geändert, ohne alte Termine zu entfernen.

Lösung:

- IDs stabil lassen.
- Doppelte, alte Termine manuell aus dem Kalender entfernen.
- Danach `./scripts/run-once.sh`.

## Therapieplan-Login schlägt fehl

Prüfen:

- URL vollständig und mit abschließendem `/`?
- Geburtsdatum im erwarteten Format, z. B. `TT.MM.JJJJ`?
- Therapieplan-Link im Browser noch gültig?
- Firewall/Proxy blockiert Zugriff vom Container?

Dry-Run mit Verbose:

```bash
VERBOSE=1 ./scripts/dry-run.sh
```

Oder in `.env`:

```env
VERBOSE=1
```

## `Network is unreachable` zu `oauth2.googleapis.com`

Fehlerbild:

```text
HTTPSConnectionPool(host='oauth2.googleapis.com', port=443)
Failed to establish a new connection: [Errno 101] Network is unreachable
```

Das ist kein Therapieplan-Loginfehler. Der Container konnte in diesem Moment den Google-OAuth-Token-Endpunkt nicht erreichen. Typische Ursachen:

- Docker-Host hatte kurzzeitig kein Internet.
- DNS-/Routingproblem im Docker-Netz.
- Firewall/Proxy blockiert ausgehende HTTPS-Verbindungen aus Containern.
- Kurzzeitiges Netzwerkproblem direkt während einer Google-Token-Aktualisierung.

Prüfen:

```bash
docker exec -it therapieplan-calendar-sync sh
python - <<'PY'
import urllib.request
print(urllib.request.urlopen('https://oauth2.googleapis.com/token', timeout=10).status)
PY
```

Ein HTTP-Fehler wie `405` wäre als Erreichbarkeitstest ausreichend, weil der Endpunkt erreichbar ist. Ein DNS-, Timeout- oder Network-Unreachable-Fehler weist auf Netzwerk/Routing hin.

Die geplanten Neuversuche können solche kurzzeitigen Fehler abfangen:

```env
SYNC_RETRY_ENABLED=1
SYNC_RETRY_MAX_ATTEMPTS=3
SYNC_RETRY_DELAY_SECONDS=300
SYNC_RETRY_WHEN_ERRORS=1
```

## Neuversuche laufen zu oft

Wenn bei jedem geplanten Zeitpunkt zusätzliche Läufe erfolgen, liegt das meist an:

```env
SYNC_RETRY_WHEN_NO_CHANGES=1
```

Dann wird auch bei einem erfolgreichen Lauf ohne Kalenderänderungen erneut versucht. Wenn du nur Fehler erneut versuchen willst:

```env
SYNC_RETRY_WHEN_NO_CHANGES=0
SYNC_RETRY_WHEN_ERRORS=1
```
