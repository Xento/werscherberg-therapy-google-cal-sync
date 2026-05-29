#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOKEN_FILE="${PROJECT_ROOT}/data/token.json"

backup_invalid() {
  local reason="$1"
  local ts
  ts="$(date -u +%Y%m%dT%H%M%SZ)"
  local target="${TOKEN_FILE}.invalid-${ts}"
  mv "$TOKEN_FILE" "$target"
  echo "token.json wurde wegen folgendem Problem verschoben: $reason"
  echo "Sicherung: $target"
  echo
  echo "Nächste Schritte:"
  echo "1. ./scripts/init-google-auth.sh"
  echo "2. ./scripts/run-once.sh"
}

echo "Prüfe Google OAuth Token-Datei: $TOKEN_FILE"

if [[ ! -e "$TOKEN_FILE" ]]; then
  echo "Keine token.json vorhanden."
  echo "Nächster Schritt: ./scripts/init-google-auth.sh"
  exit 0
fi

if [[ ! -s "$TOKEN_FILE" ]]; then
  backup_invalid "Datei ist leer"
  exit 0
fi

if python3 - <<PY
import json
from pathlib import Path
p = Path(r"$TOKEN_FILE")
obj = json.loads(p.read_text(encoding="utf-8"))
if not isinstance(obj, dict):
    raise SystemExit(2)
required = ["client_id", "client_secret", "refresh_token", "token", "token_uri"]
missing = [k for k in required if not obj.get(k)]
if missing:
    raise SystemExit(3)
PY
then
  echo "token.json ist gültig und enthält die erwarteten OAuth-Felder."
  echo "Kein Reparaturschritt notwendig."
  echo "Nächster Test: ./scripts/run-once.sh"
  exit 0
else
  backup_invalid "Datei ist kein gültiges OAuth-Token-JSON oder enthält nicht alle Pflichtfelder"
  exit 1
fi
