"""统一发布预检：只读取Git跟踪源码和显式环境，不读取.env正文。"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    detail: str


REQUIRED_FILES = (
    "compose.yaml",
    "deploy/compose.https.yaml",
    "backend/alembic.ini",
    "backend/requirements.txt",
    "frontend/package-lock.json",
    "deploy/post_release_check.sh",
    "backend/Dockerfile",
    "frontend/Dockerfile",
    ".github/workflows/ci.yml",
)
FORBIDDEN_TRACKED_PARTS = (
    "backend/data/uploads/",
    "backend/data/media/",
    "backend/chroma_db/",
    "backend/backups/",
)
SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"\bsk-[A-Za-z0-9_-]{24,}\b"),
)


def _git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def check_layout(repo_root: Path) -> CheckResult:
    missing = [name for name in REQUIRED_FILES if not (repo_root / name).is_file()]
    return CheckResult(
        "repository_layout",
        "FAIL" if missing else "PASS",
        "missing=" + ",".join(missing) if missing else "required release files present",
    )


def check_git(repo_root: Path, allow_dirty: bool) -> CheckResult:
    if allow_dirty:
        return CheckResult("git_diff_check", "SKIP", "explicit --allow-dirty")
    inside = _git(repo_root, "rev-parse", "--is-inside-work-tree")
    if inside.returncode != 0:
        return CheckResult("git_diff_check", "FAIL", "not a git worktree")
    status = _git(repo_root, "status", "--porcelain", "--untracked-files=all")
    diff = _git(repo_root, "diff", "--check", "HEAD", "--")
    clean = status.returncode == 0 and not status.stdout.strip()
    return CheckResult(
        "git_diff_check",
        "PASS" if diff.returncode == 0 and clean else "FAIL",
        "clean worktree and diff syntax"
        if diff.returncode == 0 and clean
        else "dirty worktree or git diff --check failed",
    )


def check_sensitive_files(
    repo_root: Path,
    excluded_paths: set[str] | None = None,
) -> CheckResult:
    excluded_paths = excluded_paths or set()
    tracked = _git(repo_root, "ls-files", "-z")
    if tracked.returncode != 0:
        return CheckResult("sensitive_file_scan", "FAIL", "cannot list tracked files")
    names = [name for name in tracked.stdout.split("\0") if name]
    forbidden: list[str] = []
    matched: list[str] = []
    excluded = 0
    for name in names:
        normalized = name.replace("\\", "/")
        basename = normalized.rsplit("/", 1)[-1]
        env_file = basename == ".env" or (
            basename.startswith(".env.") and basename != ".env.example"
        )
        if env_file or any(part in normalized for part in FORBIDDEN_TRACKED_PARTS):
            forbidden.append(name)
            continue
        if name in excluded_paths:
            excluded += 1
            continue
        path = repo_root / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
            continue
        content = path.read_bytes()
        if b"\0" in content:
            continue
        if any(pattern.search(content) for pattern in SECRET_PATTERNS):
            matched.append(name)
    if forbidden or matched:
        return CheckResult(
            "sensitive_file_scan",
            "FAIL",
            f"forbidden={len(forbidden)} secret_patterns={len(matched)}",
        )
    if excluded:
        return CheckResult(
            "sensitive_file_scan",
            "SKIP",
            f"excluded_paths={excluded}",
        )
    return CheckResult("sensitive_file_scan", "PASS", "tracked files only")


def check_compose_contract(repo_root: Path) -> CheckResult:
    compose_path = repo_root / "compose.yaml"
    https_path = repo_root / "deploy" / "compose.https.yaml"
    if not compose_path.is_file() or not https_path.is_file():
        return CheckResult("compose_contract", "FAIL", "compose files missing")
    environment = os.environ.copy()
    environment.update(
        {
            "MYSQL_DATABASE": "preflight",
            "MYSQL_USER": "preflight",
            "MYSQL_PASSWORD": "preflight",
            "MYSQL_ROOT_PASSWORD": "preflight",
            "JWT_SECRET_KEY": "preflight-only-secret-longer-than-32-characters",
            "DASHSCOPE_API_KEY": "preflight-disabled",
            "HTTPS_IDENTIFIER": "example.invalid",
        }
    )
    resolved = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(compose_path),
            "-f",
            str(https_path),
            "config",
            "--format",
            "json",
        ],
        cwd=repo_root,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    if resolved.returncode != 0:
        return CheckResult("compose_contract", "FAIL", "docker compose config failed")
    try:
        model = json.loads(resolved.stdout)
    except (TypeError, ValueError):
        return CheckResult("compose_contract", "FAIL", "invalid compose config JSON")

    services = model.get("services", {})
    volumes = model.get("volumes", {})
    backend = services.get("backend", {})
    healthcheck = backend.get("healthcheck", {}).get("test", [])
    backup_mount = next(
        (
            item
            for item in backend.get("volumes", [])
            if isinstance(item, dict) and item.get("target") == "/backups"
        ),
        None,
    )
    valid = (
        {"mysql", "redis", "backend", "worker", "web"} <= set(services)
        and {"mysql_data", "chroma_data"} <= set(volumes)
        and any("readyz" in str(item) for item in healthcheck)
        and backup_mount is not None
        and bool(backup_mount.get("read_only"))
        and any(
            str(port.get("target")) == "443"
            for port in services.get("web", {}).get("ports", [])
            if isinstance(port, dict)
        )
    )
    return CheckResult(
        "compose_contract",
        "PASS" if valid else "FAIL",
        "resolved base+https readiness and volume contract"
        if valid
        else "resolved compose contract mismatch",
    )


def check_runtime_environment(required: bool) -> CheckResult:
    if not required:
        return CheckResult("runtime_environment", "SKIP", "not requested")
    names = ("DATABASE_URL", "REDIS_URL", "JWT_SECRET_KEY")
    missing = [name for name in names if not os.environ.get(name)]
    return CheckResult(
        "runtime_environment",
        "FAIL" if missing else "PASS",
        "missing=" + ",".join(missing) if missing else "required variable names present",
    )


def check_supply_chain(repo_root: Path) -> CheckResult:
    backend = (repo_root / "backend" / "Dockerfile").read_text(encoding="utf-8")
    frontend = (repo_root / "frontend" / "Dockerfile").read_text(encoding="utf-8")
    compose = (repo_root / "compose.yaml").read_text(encoding="utf-8")
    workflow = (repo_root / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    image_pattern = re.compile(r"@sha256:[0-9a-f]{64}\b")
    action_refs = re.findall(r"uses:\s*[^\s@]+@([^\s#]+)", workflow)
    valid = (
        bool(image_pattern.search(backend.splitlines()[0]))
        and bool(image_pattern.search(frontend.splitlines()[0]))
        and len(image_pattern.findall(compose)) >= 2
        and "pip install --upgrade" not in backend
        and "ubuntu-latest" not in workflow
        and bool(action_refs)
        and all(re.fullmatch(r"[0-9a-f]{40}", ref) for ref in action_refs)
    )
    return CheckResult(
        "supply_chain_pins",
        "PASS" if valid else "FAIL",
        "production images and CI actions are immutable"
        if valid
        else "mutable image, installer, runner, or action reference",
    )


def check_endpoint(name: str, url: str | None, expected_status: str) -> CheckResult:
    if not url:
        return CheckResult(name, "SKIP", "URL not supplied")
    try:
        with urlopen(url, timeout=3) as response:  # noqa: S310 - operator supplied URL
            body = json.loads(response.read(4096).decode("utf-8"))
        ready = response.status == 200 and body.get("status") == expected_status
    except (HTTPError, URLError, TimeoutError, ValueError, OSError):
        ready = False
    return CheckResult(
        name,
        "PASS" if ready else "FAIL",
        "status contract matched" if ready else "endpoint unavailable or invalid",
    )


def run_preflight(
    repo_root: Path,
    *,
    allow_dirty: bool = False,
    excluded_paths: set[str] | None = None,
    require_runtime_env: bool = False,
    live_url: str | None = None,
    ready_url: str | None = None,
) -> list[CheckResult]:
    return [
        check_layout(repo_root),
        check_git(repo_root, allow_dirty),
        check_sensitive_files(repo_root, excluded_paths),
        check_compose_contract(repo_root),
        check_supply_chain(repo_root),
        check_runtime_environment(require_runtime_env),
        check_endpoint("livez", live_url, "ok"),
        check_endpoint("readyz", ready_url, "ready"),
    ]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Medical RAG release preflight")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--exclude-path", action="append", default=[])
    parser.add_argument("--require-runtime-env", action="store_true")
    parser.add_argument("--live-url")
    parser.add_argument("--ready-url")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    results = run_preflight(
        args.repo_root.resolve(),
        allow_dirty=args.allow_dirty,
        excluded_paths=set(args.exclude_path),
        require_runtime_env=args.require_runtime_env,
        live_url=args.live_url,
        ready_url=args.ready_url,
    )
    for result in results:
        print(f"{result.status} {result.name}: {result.detail}")
    return 1 if any(result.status == "FAIL" for result in results) else 0


if __name__ == "__main__":
    sys.exit(main())
