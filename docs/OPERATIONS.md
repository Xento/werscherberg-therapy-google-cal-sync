# Betrieb, Tests und Updates

## Container bauen

```bash
docker compose build
```

## Google OAuth initialisieren

```bash
./scripts/init-google-auth.sh
```

Dieser Schritt ist nur einmal notwendig oder wenn `data/token.json` gelöscht/ungültig ist.

## Dry-Run

```bash
./scripts/dry-run.sh
```

Der Dry-Run ruft Daten ab und zeigt geplante Aktionen, schreibt aber keine Kalenderänderungen.

## Einmaliger echter Sync

```bash
./scripts/run-once.sh
```

## Dauerbetrieb starten

```bash
docker compose up -d --build therapieplan-sync
```

Oder:

```bash
./scripts/start.sh
```

## Dauerbetrieb stoppen

```bash
./scripts/stop.sh
```

Oder:

```bash
docker compose down
```

## Logs anzeigen

```bash
./scripts/logs.sh
```

Oder:

```bash
docker logs -f therapieplan-calendar-sync
```

## Status prüfen

```bash
docker ps
```

## Neuversuche prüfen

Die Neuversuche werden im Containerlog protokolliert:

```bash
./scripts/logs.sh
```

Typische Logzeilen:

```text
Neuversuch geplant in 300 Sekunden: keine Kalenderänderungen erkannt
Starte Sync-Neuversuch 1/3.
```

Die zuletzt vom Daemon gelesene Sync-Statistik liegt standardmäßig hier:

```text
data/last_sync_stats.json
```

Anzeigen:

```bash
cat data/last_sync_stats.json
```

## Automatischer Start nach Reboot

Der Service nutzt:

```yaml
restart: unless-stopped
```

Docker selbst muss aktiviert sein:

```bash
sudo systemctl enable --now docker
```

## Pushbenachrichtigungen testen

Normale Provider-Testmeldung:

```bash
./scripts/test-notification.sh
```

Pushover-Diagnose:

```bash
./scripts/diagnose-pushover.sh
```

Drei Pushover-Stufen testen:

```bash
./scripts/test-pushover-levels.sh
```

Das Skript sendet jeweils eine Meldung für Stufe 0, Stufe 1 und Stufe 2.

## Typischer Update-Ablauf

Wenn nur `.env` oder `data/config.yaml` geändert wurden:

```bash
docker compose down
docker compose up -d therapieplan-sync
```

Wenn Code, Dockerfile oder Python-Abhängigkeiten geändert wurden:

```bash
docker compose down
docker compose build --no-cache
docker compose up -d therapieplan-sync
```

## Backup

Vor größeren Änderungen sichern:

```bash
mkdir -p backup
cp .env backup/.env.$(date +%Y%m%d-%H%M%S)
cp data/config.yaml backup/config.yaml.$(date +%Y%m%d-%H%M%S)
cp data/token.json backup/token.json.$(date +%Y%m%d-%H%M%S) 2>/dev/null || true
cp data/state.json backup/state.json.$(date +%Y%m%d-%H%M%S) 2>/dev/null || true
```

## Relevante Laufzeitdateien

| Datei | Zweck |
|---|---|
| `data/credentials.json` | Google OAuth Client Secret |
| `data/token.json` | Google OAuth Access-/Refresh-Token |
| `data/state.json` | Sync-Status, Access-Tokens der Therapieplanquellen |
| `data/plan.json` | optionaler Dump aus Dry-Run |

## Änderungserkennung

Der Sync speichert interne Kennungen in Google Calendar Extended Properties. Dadurch erkennt er eigene Events wieder und kann Updates/Löschungen gezielt durchführen.

Bei mehreren Kalendern wird die Zuordnung pro Zielkalender getrennt behandelt. Dadurch überschreiben sich gleiche Termine in unterschiedlichen Kalendern nicht gegenseitig.

## Duplikate vermeiden

Nicht ändern, nachdem bereits produktiv synchronisiert wurde:

- `therapy_plans[].id`
- `sync.source_name`
- Zielkalender ohne bewusste Migration

Wenn diese Werte geändert werden, kann der Sync alte Events nicht mehr als eigene Events erkennen.
