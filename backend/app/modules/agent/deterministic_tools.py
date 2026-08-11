"""Stage 26.5 read-only deterministic Agent tools.

The tools in this module deliberately consume public application contracts and
structured observations only.  They do not call a model, execute arbitrary
code, mutate the database, or infer tables/sections from free-form prose.
"""

from __future__ import annotations

import ast
import math
import operator
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Protocol

from pydantic import Field, model_validator

from app.modules.agent.contracts import (
    AgentToolArguments,
    AgentToolContext,
    AgentToolCost,
    AgentToolMetadata,
    AgentToolResult,
    AgentToolBudget,
)
from app.modules.vision.contracts import VisionObservation


class StructuredKnowledgePort(Protocol):
    """Optional public port for already parsed, published document structure."""

    def get_published_document(self, document_id: str): ...

    def get_published_sections(self, document_id: str) -> Sequence[Mapping[str, object]]: ...

    def get_published_tables(self, document_id: str) -> Sequence[Mapping[str, object]]: ...


def _metadata(
    *,
    risk: str,
    permissions: tuple[str, ...],
    timeout_seconds: float,
    max_items: int,
    max_input_chars: int,
) -> AgentToolMetadata:
    return AgentToolMetadata(
        version="1.0.0",
        risk=risk,
        permissions=permissions,
        timeout_seconds=timeout_seconds,
        budget=AgentToolBudget(
            max_calls_per_run=1,
            max_items=max_items,
            max_input_chars=max_input_chars,
        ),
        cost=AgentToolCost(mode="none", model_calls=0),
    )


def _clean_id(value: object) -> str:
    return str(value or "").strip()


def _clean_text(value: object, limit: int = 2000) -> str:
    return " ".join(str(value or "").split())[:limit]


def _norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _published(catalog: object, document_id: str):
    getter = getattr(catalog, "get_published_document", None)
    if not callable(getter):
        return None
    info = getter(document_id)
    if info is None or getattr(info, "status", None) not in {"published", "ready"}:
        return None
    return info


def _structured_items(catalog: object, document_id: str, kind: str) -> list[dict[str, object]]:
    """Read exact structured items exposed by a public port; never parse prose."""

    method_name = "get_published_sections" if kind == "section" else "get_published_tables"
    getter = getattr(catalog, method_name, None)
    raw: object = getter(document_id) if callable(getter) else []
    if isinstance(raw, Mapping):
        raw = raw.get(f"{kind}s", [])
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        return []
    result: list[dict[str, object]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        item_id = _clean_id(item.get(f"{kind}_id") or item.get("id"))
        if not item_id:
            continue
        normalized = {str(key): value for key, value in item.items()}
        normalized[f"{kind}_id"] = item_id
        result.append(normalized)
    return result


class CalculatorArguments(AgentToolArguments):
    expression: str = Field(min_length=1, max_length=200)


class CalculatorTool:
    name = "calculator"
    description = "在严格算术白名单内计算表达式，不执行函数、变量、代码或系统操作。"
    arguments_model = CalculatorArguments
    metadata = _metadata(
        risk="low",
        permissions=("compute:bounded",),
        timeout_seconds=0.2,
        max_items=1,
        max_input_chars=200,
    )

    _binary = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
    }
    _unary = {ast.UAdd: operator.pos, ast.USub: operator.neg}

    def invoke(self, context: AgentToolContext, arguments: CalculatorArguments) -> AgentToolResult:
        del context
        try:
            value = self._evaluate(arguments.expression)
        except (ArithmeticError, ValueError, SyntaxError, TypeError, OverflowError):
            return AgentToolResult(
                summary="表达式不在安全算术白名单内，未执行计算。",
                data={"ok": False, "error_code": "UNSAFE_EXPRESSION"},
            )
        formatted = str(int(value)) if float(value).is_integer() else format(value, ".12g")
        return AgentToolResult(
            summary=f"计算结果：{formatted}",
            data={"ok": True, "expression": arguments.expression.strip(), "value": value, "formatted": formatted},
        )

    @classmethod
    def _evaluate(cls, expression: str) -> float:
        tree = ast.parse(expression.strip(), mode="eval")
        value = cls._eval_node(tree.body, depth=0)
        if not math.isfinite(value) or abs(value) > 1_000_000_000_000:
            raise ValueError("result out of bounds")
        return value

    @classmethod
    def _eval_node(cls, node: ast.AST, *, depth: int) -> float:
        if depth > 12:
            raise ValueError("expression too deep")
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            value = float(node.value)
            if not math.isfinite(value) or abs(value) > 1_000_000_000:
                raise ValueError("number out of bounds")
            return value
        if isinstance(node, ast.UnaryOp) and type(node.op) in cls._unary:
            return cls._unary[type(node.op)](cls._eval_node(node.operand, depth=depth + 1))
        if isinstance(node, ast.BinOp) and type(node.op) in cls._binary:
            left = cls._eval_node(node.left, depth=depth + 1)
            right = cls._eval_node(node.right, depth=depth + 1)
            if isinstance(node.op, ast.Pow) and (not right.is_integer() or abs(right) > 10):
                raise ValueError("power out of bounds")
            return float(cls._binary[type(node.op)](left, right))
        raise ValueError("node not allowed")


