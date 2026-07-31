"""调用模型前的保守额度预留估算；估算值绝不冒充供应商实际usage。"""

from dataclasses import dataclass
from typing import Protocol

from app.core.exceptions import AppError


class QuotaReservationTooLargeError(AppError):
    def __init__(self):
        super().__init__(
            "本次上下文过长，请缩短问题、历史或引用范围后重试",
            code="QUOTA_RESERVATION_TOO_LARGE",
            status_code=422,
        )


@dataclass(frozen=True, slots=True)
class QuotaReservationEstimate:
    estimated_input_tokens: int
    estimated_output_tokens: int
    safety_margin_tokens: int
    requested_tokens: int
    estimation_method: str
    exceeds_policy_limit: bool = False


@dataclass(frozen=True, slots=True)
class RagReservationInput:
    system_prompt: str
    question: str
    history: tuple[tuple[str, str], ...]
    top_k: int
    chunk_char_budget: int
    source_wrapper_tokens: int
    max_output_tokens: int


@dataclass(frozen=True, slots=True)
class AgentReservationInput:
    rendered_context: str
    estimated_context_tokens: int
    max_output_tokens: int
    policy_token_limit: int


class QuotaReservationEstimatorPort(Protocol):
    def estimate_rag(self, value: RagReservationInput) -> QuotaReservationEstimate: ...

    def estimate_agent(
        self, value: AgentReservationInput
    ) -> QuotaReservationEstimate: ...


class ConservativeQuotaReservationEstimator:
    """无需外部Tokenizer的可替换第一版估算器。"""

    METHOD = "conservative_chars_v1"

    def __init__(
        self,
        *,
        rag_min_tokens: int = 4_000,
        rag_max_tokens: int = 20_000,
        safety_margin_ratio: float = 0.2,
        agent_min_input_tokens: int = 1_000,
    ) -> None:
        self.rag_min_tokens = rag_min_tokens
        self.rag_max_tokens = rag_max_tokens
        self.safety_margin_ratio = safety_margin_ratio
        self.agent_min_input_tokens = agent_min_input_tokens

    @staticmethod
    def estimate_text_tokens(text: str) -> int:
        if not text:
            return 0
        # 中文字符通常接近一字一Token；英文按约四字符一Token。取两者较保守值。
        utf8_tokens = (len(text.encode("utf-8")) + 2) // 3
        char_tokens = (len(text) + 3) // 4
        return max(utf8_tokens, char_tokens, 1)

    def estimate_rag(self, value: RagReservationInput) -> QuotaReservationEstimate:
        history_tokens = sum(
            self.estimate_text_tokens(role) + self.estimate_text_tokens(content)
            for role, content in value.history
        )
        chunk_tokens = max(value.top_k, 0) * self.estimate_text_tokens(
            "中" * max(value.chunk_char_budget, 0)
        )
        estimated_input = (
            self.estimate_text_tokens(value.system_prompt)
            + self.estimate_text_tokens(value.question)
            + history_tokens
            + chunk_tokens
            + max(value.source_wrapper_tokens, 0)
        )
        base = estimated_input + max(value.max_output_tokens, 0)
        margin = max(0, int(base * self.safety_margin_ratio + 0.999999))
        raw_requested = base + margin
        requested = max(self.rag_min_tokens, raw_requested)
        return QuotaReservationEstimate(
            estimated_input_tokens=estimated_input,
            estimated_output_tokens=max(value.max_output_tokens, 0),
            safety_margin_tokens=margin,
            requested_tokens=requested,
            estimation_method=self.METHOD,
            exceeds_policy_limit=requested > self.rag_max_tokens,
        )

    def estimate_agent(
        self, value: AgentReservationInput
    ) -> QuotaReservationEstimate:
        policy_limit = max(value.policy_token_limit, 1)
        output_tokens = min(max(value.max_output_tokens, 0), policy_limit)
        estimated_input = max(
            value.estimated_context_tokens,
            self.estimate_text_tokens(value.rendered_context),
            self.agent_min_input_tokens,
        )
        base = estimated_input + output_tokens
        margin = max(0, int(base * self.safety_margin_ratio + 0.999999))
        requested = min(policy_limit, base + margin)
        requested = max(requested, min(policy_limit, self.agent_min_input_tokens + output_tokens))
        return QuotaReservationEstimate(
            estimated_input_tokens=estimated_input,
            estimated_output_tokens=output_tokens,
            safety_margin_tokens=max(0, requested - base),
            requested_tokens=requested,
            estimation_method=self.METHOD,
            exceeds_policy_limit=False,
        )
