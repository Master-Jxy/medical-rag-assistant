"""部署备份恢复入口的安全契约。"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKUP_SCRIPT = ROOT / "deploy" / "backup.sh"
RESTORE_SCRIPT = ROOT / "deploy" / "restore.sh"
DRILL_SCRIPT = ROOT / "deploy" / "backup_restore_drill.sh"
BACKUP_SERVICE = ROOT / "deploy" / "systemd" / "medical-rag-backup.service"
BACKUP_TIMER = ROOT / "deploy" / "systemd" / "medical-rag-backup.timer"


def test_backup_script_has_manifest_checksums_retention_and_incomplete_cleanup() -> None:
    script = BACKUP_SCRIPT.read_text(encoding="utf-8")
    assert script.startswith("#!/usr/bin/env bash\nset -Eeuo pipefail")
    assert "medical-rag-backup-v1" in script
    assert "SHA256SUMS" in script and "sha256sum -c" in script
    assert ".incomplete-" in script and "cleanup_staging" in script
    assert "BACKUP_RETENTION_COUNT" in script
    assert "--single-transaction" in script
    assert "--no-tablespaces" in script
    assert "redis-cli SAVE" in script
    assert "app_data" in script and "chroma_data" in script and "redis_data" in script
    assert "down -v" not in script


def test_restore_requires_exact_confirmation_and_verified_backup() -> None:
    script = RESTORE_SCRIPT.read_text(encoding="utf-8")
    assert script.startswith("#!/usr/bin/env bash\nset -Eeuo pipefail")
    assert "--confirm-restore" in script
    assert '--confirm-project must exactly match' in script
    assert "sha256sum -c SHA256SUMS" in script
    assert "backup_format=medical-rag-backup-v1" in script
    assert "pre-restore" in script
    assert "DROP DATABASE IF EXISTS" in script
    assert "down -v" not in script


def test_restore_drill_is_isolated_and_checks_all_persistent_data_classes() -> None:
    script = DRILL_SCRIPT.read_text(encoding="utf-8")
    assert "medical-rag-drill-" in script
    assert "--confirm-project" in script and "--skip-safety-backup" in script
    assert "baseline-app" in script
    assert "baseline-chroma" in script
    assert "restore_probe" in script
    assert "BACKUP_RESTORE_DRILL_OK" in script


def test_systemd_backup_schedule_is_bounded_and_uses_deploy_user() -> None:
    service = BACKUP_SERVICE.read_text(encoding="utf-8")
    timer = BACKUP_TIMER.read_text(encoding="utf-8")
    assert "User=deploy" in service and "Group=deploy" in service
    assert "APPLICATION_ROOT=/home/deploy/medical-rag-assistant" in service
    assert "BACKUP_RETENTION_COUNT=7" in service
    assert "ExecStart=/usr/bin/bash /usr/local/lib/medical-rag/backup.sh" in service
    assert "OnCalendar=*-*-* 03:30:00" in timer
    assert "RandomizedDelaySec=10m" in timer
    assert "Persistent=true" in timer
