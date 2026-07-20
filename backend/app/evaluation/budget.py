"""真实评估的调用、Token 与费用硬预算。"""

from dataclasses import dataclass

from app.evaluation.ports import TokenUsageObservation


class EvaluationBudgetExceeded(RuntimeError):
    """任一硬上限不足以容纳下一次调用，或调用后越界。"""


@dataclass(frozen=True)
class EvaluationBudgetLimits:
    max_retrieval_calls: int
    max_model_calls: int
    max_total_tokens: int
    max_estimated_cost_cny: float
    embedding_tokens_reserved_per_call: int
    model_input_tokens_reserved_per_call: int
    model_output_tokens_reserved_per_call: int
    embedding_price_per_million_tokens_cny: float
    model_input_price_per_million_tokens_cny: float
    model_output_price_per_million_tokens_cny: float
    max_rerank_calls: int = 0
    rerank_tokens_reserved_per_call: int = 0
    rerank_cost_reserved_per_call_cny: float = 0.0

    def __post_init__(self) -> None:
        integer_values = (
            self.max_retrieval_calls,
            self.max_model_calls,
            self.max_total_tokens,
            self.embedding_tokens_reserved_per_call,
            self.model_input_tokens_reserved_per_call,
            self.model_output_tokens_reserved_per_call,
        )
        if any(value <= 0 for value in integer_values):
            raise ValueError("预算中的调用次数和 Token 上限必须为正数")
        price_values = (
            self.max_estimated_cost_cny,
            self.embedding_price_per_million_tokens_cny,
            self.model_input_price_per_million_tokens_cny,
            self.model_output_price_per_million_tokens_cny,
        )
        if any(value <= 0 for value in price_values):
            raise ValueError("预算中的费用和单价必须为正数")
        if self.max_rerank_calls < 0:
            raise ValueError("重排调用上限不能为负数")
        if self.max_rerank_calls == 0:
            if self.rerank_tokens_reserved_per_call != 0 or self.rerank_cost_reserved_per_call_cny != 0:
                raise ValueError("未启用重排预算时不能预留重排Token或费用")
        elif (
            self.rerank_tokens_reserved_per_call <= 0
            or self.rerank_cost_reserved_per_call_cny <= 0
        ):
            raise ValueError("启用重排预算时必须设置正数Token和费用预留")


