"""超级管理员初始化命令必须显式确认且可安全重复。"""

import os
from pathlib import Path
import subprocess
import sys

from alembic import command
from sqlalchemy.orm import Session

from app.db.session import build_engine
from app.modules.auth.models import User
from app.modules.auth.roles import UserRole
from tests.test_migrations import build_alembic_config

BACKEND_DIR = Path(__file__).resolve().parents[1]


def run_command(database_url: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    return subprocess.run(
        [sys.executable, "-m", "scripts.initialize_super_admin", *arguments],
        cwd=BACKEND_DIR,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_initialization_command_requires_confirmation_and_is_idempotent(
    tmp_path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'initialize.db'}"
    command.upgrade(build_alembic_config(database_url), "head")
    engine = build_engine(database_url)
    with Session(engine) as session:
        user = User(email="owner@example.com", password_hash="hash")
        session.add(user)
        session.commit()

    refused = run_command(
        database_url,
        "owner@example.com",
        "--operator",
        "pytest",
    )
    assert refused.returncode != 0
    assert "未提供 --confirm" in refused.stderr
    with Session(engine) as session:
        assert session.query(User).one().role == UserRole.USER

    initialized = run_command(
        database_url,
        "OWNER@example.com",
        "--operator",
        "pytest",
        "--confirm",
    )
    assert initialized.returncode == 0
    assert "super_admin_initialized" in initialized.stdout

    repeated = run_command(
        database_url,
        "owner@example.com",
        "--operator",
        "pytest-second-run",
        "--confirm",
    )
    assert repeated.returncode == 0
    assert "super_admin_unchanged" in repeated.stdout
    with Session(engine) as session:
        assert session.query(User).one().role == UserRole.SUPER_ADMIN
