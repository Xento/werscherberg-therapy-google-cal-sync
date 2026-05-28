#!/usr/bin/env bash
set -euo pipefail

docker compose --profile tools run --rm --entrypoint python test-notification - <<'PY'
from pathlib import Path
from therapieplan_sync import load_config

cfg = load_config(Path('/app/data/config.yaml'))
po = cfg.notifications.pushover
errors = []

print('Pushover-Konfiguration:')
print(f'  notifications.enabled = {cfg.notifications.enabled}')
print(f'  pushover.enabled      = {po.get("enabled")}')
print(f'  token                 = {po.get("token", "")[:4]}...{po.get("token", "")[-4:] if po.get("token") else ""}' if po.get('token') else '  token                 = <leer>')
print(f'  user                  = {po.get("user", "")[:4]}...{po.get("user", "")[-4:] if po.get("user") else ""}' if po.get('user') else '  user                  = <leer>')
print(f'  device                = {po.get("device") or "<alle>"}')
print(f'  level0                = priority={cfg.notifications.level0_priority}, sound={cfg.notifications.level0_sound}')
print(f'  level1                = priority={cfg.notifications.level1_priority}, sound={cfg.notifications.level1_sound}')
print(f'  level2                = priority={cfg.notifications.level2_priority}, sound={cfg.notifications.level2_sound}, retry={cfg.notifications.level2_retry}, expire={cfg.notifications.level2_expire}')

if not cfg.notifications.enabled:
    errors.append('notifications.enabled ist false.')
if not po.get('enabled'):
    errors.append('notifications.providers.pushover.enabled ist false.')
if not po.get('token'):
    errors.append('Pushover token fehlt. Setze PUSHOVER_TOKEN in .env oder token in config.yaml.')
if not po.get('user'):
    errors.append('Pushover user fehlt. Setze PUSHOVER_USER in .env oder user in config.yaml.')
if int(cfg.notifications.level2_priority) == 2 and (int(cfg.notifications.level2_retry) < 30 or int(cfg.notifications.level2_expire) <= 0):
    errors.append('Pushover Priority 2 benötigt retry >= 30 und expire > 0.')

if errors:
    print('\nFehler/Hinweise:')
    for error in errors:
        print(f'  - {error}')
    raise SystemExit(1)

print('\nPushover-Konfiguration sieht plausibel aus.')
PY
