#!/usr/bin/env bash
set -Eeuo pipefail

APPLICATION_ROOT="${APPLICATION_ROOT:-/home/deploy/medical-rag-assistant}"
ENV_FILE="${ENV_FILE:-$APPLICATION_ROOT/deploy/.env}"
ACME_WEBROOT="${ACME_WEBROOT:-/var/lib/medical-rag/acme}"
LETSENCRYPT_DIR="${LETSENCRYPT_DIR:-/etc/letsencrypt}"
CERTBOT_BIN="${CERTBOT_BIN:-certbot}"

domain=""
ip_address=""
email=""
no_email=0
expected_ip=""
confirm_issue=""
staging=0

usage() {
  cat <<'EOF'
Usage:
  bash deploy/enable_https.sh \
    (--domain demo.example.com | --ip-address 203.0.113.10) \
    --email operator@example.com \
    --expected-ip 203.0.113.10 \
    --confirm-issue <exact domain or IP> \
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
    --ip-address)
      ip_address="${2:-}"
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

if [[ -n "$domain" && -n "$ip_address" ]] || [[ -z "$domain" && -z "$ip_address" ]]; then
  echo "Use exactly one of --domain or --ip-address." >&2
  exit 2
fi
if [[ -n "$domain" ]] && {
  [[ ! "$domain" =~ ^[A-Za-z0-9.-]+$ ]] || [[ "$domain" != *.* ]];
}; then
  echo "A valid DNS hostname is required." >&2
  exit 2
fi
if [[ -n "$ip_address" ]] && [[ ! "$ip_address" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
  echo "A valid public IPv4 identifier is required." >&2
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
identifier="${domain:-$ip_address}"
identifier_type="domain"
if [[ -n "$ip_address" ]]; then
  identifier_type="ip"
fi
if [[ "$confirm_issue" != "$identifier" ]]; then
  echo "--confirm-issue must exactly match the requested identifier." >&2
  exit 2
fi
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Environment file not found: $ENV_FILE" >&2
  exit 2
fi
if ! command -v "$CERTBOT_BIN" >/dev/null 2>&1; then
  echo "certbot is required; IP mode needs Certbot 5.4 or newer." >&2
  exit 2
fi
if [[ "$identifier_type" == "ip" ]]; then
  certbot_version="$("$CERTBOT_BIN" --version 2>&1 | awk '{print $2}')"
  certbot_major="${certbot_version%%.*}"
  certbot_minor="${certbot_version#*.}"
  certbot_minor="${certbot_minor%%.*}"
  if ((certbot_major < 5 || (certbot_major == 5 && certbot_minor < 4))); then
    echo "IP certificates require Certbot 5.4 or newer." >&2
    exit 2
  fi
fi

if ((staging)); then
  LETSENCRYPT_DIR="$LETSENCRYPT_DIR/staging"
fi

cd "$APPLICATION_ROOT"
export HTTPS_IDENTIFIER="$identifier" ACME_WEBROOT LETSENCRYPT_DIR

if [[ "$identifier_type" == "domain" ]]; then
  mapfile -t resolved_ips < <(
    getent ahostsv4 "$domain" |
      awk '{print $1}' |
      sort -u
  )
  if [[ ! " ${resolved_ips[*]} " =~ " $expected_ip " ]]; then
    echo "DNS precheck failed: $domain does not resolve to $expected_ip." >&2
    exit 1
  fi
elif [[ "$identifier" != "$expected_ip" ]]; then
  echo "The IP identifier must exactly match --expected-ip." >&2
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
    -H "Host: $identifier" \
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
)
if [[ "$identifier_type" == "ip" ]]; then
  certbot_args+=(--preferred-profile shortlived --ip-address "$identifier")
else
  certbot_args+=(--domain "$identifier")
fi
if ((no_email)); then
  certbot_args+=(--register-unsafely-without-email)
else
  certbot_args+=(--email "$email" --no-eff-email)
fi
if ((staging)); then
  certbot_args+=(--staging)
fi
"$CERTBOT_BIN" "${certbot_args[@]}"

test -s "$LETSENCRYPT_DIR/live/$identifier/fullchain.pem"
test -s "$LETSENCRYPT_DIR/live/$identifier/privkey.pem"

if ((staging)); then
  state="complete"
  echo "HTTPS_STAGING_OK identifier=$identifier type=$identifier_type expected_ip=$expected_ip"
  exit 0
fi

state="finalizing"
"${https_compose[@]}" up -d --force-recreate --wait --wait-timeout 60 web

https_probe_args=(
  --fail
  --silent
  --show-error
  --max-time 15
  --resolve "$identifier:443:127.0.0.1"
)
curl "${https_probe_args[@]}" "https://$identifier/api/v1/health" >/dev/null

state="complete"
echo "HTTPS_ENABLE_OK identifier=$identifier type=$identifier_type expected_ip=$expected_ip"
