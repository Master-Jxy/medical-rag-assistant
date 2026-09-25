"""Agent消息读取和稳定状态更新用例。"""

from sqlalchemy.orm import Session

from app.core.exceptions import (
    AgentMessageNotFoundAppError,
    AgentThreadNotFoundAppError,
)
from app.modules.agent.thread_repository import (
    AgentMessageNotFoundError,
    AgentThreadNotFoundError,
    AgentThreadRepository,
)
from app.modules.agent.thread_schemas import AgentMessageResponse
from app.modules.usage.query_service import UsageQueryService
from app.modules.media.models import MediaAsset, MessageAttachment
from app.modules.vision.models import VisionObservationRecord
from sqlalchemy import select


class AgentMessageService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = AgentThreadRepository(session)
        self.usage = UsageQueryService(session)

    def _response(self, message) -> AgentMessageResponse:
        payload = AgentMessageResponse.model_validate(message).model_dump()
        payload["message_metadata"] = payload.pop("metadata")
        rows = self.session.execute(
            select(MessageAttachment, MediaAsset)
            .join(MediaAsset, MediaAsset.id == MessageAttachment.media_asset_id)
            .where(MessageAttachment.agent_message_id == message.id)
            .order_by(MessageAttachment.position)
        ).all()
        if not rows:
            attachment_ids = [
                str(value)
                for value in (message.message_metadata or {}).get("attachment_ids", [])
                if value
            ]
            if attachment_ids:
                assets = list(self.session.scalars(
                    select(MediaAsset).where(
                        MediaAsset.user_id == message.user_id,
                        MediaAsset.id.in_(attachment_ids),
                    )
                ))
                assets_by_id = {asset.id: asset for asset in assets}
                rows = [
                    (None, assets_by_id[asset_id])
                    for asset_id in attachment_ids
                    if asset_id in assets_by_id
                ]
        payload["attachments"] = [
            {
                "id": attachment.id if attachment is not None else f"reused:{message.id}:{asset.id}",
                "media_asset_id": asset.id,
                "position": attachment.position if attachment is not None else position,
                "original_name": asset.original_name,
                "mime_type": asset.mime_type, "byte_size": asset.byte_size,
                "width": asset.width, "height": asset.height,
                "preview_url": f"/api/v1/media/assets/{asset.id}/preview",
            }
            for position, (attachment, asset) in enumerate(rows, start=1)
        ]
        observations = list(self.session.scalars(
            select(VisionObservationRecord).where(
                VisionObservationRecord.run_id == message.run_id,
                VisionObservationRecord.status == "completed",
                VisionObservationRecord.kind.in_(("overview", "focused")),
            ).order_by(VisionObservationRecord.sequence_no)
        )) if message.run_id else []
        payload["vision_observations"] = [
            {
                "media_asset_id": item.media_asset_id,
                "kind": item.kind,
                "sequence_no": item.sequence_no,
                "observation": item.observation_json or {},
            }
            for item in observations
        ]
        response = AgentMessageResponse.model_validate(payload)
        if message.role == "assistant":
            return response.model_copy(update={
                "usage": self.usage.group_summary(message.id, message.user_id)
            })
        return response

    def list(
        self,
        user_id: str,
        thread_id: str,
        *,
        offset: int,
        limit: int,
    ) -> list[AgentMessageResponse]:
        try:
            messages = self.repository.list_messages(
                user_id, thread_id, offset=offset, limit=limit
            )
        except AgentThreadNotFoundError as exc:
            raise AgentThreadNotFoundAppError() from exc
        return [
            self._response(message) for message in messages
        ]

    def get(
        self,
        user_id: str,
        thread_id: str,
        message_id: str,
    ) -> AgentMessageResponse:
        try:
            message = self.repository.get_message(
                user_id, thread_id, message_id
            )
        except AgentMessageNotFoundError as exc:
            raise AgentMessageNotFoundAppError() from exc
        return self._response(message)
