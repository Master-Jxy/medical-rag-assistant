"""任务12.3/12.4：解析质量与候选解析器晋级门槛。"""

import json
import multiprocessing
import time
from pathlib import Path

from app.infrastructure import docling_pdf_parser
from app.infrastructure.docling_pdf_parser import DoclingPdfStructuredParser
from app.modules.knowledge.ingestion import (
    ParseRequest,
    ParsedAsset,
    ParsedDocument,
    ParsedElement,
    ParseQuality,
)
from app.modules.knowledge.parser import LocalDocumentParser, ParsedPreview
from app.modules.knowledge.parser import PdfCandidateFallbackParser
from app.modules.knowledge.parser_experiments import (
    ComplexPdfFixtureCase,
    OptionalDoclingParser,
    ParserEvaluationCase,
    candidate_structured_pdf_can_replace_baseline,
    candidate_can_replace_baseline,
    evaluate_structured_pdf_output,
    evaluate_parser,
    load_complex_pdf_manifest,
)


class BetterParser:
    def parse(self, path, suffix):
        return ParsedPreview("表格 单元格", 1, (), {"status": "pass"})


class WorseParser:
    def parse(self, path, suffix):
        return ParsedPreview("只有表格", 1)


def hanging_docling_worker(_path_text, _output_queue) -> None:
    time.sleep(30)


def failing_docling_worker(_path_text, output_queue) -> None:
    output_queue.put({"ok": False, "error_code": "docling_parse_failed"})


class BaselineStructuredParser:
    def __init__(self) -> None:
        self.calls = 0

    def parse(self, request: ParseRequest) -> ParsedDocument:
        self.calls += 1
        return ParsedDocument(
            document_metadata={"page_count": 1, "parser": "pypdf"},
            elements=(ParsedElement("b1", "paragraph", "PyPDF基线文本", 1, 1),),
            quality=ParseQuality(status="pass", parser_name="pypdf"),
        )


class CandidateStructuredParser:
    def __init__(self, *, fail: bool = False, bad_page_order: bool = False) -> None:
        self.fail = fail
        self.bad_page_order = bad_page_order
        self.calls = 0

    def parse(self, request: ParseRequest) -> ParsedDocument:
        self.calls += 1
        if self.fail:
            raise RuntimeError("candidate failed")
        first_page, second_page = (2, 1) if self.bad_page_order else (1, 1)
        return ParsedDocument(
            document_metadata={"page_count": 1, "parser": "docling_pdf_candidate"},
            elements=(
                ParsedElement("c1", "title", "Docling标题", first_page, 1),
                ParsedElement(
                    "c2",
                    "table",
                    "Header | Value\nA | B",
                    second_page,
                    2,
                    table_html="<table><tr><td>Header</td></tr></table>",
                ),
            ),
            quality=ParseQuality(status="warning", parser_name="docling_pdf_candidate"),
        )


def test_text_preview_has_structured_quality(tmp_path) -> None:
    path = tmp_path / "sample.txt"
    path.write_text("普通文本内容", encoding="utf-8")
    preview = LocalDocumentParser().parse(path, ".txt")
    assert preview.quality["status"] == "pass"
    assert preview.quality["counts"] == {
        "text": 1,
        "table_like": 0,
        "scanned_or_image": 0,
    }


def test_candidate_must_strictly_beat_baseline_on_fixed_cases(tmp_path) -> None:
    path = tmp_path / "table.txt"
    path.write_text("表格", encoding="utf-8")
    cases = [ParserEvaluationCase(path, ".txt", ("表格", "单元格"))]
    baseline = evaluate_parser("pypdf", WorseParser(), cases)
    candidate = evaluate_parser("candidate", BetterParser(), cases)
    assert baseline.pass_rate == 0
    assert candidate_can_replace_baseline(baseline, candidate) is True
    assert candidate_can_replace_baseline(candidate, candidate) is False


def test_docling_is_optional_and_cannot_be_claimed_when_absent() -> None:
    parser = OptionalDoclingParser()
    if not parser.available:
        try:
            parser.parse(Path("missing.pdf"), ".pdf")
        except RuntimeError as exc:
            assert "未安装" in str(exc)


def test_pdf_candidate_fallback_keeps_baseline_when_disabled_or_failed(tmp_path, monkeypatch) -> None:
    path = tmp_path / "sample.pdf"
    path.write_bytes(b"%PDF-1.4\n%fake")
    baseline = BaselineStructuredParser()
    candidate = CandidateStructuredParser()
    disabled = PdfCandidateFallbackParser(baseline, candidate, enabled=False)

    parsed = disabled.parse(ParseRequest(path=path, suffix=".pdf"))

    assert parsed.text == "PyPDF基线文本"
    assert baseline.calls == 1
    assert candidate.calls == 0

    failing_candidate = CandidateStructuredParser(fail=True)
    enabled = PdfCandidateFallbackParser(
        baseline,
        failing_candidate,
        enabled=True,
        max_pages=1,
        max_file_size_bytes=100,
    )
    monkeypatch.setattr(enabled, "_check_resource_bounds", lambda _path: None)
    parsed = enabled.parse(ParseRequest(path=path, suffix=".pdf"))

    assert parsed.text == "PyPDF基线文本"
    assert failing_candidate.calls == 1
    assert any("Docling候选已回退PyPDF" in warning for warning in parsed.warnings)


