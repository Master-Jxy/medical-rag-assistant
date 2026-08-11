#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
ENV_FILE="${ENV_FILE:-${REPO_ROOT}/deploy/.env}"
BASE_URL="${BASE_URL:-http://127.0.0.1}"
HTTPS_IDENTIFIER="${HTTPS_IDENTIFIER:-}"
BACKUP_ROOT="${BACKUP_ROOT:-/home/deploy/medical-rag-backups}"
COMPOSE=(docker compose --env-file "${ENV_FILE}" -f "${REPO_ROOT}/compose.yaml" -f "${REPO_ROOT}/deploy/compose.https.yaml")
failures=0

check() {
  local name="$1"
  shift
  if "$@" >/dev/null 2>&1; then
    printf 'PASS %s\n' "${name}"
  else
    printf 'FAIL %s\n' "${name}"
    failures=$((failures + 1))
  fi
}

check livez curl -fsS --max-time 5 "${BASE_URL}/livez"
check readyz curl -fsS --max-time 5 "${BASE_URL}/readyz"

running="$("${COMPOSE[@]}" ps --status running --services 2>/dev/null || true)"
for service in mysql redis backend worker web; do
  if grep -qx "${service}" <<<"${running}"; then
    printf 'PASS container_%s_running\n' "${service}"
  else
    printf 'FAIL container_%s_running\n' "${service}"
    failures=$((failures + 1))
  fi
done

restart_total=0
while IFS= read -r container_id; do
  [[ -n "${container_id}" ]] || continue
  count="$(docker inspect -f '{{.RestartCount}}' "${container_id}" 2>/dev/null || echo 999)"
  restart_total=$((restart_total + count))
done < <("${COMPOSE[@]}" ps -q)
if (( restart_total == 0 )); then
  printf 'PASS container_restart_count total=0\n'
else
  printf 'FAIL container_restart_count total=%s\n' "${restart_total}"
  failures=$((failures + 1))
fi

disk_used="$(df -P / | awk 'NR==2 {gsub(/%/,"",$5); print $5}')"
if [[ "${disk_used}" =~ ^[0-9]+$ ]] && (( disk_used < 85 )); then
  printf 'PASS disk_usage percent=%s\n' "${disk_used}"
else
  printf 'FAIL disk_usage percent=%s\n' "${disk_used:-unknown}"
  failures=$((failures + 1))
fi

memory_available="$(free -m | awk '/^Mem:/ {print $7}')"
if [[ "${memory_available}" =~ ^[0-9]+$ ]] && (( memory_available >= 128 )); then
  printf 'PASS memory_available_mb value=%s\n' "${memory_available}"
else
  printf 'FAIL memory_available_mb value=%s\n' "${memory_available:-unknown}"
  failures=$((failures + 1))
fi

recent_errors="$(${COMPOSE[@]} logs --since 10m --no-color 2>/dev/null | grep -Eic 'Traceback|Unhandled|CRITICAL|OutOfMemory|Killed process' || true)"
if (( recent_errors == 0 )); then
  printf 'PASS recent_error_markers count=0\n'
else
  printf 'FAIL recent_error_markers count=%s\n' "${recent_errors}"
  failures=$((failures + 1))
fi

latest_manifest="$(find "${BACKUP_ROOT}" -mindepth 2 -maxdepth 2 -name manifest.txt -type f -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -n1 | cut -d' ' -f2- || true)"
if [[ -n "${latest_manifest}" ]] && find "${latest_manifest}" -mmin -1440 -print -quit | grep -q .; then
  printf 'PASS backup_freshness\n'
else
  printf 'FAIL backup_freshness\n'
  failures=$((failures + 1))
fi

if [[ -n "${HTTPS_IDENTIFIER}" ]]; then
  if echo | openssl s_client -servername "${HTTPS_IDENTIFIER}" -connect "${HTTPS_IDENTIFIER}:443" 2>/dev/null | openssl x509 -checkend 1209600 -noout >/dev/null 2>&1; then
    printf 'PASS certificate_14d\n'
  else
    printf 'FAIL certificate_14d\n'
    failures=$((failures + 1))
  fi
else
  printf 'SKIP certificate_14d HTTPS_IDENTIFIER_not_supplied\n'
fi

exit "${failures}"
