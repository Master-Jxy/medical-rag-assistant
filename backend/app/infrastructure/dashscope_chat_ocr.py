"""DashScope OCR-mode adapter for private chat images only."""

import base64
import json

from dashscope import MultiModalConversation

from app.core.config import Settings
from app.core.exceptions import VisionUnavailableError
from app.modules.usage.contracts import ModelUsage
from app.modules.vision.contracts import (
    VisionTextExtraction,
    VisionTextExtractionConsumedError,
    VisionTextExtractionRequest,
    VisionTextExtractionResult,
)
from app.modules.vision.ocr_prompts import build_ocr_prompt


class DashScopeVisionTextExtractionAdapter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def extract(
        self, request: VisionTextExtractionRequest
    ) -> VisionTextExtractionResult:
        data_url = (
            f"data:{request.mime_type};base64,"
            f"{base64.b64encode(request.image_bytes).decode('ascii')}"
        )
        try:
            response = MultiModalConversation.call(
                api_key=self.settings.require_dashscope_api_key(),
                model=self.settings.vision_model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"image": data_url},
                            {
                                "text": build_ocr_prompt(
                                    language_hints=request.language_hints,
                                    extract_tables=request.extract_tables,
                                    max_output_chars=request.max_output_chars,
                                )
                            },
                        ],
                    }
                ],
                result_format="message",
                timeout=self.settings.vision_timeout_seconds,
            )
        except Exception as exc:
            raise VisionUnavailableError() from exc
        if getattr(response, "status_code", None) != 200:
            raise VisionUnavailableError()

        usage = self._usage(response)
        provider_request_id = getattr(response, "request_id", None)
        try:
            text = self._response_text(response)
            if len(text) > request.max_output_chars:
                raise ValueError("OCR response exceeds controlled character limit")
            extraction = VisionTextExtraction.model_validate(
                self._normalize_payload(text)
            )
            return VisionTextExtractionResult(
                extraction=extraction,
                usage=usage,
                model_name=self.settings.vision_model,
                provider_request_id=provider_request_id,
            )
        except Exception as exc:
            raise VisionTextExtractionConsumedError(
                usage=usage,
                model_name=self.settings.vision_model,
                provider_request_id=provider_request_id,
            ) from exc

    @classmethod
    def _usage(cls, response) -> ModelUsage:
        usage_payload = getattr(response, "usage", {}) or {}
        if cls._value(usage_payload, "input_tokens") is not None and cls._value(
            usage_payload, "output_tokens"
        ) is not None:
            return ModelUsage.actual(
                int(cls._value(usage_payload, "input_tokens", 0)),
                int(cls._value(usage_payload, "output_tokens", 0)),
                provider_request_id=getattr(response, "request_id", None),
            )
        return ModelUsage.unknown()

    @classmethod
    def _response_text(cls, response) -> str:
        output = getattr(response, "output", {}) or {}
        choices = cls._value(output, "choices", None)
        if not choices:
            raise VisionUnavailableError()
        message = cls._value(choices[0], "message", None)
        content = cls._value(message, "content", None)
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                str(item.get("text", "")) for item in content if isinstance(item, dict)
            )
        raise VisionUnavailableError()

    @staticmethod
    def _normalize_payload(text: str) -> dict:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()[1:]
            if lines and lines[-1].strip() == "```":
                lines.pop()
            cleaned = "\n".join(lines).strip()
        payload = json.loads(cleaned)
        if not isinstance(payload, dict):
            raise VisionUnavailableError()
        for field in ("visible_text", "uncertain_content"):
            values = payload.get(field, [])
            if values is None:
                values = []
            elif not isinstance(values, list):
                values = [values]
            payload[field] = [
                value
                if isinstance(value, str)
                else json.dumps(value, ensure_ascii=False, sort_keys=True)
                for value in values
            ]
        rows = payload.get("table_rows", [])
        if rows is None:
            rows = []
        elif not isinstance(rows, list):
            rows = [rows]
        payload["table_rows"] = [
            [str(cell) for cell in row] if isinstance(row, list) else [str(row)]
            for row in rows
        ]
        measurements = payload.get("measurements", [])
        if measurements is None:
            measurements = []
        elif not isinstance(measurements, list):
            measurements = [measurements]
        normalized_measurements = []
        for item in measurements:
            if not isinstance(item, dict):
                continue
            normalized = dict(item)
            for field in ("name", "value", "unit", "reference_range", "flag"):
                value = normalized.get(field)
                if value is not None and not isinstance(value, str):
                    normalized[field] = str(value)
            normalized_measurements.append(normalized)
        payload["measurements"] = normalized_measurements
        return payload

    @staticmethod
    def _value(payload, name: str, default=None):
        return (
            payload.get(name, default)
            if isinstance(payload, dict)
            else getattr(payload, name, default)
        )