def test_pdf_candidate_fallback_observes_valid_candidate_without_promoting(tmp_path, monkeypatch) -> None:
    path = tmp_path / "sample.pdf"
    path.write_bytes(b"%PDF-1.4\n%fake")
    baseline = BaselineStructuredParser()
    candidate = CandidateStructuredParser()
    parser = PdfCandidateFallbackParser(
        baseline,
        candidate,
        enabled=True,
        max_pages=1,
        max_file_size_bytes=100,
    )
    monkeypatch.setattr(parser, "_check_resource_bounds", lambda _path: None)

    parsed = parser.parse(ParseRequest(path=path, suffix=".pdf"))

    assert parsed.document_metadata["parser"] == "pypdf"
    assert parsed.quality.parser_name == "pypdf"
    assert "PyPDF基线文本" in parsed.text
    assert any("尚未批准替换PyPDF" in warning for warning in parsed.warnings)

    promoted = PdfCandidateFallbackParser(
        baseline,
        candidate,
        enabled=True,
        promoted=True,
        max_pages=1,
        max_file_size_bytes=100,
    )
    monkeypatch.setattr(promoted, "_check_resource_bounds", lambda _path: None)
    parsed = promoted.parse(ParseRequest(path=path, suffix=".pdf"))

    assert parsed.document_metadata["parser"] == "docling_pdf_candidate"
    assert parsed.quality.parser_name == "docling_pdf_candidate"
    assert "Header | Value" in parsed.text


def test_pdf_candidate_fallback_rejects_busy_or_out_of_order_candidate(tmp_path, monkeypatch) -> None:
    path = tmp_path / "sample.pdf"
    path.write_bytes(b"%PDF-1.4\n%fake")
    baseline = BaselineStructuredParser()
    candidate = CandidateStructuredParser()
    parser = PdfCandidateFallbackParser(
        baseline,
        candidate,
        enabled=True,
        max_pages=1,
        max_file_size_bytes=100,
    )
    monkeypatch.setattr(parser, "_check_resource_bounds", lambda _path: None)

    acquired = parser._candidate_semaphore.acquire(blocking=False)
    try:
        assert acquired is True
        parsed = parser.parse(ParseRequest(path=path, suffix=".pdf"))
    finally:
        parser._candidate_semaphore.release()

    assert parsed.text == "PyPDF基线文本"
    assert candidate.calls == 0
    assert any("并发限制" in warning for warning in parsed.warnings)

    bad_candidate = CandidateStructuredParser(bad_page_order=True)
    parser = PdfCandidateFallbackParser(
        baseline,
        bad_candidate,
        enabled=True,
        max_pages=1,
        max_file_size_bytes=100,
    )
    monkeypatch.setattr(parser, "_check_resource_bounds", lambda _path: None)

    parsed = parser.parse(ParseRequest(path=path, suffix=".pdf"))

    assert parsed.text == "PyPDF基线文本"
    assert bad_candidate.calls == 1
    assert any("页序异常" in warning for warning in parsed.warnings)


class FakeDoclingConverter:
    def convert(self, _path):
        return {
            "page_count": 2,
            "elements": [
                {
                    "kind": "title",
                    "text": "复杂PDF标题",
                    "page_no": 1,
                    "bbox": [0.1, 0.1, 0.8, 0.18],
                },
                {
                    "kind": "paragraph",
                    "text": "left column then right column",
                    "page_no": 1,
                    "bbox": [0.1, 0.2, 0.9, 0.4],
                },
                {
                    "kind": "table",
                    "page_no": 2,
                    "rows": [["Header A", "Header B"], ["continued row", "value"]],
                    "bbox": [0.1, 0.2, 0.9, 0.7],
                },
                {
                    "kind": "image",
                    "page_no": 2,
                    "storage_ref": "docling://image/1",
                    "sha256": "a" * 64,
                },
            ],
        }


def test_docling_adapter_normalizes_elements_tables_assets_and_bbox(tmp_path) -> None:
    path = tmp_path / "candidate.pdf"
    path.write_bytes(b"%PDF-1.4\n%fake")
    parser = DoclingPdfStructuredParser(converter_factory=FakeDoclingConverter)

    parsed = parser.parse(ParseRequest(path=path, suffix=".pdf"))

    assert parsed.document_metadata["parser"] == "docling_pdf_candidate"
    assert [element.kind for element in parsed.elements] == [
        "title",
        "paragraph",
        "table",
    ]
    assert parsed.elements[0].bbox == (0.1, 0.1, 0.8, 0.18)
    assert "Header A | Header B" in parsed.elements[-1].text
    assert parsed.elements[-1].table_html.startswith("<table>")
    assert parsed.assets[0].storage_ref == "docling://image/1"
    assert parsed.assets[0].page_no == 2


