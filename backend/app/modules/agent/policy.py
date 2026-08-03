"""Agent第一版固定安全边界。"""

from dataclasses import dataclass

from app.core.config import Settings


@dataclass(frozen=True, slots=True)
class AgentPolicy:
    enabled: bool = False
    max_steps: int = 5
    max_tool_calls: int = 3
    max_model_calls: int = 4
    max_specialists: int = 2
    max_handoffs: int = 1
    tool_timeout_seconds: float = 30.0
    run_timeout_seconds: float = 120.0
    max_tokens: int = 12_000
    max_estimated_cost_cny: float = 0.05

    def __post_init__(self) -> None:
        if not 1 <= self.max_steps <= 5:
            raise ValueError("Agent第一版最大步骤数必须位于1到5之间")
        if not 1 <= self.max_tool_calls <= 3:
            raise ValueError("Agent工具调用上限必须位于1到3之间")
        if not 1 <= self.max_model_calls <= 4:
            raise ValueError("Agent模型调用上限必须位于1到4之间")
        if not 1 <= self.max_specialists <= 2:
            raise ValueError("Agent specialist上限必须位于1到2之间")
        if not 0 <= self.max_handoffs <= 1:
            raise ValueError("Agent handoff上限必须位于0到1之间")
        if not 0 < self.tool_timeout_seconds <= 60:
            raise ValueError("Agent单工具超时必须大于0且不超过60秒")
        if not 0 < self.run_timeout_seconds <= 600:
            raise ValueError("Agent运行超时必须大于0且不超过600秒")
        if self.tool_timeout_seconds > self.run_timeout_seconds:
            raise ValueError("Agent单工具超时不能超过整次运行超时")
        if not 1 <= self.max_tokens <= 200_000:
            raise ValueError("Agent Token预算必须位于1到200000之间")
        if not 0 <= self.max_estimated_cost_cny <= 10:
            raise ValueError("Agent费用预算必须位于0到10元之间")

    @classmethod
    def from_settings(cls, settings: Settings) -> "AgentPolicy":
        return cls(
            enabled=settings.agent_enabled,
            max_steps=settings.agent_max_steps,
            max_tool_calls=settings.agent_max_tool_calls,
            max_model_calls=settings.agent_max_model_calls,
            max_specialists=settings.agent_max_specialists,
            max_handoffs=settings.agent_max_handoffs,
            tool_timeout_seconds=settings.agent_tool_timeout_seconds,
            run_timeout_seconds=settings.agent_run_timeout_seconds,
            max_tokens=settings.agent_max_tokens,
            max_estimated_cost_cny=settings.agent_max_estimated_cost_cny,
        )
