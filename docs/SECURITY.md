# Sicherheit und Datenschutz

Das Projekt verarbeitet sensible Daten:

- Therapieplan-URLs
- Geburtsdaten
- Termine, Räume und ggf. Mitarbeiter/Hinweise
- Google OAuth Tokens
- Pushover-/Home-Assistant-Tokens

## Nicht committen

Diese Dateien dürfen nicht in ein öffentliches Git-Repository:

```text
.env
data/config.yaml
data/credentials.json
data/token.json
data/state.json
data/plan.json
```

Das Paket enthält eine `.gitignore`, die diese Dateien ausschließt.

## Empfohlene Arbeitsweise

- `data/config.example.yaml` versionieren.
- `.env.example` versionieren.
- echte `.env` und echte `data/config.yaml` lokal halten.
- für Backups verschlüsselte Ablage verwenden.

## Dateirechte

```bash
chmod 600 .env data/config.yaml data/credentials.json data/token.json data/state.json 2>/dev/null || true
```

## Google OAuth Token

`data/token.json` erlaubt dem Skript Kalenderzugriff im Rahmen der erteilten OAuth-Rechte. Wenn diese Datei kompromittiert wurde:

1. Google Account öffnen.
2. Sicherheit → Drittanbieterzugriff / Verbindungen prüfen.
3. Zugriff für die App entfernen.
4. `data/token.json` löschen.
5. OAuth neu durchführen.

## Pushover Token

Wenn `PUSHOVER_TOKEN` oder `PUSHOVER_USER` versehentlich veröffentlicht wurde:

- Pushover Application Token neu erzeugen oder App löschen/neu anlegen.
- User Key bei Bedarf im Pushover-Konto zurücksetzen.
- `.env` aktualisieren.

## Kalenderfreigaben

Wenn `sync.visibility: "default"` gesetzt ist, bestimmt die Kalenderfreigabe, wer Details sieht. Prüfe daher die Freigabe des Zielkalenders.

Wenn Details nicht in Terminbeschreibungen landen sollen:

```yaml
sync:
  include_details_in_description: false
```

## Löschlogik

```yaml
sync:
  delete_missing_future: true
```

Diese Option ist fachlich sinnvoll, damit entfernte Termine als abgesagt erkannt werden. Sie löscht aber zukünftige Termine, die vom Sync erzeugt wurden und in der Quelle nicht mehr vorhanden sind. Das Skript sollte deshalb nur auf Kalender schreiben, die für diesen Zweck vorgesehen sind.
