"""Preflight by default; execute only after two explicit paid-run confirmations."""

import argparse
import hashlib
import json
import os
from pathlib import Path

from app.core.config import get_settings
from app.evaluation.budget import EvaluationBudget, EvaluationBudgetLimits
from app.evaluation.current_adapters import create_current_vector_search
from app.evaluation.retrieval_ranking_adapters import SharedRetrievalRankingAdapter
from app.evaluation.retrieval_ranking_preflight import run_full_ranking_preflight
from app.evaluation.retrieval_ranking_real import build_real_retrieval_ranking_report
from app.evaluation.retrieval_ranking_real_schemas import RetrievalRankingRunPlan
from app.infrastructure.reranker import DashScopeRerankAdapter
from app.modules.rag.keyword_search import ChromaKeywordSearchAdapter
from app.modules.rag.adapters import CurrentChromaKnowledgeSearchAdapter
from app.modules.rag.policies import HybridSearchPolicy
from scripts.build_corpus_manifest import build_current_manifest
from scripts.run_mock_comparison import load_assets

EVALUATION_ROOT = Path(__file__).resolve().parents[1] / "evaluation"
PLAN_PATH = EVALUATION_ROOT / "plans" / "retrieval_ranking_recovery_preflight_v2.json"
OUTPUT_PATH = EVALUATION_ROOT / "reports" / "retrieval_ranking_real_v1.json"
CONFIRMATION = "RUN_RETRIEVAL_RANKING_RECOVERY_V2"


def plan_sha256() -> str:
    return hashlib.sha256(PLAN_PATH.read_bytes()).hexdigest()


def authorize_execution(*, execute: bool, confirmation: str | None, supplied_sha256: str | None) -> str:
    digest = plan_sha256()
    if not execute:
        return digest
    if confirmation != CONFIRMATION:
        raise ValueError("paid execution confirmation phrase is missing")
    if supplied_sha256 != digest:
        raise ValueError("paid execution plan SHA-256 does not match")
    if OUTPUT_PATH.exists():
        raise FileExistsError("formal real ranking report already exists")
    return digest


def budget_for(plan: RetrievalRankingRunPlan) -> EvaluationBudget:
    limits = plan.hard_limits
    pricing = plan.pricing
    return EvaluationBudget(EvaluationBudgetLimits(
        max_retrieval_calls=limits.max_embedding_calls,
        max_model_calls=1,
        max_total_tokens=limits.max_total_tokens,
        max_estimated_cost_cny=limits.max_estimated_cost_cny,
        embedding_tokens_reserved_per_call=limits.embedding_tokens_reserved_per_call,
        model_input_tokens_reserved_per_call=1,
        model_output_tokens_reserved_per_call=1,
        embedding_price_per_million_tokens_cny=pricing.embedding_price_per_million_tokens_cny,
        model_input_price_per_million_tokens_cny=0.000001,
        model_output_price_per_million_tokens_cny=0.000001,
        max_rerank_calls=limits.max_rerank_calls,
        rerank_tokens_reserved_per_call=limits.rerank_tokens_reserved_per_call,
        rerank_cost_reserved_per_call_cny=(
            limits.rerank_tokens_reserved_per_call
            * pricing.rerank_price_per_million_tokens_cny / 1_000_000
        ),
    ))


def write_report_without_overwrite(report) -> None:
    if OUTPUT_PATH.exists():
        raise FileExistsError("formal real ranking report already exists")
    temporary = OUTPUT_PATH.with_suffix(OUTPUT_PATH.suffix + ".tmp")
    try:
        payload = json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
        temporary.write_text(payload, encoding="utf-8")
        type(report).model_validate_json(temporary.read_text(encoding="utf-8"))
        if OUTPUT_PATH.exists():
            raise FileExistsError("formal real ranking report already exists")
        os.replace(temporary, OUTPUT_PATH)
    finally:
        temporary.unlink(missing_ok=True)


def create_real_adapter(settings, plan: RetrievalRankingRunPlan, budget: EvaluationBudget):
    """Assemble the read-only store behind the stable search port used by evaluation."""
    vector_store = create_current_vector_search(settings)
    return SharedRetrievalRankingAdapter(
        vector_search=CurrentChromaKnowledgeSearchAdapter(vector_store),
        keyword_search=ChromaKeywordSearchAdapter(vector_store),
        reranker=DashScopeRerankAdapter(
            api_key=settings.require_dashscope_api_key(),
            model_name=settings.rag_rerank_model_name,
            timeout_seconds=settings.rag_rerank_timeout_seconds,
            input_price_per_million_tokens_cny=plan.pricing.rerank_price_per_million_tokens_cny,
        ),
        budget=budget,
        hybrid_policy=HybridSearchPolicy(
            enabled=True,
            vector_weight=settings.rag_hybrid_vector_weight,
            keyword_weight=settings.rag_hybrid_keyword_weight,
            rrf_k=settings.rag_hybrid_rrf_k,
        ),
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-paid-run")
    parser.add_argument("--confirm-plan-sha256")
    args = parser.parse_args(argv)
    plan = RetrievalRankingRunPlan.model_validate_json(PLAN_PATH.read_text(encoding="utf-8"))
    digest = authorize_execution(
        execute=args.execute,
        confirmation=args.confirm_paid_run,
        supplied_sha256=args.confirm_plan_sha256,
    )
    evaluation_set, corpus, categories = load_assets()
    settings = get_settings()
    preflight = run_full_ranking_preflight(
        plan=plan, evaluation_set=evaluation_set, corpus=corpus,
        category_config=categories, settings=settings,
        evaluation_root=EVALUATION_ROOT,
        current_manifest_reader=build_current_manifest,
    )
    print(json.dumps(preflight.__dict__, ensure_ascii=False, indent=2))
    print(f"plan_sha256={digest}")
    if not args.execute:
        print("PRECHECK_ONLY: no Embedding, Reranker, or Qwen call was made")
        return

    budget = budget_for(plan)
    adapter = create_real_adapter(settings, plan, budget)
    report = build_real_retrieval_ranking_report(
        evaluation_set=evaluation_set, adapter=adapter,
        budget=budget, plan_sha256=digest,
    )
    write_report_without_overwrite(report)
    print(f"written={OUTPUT_PATH}")


if __name__ == "__main__":
    main()
