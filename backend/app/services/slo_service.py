"""Read-only SLO and hygiene checks with bounded, non-content output."""

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.modules.jobs.models import ProcessingJob
from app.modules.media.models import MediaAsset, MessageAttachment
from app.modules.usage.models import QuotaReservation
from app.schemas.slo import SloChecksResponse


class SloChecksService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def get_checks(self) -> SloChecksResponse:
        now = datetime.now(timezone.utc)
        stale_jobs = int(
            self.session.scalar(
                select(func.count())
                .select_from(ProcessingJob)
                .where(
                    ProcessingJob.status == "running",
                    ProcessingJob.lease_expires_at.is_not(None),
                    ProcessingJob.lease_expires_at <= now,
                )
            )
            or 0
        )
        expired_reservations = int(
            self.session.scalar(
                select(func.count())
                .select_from(QuotaReservation)
                .where(
                    QuotaReservation.status == "reserved",
                    QuotaReservation.expires_at <= now,
                )
            )
            or 0
        )
        orphan_media = int(
            self.session.scalar(
                select(func.count())
                .select_from(MediaAsset)
                .where(
                    MediaAsset.status.in_(("uploaded", "attached")),
                    ~exists(
                        select(MessageAttachment.id).where(
                            MessageAttachment.media_asset_id == MediaAsset.id
                        )
                    ),
                )
            )
            or 0
        )
        backup_status, backup_age = self._backup_status(now)
        overall = (
            "ok"
            if not stale_jobs
            and not expired_reservations
            and not orphan_media
            and backup_status in {"fresh", "not_configured"}
            else "attention"
        )
        return SloChecksResponse(
            generated_at=now,
            stale_job_count=stale_jobs,
            expired_quota_reservation_count=expired_reservations,
            orphan_media_count=orphan_media,
            backup_status=backup_status,
            backup_age_hours=backup_age,
            overall_status=overall,
        )

    def _backup_status(self, now: datetime) -> tuple[str, float | None]:
        path = self.settings.backup_manifest_path
        if path is None:
            return "not_configured", None
        try:
            modified = datetime.fromtimestamp(Path(path).stat().st_mtime, tz=timezone.utc)
        except FileNotFoundError:
            return "missing", None
        except OSError:
            return "unreadable", None
        age_hours = max(0.0, (now - modified).total_seconds() / 3600)
        return (
            ("fresh" if age_hours <= self.settings.backup_max_age_hours else "stale"),
            round(age_hours, 3),
        )
