"""任务12.3/12.4：解析质量与候选解析器晋级门槛。"""

from pathlib import Path

from app.modules.knowledge.parser import LocalDocumentParser, ParsedPreview
from app.modules.knowledge.parser_experiments import (
    OptionalDoclingParser,
    ParserEvaluationCase,
    candidate_can_replace_baseline,
    evaluate_parser,
)


class BetterParser:
    def parse(self, path, suffix):
        return ParsedPreview("表格 单元格", 1, (), {"status": "pass"})


class WorseParser:
    def parse(self, path, suffix):
        return ParsedPreview("只有表格", 1)


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
