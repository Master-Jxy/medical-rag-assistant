"""跨模块演示账号清理；只由受控维护命令调用。"""

from dataclasses import asdict, dataclass
import hashlib
import json

from sqlalchemy import delete, func, inspect, select, update
from sqlalchemy.orm import Session

from app.models.conversation import Conversation, Message, MessageSource
from app.modules.agent.models import AgentArtifact, AgentRun, AgentStep
from app.modules.agent.thread_models import AgentMessage, AgentThread
from app.modules.auth.models import User
from app.modules.auth.roles import UserRole
from app.modules.knowledge.models import KnowledgeDocument, KnowledgeSubmission
from app.modules.memory.models import (
    ConversationSummaryMemory,
    UserMemory,
    UserMemorySetting,
)
from app.modules.quality.models import AnswerFeedback
from app.modules.usage.models import ModelUsageRecord, QuotaPolicyEvent

DEMO_ACCOUNT_CONFIRM_PHRASE = "DELETE_DEMO_ACCOUNTS"
KNOWN_USER_FOREIGN_KEYS = {
    ("agent_messages", "user_id"),
    ("agent_runs", "user_id"),
    ("agent_threads", "user_id"),
    ("answer_feedback", "reviewer_id"),
    ("answer_feedback", "user_id"),
    ("conversations", "user_id"),
    ("documents", "uploader_id"),
    ("knowledge_submissions", "submitter_id"),
    ("model_usage_records", "user_id"),
    ("memory_extraction_runs", "user_id"),
    ("quota_periods", "user_id"),
    ("quota_policy_events", "user_id"),
    ("quota_reservations", "user_id"),
    ("user_quota_assignments", "user_id"),
    ("user_quota_assignments", "updated_by"),
    ("user_memories", "user_id"),
    ("user_memory_settings", "user_id"),
}


class DemoAccountCleanupBlockedError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DemoAccountCleanupPlan:
    owner_user_id: str
    owner_email: str
    users_total: int
    users_to_delete: int
    user_ids_to_delete: tuple[str, ...]
    public_documents_to_transfer: int
    public_submissions_to_transfer: int
    personal_submissions_to_delete: int
    conversations_to_delete: int
    agent_threads_to_delete: int
    agent_runs_to_delete: int
    agent_messages_to_delete: int
    feedback_to_delete: int
    reviewed_feedback_to_unassign: int
    memory_settings_to_delete: int
    memories_to_delete: int
    usage_records_to_anonymize: int
    quota_policy_events_to_delete: int
    fingerprint: str


