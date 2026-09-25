"""不访问 Redis 的会话幂等测试替身。"""

from app.services.idempotency_service import IdempotencyClaim


class AllowingIdempotency:
    def __init__(self) -> None:
        self.completed = 0
        self.abandoned = 0

    def begin(
        self,
        user_id,
        endpoint,
        client_request_id,
        conversation_id,
        question,
        top_k,
        attachment_ids=None,
        model_id=None,
    ) -> IdempotencyClaim:
        return IdempotencyClaim(
            f"test:{endpoint}:{client_request_id}",
            f"fingerprint:{conversation_id}:{question}:{top_k}:{attachment_ids or []}:{model_id}",
        )

    def complete(self, claim, **result) -> None:
        self.completed += 1

    def abandon(self, claim) -> None:
        self.abandoned += 1
