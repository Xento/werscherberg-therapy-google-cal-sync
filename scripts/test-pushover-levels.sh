#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${PROJECT_ROOT}/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Fehler: .env nicht gefunden: $ENV_FILE" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

if [[ -z "${PUSHOVER_TOKEN:-}" || -z "${PUSHOVER_USER:-}" ]]; then
  echo "Fehler: PUSHOVER_TOKEN und PUSHOVER_USER müssen in .env gesetzt sein." >&2
  exit 1
fi

send_level() {
  local level="$1"
  local title="$2"
  local message="$3"
  local priority_var="PUSHOVER_LEVEL${level}_PRIORITY"
  local sound_var="PUSHOVER_LEVEL${level}_SOUND"
  local retry_var="PUSHOVER_LEVEL${level}_RETRY"
  local expire_var="PUSHOVER_LEVEL${level}_EXPIRE"
  local priority="${!priority_var:-0}"
  local sound="${!sound_var:-}"
  local retry="${!retry_var:-60}"
  local expire="${!expire_var:-1800}"

  echo "Sende Stufe ${level}: priority=${priority}, sound=${sound:-<default>}"

  args=(
    --silent
    --show-error
    --fail
    --form-string "token=${PUSHOVER_TOKEN}"
    --form-string "user=${PUSHOVER_USER}"
    --form-string "title=${title}"
    --form-string "message=${message}"
    --form-string "priority=${priority}"
  )

  if [[ -n "${PUSHOVER_DEVICE:-}" ]]; then
    args+=(--form-string "device=${PUSHOVER_DEVICE}")
  fi
  if [[ -n "$sound" ]]; then
    args+=(--form-string "sound=${sound}")
  fi
  if [[ "$priority" == "2" ]]; then
    args+=(--form-string "retry=${retry}")
    args+=(--form-string "expire=${expire}")
  fi

  curl "${args[@]}" https://api.pushover.net/1/messages.json
  echo
  echo
}

send_level 0 "Therapieplan Test: Stufe 0" "Normale Änderung für einen späteren Tag."
sleep 2
send_level 1 "Therapieplan Test: Stufe 1" "Änderung am gleichen Tag."
sleep 2
send_level 2 "Therapieplan Test: Stufe 2" "Änderung im nächsten Abschnitt bis zum nächsten Sync-Zeitpunkt."

echo "Pushover-Stufentests gesendet."
