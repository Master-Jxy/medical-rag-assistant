import subprocess
from pathlib import Path

from scripts.release_preflight import (
    check_git,
    check_runtime_environment,
    check_sensitive_files,
    run_preflight,
)


def init_repo(path: Path, files: dict[str, bytes]) -> None:
    for name, content in files.items():
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)


def test_sensitive_scan_only_reads_tracked_files_and_detects_forbidden_env(
    tmp_path: Path,
) -> None:
    init_repo(tmp_path, {"safe.txt": b"safe", ".env": b"DO_NOT_READ=value"})
    result = check_sensitive_files(tmp_path)
    assert result.status == "FAIL"
    assert result.detail == "forbidden=1 secret_patterns=0"


def test_sensitive_scan_can_explicitly_skip_protected_local_path(
    tmp_path: Path,
) -> None:
    protected = "backend/app/modules/auth/service.py"
    init_repo(tmp_path, {protected: b"sk-" + (b"x" * 32)})
    result = check_sensitive_files(tmp_path, {protected})
    assert result.status == "SKIP"
    assert result.detail == "excluded_paths=1"


def test_runtime_environment_reports_names_without_values(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "mysql://user:secret@example/db")
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    result = check_runtime_environment(required=True)
    assert result.status == "FAIL"
    assert result.detail == "missing=REDIS_URL,JWT_SECRET_KEY"
    assert "secret" not in result.detail


def test_git_check_rejects_non_whitespace_dirty_worktree(tmp_path: Path) -> None:
    init_repo(tmp_path, {"tracked.txt": b"before\n"})
    commit_environment = {
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-qm", "initial"],
        check=True,
        env=commit_environment,
    )
    (tmp_path / "tracked.txt").write_text("after\n", encoding="utf-8")

    result = check_git(tmp_path, allow_dirty=False)

    assert result.status == "FAIL"
    assert result.detail == "dirty worktree or git diff --check failed"


def test_repository_preflight_outputs_pass_fail_skip_contract(tmp_path: Path) -> None:
    files = {
        "compose.yaml": (
            b"services:\n"
            b"  mysql:\n"
            b"    image: mysql:8@sha256:" + (b"d" * 64) + b"\n"
            b"    volumes:\n      - mysql_data:/var/lib/mysql\n"
            b"  redis:\n    image: redis:6@sha256:" + (b"e" * 64) + b"\n"
            b"  backend:\n"
            b"    image: backend\n"
            b"    healthcheck:\n"
            b"      test: ['CMD', 'curl', 'http://127.0.0.1:8000/readyz']\n"
            b"    volumes:\n"
            b"      - chroma_data:/app/chroma_db\n"
            b"      - type: bind\n"
            b"        source: ./backups\n"
            b"        target: /backups\n"
            b"        read_only: true\n"
            b"  worker:\n    image: worker\n"
            b"  web:\n    image: web\n"
            b"volumes:\n  mysql_data:\n  chroma_data:\n"
        ),
        "deploy/compose.https.yaml": (
            b"services:\n  web:\n    ports:\n      - '443:443'\n"
        ),
        "deploy/post_release_check.sh": b"#!/usr/bin/env bash\n",
        "backend/Dockerfile": (
            b"FROM ubuntu:22.04@sha256:" + (b"a" * 64) + b"\n"
        ),
        "frontend/Dockerfile": (
            b"FROM nginx:1.0@sha256:" + (b"b" * 64) + b"\n"
        ),
        ".github/workflows/ci.yml": (
            b"jobs:\n  test:\n    runs-on: ubuntu-24.04\n"
            b"    steps:\n      - uses: actions/checkout@"
            + (b"c" * 40)
            + b"\n"
        ),
        "backend/alembic.ini": b"[alembic]\n",
        "backend/requirements.txt": b"fastapi==0.139.0\n",
        "frontend/package-lock.json": b"{}\n",
    }
    init_repo(tmp_path, files)
    results = run_preflight(tmp_path, allow_dirty=True)
    statuses = {result.name: result.status for result in results}
    assert statuses == {
        "repository_layout": "PASS",
        "git_diff_check": "SKIP",
        "sensitive_file_scan": "PASS",
        "compose_contract": "PASS",
        "supply_chain_pins": "PASS",
        "runtime_environment": "SKIP",
        "livez": "SKIP",
        "readyz": "SKIP",
    }


def test_ci_runs_all_no_cost_release_gates() -> None:
    workflow = (
        Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"
    ).read_text(encoding="utf-8")
    required = (
        "python -m pytest -q backend/tests",
        "downgrade 0032_stage26_vision_ocr_routes",
        "test_stage26_job_leases_mysql_dirty_data_roundtrip",
        "python -m pip check",
        "npm test",
        "npm run test:stream",
        "npm run build",
        "npm audit --omit=dev --audit-level=high",
        "git diff --check",
        "release_preflight.py --repo-root .",
        'VISION_PROVIDER: disabled',
        'VISION_AUTOMATIC_RETRIES: "0"',
    )
    assert all(item in workflow for item in required)
    assert "DASHSCOPE_API_KEY" not in workflow


def test_post_release_check_handles_short_lived_ip_certificates() -> None:
    script = (
        Path(__file__).resolve().parents[2] / "deploy" / "post_release_check.sh"
    ).read_text(encoding="utf-8")

    assert "CERTIFICATE_MIN_VALIDITY_SECONDS" in script
    assert "certificate_min_seconds=172800" in script
    assert "certificate_min_seconds=1209600" in script
    assert "CERTBOT_RENEW_TIMER_UNIT" in script
    assert "certificate_validity" in script
    assert "certificate_14d" not in script
    assert "BACKUP_MANIFEST_PATH" in script
    assert "sha256sum -c SHA256SUMS" in script
    assert "backup_freshness_and_checksums" in script


def test_nginx_proxies_metrics_and_sets_browser_security_headers() -> None:
    root = Path(__file__).resolve().parents[2]
    for relative in ("deploy/nginx.conf", "deploy/nginx.https.conf.template"):
        config = (root / relative).read_text(encoding="utf-8")
        assert "location = /metrics" in config
        assert "Content-Security-Policy" in config
        assert "Permissions-Policy" in config
