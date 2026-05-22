# Installation

Diese Anleitung beschreibt die Installation unter Linux mit Docker Compose.

## Voraussetzungen

- Linux-Host oder Linux-VM
- Docker Engine
- Docker Compose Plugin (`docker compose`)
- ausgehender HTTPS-Zugriff auf:
  - die Therapieplan-Webseite
  - Google APIs
  - optional Pushover oder Home Assistant
- Google-Konto mit Schreibrechten auf den Zielkalender

## 1. Docker installieren

Debian/Ubuntu-Beispiel:

```bash
sudo apt update
sudo apt install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
```

Danach gemäß Docker-Dokumentation das passende Repository für deine Distribution einrichten und installieren:

```bash
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

Docker aktivieren:

```bash
sudo systemctl enable --now docker
```

Optional den aktuellen Benutzer in die Docker-Gruppe aufnehmen:

```bash
sudo usermod -aG docker "$USER"
```

Danach einmal abmelden/anmelden.

## 2. Projekt vorbereiten

Aus ZIP:

```bash
unzip therapieplan-calendar-sync-container-github-docs.zip -d therapieplan-calendar-sync
cd therapieplan-calendar-sync
```

Aus Git:

```bash
git clone <repository-url> therapieplan-calendar-sync
cd therapieplan-calendar-sync
```

## 3. Beispielkonfiguration kopieren

```bash
cp .env.example .env
cp data/config.example.yaml data/config.yaml
```


## 4. Zugriffsrechte setzen

```bash
chmod +x scripts/*.sh
chmod 600 .env data/config.yaml 2>/dev/null || true
```

Wenn echte Google-/Pushover-Schlüssel eingetragen sind, sollten `.env`, `data/config.yaml`, `data/credentials.json`, `data/token.json` und `data/state.json` nicht für andere Benutzer lesbar sein.

## 5. Container bauen

```bash
docker compose build
```

## 6. Google-OAuth einrichten

Die Google-Einrichtung ist im Detail in [GOOGLE_SETUP.md](GOOGLE_SETUP.md) beschrieben.

Kurzform:

```bash
cp ~/Downloads/client_secret_*.json data/credentials.json
./scripts/init-google-auth.sh
```

Nach erfolgreichem Login muss diese Datei existieren:

```bash
ls -l data/token.json
```

## 7. Therapieplan und Kalender konfigurieren

Öffne:

```bash
nano data/config.yaml
```

Mindestens setzen:

```yaml
therapy_plans:
  - id: "person-1"
    name: "Person 1"
    url: "https://rehaklinik-werscherberg.ssint-online.de:996/ipp/app/DEIN_TOKEN/"
    birth_date: "TT.MM.JJJJ"

google:
  calendar_ids:
    - "primary"
```

Für einen separaten Kalender trägst du dessen Kalender-ID ein:

```yaml
google:
  calendar_ids:
    - "abcdef1234567890@group.calendar.google.com"
```

## 8. Testlauf ohne Änderungen

```bash
./scripts/dry-run.sh
```

Der Dry-Run ruft den Therapieplan ab und schreibt eine Diagnoseausgabe, ändert aber keine Google-Kalendertermine.

## 9. Einmaliger echter Sync

```bash
./scripts/run-once.sh
```

Prüfe danach Google Kalender.

## 10. Dauerbetrieb starten

```bash
docker compose up -d therapieplan-sync
```

Oder:

```bash
./scripts/start.sh
```

## 11. Autostart nach Reboot

In `docker-compose.yml` ist für den Hauptcontainer gesetzt:

```yaml
restart: unless-stopped
```

Damit der Container nach einem Host-Neustart wieder startet, muss Docker selbst automatisch starten:

```bash
sudo systemctl enable --now docker
```

## 12. Status prüfen

```bash
docker ps
./scripts/logs.sh
```
