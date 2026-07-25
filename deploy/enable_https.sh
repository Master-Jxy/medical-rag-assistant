#!/usr/bin/env bash
set -Eeuo pipefail

APPLICATION_ROOT="${APPLICATION_ROOT:-/home/deploy/medical-rag-assistant}"
ENV_FILE="${ENV_FILE:-$APPLICATION_ROOT/deploy/.env}"
ACME_WEBROOT="${ACME_WEBROOT:-/var/lib/medical-rag/acme}"
LETSENCRYPT_DIR="${LETSENCRYPT_DIR:-/etc/letsencrypt}"

domain=""
email=""
no_email=0
expected_ip=""
confirm_issue=""
staging=0

usage() {
  cat <<'EOF'
Usage:
  bash deploy/enable_https.sh \
    --domain demo.example.com \
    --email operator@example.com \
    --expected-ip 203.0.113.10 \
    --confirm-issue demo.example.com \
    [--staging]

Use --no-email instead of --email only when no authorized ACME contact address
is available. Certificate renewal will still work, but expiry notices are lost.
EOF
}

while (($#)); do
  case "$1" in
    --domain)
      domain="${2:-}"
      shift 2
      ;;
    --email)
      email="${2:-}"
      shift 2
      ;;
    --no-email)
      no_email=1
      shift
      ;;
    --expected-ip)
      expected_ip="${2:-}"
      shift 2
      ;;
    --confirm-issue)
      confirm_issue="${2:-}"
      shift 2
      ;;
    --staging)
      staging=1
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ ! "$domain" =~ ^[A-Za-z0-9.-]+$ ]] || [[ "$domain" != *.* ]]; then
  echo "A valid DNS hostname is required." >&2
  exit 2
fi
if ((no_email)) && [[ -n "$email" ]]; then
  echo "Use exactly one of --email or --no-email." >&2
  exit 2
fi
if ((!no_email)) && [[ ! "$email" =~ ^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$ ]]; then
  echo "A valid ACME contact email or --no-email is required." >&2
  exit 2
fi
if [[ ! "$expected_ip" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
  echo "A valid expected IPv4 address is required." >&2
  exit 2
fi
if [[ "$confirm_issue" != "$domain" ]]; then
  echo "--confirm-issue must exactly match --domain." >&2
  exit 2
fi
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Environment file not found: $ENV_FILE" >&2
  exit 2
fi
if ! command -v certbot >/dev/null 2>&1; then
  echo "certbot is required. Install the Ubuntu certbot package first." >&2
  exit 2
fi

if ((staging)); then
  LETSENCRYPT_DIR="$LETSENCRYPT_DIR/staging"
fi

cd "$APPLICATION_ROOT"
export HTTPS_DOMAIN="$domain" ACME_WEBROOT LETSENCRYPT_DIR

mapfile -t resolved_ips < <(
  getent ahostsv4 "$domain" |
    awk '{print $1}' |
    sort -u
)
if [[ ! " ${resolved_ips[*]} " =~ " $expected_ip " ]]; then
  echo "DNS precheck failed: $domain does not resolve to $expected_ip." >&2
  exit 1
fi

compose_base=(
  docker compose
  --env-file "$ENV_FILE"
  -f compose.yaml
)
bootstrap_compose=(
  "${compose_base[@]}"
  -f deploy/compose.https-bootstrap.yaml
)
https_compose=(
  "${compose_base[@]}"
  -f deploy/compose.https.yaml
)

"${bootstrap_compose[@]}" config --quiet
"${https_compose[@]}" config --quiet

install -d -m 755 "$ACME_WEBROOT/.well-known/acme-challenge"
install -d -m 700 "$LETSENCRYPT_DIR"

state="precheck"
restore_http_on_error() {
  exit_code=$?
  if [[ "$state" == "finalizing" ]]; then
    echo "HTTPS activation failed; restoring the HTTP ACME configuration." >&2
    "${bootstrap_compose[@]}" up -d --force-recreate --wait --wait-timeout 60 web || true
  fi
  exit "$exit_code"
}
trap restore_http_on_error ERR

"${bootstrap_compose[@]}" up -d --force-recreate --wait --wait-timeout 60 web
state="bootstrap"

probe_name="medical-rag-https-precheck-$$"
probe_path="$ACME_WEBROOT/.well-known/acme-challenge/$probe_name"
printf '%s' "$probe_name" >"$probe_path"
trap 'rm -f "$probe_path"' EXIT
probe_result="$(
  curl --fail --silent --show-error \
    --max-time 10 \
    -H "Host: $domain" \
    "http://127.0.0.1/.well-known/acme-challenge/$probe_name"
)"
if [[ "$probe_result" != "$probe_name" ]]; then
  echo "Local ACME webroot probe failed." >&2
  exit 1
fi

certbot_args=(
  certonly
  --webroot
  --webroot-path "$ACME_WEBROOT"
  --non-interactive
  --agree-tos
  --keep-until-expiring
  --domain "$domain"
)
if ((no_email)); then
  certbot_args+=(--register-unsafely-without-email)
else
  certbot_args+=(--email "$email" --no-eff-email)
fi
if ((staging)); then
  certbot_args+=(--staging)
fi
certbot "${certbot_args[@]}"

test -s "$LETSENCRYPT_DIR/live/$domain/fullchain.pem"
test -s "$LETSENCRYPT_DIR/live/$domain/privkey.pem"

if ((staging)); then
  state="complete"
  echo "HTTPS_STAGING_OK domain=$domain expected_ip=$expected_ip"
  exit 0
fi

state="finalizing"
"${https_compose[@]}" up -d --force-recreate --wait --wait-timeout 60 web

https_probe_args=(
  --fail
  --silent
  --show-error
  --max-time 15
  --resolve "$domain:443:127.0.0.1"
)
curl "${https_probe_args[@]}" "https://$domain/api/v1/health" >/dev/null

state="complete"
echo "HTTPS_ENABLE_OK domain=$domain expected_ip=$expected_ip staging=$staging"
