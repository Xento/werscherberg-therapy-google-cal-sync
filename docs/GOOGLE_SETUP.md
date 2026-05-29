# Google Calendar API und OAuth einrichten

Der Sync schreibt über die Google Calendar API in deinen Kalender. Dafür wird ein einmaliger OAuth-Login benötigt. Danach nutzt der Container das gespeicherte `data/token.json`.

## Überblick

Benötigt werden:

1. Google Cloud Projekt
2. aktivierte Google Calendar API
3. OAuth Consent Screen / Google Auth Platform
4. OAuth Client vom Typ `Desktop application`
5. heruntergeladene JSON-Datei als `data/credentials.json`
6. einmaliger Login über `./scripts/init-google-auth.sh`

Google beschreibt im Python-Quickstart ebenfalls die Aktivierung der Calendar API, die Konfiguration des OAuth Consent Screens und das Erstellen eines Desktop-OAuth-Clients. Siehe: <https://developers.google.com/workspace/calendar/api/quickstart/python>

## 1. Google Cloud Projekt erstellen

1. Öffne <https://console.cloud.google.com/>
2. Erstelle ein neues Projekt oder wähle ein vorhandenes Projekt.
3. Vergib z. B. den Namen `Therapieplan Calendar Sync`.

## 2. Google Calendar API aktivieren

1. Öffne im Projekt: `APIs & Services` → `Library`.
2. Suche `Google Calendar API`.
3. Öffne den Treffer.
4. Klicke auf `Enable` / `Aktivieren`.

Ohne aktivierte Calendar API kann der OAuth-Login zwar funktionieren, aber der spätere API-Zugriff schlägt fehl.

## 3. OAuth Consent Screen / Google Auth Platform einrichten

1. Öffne `Google Auth Platform` → `Branding`.
2. Falls noch nicht eingerichtet, klicke auf `Get started`.
3. Trage ein:
   - App name: `Therapieplan Sync`
   - User support email: deine E-Mail-Adresse
   - Developer contact information: deine E-Mail-Adresse
4. Audience:
   - bei Google Workspace intern: `Internal`, sofern verfügbar
   - bei privatem Gmail-Konto: normalerweise `External`
5. Speichern.

### Test User eintragen

Wenn die App im Status `Testing` bleibt und `External` verwendet wird:

1. Öffne `Google Auth Platform` → `Audience`.
2. Unter `Test users` deine Google-E-Mail-Adresse hinzufügen.

Sonst kann beim Login `access_denied` erscheinen.

## 4. OAuth Client erstellen

1. Öffne `Google Auth Platform` → `Clients`.
2. `Create client`.
3. Application type: `Desktop application`.
4. Name: `Therapieplan Sync Desktop Client`.
5. Erstellen.
6. JSON-Datei herunterladen.

Die Datei im Projekt speichern als:

```bash
cp ~/Downloads/client_secret_*.json data/credentials.json
chmod 600 data/credentials.json
```

Wichtig: Nicht als Web Application anlegen. Für dieses Projekt ist `Desktop application` korrekt.

## 5. OAuth-Port konfigurieren

Für den Google-OAuth-Login muss der Redirect-Host **localhost** bleiben. Verwende keine private IP-Adresse wie `192.168.x.x` als `GOOGLE_AUTH_HOST`, weil Google diesen Redirect bei Desktop-OAuth-Clients ablehnen kann.

Standard in `.env`:

```env
GOOGLE_AUTH_HOST=localhost
GOOGLE_AUTH_BIND_ADDR=0.0.0.0
GOOGLE_AUTH_PORT=6080
GOOGLE_AUTH_PUBLISH_ADDR=127.0.0.1
```

Das passt, wenn Browser und Docker-Host derselbe Rechner sind.

### Docker-Host ohne Browser: Variante A mit SSH-Tunnel

Empfohlen, wenn der Browser auf einem anderen Rechner läuft:

```bash
ssh -L 6080:127.0.0.1:6080 benutzer@DOCKER_HOST_IP
```

Danach bleibt `.env` auf `localhost` und der Link `http://localhost:6080/` funktioniert im Browser deines PCs über den Tunnel.

### Docker-Host ohne Browser: Variante B mit manuellem Hostwechsel im Redirect-Link

