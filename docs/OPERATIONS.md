# Betrieb

## Dauerbetrieb starten

```bash
./scripts/start.sh
```

Der Container nutzt die Sync-Zeiten aus `data/config.yaml`:

```yaml
scheduler:
  sync_times:
    - "07:30"
    - "10:00"
    - "12:00"
    - "18:00"
```

## Stoppen

```bash
./scripts/stop.sh
```

## Logs

```bash
./scripts/logs.sh
```

## Einmaliger Sync

```bash
./scripts/run-once.sh
```

`run-once.sh` nutzt dieselbe `data/config.yaml` und sendet Pushmeldungen gemäß `notifications.*`.

## Dry-Run

```bash
./scripts/dry-run.sh
```

## Pushover testen

Normale Testmeldung:

```bash
./scripts/test-notification.sh
```

Alle drei Eskalationsstufen testen:

```bash
./scripts/test-pushover-levels.sh
```

Die Stufen werden aus `data/config.yaml` gelesen. Token/User kommen bevorzugt aus `.env`.

## Token prüfen/reparieren

```bash
./scripts/check-google-token.sh
```

Bei defekter `token.json`:

```bash
./scripts/repair-google-token.sh
./scripts/init-google-auth.sh
./scripts/run-once.sh
```

## Nach Änderungen an `data/config.yaml` oder `.env`

```bash
./scripts/stop.sh
./scripts/start.sh
```

Nach Code-/Patchänderungen:

```bash
./scripts/stop.sh
docker compose build --no-cache therapieplan-sync
./scripts/start.sh
```
