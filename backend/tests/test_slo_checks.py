from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.db.base import Base
from app.db.session import build_engine
from app.modules.jobs.models import ProcessingJob
from app.modules.usage.models import QuotaReservation
from app.services.slo_service import SloChecksService


def test_slo_checks_are_bounded_and_detect_stale_records(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'slo.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime.now(timezone.utc)
    with factory() as session:
        session.add(
            ProcessingJob(
                id="stale-job",
                job_type="publish_submission",
                object_type="knowledge_submission",
                object_id="submission",
                status="running",
                lease_expires_at=now - timedelta(minutes=1),
            )
        )
        session.add(
            QuotaReservation(
                id="expired-reservation",
                idempotency_key="expired-reservation",
                user_id="user",
                quota_period_id="period",
                surface="rag",
                usage_group_id="group",
                reserved_tokens=1,
                status="reserved",
                expires_at=now - timedelta(minutes=1),
            )
        )
        session.commit()
        result = SloChecksService(session, Settings(_env_file=None)).get_checks()
    assert result.stale_job_count == 1
    assert result.expired_quota_reservation_count == 1
    assert result.orphan_media_count == 0
    assert result.backup_status == "not_configured"
    assert result.overall_status == "attention"
    engine.dispose()