class EvaluationBudget:
    """在每次外部调用前预留额度，避免开始一个无法容纳的请求。"""

    def __init__(self, limits: EvaluationBudgetLimits) -> None:
        self.limits = limits
        self.retrieval_calls = 0
        self.model_calls = 0
        self.rerank_calls = 0
        self.embedding_tokens = 0
        self.model_input_tokens = 0
        self.model_output_tokens = 0
        self.rerank_tokens = 0
        self.estimated_cost_cny = 0.0
        self._pending_model_reservation: tuple[int, int, float] | None = None
        self._pending_rerank_reservation: tuple[int, float] | None = None

    @property
    def total_tokens(self) -> int:
        return (
            self.embedding_tokens
            + self.model_input_tokens
            + self.model_output_tokens
            + self.rerank_tokens
        )

    def before_retrieval(self) -> None:
        limits = self.limits
        if self.retrieval_calls >= limits.max_retrieval_calls:
            raise EvaluationBudgetExceeded("retrieval_call_limit")
        reserved_tokens = limits.embedding_tokens_reserved_per_call
        reserved_cost = (
            reserved_tokens
            * limits.embedding_price_per_million_tokens_cny
            / 1_000_000
        )
        self._require_capacity(reserved_tokens, reserved_cost)
        self.retrieval_calls += 1
        self.embedding_tokens += reserved_tokens
        self.estimated_cost_cny += reserved_cost

    def before_answer(self) -> None:
        limits = self.limits
        if self._pending_model_reservation is not None:
            # 上一次调用失败且没有可核验计量时，保留最坏情况预算。
            self._pending_model_reservation = None
        if self.model_calls >= limits.max_model_calls:
            raise EvaluationBudgetExceeded("model_call_limit")
        reserved_tokens = (
            limits.model_input_tokens_reserved_per_call
            + limits.model_output_tokens_reserved_per_call
        )
        reserved_cost = (
            limits.model_input_tokens_reserved_per_call
            * limits.model_input_price_per_million_tokens_cny
            + limits.model_output_tokens_reserved_per_call
            * limits.model_output_price_per_million_tokens_cny
        ) / 1_000_000
        self._require_capacity(reserved_tokens, reserved_cost)
        self.model_calls += 1
        self.model_input_tokens += limits.model_input_tokens_reserved_per_call
        self.model_output_tokens += limits.model_output_tokens_reserved_per_call
        self.estimated_cost_cny += reserved_cost
        self._pending_model_reservation = (
            limits.model_input_tokens_reserved_per_call,
            limits.model_output_tokens_reserved_per_call,
            reserved_cost,
        )

    def record_answer_usage(self, usage: TokenUsageObservation | None) -> None:
        if usage is None:
            raise EvaluationBudgetExceeded("model_usage_missing")
        if self._pending_model_reservation is None:
            raise RuntimeError("没有待核销的模型调用预算")
        reserved_input, reserved_output, reserved_cost = self._pending_model_reservation
        self.model_input_tokens -= reserved_input
        self.model_output_tokens -= reserved_output
        self.estimated_cost_cny -= reserved_cost
        self._pending_model_reservation = None
        cost = usage.estimated_cost_cny
        if cost is None:
            cost = (
                usage.input_tokens
                * self.limits.model_input_price_per_million_tokens_cny
                + usage.output_tokens
                * self.limits.model_output_price_per_million_tokens_cny
            ) / 1_000_000
        tokens = usage.input_tokens + usage.output_tokens
        self._require_capacity(tokens, cost)
        self.model_input_tokens += usage.input_tokens
        self.model_output_tokens += usage.output_tokens
        self.estimated_cost_cny += cost

    def record_answer_failure(self) -> None:
        """保留失败调用的最坏情况预留，并允许下一道题继续。"""
        if self._pending_model_reservation is None:
            raise RuntimeError("没有待结算的模型调用预算")
        self._pending_model_reservation = None

    def before_rerank(self) -> None:
        limits = self.limits
        if self._pending_rerank_reservation is not None:
            raise EvaluationBudgetExceeded("rerank_usage_missing")
        if self.rerank_calls >= limits.max_rerank_calls:
            raise EvaluationBudgetExceeded("rerank_call_limit")
        tokens = limits.rerank_tokens_reserved_per_call
        cost = limits.rerank_cost_reserved_per_call_cny
        self._require_capacity(tokens, cost)
        self.rerank_calls += 1
        self.rerank_tokens += tokens
        self.estimated_cost_cny += cost
        self._pending_rerank_reservation = (tokens, cost)

    def record_rerank_usage(self, usage: TokenUsageObservation | None) -> None:
        if usage is None:
            raise EvaluationBudgetExceeded("rerank_usage_missing")
        if self._pending_rerank_reservation is None:
            raise RuntimeError("没有待核销的重排调用预算")
        reserved_tokens, reserved_cost = self._pending_rerank_reservation
        self.rerank_tokens -= reserved_tokens
        self.estimated_cost_cny -= reserved_cost
        self._pending_rerank_reservation = None
        cost = usage.estimated_cost_cny
        if cost is None:
            raise EvaluationBudgetExceeded("rerank_cost_missing")
        self._require_capacity(usage.input_tokens, cost)
        self.rerank_tokens += usage.input_tokens
        self.estimated_cost_cny += cost

    def record_rerank_failure(self) -> None:
        """保留失败调用的最坏情况预留，并允许当前题回退。"""
        if self._pending_rerank_reservation is None:
            raise RuntimeError("没有待结算的重排调用预算")
        self._pending_rerank_reservation = None

    def ensure_settled(self) -> None:
        if self._pending_model_reservation is not None:
            raise EvaluationBudgetExceeded("model_usage_missing")
        if self._pending_rerank_reservation is not None:
            raise EvaluationBudgetExceeded("rerank_usage_missing")

    def _require_capacity(self, additional_tokens: int, additional_cost: float) -> None:
        if self.total_tokens + additional_tokens > self.limits.max_total_tokens:
            raise EvaluationBudgetExceeded("total_token_limit")
        if (
            self.estimated_cost_cny + additional_cost
            > self.limits.max_estimated_cost_cny
        ):
            raise EvaluationBudgetExceeded("estimated_cost_limit")
