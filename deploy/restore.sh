#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

SCRIPT_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="${APPLICATION_ROOT:-${SCRIPT_REPO_ROOT}}"
ENV_FILE="${ENV_FILE:-${REPO_ROOT}/deploy/.env}"
COMPOSE_FILE="${COMPOSE_FILE:-${REPO_ROOT}/compose.yaml}"
BACKUP_DIR=""
CONFIRM_PROJECT=""
CONFIRM_RESTORE=false
SKIP_SAFETY_BACKUP=false

fail() {
  printf 'restore_failed: %s\n' "$*" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --backup)
      BACKUP_DIR="${2:-}"
      shift 2
      ;;
    --confirm-project)
      CONFIRM_PROJECT="${2:-}"
      shift 2
      ;;
    --confirm-restore)
      CONFIRM_RESTORE=true
      shift
      ;;
    --skip-safety-backup)
      SKIP_SAFETY_BACKUP=true
      shift
      ;;
    *)
      fail "unknown argument: $1"
      ;;
  esac
done

[[ -n "${BACKUP_DIR}" && -d "${BACKUP_DIR}" ]] || fail "backup directory is required"
BACKUP_DIR="$(cd "${BACKUP_DIR}" && pwd)"
[[ -f "${ENV_FILE}" ]] || fail "missing env file"
[[ -f "${COMPOSE_FILE}" ]] || fail "missing compose file"
[[ "${CONFIRM_RESTORE}" == true ]] || fail "--confirm-restore is required"
for command_name in docker gzip sha256sum tar awk; do
  command -v "${command_name}" >/dev/null || fail "missing command: ${command_name}"
done

required_files=(
  SHA256SUMS manifest.txt mysql.sql.gz app_data.tar.gz
  chroma_data.tar.gz redis_data.tar.gz deploy.env compose.yaml
)
for required_file in "${required_files[@]}"; do
  [[ -f "${BACKUP_DIR}/${required_file}" ]] || fail "missing backup file: ${required_file}"
done
(
  cd "${BACKUP_DIR}"
  sha256sum -c SHA256SUMS
)
grep -qx 'backup_format=medical-rag-backup-v1' "${BACKUP_DIR}/manifest.txt" \
  || fail "unsupported backup format"

compose=(docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}")
project_name="$("${compose[@]}" config | awk '$1 == "name:" { print $2; exit }')"
[[ -n "${project_name}" ]] || fail "cannot resolve compose project"
[[ "${CONFIRM_PROJECT}" == "${project_name}" ]] \
  || fail "--confirm-project must exactly match ${project_name}"

backend_image="$("${compose[@]}" images -q backend)"
[[ -n "${backend_image}" ]] || fail "cannot resolve backend image"

volume_name() {
  local logical_name="$1"
  local resolved
  resolved="$(docker volume ls \
    --filter "label=com.docker.compose.project=${project_name}" \
    --filter "label=com.docker.compose.volume=${logical_name}" \
    --format '{{.Name}}')"
  [[ -n "${resolved}" && "$(printf '%s\n' "${resolved}" | wc -l)" -eq 1 ]] \
    || fail "cannot uniquely resolve volume: ${logical_name}"
  printf '%s' "${resolved}"
}

restore_volume() {
  local logical_name="$1"
  local archive_name="$2"
  local resolved_volume
  resolved_volume="$(volume_name "${logical_name}")"
  docker run --rm \
    --entrypoint sh \
    --volume "${resolved_volume}:/target" \
    "${backend_image}" \
    -ec 'find /target -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +'
  gzip -dc "${BACKUP_DIR}/${archive_name}" \
    | docker run --rm -i \
        --entrypoint tar \
        --volume "${resolved_volume}:/target" \
        "${backend_image}" \
        -C /target -xf -
}

if [[ "${SKIP_SAFETY_BACKUP}" == false ]]; then
  safety_root="$(dirname "${BACKUP_DIR}")/pre-restore"
  ENV_FILE="${ENV_FILE}" COMPOSE_FILE="${COMPOSE_FILE}" BACKUP_ROOT="${safety_root}" \
    BACKUP_RETENTION_COUNT=3 "${SCRIPT_REPO_ROOT}/backup.sh"
fi

"${compose[@]}" stop backend web redis
restore_volume app_data app_data.tar.gz
restore_volume chroma_data chroma_data.tar.gz
restore_volume redis_data redis_data.tar.gz

"${compose[@]}" up -d --wait --wait-timeout 120 mysql
"${compose[@]}" exec -T mysql sh -ec '
  case "$MYSQL_DATABASE" in *[!A-Za-z0-9_]*) exit 64;; esac
  mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -e "
    DROP DATABASE IF EXISTS \`$MYSQL_DATABASE\`;
    CREATE DATABASE \`$MYSQL_DATABASE\`
      CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
'
gzip -dc "${BACKUP_DIR}/mysql.sql.gz" \
  | "${compose[@]}" exec -T mysql sh -ec \
      'exec mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"'

"${compose[@]}" up -d --wait --wait-timeout 180 redis backend web
"${compose[@]}" ps
printf 'restore_completed: project=%s backup=%s\n' "${project_name}" "${BACKUP_DIR}"
