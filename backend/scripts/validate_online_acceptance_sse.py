"""任务7.8线上验收SSE校验器；只读取临时响应，不调用模型或写业务数据。"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path


class AcceptanceValidationError(ValueError):
    """固定样例或真实SSE不符合验收契约。"""


@dataclass(frozen=True)
class AcceptanceValidationResult:
    token_event_count: int
    source_count: int
    answer_content: str


def parse_sse(text: str) -> list[tuple[str, dict]]:
    """解析当前单行JSON data帧，并拒绝缺少事件名或非法JSON的帧。"""
    events: list[tuple[str, dict]] = []
    normalized = text.replace("\r\n", "\n")
    for block in normalized.split("\n\n"):
        if not block.strip():
            continue
        event_name: str | None = None
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event_name = line.partition(":")[2].strip()
            elif line.startswith("data:"):
                data_lines.append(line.partition(":")[2].lstrip())
        if event_name is None and not data_lines:
            continue
        if not event_name or not data_lines:
            raise AcceptanceValidationError("malformed_sse_frame")
        try:
            data = json.loads("\n".join(data_lines))
        except json.JSONDecodeError as exc:
            raise AcceptanceValidationError("invalid_sse_json") from exc
        if not isinstance(data, dict):
            raise AcceptanceValidationError("sse_data_must_be_object")
        events.append((event_name, data))
    return events


def _normalize_answer(answer: str) -> str:
    return re.sub(
        r"[\s*_`\"'“”‘’《》：:，,、。.;；（）()\-]",
        "",
        answer,
    )


def match_heart_chamber_fact(answer: str) -> tuple[bool, bool]:
    """接受标准全称和常见压缩同义写法，但仍要求数量与四个名称齐全。"""
    normalized = _normalize_answer(answer)
    count_matched = any(
        wording in normalized
        for wording in (
            "四个腔室",
            "4个腔室",
            "四个心腔",
            "4个心腔",
            "心脏四腔",
            "心脏4腔",
        )
    )
    explicit_names = all(
        name in normalized
        for name in ("左心房", "右心房", "左心室", "右心室")
    )
    compressed_names = (
        ("左右心房" in normalized and "左右心室" in normalized)
        or all(alias in normalized for alias in ("左房", "右房", "左室", "右室"))
    )
    return count_matched, explicit_names or compressed_names


def validate_acceptance_sse(
    text: str,
    *,
    expected_source_file_name: str,
) -> AcceptanceValidationResult:
    events = parse_sse(text)
    errors = [data for event, data in events if event == "error"]
    if errors:
        raise AcceptanceValidationError("stream_returned_error")

    token_payloads = [data for event, data in events if event == "token"]
    if not token_payloads:
        raise AcceptanceValidationError("token_event_missing")
    contents: list[str] = []
    for payload in token_payloads:
        content = payload.get("content")
        if not isinstance(content, str) or not content:
            raise AcceptanceValidationError("token_content_missing")
        contents.append(content)

    source_payloads = [data for event, data in events if event == "sources"]
    if not source_payloads:
        raise AcceptanceValidationError("sources_event_missing")
    sources = source_payloads[-1].get("sources")
    if not isinstance(sources, list):
        raise AcceptanceValidationError("sources_must_be_list")
    source_names = [
        item.get("file_name")
        for item in sources
        if isinstance(item, dict) and isinstance(item.get("file_name"), str)
    ]
    if expected_source_file_name not in source_names:
        raise AcceptanceValidationError("uploaded_source_missing")

    if not any(event == "done" for event, _ in events):
        raise AcceptanceValidationError("done_event_missing")

    answer = "".join(contents)
    count_matched, names_matched = match_heart_chamber_fact(answer)
    if not count_matched:
        raise AcceptanceValidationError("heart_chamber_count_missing")
    if not names_matched:
        raise AcceptanceValidationError("heart_chamber_names_missing")

    return AcceptanceValidationResult(
        token_event_count=len(token_payloads),
        source_count=len(source_names),
        answer_content=answer,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("sse_path", type=Path)
    parser.add_argument("expected_source_file_name")
    args = parser.parse_args()
    result = validate_acceptance_sse(
        args.sse_path.read_text(encoding="utf-8"),
        expected_source_file_name=args.expected_source_file_name,
    )
    print(f"normal_token_events={result.token_event_count}")
    print(f"normal_source_count={result.source_count}")
    print("normal_uploaded_source=matched")
    print("normal_done=present")
    print("normal_expected_fact=matched")


if __name__ == "__main__":
    main()
