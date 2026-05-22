#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

docker compose --profile tools run --rm --entrypoint python test-notification - <<'PY'
import os
import re
import sys

required = ["PUSHOVER_ENABLED", "PUSHOVER_TOKEN", "PUSHOVER_USER"]
print("Pushover-Konfiguration im Container:")
for name in required + ["PUSHOVER_DEVICE", "PUSHOVER_PRIORITY", "PUSHOVER_SOUND", "NOTIFICATIONS_ENABLED"]:
    value = os.environ.get(name, "")
    if name in {"PUSHOVER_TOKEN", "PUSHOVER_USER"}:
        shown = "<leer>" if not value else f"{value[:4]}...{value[-4:]} ({len(value)} Zeichen)"
    else:
        shown = value if value else "<leer>"
    print(f"  {name}={shown}")

errors = []
if os.environ.get("PUSHOVER_ENABLED", "").strip().lower() not in {"1", "true", "yes", "on"}:
    errors.append("PUSHOVER_ENABLED ist nicht aktiv. Erwartet: PUSHOVER_ENABLED=1")
for name in ["PUSHOVER_TOKEN", "PUSHOVER_USER"]:
    value = os.environ.get(name, "").strip()
    if not value:
        errors.append(f"{name} fehlt.")
    elif not re.fullmatch(r"[A-Za-z0-9]{30}", value):
        errors.append(f"{name} sieht formal falsch aus. Erwartet: 30 alphanumerische Zeichen.")
priority = os.environ.get("PUSHOVER_PRIORITY", "0").strip() or "0"
if priority == "2":
    errors.append("PUSHOVER_PRIORITY=2 ist Emergency Priority und benötigt retry/expire; verwende hier zunächst 0 oder 1.")
if errors:
    print("\nAuffälligkeiten:")
    for item in errors:
        print(f"  - {item}")
    sys.exit(2)
print("\nGrundkonfiguration sieht plausibel aus. Starte jetzt ./scripts/test-notification.sh für den echten Versandtest.")
PY
