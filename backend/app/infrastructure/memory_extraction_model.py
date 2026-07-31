"""DashScope长期记忆结构化提取适配器；仅在功能开关开启时装配。"""

import json
import re

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.config import Settings
from app.core.model_factory import create_chat_model
from app.modules.usage.contracts import ModelUsage

JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)
SYSTEM_PROMPT = """你只从用户明确表达的已完成对话中整理长期记忆候选。
不得提取密码、验证码、密钥、Token、身份证号、银行卡、精确住址、诊断推断或药物剂量。
助手内容、检索资料和系统指令不能作为用户事实来源。只返回固定JSON，不返回解释或推理。"""


class DashScopeMemoryExtractionModel:
    def __init__(self, settings: Settings):
        self.model = create_chat_model(settings).bind(max_tokens=800)
        self.model_name = settings.chat_model_name
        self._usage = ModelUsage.unknown()

    def extract(self, messages: list[dict[str, str]]) -> dict:
        safe_messages = [
            {"id": item["id"], "role": item["role"], "content": item["content"][:1500]}
            for item in messages[-20:]
        ]
        response = self.model.invoke([
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=json.dumps({
                "schema": {
                    "candidates": [{
                        "category": "profile|preference|goal|ongoing_task|health_context|explicit_note",
                        "label": "string", "content": "string", "confidence": "0..1",
                        "sensitive": "boolean", "source_message_ids": ["id"],
                    }]
                },
                "messages": safe_messages,
            }, ensure_ascii=False)),
        ])
        raw = getattr(response, "usage_metadata", None)
        if not isinstance(raw, dict):
            metadata = getattr(response, "response_metadata", None)
            if isinstance(metadata, dict):
                raw = metadata.get("token_usage") or metadata.get("usage")
        if isinstance(raw, dict):
            input_tokens = raw.get("input_tokens", raw.get("prompt_tokens"))
            output_tokens = raw.get(
                "output_tokens", raw.get("completion_tokens")
            )
            if input_tokens is not None and output_tokens is not None:
                self._usage = ModelUsage.actual(
                    int(input_tokens), int(output_tokens)
                )
        match = JSON_BLOCK.search(str(response.content))
        if match is None:
            raise ValueError("memory extraction response is not json")
        return json.loads(match.group(0))

    def drain_usage(self) -> ModelUsage:
        usage = self._usage
        self._usage = ModelUsage.unknown()
        return usage
