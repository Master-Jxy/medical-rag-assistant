"""Bounded Agent image tools backed only by the public vision application service."""

from pydantic import Field

from app.core.exceptions import MediaNotFoundError
from app.modules.agent.contracts import AgentToolArguments, AgentToolContext, AgentToolResult
from app.modules.vision.router_service import VisionRouterService


class ObserveImageArguments(AgentToolArguments):
    media_asset_ids: list[str] = Field(min_length=1, max_length=3)
    user_question: str = Field(default="请描述图片中的可见信息", max_length=2000)


class InspectImageArguments(AgentToolArguments):
    media_asset_id: str = Field(min_length=1, max_length=36)
    focus_instruction: str = Field(min_length=1, max_length=500)


class _VisionTool:
    def __init__(self, vision: VisionRouterService, *, allowed_asset_ids: list[str], run_id: str, usage_group_id: str) -> None:
        self.vision = vision
        self.allowed_asset_ids = frozenset(allowed_asset_ids)
        self.run_id = run_id
        self.usage_group_id = usage_group_id

    def _assert_allowed(self, asset_id: str) -> None:
        if asset_id not in self.allowed_asset_ids:
            raise MediaNotFoundError()


class ObserveImageTool(_VisionTool):
    name = "observe_image"
    description = "读取本次用户消息已授权图片的整体可见事实；每张图只执行一次整体观察，不诊断。"
    arguments_model = ObserveImageArguments

    def invoke(self, context: AgentToolContext, arguments: ObserveImageArguments) -> AgentToolResult:
        observations = []
        for asset_id in arguments.media_asset_ids:
            self._assert_allowed(asset_id)
            observation = self.vision.route_overview(
                user_id=context.user_id, asset_id=asset_id,
                user_question=arguments.user_question or context.task_context,
                surface="vision_agent", usage_group_id=self.usage_group_id,
                run_id=self.run_id,
            )
            observations.append({"media_asset_id": asset_id, "observation": observation.model_dump(mode="json")})
        return AgentToolResult(
            summary=f"已完成 {len(observations)} 张图片的整体可见事实观察。",
            data={"observations": observations},
        )


class InspectImageTool(_VisionTool):
    name = "inspect_image"
    description = "仅在整体观察信息不足时，按一个明确目标再次检查已授权原图；同目标不可重复，每图最多两次。"
    arguments_model = InspectImageArguments

    def invoke(self, context: AgentToolContext, arguments: InspectImageArguments) -> AgentToolResult:
        self._assert_allowed(arguments.media_asset_id)
        observation = self.vision.inspect(
            user_id=context.user_id, asset_id=arguments.media_asset_id,
            user_question=context.task_context,
            focus_instruction=arguments.focus_instruction,
            surface="vision_agent", usage_group_id=self.usage_group_id,
            run_id=self.run_id,
        )
        return AgentToolResult(
            summary="已按指定目标完成一次定向图片观察。",
            data={"observations": [{"media_asset_id": arguments.media_asset_id, "observation": observation.model_dump(mode="json")}]},
        )