Diese Variante ist nützlich, wenn du keinen SSH-Tunnel nutzen willst. Wichtig: Auch hier bleibt der OAuth-Redirect für Google auf `localhost`. Nur der finale Browseraufruf wird manuell an den Docker-Host geschickt.

`.env`:

```env
GOOGLE_AUTH_HOST=localhost
GOOGLE_AUTH_BIND_ADDR=0.0.0.0
GOOGLE_AUTH_PORT=6080
GOOGLE_AUTH_PUBLISH_ADDR=0.0.0.0
```

Ablauf:

1. Starte den Login:

   ```bash
   ./scripts/init-google-auth.sh
   ```

2. Öffne die angezeigte Google-URL im Browser.
3. Melde dich bei Google an.
4. Google leitet danach auf eine URL ähnlich dieser um:

   ```text
   http://localhost:6080/?state=...&code=...&scope=...
   ```

5. Wenn dein Browser nicht auf dem Docker-Host läuft, kann `localhost` nicht funktionieren. Ändere dann **nur den Hostnamen** in der Adresszeile, lasse Pfad und Query unverändert:

   ```text
   http://DOCKER_HOST_IP:6080/?state=...&code=...&scope=...
   ```

   Beispiel:

   ```text
   http://192.168.158.10:6080/?state=...&code=...&scope=...
   ```

6. Drücke Enter. Der Container erhält dadurch den Authorization Code und erzeugt `data/token.json`.

Nicht setzen:

```env
GOOGLE_AUTH_HOST=192.168.158.10
```

Das würde die private IP bereits in den Google-Redirect einbauen und kann zu `Fehler 400: invalid_request` führen.

## 6. Login starten

```bash
./scripts/init-google-auth.sh
```

Im Terminal erscheint eine Google-URL. Diese im Browser öffnen, anmelden und Kalenderzugriff erlauben.

Nach erfolgreichem Login entsteht:

```text
data/token.json
```

Diese Datei enthält Access-/Refresh-Token und muss vertraulich behandelt werden.

## 7. Zielkalender bestimmen

### Hauptkalender

```yaml
google:
  calendar_ids:
    - "primary"
```

### Separater Kalender

Empfohlen ist ein eigener Kalender, z. B. `Therapieplan`.

In Google Kalender:

1. Kalender erstellen oder vorhandenen Kalender auswählen.
2. Einstellungen öffnen.
3. `Kalender integrieren` öffnen.
4. `Kalender-ID` kopieren.

Dann in `data/config.yaml`:

```yaml
google:
  calendar_ids:
    - "abcdef1234567890@group.calendar.google.com"
```

## 8. Mehrere Zielkalender

```yaml
google:
  calendar_ids:
    - "primary"
    - "abcdef1234567890@group.calendar.google.com"
```

Der Google-Account aus `token.json` muss in allen Zielkalendern Termine erstellen und ändern dürfen.

## 9. Berechtigungen prüfen

Wenn der Sync mit `403`, `forbidden` oder `insufficient permissions` fehlschlägt:

- Kalender-ID prüfen.
- Prüfen, ob der eingeloggte Google-Account Schreibrechte auf diesen Kalender hat.
- Bei geteilten Kalendern mindestens `Make changes to events` vergeben.
- Falls der OAuth Scope geändert wurde: `data/token.json` löschen und `./scripts/init-google-auth.sh` erneut ausführen.

## 10. Technische Hinweise

Das Projekt nutzt Google-Calendar-Events mit u. a.:

- `summary` für den Termintext
- `start` / `end` für Uhrzeiten
- `location` für Raum/Ort, sofern vorhanden
- `colorId` für die Event-Farbe
- `visibility`, z. B. `default`
- `transparency`, z. B. `opaque`
- `reminders` für Erinnerungen
- `extendedProperties.private` für interne Sync-Metadaten

Google dokumentiert diese Event-Felder unter: <https://developers.google.com/workspace/calendar/api/v3/reference/events>

Die internen Sync-Metadaten werden in privaten Extended Properties gespeichert. Google beschreibt Extended Properties als versteckte Key-Value-Paare für anwendungsspezifische Metadaten: <https://developers.google.com/workspace/calendar/api/guides/extended-properties>