def test_docling_adapter_subprocess_timeout_is_killed_and_sanitized(tmp_path, monkeypatch) -> None:
    path = tmp_path / "secret-patient-content.pdf"
    path.write_bytes(b"%PDF-1.4\n%fake")
    monkeypatch.setattr(docling_pdf_parser, "find_spec", lambda _name: object())
    parser = DoclingPdfStructuredParser(
        timeout_seconds=0.2,
        worker_target=hanging_docling_worker,
    )

    started = time.monotonic()
    try:
        parser.parse(ParseRequest(path=path, suffix=".pdf"))
    except Exception as exc:
        elapsed = time.monotonic() - started
        message = str(exc)
    else:
        raise AssertionError("expected timeout")

    assert elapsed < 5
    assert "timed out" in message
    assert "secret-patient-content" not in message
    assert all(
        child.name != "docling-pdf-candidate"
        for child in multiprocessing.active_children()
    )


def test_docling_adapter_worker_error_does_not_leak_path_or_content(tmp_path, monkeypatch) -> None:
    path = tmp_path / "secret-patient-content.pdf"
    path.write_bytes(b"%PDF-1.4\n%fake")
    monkeypatch.setattr(docling_pdf_parser, "find_spec", lambda _name: object())
    parser = DoclingPdfStructuredParser(
        timeout_seconds=5,
        worker_target=failing_docling_worker,
    )

    try:
        parser.parse(ParseRequest(path=path, suffix=".pdf"))
    except Exception as exc:
        message = str(exc)
    else:
        raise AssertionError("expected worker failure")

    assert "docling_parse_failed" in message
    assert "secret-patient-content" not in message


def test_complex_pdf_manifest_and_structured_gate_require_real_improvement() -> None:
    manifest_path = Path("backend/tests/fixtures/stage24_complex_pdf_manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases = load_complex_pdf_manifest(manifest, manifest_path.parent)
    assert [case.case_id for case in cases] == [
        "two_column_order",
        "cross_page_table",
        "image_asset",
        "blank_page_candidate",
        "damaged_candidate",
    ]

    target = ComplexPdfFixtureCase(
        case_id="cross_page_table",
        path=Path("synthetic/cross-page-table.pdf"),
        expected_pages=2,
        expected_min_elements=2,
        expected_min_tables=1,
        expected_required_text=("Header A", "continued row"),
    )
    baseline_doc = ParsedDocument(
        document_metadata={"page_count": 2},
        elements=(
            ParsedElement("b1", "paragraph", "Header A continued row", 1, 1),
        ),
        quality=ParseQuality(status="pass"),
    )
    candidate_doc = ParsedDocument(
        document_metadata={"page_count": 2},
        elements=(
            ParsedElement("c1", "paragraph", "Header A intro", 1, 1, bbox=(0.1, 0.1, 0.9, 0.2)),
            ParsedElement(
                "c2",
                "table",
                "Header A | Header B\ncontinued row | value",
                2,
                2,
                bbox=(0.1, 0.2, 0.9, 0.7),
                table_html="<table><tr><td>Header A</td></tr></table>",
            ),
        ),
        assets=(ParsedAsset("a1", "embedded_image", 2, "image/png", "asset://1", "b" * 64),),
        quality=ParseQuality(status="warning"),
    )

    baseline = evaluate_structured_pdf_output("pypdf", [(target, baseline_doc)])
    candidate = evaluate_structured_pdf_output("docling", [(target, candidate_doc)])

    assert baseline.hard_failures
    assert not candidate.hard_failures
    assert candidate.average_score > baseline.average_score
    assert candidate_structured_pdf_can_replace_baseline(baseline, candidate) is True
    assert candidate_structured_pdf_can_replace_baseline(candidate, candidate) is False


def test_structured_gate_marks_damaged_or_empty_candidate_as_not_promotable() -> None:
    target = ComplexPdfFixtureCase(
        "damaged_candidate",
        Path("synthetic/damaged.pdf"),
        expected_pages=1,
        expected_min_elements=1,
        expected_required_text=("recoverable fallback",),
    )
    baseline_doc = ParsedDocument(
        document_metadata={"page_count": 1},
        elements=(ParsedElement("b1", "paragraph", "recoverable fallback", 1, 1),),
    )
    baseline = evaluate_structured_pdf_output("pypdf", [(target, baseline_doc)])
    candidate = evaluate_structured_pdf_output(
        "docling",
        [(target, RuntimeError("damaged"))],
    )

    assert candidate.hard_failures == ("damaged_candidate:RuntimeError",)
    assert candidate_structured_pdf_can_replace_baseline(baseline, candidate) is False
