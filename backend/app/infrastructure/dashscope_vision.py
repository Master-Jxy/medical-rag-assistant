"""DashScope multimodal adapter; instantiated only when explicitly enabled."""

import base64
import json

from dashscope import MultiModalConversation

from app.core.config import Settings
from app.core.exceptions import VisionUnavailableError
from app.modules.usage.contracts import ModelUsage
from app.modules.vision.contracts import VisionObservation, VisionResult
from app.modules.vision.prompts import build_vision_prompt


class DashScopeVisionChatAdapter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def observe(self, *, image_bytes: bytes, mime_type: str, user_question: str, focus_instruction: str | None) -> VisionResult:
        data_url = f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"
        try:
            response = MultiModalConversation.call(
                api_key=self.settings.require_dashscope_api_key(),
                model=self.settings.vision_model,
                messages=[{"role": "user", "content": [{"image": data_url}, {"text": build_vision_prompt(user_question, focus_instruction)}]}],
                result_format="message",
                timeout=self.settings.vision_timeout_seconds,
            )
            status_code = getattr(response, "status_code", None)
            if status_code != 200:
                raise VisionUnavailableError()
            output = getattr(response, "output", {}) or {}
            choices = output.get("choices") if isinstance(output, dict) else getattr(output, "choices", None)
            message = choices[0]["message"] if choices and isinstance(choices[0], dict) else choices[0].message
            content = message.get("content") if isinstance(message, dict) else message.content
            text = self._content_text(content)
            observation = VisionObservation.model_validate(json.loads(text))
            usage_payload = getattr(response, "usage", {}) or {}
            usage = ModelUsage.actual(int(self._value(usage_payload, "input_tokens", 0)), int(self._value(usage_payload, "output_tokens", 0))) if self._has_usage(usage_payload) else ModelUsage.unknown()
            return VisionResult(
                observation=observation,
                usage=usage,
                model_name=self.settings.vision_model,
                provider_request_id=getattr(response, "request_id", None),
            )
        except VisionUnavailableError:
            raise
        except Exception as exc:
            raise VisionUnavailableError() from exc

    @staticmethod
    def _content_text(content) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
        raise VisionUnavailableError()

    @staticmethod
    def _value(payload, name: str, default=None):
        return payload.get(name, default) if isinstance(payload, dict) else getattr(payload, name, default)

    @classmethod
    def _has_usage(cls, payload) -> bool:
        return cls._value(payload, "input_tokens") is not None and cls._value(payload, "output_tokens") is not None
