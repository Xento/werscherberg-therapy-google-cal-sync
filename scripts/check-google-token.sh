#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOKEN_FILE="${PROJECT_ROOT}/data/token.json"
CREDENTIALS_FILE="${PROJECT_ROOT}/data/credentials.json"

status=0

section() {
  echo
  echo "== $1 =="
}

ok() {
  echo "OK: $1"
}

warn() {
  echo "WARNUNG: $1"
}

fail() {
  echo "FEHLER: $1"
  status=1
}

section "Google OAuth Token-Prüfung"
echo "Projekt: $PROJECT_ROOT"
echo "Token-Datei: $TOKEN_FILE"
echo "Credentials-Datei: $CREDENTIALS_FILE"

section "1. credentials.json"
if [[ ! -e "$CREDENTIALS_FILE" ]]; then
  fail "data/credentials.json fehlt."
  echo "Maßnahme: OAuth-Client-JSON aus der Google Cloud Console nach data/credentials.json kopieren."
elif [[ ! -s "$CREDENTIALS_FILE" ]]; then
  fail "data/credentials.json ist leer."
  echo "Maßnahme: Datei ersetzen und erneut prüfen."
elif python3 - <<PY
import json
from pathlib import Path
p = Path(r"$CREDENTIALS_FILE")
obj = json.loads(p.read_text(encoding="utf-8"))
if not isinstance(obj, dict) or not (obj.get("installed") or obj.get("web")):
    raise SystemExit(2)
PY
then
  ok "credentials.json ist gültiges JSON und sieht wie eine Google-OAuth-Client-Datei aus."
else
  fail "credentials.json ist kein gültiges Google-OAuth-Client-JSON."
  echo "Maßnahme: Datei aus der Google Cloud Console erneut herunterladen und als data/credentials.json ablegen."
fi

section "2. token.json"
if [[ ! -e "$TOKEN_FILE" ]]; then
  warn "data/token.json ist noch nicht vorhanden."
  echo "Maßnahme: Einmalige Google-Anmeldung starten: ./scripts/init-google-auth.sh"
  exit "$status"
fi

if [[ ! -s "$TOKEN_FILE" ]]; then
  fail "data/token.json ist leer."
  echo "Maßnahme: ./scripts/repair-google-token.sh ausführen, danach ./scripts/init-google-auth.sh."
  exit "$status"
fi

python3 - <<PY
import json
import sys
from pathlib import Path
from datetime import datetime, timezone

p = Path(r"$TOKEN_FILE")
try:
    obj = json.loads(p.read_text(encoding="utf-8"))
except Exception as exc:
    print(f"FEHLER: token.json ist kein gültiges JSON: {exc}")
    print("Maßnahme: ./scripts/repair-google-token.sh ausführen, danach ./scripts/init-google-auth.sh.")
    sys.exit(1)

if not isinstance(obj, dict):
    print("FEHLER: token.json enthält kein JSON-Objekt.")
    print("Maßnahme: ./scripts/repair-google-token.sh ausführen, danach ./scripts/init-google-auth.sh.")
    sys.exit(1)

required = ["client_id", "client_secret", "refresh_token", "token", "token_uri"]
missing = [k for k in required if not obj.get(k)]
if missing:
    print("FEHLER: token.json ist JSON, aber es fehlen OAuth-Felder: " + ", ".join(missing))
    print("Maßnahme: data/token.json sichern/löschen und Google-Anmeldung neu starten: ./scripts/init-google-auth.sh")
    sys.exit(1)

print("OK: token.json ist gültiges JSON und enthält die erwarteten OAuth-Felder.")

expiry = obj.get("expiry")
if expiry:
    print(f"Info: gespeicherter Access-Token-Ablauf: {expiry}")
    try:
        exp = datetime.fromisoformat(str(expiry).replace("Z", "+00:00"))
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < datetime.now(timezone.utc):
            print("Info: Access Token ist abgelaufen, aber ein Refresh Token ist vorhanden. Das ist normal; der Sync erneuert ihn automatisch.")
        else:
            print("OK: Access Token ist noch nicht abgelaufen.")
    except Exception:
        print("WARNUNG: expiry konnte nicht ausgewertet werden. Wenn der Sync fehlschlägt, Google-Anmeldung erneuern.")
else:
    print("WARNUNG: token.json enthält kein expiry-Feld. Wenn der Sync fehlschlägt, Google-Anmeldung erneuern.")

scopes = obj.get("scopes") or []
if isinstance(scopes, str):
    scopes = [scopes]
calendar_scope_found = any("calendar" in str(scope) for scope in scopes)
if calendar_scope_found:
    print("OK: Calendar-Scope ist im Token enthalten.")
else:
    print("WARNUNG: Im Token wurde kein Calendar-Scope erkannt.")
    print("Maßnahme bei 403/insufficient permissions: data/token.json löschen und ./scripts/init-google-auth.sh erneut ausführen.")
PY
rc=$?
if [[ $rc -ne 0 ]]; then
  status=1
fi

section "3. Handlungsempfehlung"
if [[ $status -eq 0 ]]; then
  echo "Token-Dateien sehen grundsätzlich korrekt aus."
  echo "Nächster Test: ./scripts/run-once.sh"
else
  echo "Mindestens eine Prüfung ist fehlgeschlagen."
  echo "Empfohlene Reihenfolge:"
  echo "1. ./scripts/repair-google-token.sh"
  echo "2. ./scripts/init-google-auth.sh"
  echo "3. ./scripts/run-once.sh"
fi

exit "$status"
