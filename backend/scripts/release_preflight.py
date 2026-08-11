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
    diff = _git(repo_root, "diff", "--check", "HEAD", "--")
    return CheckResult(
        "git_diff_check",
        "PASS" if diff.returncode == 0 else "FAIL",
        "clean diff syntax" if diff.returncode == 0 else "git diff --check failed",
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
    compose = compose_path.read_text(encoding="utf-8")
    https = https_path.read_text(encoding="utf-8")
    valid = (
        "http://127.0.0.1:8000/readyz" in compose
        and "mysql_data:" in compose
        and "chroma_data:" in compose
        and "services:" in https
        and "down -v" not in compose
        and "down -v" not in https
        and "worker:" in compose
    )
    return CheckResult(
        "compose_contract",
        "PASS" if valid else "FAIL",
        "base+https readiness and volume contract" if valid else "compose contract mismatch",
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