class GetDocumentSectionArguments(AgentToolArguments):
    document_id: str = Field(min_length=1, max_length=36)
    section_id: str | None = Field(default=None, min_length=1, max_length=120)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    max_chars: int = Field(default=4000, ge=1, le=8000)

    @model_validator(mode="after")
    def require_one_selector(self):
        if bool(self.section_id) == bool(self.title):
            raise ValueError("section_id和title必须二选一")
        return self


class GetDocumentSectionTool:
    name = "get_document_section"
    description = "读取已发布结构化资料中的一个明确章节，不从正文猜测章节边界。"
    arguments_model = GetDocumentSectionArguments
    metadata = _metadata(
        risk="low",
        permissions=("read:published_structured_knowledge",),
        timeout_seconds=2.0,
        max_items=1,
        max_input_chars=500,
    )

    def __init__(self, catalog: StructuredKnowledgePort) -> None:
        self.catalog = catalog

    def invoke(self, context: AgentToolContext, arguments: GetDocumentSectionArguments) -> AgentToolResult:
        del context
        if _published(self.catalog, arguments.document_id) is None:
            return AgentToolResult(summary="未找到可读取的已发布资料章节。", data={"found": False})
        sections = _structured_items(self.catalog, arguments.document_id, "section")
        matches = [
            item for item in sections
            if (arguments.section_id and item["section_id"] == arguments.section_id)
            or (arguments.title and _norm(item.get("title")) == _norm(arguments.title))
        ]
        if len(matches) != 1:
            return AgentToolResult(
                summary="未找到唯一匹配的已发布结构化章节。",
                source_ids=[arguments.document_id] if matches else [],
                data={"found": False, "ambiguous": len(matches) > 1},
            )
        item = matches[0]
        result = {
            "section_id": item["section_id"],
            "title": _clean_text(item.get("title"), 200),
            "text": _clean_text(item.get("text"), arguments.max_chars),
            "level": item.get("level"),
            "page": item.get("page"),
        }
        return AgentToolResult(
            summary=f"已读取章节：{result['title'] or result['section_id']}",
            source_ids=[arguments.document_id],
            data={"found": True, "section": result},
        )


class ExtractTableArguments(AgentToolArguments):
    document_id: str = Field(min_length=1, max_length=36)
    table_id: str = Field(min_length=1, max_length=120)
    max_rows: int = Field(default=50, ge=1, le=100)


