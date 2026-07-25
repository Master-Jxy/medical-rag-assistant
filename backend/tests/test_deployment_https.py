"""HTTPS部署模板与操作脚本的静态安全边界。"""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"


def test_https_nginx_keeps_acme_redirect_security_and_sse_contract() -> None:
    bootstrap = (DEPLOY / "nginx.acme.conf.template").read_text(encoding="utf-8")
    https = (DEPLOY / "nginx.https.conf.template").read_text(encoding="utf-8")

    assert "/.well-known/acme-challenge/" in bootstrap
    assert "proxy_pass http://backend:8000;" in bootstrap
    assert "listen 443 ssl http2 default_server;" in https
    assert "https://${HTTPS_DOMAIN}$request_uri" in https
    assert "ssl_protocols TLSv1.2 TLSv1.3;" in https
    assert "ssl_session_tickets off;" in https
    assert "proxy_buffering off;" in https
    assert "proxy_read_timeout 650s;" in https
    assert "X-Forwarded-Proto $scheme" in https
    assert "Strict-Transport-Security" not in https


def test_https_compose_override_only_changes_web_boundary() -> None:
    bootstrap = yaml.safe_load(
        (DEPLOY / "compose.https-bootstrap.yaml").read_text(encoding="utf-8")
    )
    https = yaml.safe_load(
        (DEPLOY / "compose.https.yaml").read_text(encoding="utf-8")
    )

    assert set(bootstrap["services"]) == {"web"}
    assert set(https["services"]) == {"web"}
    assert https["services"]["web"]["ports"] == ["443:443"]
    volumes = https["services"]["web"]["volumes"]
    assert any("/etc/letsencrypt:ro" in volume for volume in volumes)
    assert any("/var/www/certbot:ro" in volume for volume in volumes)


def test_enable_https_requires_dns_confirmation_and_has_http_fallback() -> None:
    script = (DEPLOY / "enable_https.sh").read_text(encoding="utf-8")

    assert "set -Eeuo pipefail" in script
    assert '--confirm-issue must exactly match --domain.' in script
    assert "Use exactly one of --email or --no-email." in script
    assert "--register-unsafely-without-email" in script
    assert 'getent ahostsv4 "$domain"' in script
    assert "certbot_args=(" in script
    assert "--keep-until-expiring" in script
    assert 'LETSENCRYPT_DIR="$LETSENCRYPT_DIR/staging"' in script
    assert "HTTPS_STAGING_OK" in script
    assert 'if ((staging)); then\n  state="complete"' in script
    assert 'state="finalizing"' in script
    assert "restoring the HTTP ACME configuration" in script
    assert script.count("--wait --wait-timeout 60 web") == 3
    assert "down -v" not in script


def test_disable_and_renewal_preserve_certificates_and_reload_only_web() -> None:
    disable = (DEPLOY / "disable_https.sh").read_text(encoding="utf-8")
    renewal = (DEPLOY / "reload_nginx_after_renewal.sh").read_text(
        encoding="utf-8"
    )

    assert "--confirm-disable must exactly match --domain." in disable
    assert "certificates_preserved=" in disable
    assert "down -v" not in disable
    assert "nginx -s reload" in renewal
    assert "down -v" not in renewal
