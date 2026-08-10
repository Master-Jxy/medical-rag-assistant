"""Persistence and atomic claims for private vision observations."""

from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.media.models import MediaAsset
from app.modules.vision.models import VisionObservationRecord


@dataclass(frozen=True, slots=True)
class ObservationClaim:
    record: VisionObservationRecord
    created: bool


class VisionObservationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(
        self,
        *,
        user_id: str,
        media_asset_id: str,
        observation_scope_id: str,
        kind: str,
        focus_instruction_hash: str,
    ) -> VisionObservationRecord | None:
        return self.session.scalar(
            select(VisionObservationRecord).where(
                VisionObservationRecord.user_id == user_id,
                VisionObservationRecord.media_asset_id == media_asset_id,
                VisionObservationRecord.observation_scope_id == observation_scope_id,
                VisionObservationRecord.kind == kind,
                VisionObservationRecord.focus_instruction_hash
                == focus_instruction_hash,
            )
        )

    def get_or_create(
        self,
        *,
        user_id: str,
        media_asset_id: str,
        observation_scope_id: str,
        kind: str,
        focus_instruction_hash: str,
        model_name: str,
        run_id: str | None,
        assistant_message_id: str | None,
    ) -> ObservationClaim:
        existing = self.get(
            user_id=user_id,
            media_asset_id=media_asset_id,
            observation_scope_id=observation_scope_id,
            kind=kind,
            focus_instruction_hash=focus_instruction_hash,
        )
        if existing is not None:
            return ObservationClaim(existing, False)
        record = VisionObservationRecord(
            media_asset_id=media_asset_id,
            user_id=user_id,
            run_id=run_id,
            assistant_message_id=assistant_message_id,
            observation_scope_id=observation_scope_id,
            kind=kind,
            focus_instruction_hash=focus_instruction_hash,
            model_name=model_name,
            status="pending",
            sequence_no=0,
            route_kind="pending",
            quality_status="pending",
            quality_codes=[],
            provider_call_count=0,
        )
        self.session.add(record)
        try:
            self.session.commit()
            return ObservationClaim(record, True)
        except IntegrityError:
            self.session.rollback()
            concurrent = self.get(
                user_id=user_id,
                media_asset_id=media_asset_id,
                observation_scope_id=observation_scope_id,
                kind=kind,
                focus_instruction_hash=focus_instruction_hash,
            )
            if concurrent is None:
                raise
            return ObservationClaim(concurrent, False)

    def list_for_asset(self, user_id: str, media_asset_id: str) -> list[VisionObservationRecord]:
        return list(
            self.session.scalars(
                select(VisionObservationRecord)
                .where(
                    VisionObservationRecord.user_id == user_id,
                    VisionObservationRecord.media_asset_id == media_asset_id,
                )
                .order_by(
                    VisionObservationRecord.sequence_no,
                    VisionObservationRecord.created_at,
                    VisionObservationRecord.id,
                )
            )
        )

    def reserve_provider_call(
        self,
        record_id: str,
        *,
        media_asset_id: str,
        max_calls: int,
    ) -> bool:
        # The asset lock serializes the per-image budget on MySQL. The guarded
        # update remains the single-call truth for SQLite tests and duplicate requests.
        self.session.scalar(
            select(MediaAsset.id)
            .where(MediaAsset.id == media_asset_id)
            .with_for_update()
        )
        used_calls = int(
            self.session.scalar(
                select(func.coalesce(func.sum(VisionObservationRecord.provider_call_count), 0)).where(
                    VisionObservationRecord.media_asset_id == media_asset_id
                )
            )
            or 0
        )
        if used_calls >= max_calls:
            self.session.rollback()
            return False
        result = self.session.execute(
            update(VisionObservationRecord)
            .where(
                VisionObservationRecord.id == record_id,
                VisionObservationRecord.provider_call_count == 0,
                VisionObservationRecord.status == "pending",
            )
            .values(provider_call_count=1, sequence_no=used_calls + 1)
        )
        self.session.commit()
        return result.rowcount == 1

    def refresh(self, record_id: str) -> VisionObservationRecord | None:
        self.session.expire_all()
        return self.session.get(VisionObservationRecord, record_id)
