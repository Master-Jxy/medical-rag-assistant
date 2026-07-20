"""在内存中捕获评估回答，并仅写入受控的本地忽略文件。"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from app.evaluation.human_review import (
    HumanBehaviorDecision,
    HumanFactDecision,
    LocalHumanReviewBundle,
    LocalHumanReviewItem,
    sha256_file,
)
from app.evaluation.ports import (
    AnswerObservation,
    EvaluationAnswerPort,
    EvaluationQuery,
)
from app.evaluation.report_schemas import BaselineReport
from app.evaluation.schemas import EvaluationSet

CAPTURE_TEMP_SUFFIX = ".capture.tmp"


class RecordingAnswerAdapter:
    """装饰现有回答 Port；不改变调用，只在当前进程内保留正文。"""

    def __init__(self, wrapped: EvaluationAnswerPort) -> None:
        self._wrapped = wrapped
        self.adapter_name = f"{wrapped.adapter_name}_local_capture_v1"
        self.answers: dict[str, str] = {}

    def answer(
        self, query: EvaluationQuery, source_document_ids: tuple[str, ...]
    ) -> AnswerObservation:
        observation = self._wrapped.answer(query, source_document_ids)
        self.answers[query.case_id] = observation.answer_text
        return observation


def build_initial_review_bundle(
    *,
    evaluation_set: EvaluationSet,
    report_path: Path,
    answers: dict[str, str],
    created_at: datetime | None = None,
) -> LocalHumanReviewBundle:
    timestamp = created_at or datetime.now(timezone.utc)
    expected_ids = [case.case_id for case in evaluation_set.cases]
    if set(answers) != set(expected_ids):
        missing = sorted(set(expected_ids) - set(answers))
        extra = sorted(set(answers) - set(expected_ids))
        raise ValueError(f"回答捕获不完整：missing={missing}, extra={extra}")
    return LocalHumanReviewBundle(
        schema_version="local_human_review_v1",
        dataset_version=evaluation_set.dataset_version,
        corpus_checksum=evaluation_set.corpus_checksum,
        source_report_sha256=sha256_file(report_path),
        created_at=timestamp,
        expires_at=timestamp + timedelta(days=7),
        items=[
            LocalHumanReviewItem(
                case_id=case.case_id,
                answer_text=answers[case.case_id],
                behavior_decision=HumanBehaviorDecision.UNCERTAIN,
                key_fact_decisions=[HumanFactDecision.UNCERTAIN]
                * len(case.expected_key_facts),
                reviewer_notes="",
            )
            for case in evaluation_set.cases
        ],
    )


def write_local_review_bundle(
    *, bundle: LocalHumanReviewBundle, output_path: Path, local_review_root: Path
) -> None:
    root = local_review_root.resolve()
    path = output_path.resolve()
    if root not in path.parents:
        raise ValueError("回答正文只能写入受控 local_reviews 目录")
    if path.suffix.lower() != ".json":
        raise ValueError("本地人工复核文件必须使用 .json 后缀")
    if path.exists():
        raise FileExistsError("本地人工复核文件已存在，禁止覆盖")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    if temporary_path.exists():
        raise FileExistsError("本地人工复核临时文件已存在")
    rendered = (
        json.dumps(bundle.model_dump(mode="json"), ensure_ascii=False, indent=2)
        + "\n"
    )
    temporary_path.write_text(rendered, encoding="utf-8")
    temporary_path.replace(path)


def capture_temporary_path(output_path: Path) -> Path:
    """返回捕获专用暂存路径；它不会被当成已完成产物。"""
    return output_path.with_name(output_path.name + CAPTURE_TEMP_SUFFIX)


def cleanup_capture_temporary_files(*output_paths: Path) -> None:
    """清理上次中断遗留的捕获暂存文件，不触碰任何正式产物。"""
    for output_path in output_paths:
        temporary_path = capture_temporary_path(output_path)
        if temporary_path.is_file():
            temporary_path.unlink()


def publish_capture_artifacts(
    *,
    report: BaselineReport,
    evaluation_set: EvaluationSet,
    answers: dict[str, str],
    report_output: Path,
    local_review_output: Path,
    local_review_root: Path,
    created_at: datetime | None = None,
    replace_file: Callable[[Path, Path], None] | None = None,
) -> LocalHumanReviewBundle:
    """暂存并校验两份捕获内容，再以失败补偿方式发布正式文件。"""
    report_path = report_output.resolve()
    local_path = local_review_output.resolve()
    root = local_review_root.resolve()
    if root not in local_path.parents:
        raise ValueError("回答正文只能写入受控 local_reviews 目录")
    if report_path.suffix.lower() != ".json" or local_path.suffix.lower() != ".json":
        raise ValueError("捕获产物必须使用 .json 后缀")
    if report_path.exists() or local_path.exists():
        raise FileExistsError("捕获正式产物已存在，禁止覆盖")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    cleanup_capture_temporary_files(report_path, local_path)
    report_temporary = capture_temporary_path(report_path)
    local_temporary = capture_temporary_path(local_path)
    replace = replace_file or (lambda source, target: source.replace(target))
    published: list[Path] = []
    try:
        report_temporary.write_text(
            json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        staged_report = BaselineReport.model_validate_json(
            report_temporary.read_text(encoding="utf-8")
        )
        if staged_report != report:
            raise ValueError("暂存报告校验失败")

        bundle = build_initial_review_bundle(
            evaluation_set=evaluation_set,
            report_path=report_temporary,
            answers=answers,
            created_at=created_at,
        )
        local_temporary.write_text(
            json.dumps(bundle.model_dump(mode="json"), ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        staged_bundle = LocalHumanReviewBundle.model_validate_json(
            local_temporary.read_text(encoding="utf-8")
        )
        if staged_bundle != bundle:
            raise ValueError("暂存本地复核包校验失败")
        if staged_bundle.source_report_sha256 != sha256_file(report_temporary):
            raise ValueError("暂存报告与本地复核包哈希不一致")

        replace(report_temporary, report_path)
        published.append(report_path)
        replace(local_temporary, local_path)
        published.append(local_path)
        return bundle
    except BaseException:
        for published_path in reversed(published):
            if published_path.is_file():
                published_path.unlink()
        raise
    finally:
        cleanup_capture_temporary_files(report_path, local_path)


def replace_local_review_bundle(
    *, bundle: LocalHumanReviewBundle, output_path: Path, local_review_root: Path
) -> None:
    root = local_review_root.resolve()
    path = output_path.resolve()
    if root not in path.parents:
        raise ValueError("回答正文只能写入受控 local_reviews 目录")
    if not path.is_file():
        raise FileNotFoundError("待更新的本地人工复核文件不存在")
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    if temporary_path.exists():
        raise FileExistsError("本地人工复核临时文件已存在")
    rendered = (
        json.dumps(bundle.model_dump(mode="json"), ensure_ascii=False, indent=2)
        + "\n"
    )
    temporary_path.write_text(rendered, encoding="utf-8")
    temporary_path.replace(path)
