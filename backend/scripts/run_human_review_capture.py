"""重新运行40题并把回答写入7天后过期的本地忽略文件。"""

import argparse
import json
from pathlib import Path

from app.core.config import get_settings
from app.evaluation.budget import EvaluationBudget, EvaluationBudgetExceeded
from app.evaluation.current_adapters import (
    CurrentChromaRetrievalAdapter,
    CurrentQwenAnswerAdapter,
    RetrievedContextStore,
    create_current_chat_model,
    create_current_vector_search,
)
from app.evaluation.preflight import run_preflight
from app.evaluation.review_capture import (
    RecordingAnswerAdapter,
    cleanup_capture_temporary_files,
    publish_capture_artifacts,
)
from app.evaluation.runner import run_evaluation
from scripts.build_corpus_manifest import build_current_manifest
from scripts.run_current_baseline import default_budget_limits, load_assets

EVALUATION_ROOT = Path(__file__).resolve().parents[1] / "evaluation"
REPORT_OUTPUT = EVALUATION_ROOT / "reports" / "human_review_capture_v1.json"
LOCAL_REVIEW_ROOT = EVALUATION_ROOT / "local_reviews"
LOCAL_REVIEW_OUTPUT = LOCAL_REVIEW_ROOT / "human_review_capture_v1.json"
PAID_CONFIRMATION = "RUN_HUMAN_REVIEW_CAPTURE_V1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-paid-run", default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cleanup_capture_temporary_files(REPORT_OUTPUT, LOCAL_REVIEW_OUTPUT)
    if REPORT_OUTPUT.exists() or LOCAL_REVIEW_OUTPUT.exists():
        raise SystemExit("捕获产物已存在，禁止覆盖或重复付费运行")
    settings = get_settings()
    evaluation_set, corpus, categories = load_assets()
    limits = default_budget_limits()
    preflight = run_preflight(
        evaluation_set=evaluation_set,
        corpus=corpus,
        category_config=categories,
        settings=settings,
        budget_limits=limits,
        current_manifest_reader=build_current_manifest,
    )
    print(json.dumps(preflight.__dict__, ensure_ascii=False, indent=2))
    print("scope=all_40")
    print("local_retention_days=7")
    print(
        "hard_limits="
        + json.dumps(limits.__dict__, ensure_ascii=False, sort_keys=True)
    )
    if not args.execute:
        print("PRECHECK_ONLY：未调用真实 Embedding 或 Qwen。")
        return
    if args.confirm_paid_run != PAID_CONFIRMATION:
        raise SystemExit(
            f"付费运行还需要 --confirm-paid-run {PAID_CONFIRMATION}"
        )

    context_store = RetrievedContextStore()
    retrieval = CurrentChromaRetrievalAdapter(
        create_current_vector_search(settings), context_store
    )
    current_answer = CurrentQwenAnswerAdapter(
        create_current_chat_model(
            settings,
            max_output_tokens=limits.model_output_tokens_reserved_per_call,
        ),
        context_store,
        input_price_per_million_cny=limits.model_input_price_per_million_tokens_cny,
        output_price_per_million_cny=limits.model_output_price_per_million_tokens_cny,
    )
    recording_answer = RecordingAnswerAdapter(current_answer)
    budget = EvaluationBudget(limits)
    try:
        report = run_evaluation(
            evaluation_set=evaluation_set,
            corpus=corpus,
            category_config=categories,
            retrieval_port=retrieval,
            answer_port=recording_answer,
            report_version="human_review_capture_v1",
            run_kind="current_baseline",
            run_guard=budget,
        )
    except EvaluationBudgetExceeded as exc:
        raise SystemExit(f"BUDGET_STOP：{exc}") from exc
    if report.metrics.completed_case_count != 40 or report.metrics.failed_case_count != 0:
        raise SystemExit("40题未全部完成，不写入捕获产物")
    bundle = publish_capture_artifacts(
        report=report,
        evaluation_set=evaluation_set,
        answers=recording_answer.answers,
        report_output=REPORT_OUTPUT,
        local_review_output=LOCAL_REVIEW_OUTPUT,
        local_review_root=LOCAL_REVIEW_ROOT,
    )
    print(f"report_written={REPORT_OUTPUT}")
    print(f"local_review_written={LOCAL_REVIEW_OUTPUT}")
    print(f"local_review_expires_at={bundle.expires_at.isoformat()}")


if __name__ == "__main__":
    main()
