"""No-cost fake and disabled chat vision adapters."""

from app.core.exceptions import VisionUnavailableError
from app.modules.usage.contracts import ModelUsage
from app.modules.vision.contracts import VisionObservation, VisionResult


class DisabledVisionChatAdapter:
    def observe(self, **kwargs) -> VisionResult:
        del kwargs
        raise VisionUnavailableError("图片识别尚未启用，您仍可发送纯文字问题")


class FakeVisionChatAdapter:
    def __init__(self, observation: VisionObservation | None = None, usage: ModelUsage | None = None) -> None:
        self.observation = observation or VisionObservation(
            image_type="medical_report",
            summary="一张用于测试的医学报告图片",
            visible_text=["白细胞计数", "12.3"],
            safety_flags=["medical_data"],
        )
        self.usage = usage or ModelUsage.actual(120, 48)
        self.calls: list[dict] = []

    def observe(self, **kwargs) -> VisionResult:
        self.calls.append({key: value for key, value in kwargs.items() if key != "image_bytes"})
        return VisionResult(observation=self.observation, usage=self.usage, model_name="fake-vision")
