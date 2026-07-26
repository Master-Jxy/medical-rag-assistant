"""可选复杂文档解析器与固定集晋级规则。"""

from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path

from app.modules.knowledge.parser import ParsedPreview, ParserPort


class OptionalDoclingParser:
    name = "docling"

    @property
    def available(self) -> bool:
        return find_spec("docling") is not None

    def parse(self, path: Path, suffix: str) -> ParsedPreview:
        if not self.available:
            raise RuntimeError("Docling未安装，继续使用PyPDF基线")
        from docling.document_converter import DocumentConverter

        result = DocumentConverter().convert(path)
        text = result.document.export_to_markdown().strip()
        if not text:
            raise ValueError("Docling没有提取到有效文本")
        return ParsedPreview(
            text=text[:8000],
            page_count=len(getattr(result.document, "pages", {}) or {1: None}),
            warnings=("Docling实验输出，尚未晋级生产基线",),
            quality={"status": "experimental", "counts": {}, "page_results": []},
        )


class OptionalOcrParser:
    name = "ocr"

    @property
    def available(self) -> bool:
        return find_spec("pytesseract") is not None and find_spec("pdf2image") is not None

    def parse(self, path: Path, suffix: str) -> ParsedPreview:
        if not self.available:
            raise RuntimeError("OCR依赖未安装，不能静默伪造扫描页文本")
        raise RuntimeError("OCR候选仅登记能力，不在未完成固定集验收前启用")


@dataclass(frozen=True, slots=True)
class ParserEvaluationCase:
    path: Path
    suffix: str
    required_text: tuple[str, ...]
    expected_min_pages: int = 1


@dataclass(frozen=True, slots=True)
class ParserEvaluationResult:
    parser_name: str
    passed: int
    total: int
    failures: tuple[str, ...]

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0


def evaluate_parser(name: str, parser: ParserPort, cases: list[ParserEvaluationCase]):
    passed = 0
    failures = []
    for case in cases:
        try:
            result = parser.parse(case.path, case.suffix)
            valid = (
                result.page_count >= case.expected_min_pages
                and all(text in result.text for text in case.required_text)
            )
        except Exception as exc:
            valid = False
            failures.append(f"{case.path.name}:{type(exc).__name__}")
        if valid:
            passed += 1
        elif not failures or not failures[-1].startswith(case.path.name):
            failures.append(f"{case.path.name}:quality_mismatch")
    return ParserEvaluationResult(name, passed, len(cases), tuple(failures))


def candidate_can_replace_baseline(
    baseline: ParserEvaluationResult,
    candidate: ParserEvaluationResult,
) -> bool:
    """候选必须无失败、全量通过且严格优于基线才可晋级。"""
    return (
        candidate.total == baseline.total
        and candidate.total > 0
        and not candidate.failures
        and candidate.pass_rate == 1
        and candidate.passed > baseline.passed
    )
