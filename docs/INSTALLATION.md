# Installation

## Voraussetzungen

- Linux-Host mit Docker und Docker Compose
- Google-Konto mit Kalenderzugriff
- Google Cloud OAuth-Client vom Typ Desktop-App
- optional: Pushover oder Home Assistant für Pushmeldungen

## Repository klonen

```bash
git clone <repository-url> therapieplan-calendar-sync
cd therapieplan-calendar-sync
```

## Konfigurationsdateien erstellen

```bash
cp .env.example .env
cp data/config.example.yaml data/config.yaml
```

Danach:

```bash
nano .env
nano data/config.yaml
```

In `.env` stehen nur Secrets und technische Werte. In `data/config.yaml` stehen Therapieplan-URLs, Sync-Zeiten, Kalender, Pushregeln, Farben, Erinnerungen und Filter.

## Google-Credentials ablegen

Die aus Google Cloud heruntergeladene OAuth-Datei muss hier liegen:

```bash
cp ~/Downloads/client_secret_*.json data/credentials.json
```

## Google OAuth initialisieren

```bash
./scripts/init-google-auth.sh
```

Danach sollte `data/token.json` existieren.

Token prüfen:

```bash
./scripts/check-google-token.sh
```

## Test

```bash
./scripts/dry-run.sh
./scripts/run-once.sh
```

## Dauerbetrieb

```bash
./scripts/start.sh
```

Logs:

```bash
./scripts/logs.sh
```
