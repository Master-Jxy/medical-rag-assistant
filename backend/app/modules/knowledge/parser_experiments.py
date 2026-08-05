"""可选复杂文档解析器与固定集晋级规则。"""

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from app.infrastructure.docling_pdf_parser import DoclingPdfStructuredParser
from app.modules.knowledge.ingestion import ParseRequest, ParsedDocument
from app.modules.knowledge.parser import ParsedPreview, ParserPort


class OptionalDoclingParser(ParserPort):
    name = "docling"

    def __init__(self, structured_parser: DoclingPdfStructuredParser | None = None) -> None:
        self.structured_parser = structured_parser or DoclingPdfStructuredParser()

    @property
    def available(self) -> bool:
        return self.structured_parser.available

    def parse(self, path: Path, suffix: str) -> ParsedPreview:
        if not self.available:
            raise RuntimeError("Docling未安装，继续使用PyPDF基线")
        document = self.structured_parser.parse(ParseRequest(path=path, suffix=suffix))
        return ParsedPreview.from_document(document)


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


@dataclass(frozen=True, slots=True)
class ComplexPdfFixtureCase:
    case_id: str
    path: Path
    expected_pages: int
    expected_min_elements: int
    expected_min_tables: int = 0
    expected_min_assets: int = 0
    expected_required_text: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ComplexPdfQualityMetrics:
    page_count_match: bool
    non_empty_element_rate: float
    garbled_text_rate: float
    order_anomaly_count: int
    table_completeness_rate: float
    provenance_completeness_rate: float
    hard_failures: tuple[str, ...] = ()

    @property
    def score(self) -> float:
        if self.hard_failures:
            return 0.0
        return (
            (1.0 if self.page_count_match else 0.0)
            + self.non_empty_element_rate
            + (1.0 - self.garbled_text_rate)
            + (1.0 if self.order_anomaly_count == 0 else 0.0)
            + self.table_completeness_rate
            + self.provenance_completeness_rate
        ) / 6


@dataclass(frozen=True, slots=True)
class ComplexPdfCaseResult:
    case_id: str
    metrics: ComplexPdfQualityMetrics


@dataclass(frozen=True, slots=True)
class ComplexPdfEvaluationReport:
    parser_name: str
    cases: tuple[ComplexPdfCaseResult, ...]

    @property
    def hard_failures(self) -> tuple[str, ...]:
        failures: list[str] = []
        for case in self.cases:
            failures.extend(f"{case.case_id}:{failure}" for failure in case.metrics.hard_failures)
        return tuple(failures)

    @property
    def average_score(self) -> float:
        return (
            sum(case.metrics.score for case in self.cases) / len(self.cases)
            if self.cases
            else 0.0
        )


def evaluate_structured_pdf_output(
    parser_name: str,
    cases: list[tuple[ComplexPdfFixtureCase, ParsedDocument | Exception]],
) -> ComplexPdfEvaluationReport:
    results: list[ComplexPdfCaseResult] = []
    for case, output in cases:
        if isinstance(output, Exception):
            metrics = ComplexPdfQualityMetrics(
                page_count_match=False,
                non_empty_element_rate=0.0,
                garbled_text_rate=1.0,
                order_anomaly_count=1,
                table_completeness_rate=0.0,
                provenance_completeness_rate=0.0,
                hard_failures=(type(output).__name__,),
            )
        else:
            metrics = score_structured_pdf(case, output)
        results.append(ComplexPdfCaseResult(case.case_id, metrics))
    return ComplexPdfEvaluationReport(parser_name, tuple(results))


def score_structured_pdf(
    case: ComplexPdfFixtureCase,
    document: ParsedDocument,
) -> ComplexPdfQualityMetrics:
    elements = list(document.elements)
    failures: list[str] = []
    if not elements:
        failures.append("empty_output")
    page_count_match = document.page_count == case.expected_pages
    if not page_count_match:
        failures.append("page_count_mismatch")
    if len(elements) < case.expected_min_elements:
        failures.append("too_few_elements")
    if sum(element.kind == "table" for element in elements) < case.expected_min_tables:
        failures.append("missing_table")
    if len(document.assets) < case.expected_min_assets:
        failures.append("missing_asset")
    text = document.text
    for required in case.expected_required_text:
        if required not in text:
            failures.append(f"missing_text:{required}")

    non_empty_rate = (
        sum(1 for element in elements if element.text.strip()) / len(elements)
        if elements
        else 0.0
    )
    garbled_rate = calculate_garbled_text_rate(text)
    orders = [element.order for element in elements]
    pages = [element.page_no or 0 for element in elements]
    order_anomalies = sum(
        1
        for previous, current in zip(zip(pages, orders), zip(pages[1:], orders[1:]))
        if current < previous
    )
    tables = [element for element in elements if element.kind == "table"]
    complete_tables = [
        table
        for table in tables
        if "|" in table.text and (table.table_html or "").startswith("<table")
    ]
    table_rate = len(complete_tables) / len(tables) if tables else (1.0 if case.expected_min_tables == 0 else 0.0)
    provenance_total = len(elements) + len(document.assets)
    provenance_complete = sum(
        1 for element in elements if element.page_no is not None
    ) + sum(1 for asset in document.assets if asset.page_no is not None and asset.storage_ref)
    provenance_rate = provenance_complete / provenance_total if provenance_total else 0.0

    return ComplexPdfQualityMetrics(
        page_count_match=page_count_match,
        non_empty_element_rate=non_empty_rate,
        garbled_text_rate=garbled_rate,
        order_anomaly_count=order_anomalies,
        table_completeness_rate=table_rate,
        provenance_completeness_rate=provenance_rate,
        hard_failures=tuple(dict.fromkeys(failures)),
    )


def candidate_structured_pdf_can_replace_baseline(
    baseline: ComplexPdfEvaluationReport,
    candidate: ComplexPdfEvaluationReport,
) -> bool:
    return (
        len(candidate.cases) == len(baseline.cases)
        and bool(candidate.cases)
        and not candidate.hard_failures
        and candidate.average_score > baseline.average_score
    )


def load_complex_pdf_manifest(data: Mapping[str, object], root: Path) -> list[ComplexPdfFixtureCase]:
    cases = data.get("cases")
    if not isinstance(cases, list):
        raise ValueError("复杂PDF固定集manifest缺少cases")
    loaded: list[ComplexPdfFixtureCase] = []
    for item in cases:
        if not isinstance(item, Mapping):
            raise ValueError("复杂PDF固定集case格式错误")
        loaded.append(
            ComplexPdfFixtureCase(
                case_id=str(item["case_id"]),
                path=root / str(item["path"]),
                expected_pages=int(item["expected_pages"]),
                expected_min_elements=int(item["expected_min_elements"]),
                expected_min_tables=int(item.get("expected_min_tables", 0)),
                expected_min_assets=int(item.get("expected_min_assets", 0)),
                expected_required_text=tuple(
                    str(text) for text in item.get("expected_required_text", ())
                ),
            )
        )
    return loaded


def calculate_garbled_text_rate(text: str) -> float:
    if not text:
        return 1.0
    suspicious = sum(1 for char in text if char == "\ufffd" or ord(char) < 32 and char not in "\n\t")
    return suspicious / len(text)
