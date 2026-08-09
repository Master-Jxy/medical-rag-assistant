"""SQLAlchemy persistence for private media assets."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.media.models import MediaAsset, MessageAttachment


class MediaRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, asset: MediaAsset) -> None:
        self.session.add(asset)

    def owned(self, user_id: str, asset_id: str, *, lock: bool = False) -> MediaAsset | None:
        statement = select(MediaAsset).where(MediaAsset.id == asset_id, MediaAsset.user_id == user_id)
        if lock:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def attachment_for_asset(self, asset_id: str) -> MessageAttachment | None:
        return self.session.scalar(select(MessageAttachment).where(MessageAttachment.media_asset_id == asset_id))

    def asset_ids_for_agent_message(self, message_id: str | None) -> list[str]:
        if not message_id:
            return []
        return list(self.session.scalars(
            select(MessageAttachment.media_asset_id)
            .where(MessageAttachment.agent_message_id == message_id)
            .order_by(MessageAttachment.position)
        ))
