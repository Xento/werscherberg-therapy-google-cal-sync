#!/usr/bin/env bash
set -euo pipefail

# Testet die drei Pushover-Eskalationsstufen mit den Werten aus data/config.yaml.
# PUSHOVER_TOKEN/PUSHOVER_USER können aus .env oder aus config.yaml kommen.

docker compose --profile tools run --rm --entrypoint python test-notification - <<'PY'
from pathlib import Path
import os
import requests

from therapieplan_sync import load_config

cfg = load_config(Path('/app/data/config.yaml'))
po = cfg.notifications.pushover

if not po.get('token') or not po.get('user'):
    raise SystemExit('Fehler: Pushover token/user fehlen. Setze PUSHOVER_TOKEN/PUSHOVER_USER in .env oder token/user in config.yaml.')
if not po.get('enabled'):
    print('Hinweis: Pushover ist in config.yaml deaktiviert. Für diesen Test wird trotzdem gesendet, sofern token/user gesetzt sind.')

levels = [
    (0, cfg.notifications.level0_priority, cfg.notifications.level0_sound, cfg.notifications.level0_retry, cfg.notifications.level0_expire, 'Änderungen für spätere Tage'),
    (1, cfg.notifications.level1_priority, cfg.notifications.level1_sound, cfg.notifications.level1_retry, cfg.notifications.level1_expire, 'Änderungen am gleichen Tag'),
    (2, cfg.notifications.level2_priority, cfg.notifications.level2_sound, cfg.notifications.level2_retry, cfg.notifications.level2_expire, 'Änderungen im nächsten Sync-Abschnitt'),
]

for level, priority, sound, retry, expire, label in levels:
    data = {
        'token': po['token'],
        'user': po['user'],
        'title': f'{cfg.notifications.title_prefix}: Test Stufe {level}',
        'message': f'Testmeldung für Stufe {level}: {label}\npriority={priority}, sound={sound or "<default>"}',
        'priority': str(priority),
    }
    if po.get('device'):
        data['device'] = po['device']
    if sound:
        data['sound'] = sound
    if int(priority) == 2:
        data['retry'] = str(retry)
        data['expire'] = str(expire)

    print(f'Sende Stufe {level}: priority={priority}, sound={sound or "<default>"}')
    response = requests.post('https://api.pushover.net/1/messages.json', data=data, timeout=30)
    if response.status_code >= 400:
        print(response.text)
    response.raise_for_status()

print('Pushover-Leveltests gesendet.')
PY