class ExtractTableTool:
    name = "extract_table"
    description = "读取已发布结构化资料中已解析的指定表格，不从普通文本猜测表格。"
    arguments_model = ExtractTableArguments
    metadata = _metadata(
        risk="low",
        permissions=("read:published_structured_knowledge",),
        timeout_seconds=2.0,
        max_items=100,
        max_input_chars=300,
    )

    def __init__(self, catalog: StructuredKnowledgePort) -> None:
        self.catalog = catalog

    def invoke(self, context: AgentToolContext, arguments: ExtractTableArguments) -> AgentToolResult:
        del context
        if _published(self.catalog, arguments.document_id) is None:
            return AgentToolResult(summary="未找到可读取的已发布资料表格。", data={"found": False})
        matches = [
            item for item in _structured_items(self.catalog, arguments.document_id, "table")
            if item["table_id"] == arguments.table_id
        ]
        if len(matches) != 1:
            return AgentToolResult(
                summary="未找到唯一匹配的已发布结构化表格。",
                source_ids=[arguments.document_id] if matches else [],
                data={"found": False, "ambiguous": len(matches) > 1},
            )
        item = matches[0]
        headers = [_clean_text(cell, 500) for cell in (item.get("headers") or [])]
        raw_rows = item.get("rows") or []
        rows = [
            [_clean_text(cell, 500) for cell in row]
            for row in raw_rows[: arguments.max_rows]
            if isinstance(row, Sequence) and not isinstance(row, (str, bytes, bytearray))
        ]
        if not headers and not rows:
            return AgentToolResult(summary="已发布表格没有可用结构化单元格。", data={"found": False})
        return AgentToolResult(
            summary=f"已读取表格 {arguments.table_id}，共 {len(rows)} 行。",
            source_ids=[arguments.document_id],
            data={"found": True, "table": {"table_id": arguments.table_id, "caption": _clean_text(item.get("caption"), 300), "headers": headers, "rows": rows, "page": item.get("page")}},
        )


class VerifyCitationsArguments(AgentToolArguments):
    citation_ids: list[str] = Field(min_length=1, max_length=20)


class VerifyCitationsTool:
    name = "verify_citations"
    description = "核对引用是否来自本次受控工具结果或仍处于公开状态的资料。"
    arguments_model = VerifyCitationsArguments
    metadata = _metadata(
        risk="low",
        permissions=("read:published_knowledge", "read:run_provenance"),
        timeout_seconds=2.0,
        max_items=20,
        max_input_chars=2000,
    )

    def __init__(self, catalog: StructuredKnowledgePort) -> None:
        self.catalog = catalog

    def invoke(self, context: AgentToolContext, arguments: VerifyCitationsArguments) -> AgentToolResult:
        requested = list(dict.fromkeys(_clean_id(item) for item in arguments.citation_ids if _clean_id(item)))
        available = set(context.source_ids)
        valid: list[str] = []
        invalid: list[str] = []
        details: list[dict[str, object]] = []
        for source_id in requested:
            published = _published(self.catalog, source_id)
            in_run = source_id in available
            ok = in_run and (published is not None or source_id in available)
            (valid if ok else invalid).append(source_id)
            details.append({"source_id": source_id, "in_current_run": in_run, "published": published is not None, "valid": ok})
        return AgentToolResult(
            summary=(f"已核对 {len(requested)} 条引用：{len(valid)} 条有效，{len(invalid)} 条无效。"),
            source_ids=valid,
            data={"verified": not invalid, "valid_ids": valid, "invalid_ids": invalid, "details": details},
        )


class ExtractMeasurementsArguments(AgentToolArguments):
    media_asset_ids: list[str] | None = Field(default=None, max_length=3)


class ExtractMeasurementsTool:
    name = "extract_measurements"
    description = "整理当前任务已授权视觉观察中的结构化测量指标，不进行诊断或异常判定。"
    arguments_model = ExtractMeasurementsArguments
    metadata = _metadata(
        risk="medium",
        permissions=("read:visual_observations",),
        timeout_seconds=1.0,
        max_items=50,
        max_input_chars=500,
    )

    def invoke(self, context: AgentToolContext, arguments: ExtractMeasurementsArguments) -> AgentToolResult:
        allowed = set(arguments.media_asset_ids or [])
        measurements: list[dict[str, object]] = []
        source_ids: list[str] = []
        seen: set[tuple[str, str, str, str]] = set()
        for item in context.visual_observations:
            asset_id = _clean_id(item.get("media_asset_id"))
            if not asset_id or (allowed and asset_id not in allowed):
                continue
            raw = item.get("observation") if isinstance(item, Mapping) else None
            try:
                observation = VisionObservation.model_validate(raw)
            except Exception:
                continue
            if asset_id not in source_ids:
                source_ids.append(asset_id)
            for measurement in observation.measurements:
                key = (_norm(measurement.name), _norm(measurement.value), _norm(measurement.unit), asset_id)
                if key in seen:
                    continue
                seen.add(key)
                measurements.append({"media_asset_id": asset_id, **measurement.model_dump(mode="json")})
        return AgentToolResult(
            summary=(f"已整理 {len(measurements)} 个结构化测量指标；结果仅是图片可见信息整理，不代表诊断。"),
            source_ids=source_ids,
            data={"found": bool(measurements), "measurements": measurements, "medical_disclaimer": "仅整理图片中已有结构化指标，不构成诊断、治疗或用药建议。"},
        )


