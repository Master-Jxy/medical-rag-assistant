#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

SCRIPT_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="${APPLICATION_ROOT:-${SCRIPT_REPO_ROOT}}"
ENV_FILE="${ENV_FILE:-${REPO_ROOT}/deploy/.env}"
BACKUP_ROOT="${BACKUP_ROOT:-/home/deploy/medical-rag-backups}"
BACKUP_RETENTION_COUNT="${BACKUP_RETENTION_COUNT:-7}"
COMPOSE_FILE="${COMPOSE_FILE:-${REPO_ROOT}/compose.yaml}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
STAGING_DIR="${BACKUP_ROOT}/.incomplete-${STAMP}"
FINAL_DIR="${BACKUP_ROOT}/backup-${STAMP}"

fail() {
  printf 'backup_failed: %s\n' "$*" >&2
  exit 1
}

cleanup_staging() {
  if [[ -d "${STAGING_DIR}" ]]; then
    rm -rf -- "${STAGING_DIR}"
  fi
}
trap cleanup_staging ERR INT TERM

[[ -f "${ENV_FILE}" ]] || fail "missing env file"
[[ -f "${COMPOSE_FILE}" ]] || fail "missing compose file"
[[ "${BACKUP_ROOT}" = /* && "${BACKUP_ROOT}" != "/" ]] || fail "unsafe backup root"
[[ "${BACKUP_RETENTION_COUNT}" =~ ^[1-9][0-9]*$ ]] || fail "invalid retention count"
for command_name in docker gzip sha256sum tar awk date install; do
  command -v "${command_name}" >/dev/null || fail "missing command: ${command_name}"
done

mkdir -p -- "${BACKUP_ROOT}"
chmod 700 "${BACKUP_ROOT}"
[[ ! -e "${STAGING_DIR}" && ! -e "${FINAL_DIR}" ]] || fail "backup timestamp collision"
mkdir -- "${STAGING_DIR}"

compose=(docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}")
project_name="$("${compose[@]}" config | awk '$1 == "name:" { print $2; exit }')"
[[ -n "${project_name}" ]] || fail "cannot resolve compose project"

for service in mysql redis backend; do
  container_id="$("${compose[@]}" ps -q "${service}")"
  [[ -n "${container_id}" ]] || fail "service is not running: ${service}"
done

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

archive_volume() {
  local logical_name="$1"
  local output_name="$2"
  local resolved_volume
  resolved_volume="$(volume_name "${logical_name}")"
  docker run --rm \
    --entrypoint tar \
    --volume "${resolved_volume}:/source:ro" \
    "${backend_image}" \
    -C /source -czf - . > "${STAGING_DIR}/${output_name}"
  [[ -s "${STAGING_DIR}/${output_name}" ]] || fail "empty archive: ${logical_name}"
}

"${compose[@]}" exec -T mysql sh -ec \
  'exec mysqldump -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" \
    --single-transaction --routines --events --triggers --no-tablespaces \
    --set-gtid-purged=OFF' \
  | gzip -1 > "${STAGING_DIR}/mysql.sql.gz"
[[ -s "${STAGING_DIR}/mysql.sql.gz" ]] || fail "empty mysql dump"

"${compose[@]}" exec -T redis redis-cli SAVE >/dev/null
archive_volume app_data app_data.tar.gz
archive_volume chroma_data chroma_data.tar.gz
archive_volume redis_data redis_data.tar.gz

install -m 600 "${ENV_FILE}" "${STAGING_DIR}/deploy.env"
install -m 600 "${COMPOSE_FILE}" "${STAGING_DIR}/compose.yaml"
git_commit="$(
  git -c "safe.directory=${REPO_ROOT}" -C "${REPO_ROOT}" rev-parse HEAD 2>/dev/null \
    || printf 'unknown'
)"
if git_status="$(
  git -c "safe.directory=${REPO_ROOT}" -C "${REPO_ROOT}" status --porcelain 2>/dev/null
)"; then
  git_dirty="$(printf '%s' "${git_status}" | awk 'NF { count++ } END { print count + 0 }')"
else
  git_dirty=unknown
fi
cat > "${STAGING_DIR}/manifest.txt" <<EOF
backup_format=medical-rag-backup-v1
created_at_utc=${STAMP}
compose_project=${project_name}
git_commit=${git_commit}
git_dirty_entries=${git_dirty}
contents=mysql,app_data,chroma_data,redis_data,deploy_env,compose
EOF

(
  cd "${STAGING_DIR}"
  sha256sum \
    mysql.sql.gz app_data.tar.gz chroma_data.tar.gz redis_data.tar.gz \
    deploy.env compose.yaml manifest.txt > SHA256SUMS
  sha256sum -c SHA256SUMS >/dev/null
)

mv -- "${STAGING_DIR}" "${FINAL_DIR}"
trap - ERR INT TERM

mapfile -t backups < <(
  find "${BACKUP_ROOT}" -mindepth 1 -maxdepth 1 -type d -name 'backup-*' -printf '%f\n' \
    | sort -r
)
for ((index=BACKUP_RETENTION_COUNT; index<${#backups[@]}; index++)); do
  rm -rf -- "${BACKUP_ROOT:?}/${backups[index]}"
done

printf 'backup_completed: %s\n' "${FINAL_DIR}"
