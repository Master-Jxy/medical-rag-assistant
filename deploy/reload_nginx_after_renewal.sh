#!/usr/bin/env bash
set -Eeuo pipefail

APPLICATION_ROOT="${APPLICATION_ROOT:-/home/deploy/medical-rag-assistant}"
ENV_FILE="${ENV_FILE:-$APPLICATION_ROOT/deploy/.env}"
ACME_WEBROOT="${ACME_WEBROOT:-/var/lib/medical-rag/acme}"
LETSENCRYPT_DIR="${LETSENCRYPT_DIR:-/etc/letsencrypt}"
HTTPS_DOMAIN="${HTTPS_DOMAIN:-${RENEWED_DOMAINS%% *}}"

if [[ -z "$HTTPS_DOMAIN" ]]; then
  echo "HTTPS_DOMAIN or RENEWED_DOMAINS is required." >&2
  exit 2
fi

cd "$APPLICATION_ROOT"
export HTTPS_DOMAIN ACME_WEBROOT LETSENCRYPT_DIR
docker compose \
  --env-file "$ENV_FILE" \
  -f compose.yaml \
  -f deploy/compose.https.yaml \
  exec -T web nginx -s reload
