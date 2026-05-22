# data-Verzeichnis

Dieses Verzeichnis wird in den Container nach `/app/data` gemountet.

## Versionierbare Dateien

- `config.example.yaml` – Beispielkonfiguration ohne echte Zugangsdaten
- `README.md` – diese Datei

## Lokale Dateien, nicht committen

- `config.yaml` – echte Therapieplan-URLs, Geburtsdaten, Kalender-IDs
- `credentials.json` – Google OAuth Client Secret
- `token.json` – Google OAuth Token, wird nach `./scripts/init-google-auth.sh` erzeugt
- `state.json` – Sync-Status und Therapieplan-Access-Tokens
- `plan.json` – optionaler Dump aus Dry-Run

## Erste Einrichtung

```bash
cp data/config.example.yaml data/config.yaml
nano data/config.yaml
```