class DraftFollowUpPlanArguments(AgentToolArguments):
    goal: str = Field(min_length=1, max_length=1000)
    document_ids: list[str] = Field(default_factory=list, max_length=3)
    max_questions: int = Field(default=6, ge=1, le=10)


class DraftFollowUpPlanTool:
    name = "draft_follow_up_plan"
    description = "基于用户目标和已发布资料生成随访问题清单草稿，并明确非诊疗用途。"
    arguments_model = DraftFollowUpPlanArguments
    metadata = _metadata(
        risk="medium",
        permissions=("read:published_knowledge", "write:draft_output"),
        timeout_seconds=1.0,
        max_items=10,
        max_input_chars=1200,
    )

    DISCLAIMER = "本工具仅生成资料整理用的随访问题草稿，不构成诊断、治疗或用药建议。"
    _templates = (
        ("症状与变化", "与上次相比，相关症状的开始时间、频率、持续时间和变化趋势是什么？"),
        ("检查资料", "下次沟通前，哪些已有检查结果、报告日期和医生说明需要一并核对？"),
        ("用药记录", "目前实际使用的药物、剂量、时间和不适反应是否需要整理成清单供专业人员复核？"),
        ("生活情况", "近期饮食、睡眠、活动和其他生活因素是否出现值得记录的变化？"),
        ("风险提示", "是否出现需要尽快联系医疗机构的明显变化或紧急情况？"),
        ("下次目标", "下次随访最希望向专业人员确认的一个问题是什么？"),
    )

    def __init__(self, catalog: StructuredKnowledgePort) -> None:
        self.catalog = catalog

    def invoke(self, context: AgentToolContext, arguments: DraftFollowUpPlanArguments) -> AgentToolResult:
        del context
        source_ids: list[str] = []
        missing: list[str] = []
        for document_id in dict.fromkeys(arguments.document_ids):
            if _published(self.catalog, document_id) is None:
                missing.append(document_id)
            else:
                source_ids.append(document_id)
        if missing:
            return AgentToolResult(summary="部分资料不可见，未生成不完整的随访草稿。", data={"missing_document_ids": missing})
        goal = _norm(arguments.goal)
        selected = list(self._templates)
        if any(token in goal for token in ("检查", "报告", "指标")):
            selected = [self._templates[1], self._templates[0], self._templates[4], self._templates[5], self._templates[2], self._templates[3]]
        questions = [{"topic": topic, "question": question} for topic, question in selected[: arguments.max_questions]]
        return AgentToolResult(
            summary=f"已生成 {len(questions)} 项随访问题草稿。{self.DISCLAIMER}",
            source_ids=source_ids,
            data={"goal": arguments.goal.strip(), "questions": questions, "medical_disclaimer": self.DISCLAIMER},
        )


def stage26_tool_definitions() -> list[dict[str, object]]:
    """Metadata-only catalogue used by the authenticated tools endpoint."""

    tools = (
        CalculatorTool(),
        # The remaining tools need a catalog at runtime; their schema and
        # metadata are still safe to expose through no-op public definitions.
        GetDocumentSectionTool(_MetadataCatalog()),
        ExtractTableTool(_MetadataCatalog()),
        VerifyCitationsTool(_MetadataCatalog()),
        ExtractMeasurementsTool(),
        DraftFollowUpPlanTool(_MetadataCatalog()),
    )
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.arguments_model.model_json_schema(),
            "metadata": tool.metadata.model_dump(mode="json"),
        }
        for tool in tools
    ]


class _MetadataCatalog:
    def get_published_document(self, document_id: str):
        del document_id
        return None
