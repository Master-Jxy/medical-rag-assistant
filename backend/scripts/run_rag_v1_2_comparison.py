"""完整预检，并在双重确认后运行两个RAG v1.2真实候选。"""

import argparse
import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path

from app.core.config import get_settings
from app.evaluation.budget import (
    EvaluationBudget,
    EvaluationBudgetExceeded,
    EvaluationBudgetLimits,
)
from app.evaluation.candidate_adapters import (
    CandidateRetrievalAdapter,
    create_candidate_reranker,
)
from app.evaluation.comparison_preflight import run_full_comparison_preflight
from app.evaluation.comparison_schemas import ComparisonRunPlan
from app.evaluation.current_adapters import (
    CurrentQwenAnswerAdapter,
    RetrievedContextStore,
    create_current_chat_model,
    create_current_vector_search,
)
from app.evaluation.real_comparison import RealCandidatePorts, build_real_comparison
from app.evaluation.report_schemas import BaselineReport
from app.evaluation.schemas import CorpusManifest, EvaluationSet
from scripts.build_corpus_manifest import build_current_manifest
from scripts.preflight_rag_v1_2_comparison import build_plan
from scripts.run_mock_comparison import load_assets

EVALUATION_ROOT = Path(__file__).resolve().parents[1] / "evaluation"
PLAN_PATH = EVALUATION_ROOT / "plans" / "rag_v1_2_preflight_v1.json"
BASELINE_PATH = EVALUATION_ROOT / "reports" / "current_baseline_v1.json"
OUTPUT = EVALUATION_ROOT / "reports" / "rag_v1_2_real_comparison_v1.json"
TEMP_OUTPUT = OUTPUT.with_suffix(OUTPUT.suffix + ".comparison.tmp")
PAID_CONFIRMATION = "RUN_RAG_V1_2_COMPARISON_V1"


def comparison_budget_limits(plan: ComparisonRunPlan) -> EvaluationBudgetLimits:
    pricing = plan.pricing
    hard = plan.hard_limits
    return EvaluationBudgetLimits(
        max_retrieval_calls=hard.max_embedding_calls,
        max_model_calls=hard.max_answer_calls,
        max_total_tokens=hard.max_total_tokens,
        max_estimated_cost_cny=hard.max_estimated_cost_cny,
        embedding_tokens_reserved_per_call=512,
        model_input_tokens_reserved_per_call=9900,
        model_output_tokens_reserved_per_call=2048,
        embedding_price_per_million_tokens_cny=(
            pricing.embedding_price_per_million_tokens_cny
        ),
        model_input_price_per_million_tokens_cny=(
            pricing.qwen_input_price_per_million_tokens_cny
        ),
        model_output_price_per_million_tokens_cny=(
            pricing.qwen_output_price_per_million_tokens_cny
        ),
        max_rerank_calls=hard.max_rerank_calls,
        rerank_tokens_reserved_per_call=12000,
        rerank_cost_reserved_per_call_cny=0.01,
    )


def _load_checked_plan() -> tuple[ComparisonRunPlan, str]:
    expected = build_plan()
    content = PLAN_PATH.read_bytes()
    checked = ComparisonRunPlan.model_validate_json(content)
    if checked != expected:
        raise ValueError("版本化运行计划与当前代码、价格或冻结产物不一致")
    return checked, hashlib.sha256(content).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-paid-run", default="")
    parser.add_argument("--confirm-plan-sha256", default="")
    return parser.parse_args()


def require_execution_authorization(
    args: argparse.Namespace,
    *,
    plan_sha256: str,
    output_exists: bool,
) -> None:
    if output_exists:
        raise SystemExit(f"正式对比报告已存在，禁止覆盖：{OUTPUT}")
    if args.confirm_paid_run != PAID_CONFIRMATION:
        raise SystemExit(
            f"付费运行还需要 --confirm-paid-run {PAID_CONFIRMATION}"
        )
    if args.confirm_plan_sha256.lower() != plan_sha256:
        raise SystemExit(
            "付费运行还需要 --confirm-plan-sha256 当前预检输出的plan_sha256"
        )


def main() -> None:
    args = parse_args()
    if TEMP_OUTPUT.exists():
        TEMP_OUTPUT.unlink()
    settings = get_settings()
    evaluation_set, corpus, categories = load_assets()
    plan, plan_sha256 = _load_checked_plan()
    preflight = run_full_comparison_preflight(
        plan=plan,
        evaluation_set=evaluation_set,
        corpus=corpus,
        category_config=categories,
        settings=settings,
        current_manifest_reader=build_current_manifest,
    )
    print(json.dumps(asdict(preflight), ensure_ascii=False, indent=2))
    print(f"plan_sha256={plan_sha256}")
    print(
        "pricing="
        + json.dumps(plan.pricing.model_dump(), ensure_ascii=False, sort_keys=True)
    )
    if not args.execute:
        print("PRECHECK_ONLY：未创建模型客户端，未调用Embedding、Qwen或Reranker。")
        return
    require_execution_authorization(
        args,
        plan_sha256=plan_sha256,
        output_exists=OUTPUT.exists(),
    )

    profiles = {item.candidate_id: item for item in plan.candidate_profiles}
    limits = comparison_budget_limits(plan)
    budget = EvaluationBudget(limits)
    vector_search = create_current_vector_search(settings)
    chat_model = create_current_chat_model(
        settings,
        max_output_tokens=limits.model_output_tokens_reserved_per_call,
    )
    ports: list[RealCandidatePorts] = []
    for candidate_id in plan.new_candidate_ids:
        profile = profiles[candidate_id]
        context = RetrievedContextStore()
        retrieval = CandidateRetrievalAdapter(
            profile=profile,
            vector_store=vector_search,
            context_store=context,
            budget=budget,
            reranker=create_candidate_reranker(
                profile,
                api_key=settings.require_dashscope_api_key(),
            ),
        )
        answer = CurrentQwenAnswerAdapter(
            chat_model,
            context,
            input_price_per_million_cny=(
                plan.pricing.qwen_input_price_per_million_tokens_cny
            ),
            output_price_per_million_cny=(
                plan.pricing.qwen_output_price_per_million_tokens_cny
            ),
        )
        ports.append(RealCandidatePorts(profile, retrieval, answer))

    frozen_baseline = BaselineReport.model_validate_json(
        BASELINE_PATH.read_text(encoding="utf-8")
    )
    try:
        report = build_real_comparison(
            evaluation_set=evaluation_set,
            corpus=corpus,
            category_config=categories,
            baseline_profile=profiles[plan.baseline_candidate_id],
            frozen_baseline=frozen_baseline,
            new_candidates=ports,
            budget=budget,
        )
        rendered = (
            json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2)
            + "\n"
        )
        TEMP_OUTPUT.write_text(rendered, encoding="utf-8")
        validated = type(report).model_validate_json(
            TEMP_OUTPUT.read_text(encoding="utf-8")
        )
        if validated != report:
            raise ValueError("暂存对比报告回读校验不一致")
        os.replace(TEMP_OUTPUT, OUTPUT)
    except EvaluationBudgetExceeded as exc:
        raise SystemExit(f"BUDGET_STOP：{exc}") from exc
    finally:
        TEMP_OUTPUT.unlink(missing_ok=True)
    print(f"written={OUTPUT}")


if __name__ == "__main__":
    main()
