#!/usr/bin/env bash
set -Eeuo pipefail

APPLICATION_ROOT="${APPLICATION_ROOT:-/home/deploy/medical-rag-assistant}"
ENV_FILE="${ENV_FILE:-$APPLICATION_ROOT/deploy/.env}"
LETSENCRYPT_DIR="${LETSENCRYPT_DIR:-/etc/letsencrypt}"
identifier=""
confirm_disable=""

while (($#)); do
  case "$1" in
    --identifier)
      identifier="${2:-}"
      shift 2
      ;;
    --confirm-disable)
      confirm_disable="${2:-}"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -z "$identifier" ]] || [[ "$confirm_disable" != "$identifier" ]]; then
  echo "--confirm-disable must exactly match --identifier." >&2
  exit 2
fi

cd "$APPLICATION_ROOT"
docker compose \
  --env-file "$ENV_FILE" \
  -f compose.yaml \
  up -d --force-recreate web

echo "HTTPS_DISABLE_OK identifier=$identifier certificates_preserved=$LETSENCRYPT_DIR"
