#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DRILL_COMPOSE="${REPO_ROOT}/deploy/test-fixtures/compose.backup-drill.yaml"
DRILL_ENV="${REPO_ROOT}/deploy/test-fixtures/backup-drill.env.example"
DRILL_ROOT="$(mktemp -d /tmp/medical-rag-backup-drill.XXXXXX)"
export COMPOSE_PROJECT_NAME="medical-rag-drill-$(date -u +%Y%m%d%H%M%S)-$$"

[[ "${COMPOSE_PROJECT_NAME}" == medical-rag-drill-* ]] || {
  printf 'unsafe drill project name\n' >&2
  exit 1
}

compose=(
  docker compose --env-file "${DRILL_ENV}" -f "${DRILL_COMPOSE}"
  -p "${COMPOSE_PROJECT_NAME}"
)

cleanup() {
  "${compose[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
  rm -rf -- "${DRILL_ROOT}"
}
trap cleanup EXIT

"${compose[@]}" up -d --wait --wait-timeout 180
"${compose[@]}" exec -T mysql sh -ec '
  mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" -e "
    CREATE TABLE restore_probe (id INT PRIMARY KEY, value_text VARCHAR(30));
    INSERT INTO restore_probe VALUES (1, '\''baseline'\'');"
'
"${compose[@]}" exec -T backend sh -ec '
  mkdir -p /app/data/uploads /app/chroma_db
  printf baseline-app > /app/data/uploads/probe.txt
  printf baseline-chroma > /app/chroma_db/probe.txt
'
"${compose[@]}" exec -T redis redis-cli SET restore_probe baseline >/dev/null

ENV_FILE="${DRILL_ENV}" COMPOSE_FILE="${DRILL_COMPOSE}" \
  BACKUP_ROOT="${DRILL_ROOT}/backups" BACKUP_RETENTION_COUNT=2 \
  "${REPO_ROOT}/deploy/backup.sh"
backup_dir="$(find "${DRILL_ROOT}/backups" -mindepth 1 -maxdepth 1 -type d -name 'backup-*')"
[[ -n "${backup_dir}" ]] || {
  printf 'drill backup was not created\n' >&2
  exit 1
}

"${compose[@]}" exec -T mysql sh -ec '
  mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" -e "
    UPDATE restore_probe SET value_text = '\''mutated'\'' WHERE id = 1;"
'
"${compose[@]}" exec -T backend sh -ec '
  printf mutated-app > /app/data/uploads/probe.txt
  printf mutated-chroma > /app/chroma_db/probe.txt
'
"${compose[@]}" exec -T redis redis-cli SET restore_probe mutated >/dev/null

ENV_FILE="${DRILL_ENV}" COMPOSE_FILE="${DRILL_COMPOSE}" \
  "${REPO_ROOT}/deploy/restore.sh" \
  --backup "${backup_dir}" \
  --confirm-project "${COMPOSE_PROJECT_NAME}" \
  --confirm-restore \
  --skip-safety-backup

mysql_value="$("${compose[@]}" exec -T mysql sh -ec '
  mysql -N -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" -e "
    SELECT value_text FROM restore_probe WHERE id = 1;"
')"
app_value="$("${compose[@]}" exec -T backend cat /app/data/uploads/probe.txt)"
chroma_value="$("${compose[@]}" exec -T backend cat /app/chroma_db/probe.txt)"
redis_value="$("${compose[@]}" exec -T redis redis-cli --raw GET restore_probe)"

[[ "${mysql_value}" == baseline ]]
[[ "${app_value}" == baseline-app ]]
[[ "${chroma_value}" == baseline-chroma ]]
[[ "${redis_value}" == baseline ]]
printf 'BACKUP_RESTORE_DRILL_OK project=%s\n' "${COMPOSE_PROJECT_NAME}"