class DemoAccountMaintenanceService:
    """预检和受控执行使用同一份可校验计划；不接触文件、Chroma或Redis。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def preflight(self, owner_email: str) -> DemoAccountCleanupPlan:
        self._assert_known_user_foreign_keys()
        normalized = owner_email.strip().lower()
        owner = self.session.scalar(
            select(User).where(User.email == normalized)
        )
        if (
            owner is None
            or not owner.is_active
            or owner.role != UserRole.SUPER_ADMIN
            or owner.email_verified_at is None
        ):
            raise DemoAccountCleanupBlockedError(
                "保留账号必须是已启用、邮箱已验证的超级管理员"
            )
        target_ids = tuple(
            self.session.scalars(
                select(User.id)
                .where(User.id != owner.id)
                .order_by(User.id)
            ).all()
        )
        counts = self._counts(target_ids, owner.id)
        base = {
            "owner_user_id": owner.id,
            "owner_email": owner.email,
            "users_total": self._count(select(User.id)),
            "users_to_delete": len(target_ids),
            "user_ids_to_delete": target_ids,
            **counts,
        }
        fingerprint = hashlib.sha256(
            json.dumps(base, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        return DemoAccountCleanupPlan(**base, fingerprint=fingerprint)

    def execute(
        self,
        owner_email: str,
        *,
        expected_fingerprint: str,
        confirmation: str,
    ) -> DemoAccountCleanupPlan:
        if confirmation != DEMO_ACCOUNT_CONFIRM_PHRASE:
            raise DemoAccountCleanupBlockedError("确认短语不匹配")
        plan = self.preflight(owner_email)
        if not expected_fingerprint or plan.fingerprint != expected_fingerprint:
            raise DemoAccountCleanupBlockedError("预检计划已变化，拒绝执行")
        target_ids = list(plan.user_ids_to_delete)
        if not target_ids:
            return plan
        try:
            self._execute_database_cleanup(plan.owner_user_id, target_ids)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return plan

    def _counts(
        self, target_ids: tuple[str, ...], owner_id: str
    ) -> dict[str, int]:
        if not target_ids:
            return {
                "public_documents_to_transfer": 0,
                "public_submissions_to_transfer": 0,
                "personal_submissions_to_delete": 0,
                "conversations_to_delete": 0,
                "agent_threads_to_delete": 0,
                "agent_runs_to_delete": 0,
                "agent_messages_to_delete": 0,
                "feedback_to_delete": 0,
                "reviewed_feedback_to_unassign": 0,
                "memory_settings_to_delete": 0,
                "memories_to_delete": 0,
                "usage_records_to_anonymize": 0,
                "quota_policy_events_to_delete": 0,
            }
        public_submission = (
            KnowledgeSubmission.submitter_id.in_(target_ids)
            & (
                KnowledgeSubmission.document_id.is_not(None)
                | KnowledgeSubmission.status.in_(("published", "archived"))
            )
        )
        return {
            "public_documents_to_transfer": self._count(
                select(KnowledgeDocument.id).where(
                    KnowledgeDocument.uploader_id.in_(target_ids),
                    KnowledgeDocument.is_system.is_(False),
                )
            ),
            "public_submissions_to_transfer": self._count(
                select(KnowledgeSubmission.id).where(public_submission)
            ),
            "personal_submissions_to_delete": self._count(
                select(KnowledgeSubmission.id).where(
                    KnowledgeSubmission.submitter_id.in_(target_ids),
                    ~(
                        KnowledgeSubmission.document_id.is_not(None)
                        | KnowledgeSubmission.status.in_(("published", "archived"))
                    ),
                )
            ),
            "conversations_to_delete": self._count(
                select(Conversation.id).where(Conversation.user_id.in_(target_ids))
            ),
            "agent_threads_to_delete": self._count(
                select(AgentThread.id).where(AgentThread.user_id.in_(target_ids))
            ),
            "agent_runs_to_delete": self._count(
                select(AgentRun.id).where(AgentRun.user_id.in_(target_ids))
            ),
            "agent_messages_to_delete": self._count(
                select(AgentMessage.id).where(AgentMessage.user_id.in_(target_ids))
            ),
            "feedback_to_delete": self._count(
                select(AnswerFeedback.id).where(
                    AnswerFeedback.user_id.in_(target_ids)
                )
            ),
            "reviewed_feedback_to_unassign": self._count(
                select(AnswerFeedback.id).where(
                    AnswerFeedback.reviewer_id.in_(target_ids),
                    ~AnswerFeedback.user_id.in_(target_ids),
                )
            ),
            "memory_settings_to_delete": self._count(
                select(UserMemorySetting.user_id).where(
                    UserMemorySetting.user_id.in_(target_ids)
                )
            ),
            "memories_to_delete": self._count(
                select(UserMemory.id).where(UserMemory.user_id.in_(target_ids))
            ),
            "usage_records_to_anonymize": self._count(
                select(ModelUsageRecord.id).where(
                    ModelUsageRecord.user_id.in_(target_ids)
                )
            ),
            "quota_policy_events_to_delete": self._count(
                select(QuotaPolicyEvent.id).where(
                    QuotaPolicyEvent.user_id.in_(target_ids)
                )
            ),
        }

    def _execute_database_cleanup(
        self, owner_id: str, target_ids: list[str]
    ) -> None:
        self.session.execute(
            update(KnowledgeDocument)
            .where(
                KnowledgeDocument.uploader_id.in_(target_ids),
                KnowledgeDocument.is_system.is_(False),
            )
            .values(uploader_id=owner_id)
        )
        public_submission_filter = (
            KnowledgeSubmission.submitter_id.in_(target_ids)
            & (
                KnowledgeSubmission.document_id.is_not(None)
                | KnowledgeSubmission.status.in_(("published", "archived"))
            )
        )
        self.session.execute(
            update(KnowledgeSubmission)
            .where(public_submission_filter)
            .values(submitter_id=owner_id)
        )
        self.session.execute(
            delete(KnowledgeSubmission).where(
                KnowledgeSubmission.submitter_id.in_(target_ids)
            )
        )
        self.session.execute(
            update(AnswerFeedback)
            .where(AnswerFeedback.reviewer_id.in_(target_ids))
            .values(reviewer_id=None)
        )
        self.session.execute(
            delete(AnswerFeedback).where(AnswerFeedback.user_id.in_(target_ids))
        )
        self.session.execute(
            delete(UserMemory).where(UserMemory.user_id.in_(target_ids))
        )
        self.session.execute(
            delete(UserMemorySetting).where(
                UserMemorySetting.user_id.in_(target_ids)
            )
        )
        self.session.execute(
            update(ModelUsageRecord)
            .where(ModelUsageRecord.user_id.in_(target_ids))
            .values(user_id=None)
        )
        self.session.execute(
            delete(QuotaPolicyEvent).where(
                QuotaPolicyEvent.user_id.in_(target_ids)
            )
        )
        conversation_ids = list(
            self.session.scalars(
                select(Conversation.id).where(
                    Conversation.user_id.in_(target_ids)
                )
            ).all()
        )
        if conversation_ids:
            message_ids = list(
                self.session.scalars(
                    select(Message.id).where(
                        Message.conversation_id.in_(conversation_ids)
                    )
                ).all()
            )
            if message_ids:
                self.session.execute(
                    delete(MessageSource).where(
                        MessageSource.message_id.in_(message_ids)
                    )
                )
            self.session.execute(
                delete(ConversationSummaryMemory).where(
                    ConversationSummaryMemory.conversation_id.in_(
                        conversation_ids
                    )
                )
            )
            self.session.execute(
                delete(Message).where(Message.conversation_id.in_(conversation_ids))
            )
            self.session.execute(
                delete(Conversation).where(Conversation.id.in_(conversation_ids))
            )
        run_ids = list(
            self.session.scalars(
                select(AgentRun.id).where(AgentRun.user_id.in_(target_ids))
            ).all()
        )
        if run_ids:
            self.session.execute(
                delete(AgentArtifact).where(AgentArtifact.run_id.in_(run_ids))
            )
            self.session.execute(
                delete(AgentStep).where(AgentStep.run_id.in_(run_ids))
            )
        thread_ids = list(
            self.session.scalars(
                select(AgentThread.id).where(
                    AgentThread.user_id.in_(target_ids)
                )
            ).all()
        )
        self.session.execute(
            delete(AgentRun).where(AgentRun.user_id.in_(target_ids))
        )
        self.session.execute(
            delete(AgentMessage).where(AgentMessage.user_id.in_(target_ids))
        )
        if thread_ids:
            self.session.execute(
                delete(AgentThread).where(AgentThread.id.in_(thread_ids))
            )
        self.session.execute(delete(User).where(User.id.in_(target_ids)))

    def _assert_known_user_foreign_keys(self) -> None:
        inspector = inspect(self.session.get_bind())
        actual = set()
        for table in inspector.get_table_names():
            for foreign_key in inspector.get_foreign_keys(table):
                if foreign_key.get("referred_table") != "users":
                    continue
                for column in foreign_key.get("constrained_columns") or ():
                    actual.add((table, column))
        unknown = actual - KNOWN_USER_FOREIGN_KEYS
        if unknown:
            formatted = ", ".join(f"{table}.{column}" for table, column in sorted(unknown))
            raise DemoAccountCleanupBlockedError(
                f"发现未分类的用户外键：{formatted}"
            )

    def _count(self, statement) -> int:
        return len(self.session.scalars(statement).all())


def cleanup_plan_as_dict(plan: DemoAccountCleanupPlan) -> dict[str, object]:
    return asdict(plan)
