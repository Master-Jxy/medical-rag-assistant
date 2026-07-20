"""预检并在显式确认后运行当前 RAG 的付费真实基线。"""

import argparse
import json
from pathlib import Path

from app.core.config import get_settings
from app.evaluation.budget import (
    EvaluationBudget,
    EvaluationBudgetExceeded,
    EvaluationBudgetLimits,
)
from app.evaluation.current_adapters import (
    CurrentChromaRetrievalAdapter,
    CurrentQwenAnswerAdapter,
    RetrievedContextStore,
    create_current_chat_model,
    create_current_vector_search,
)
from app.evaluation.preflight import run_preflight
from app.evaluation.runner import run_evaluation
from app.evaluation.schemas import CorpusManifest, EvaluationSet
from scripts.build_corpus_manifest import build_current_manifest

EVALUATION_ROOT = Path(__file__).resolve().parents[1] / "evaluation"
OUTPUT = EVALUATION_ROOT / "reports" / "current_baseline_v1.json"
PAID_CONFIRMATION = "RUN_CURRENT_BASELINE_V1"

# 2026-07-18 中国内地公开价；预检会显式展示，实际运行前应再次核对。
DEFAULT_QWEN_INPUT_PRICE = 2.5
DEFAULT_QWEN_OUTPUT_PRICE = 10.0
DEFAULT_EMBEDDING_PRICE = 0.5


def default_budget_limits() -> EvaluationBudgetLimits:
    return EvaluationBudgetLimits(
        max_retrieval_calls=40,
        max_model_calls=40,
        max_total_tokens=500_000,
        max_estimated_cost_cny=2.0,
        embedding_tokens_reserved_per_call=512,
        model_input_tokens_reserved_per_call=9_900,
        model_output_tokens_reserved_per_call=2_048,
        embedding_price_per_million_tokens_cny=DEFAULT_EMBEDDING_PRICE,
        model_input_price_per_million_tokens_cny=DEFAULT_QWEN_INPUT_PRICE,
        model_output_price_per_million_tokens_cny=DEFAULT_QWEN_OUTPUT_PRICE,
    )


def load_assets() -> tuple[EvaluationSet, CorpusManifest, dict]:
    evaluation_set = EvaluationSet.model_validate_json(
        (EVALUATION_ROOT / "datasets" / "eval_v1.json").read_text(encoding="utf-8")
    )
    corpus = CorpusManifest.model_validate_json(
        (EVALUATION_ROOT / "corpora" / "corpus_v1.json").read_text(encoding="utf-8")
    )
    categories = json.loads(
        (EVALUATION_ROOT / "categories_v1.json").read_text(encoding="utf-8")
    )
    return evaluation_set, corpus, categories


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-paid-run", default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
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
    answer = CurrentQwenAnswerAdapter(
        create_current_chat_model(
            settings,
            max_output_tokens=limits.model_output_tokens_reserved_per_call,
        ),
        context_store,
        input_price_per_million_cny=limits.model_input_price_per_million_tokens_cny,
        output_price_per_million_cny=limits.model_output_price_per_million_tokens_cny,
    )
    budget = EvaluationBudget(limits)
    try:
        report = run_evaluation(
            evaluation_set=evaluation_set,
            corpus=corpus,
            category_config=categories,
            retrieval_port=retrieval,
            answer_port=answer,
            report_version="current_baseline_v1",
            run_kind="current_baseline",
            run_guard=budget,
        )
    except EvaluationBudgetExceeded as exc:
        raise SystemExit(f"BUDGET_STOP：{exc}") from exc
    OUTPUT.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"written={OUTPUT}")


if __name__ == "__main__":
    main()
