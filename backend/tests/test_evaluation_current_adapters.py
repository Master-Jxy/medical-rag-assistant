import inspect
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from langchain_core.documents import Document
from langchain_core.messages import AIMessage

from app.core.config import Settings
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
from app.evaluation.ports import EvaluationQuery
from app.evaluation.preflight import run_preflight
from app.evaluation.runner import run_evaluation
from app.evaluation.schemas import CorpusManifest, EvaluationSet, ExpectedBehavior
from app.evaluation.validation import EvaluationValidationError

BACKEND_DIR = Path(__file__).resolve().parents[1]
EVALUATION_ROOT = BACKEND_DIR / "evaluation"


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


def limits(**overrides) -> EvaluationBudgetLimits:
    values = {
        "max_retrieval_calls": 40,
        "max_model_calls": 40,
        "max_total_tokens": 500_000,
        "max_estimated_cost_cny": 2.0,
        "embedding_tokens_reserved_per_call": 512,
        "model_input_tokens_reserved_per_call": 9_900,
        "model_output_tokens_reserved_per_call": 2_048,
        "embedding_price_per_million_tokens_cny": 0.5,
        "model_input_price_per_million_tokens_cny": 2.5,
        "model_output_price_per_million_tokens_cny": 10.0,
    }
    values.update(overrides)
    return EvaluationBudgetLimits(**values)


def test_retrieval_adapter_uses_frozen_query_top_k_and_only_read_methods() -> None:
    vector_search = Mock()
    vector_search.has_documents.return_value = True
    vector_search.similarity_search.return_value = [
        Document(page_content="片段", metadata={"document_id": "doc-1"})
    ]
    context = RetrievedContextStore()
    adapter = CurrentChromaRetrievalAdapter(vector_search, context)
    query = EvaluationQuery(
        case_id="eval_001",
        question="它有什么作用？",
        history=(("user", "心脏的主要结构是什么？"), ("assistant", "...")),
    )

    result = adapter.retrieve(query)

    vector_search.has_documents.assert_called_once_with()
    vector_search.similarity_search.assert_called_once_with(
        "上一轮问题：心脏的主要结构是什么？\n当前问题：它有什么作用？",
        4,
    )
    assert result.source_document_ids == ("doc-1",)
    assert context.get("eval_001")[0].page_content == "片段"


def test_answer_adapter_uses_frozen_prompt_once_and_extracts_usage() -> None:
    context = RetrievedContextStore()
    context.put(
        "eval_001",
        [Document(page_content="心脏资料", metadata={"document_id": "doc-1", "file_name": "心脏.txt"})],
    )
    model = Mock()
    model.invoke.return_value = AIMessage(
        content="心脏负责泵血。",
        usage_metadata={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
    )
    adapter = CurrentQwenAnswerAdapter(
        model,
        context,
        input_price_per_million_cny=2.5,
        output_price_per_million_cny=10.0,
    )
    query = EvaluationQuery("eval_001", "心脏有什么功能？", ())

    result = adapter.answer(query, ("doc-1",))

    model.invoke.assert_called_once()
    prompt_messages = model.invoke.call_args.args[0].to_messages()
    assert "只依据提供的知识库上下文回答" in str(prompt_messages[0].content)
    assert "心脏资料" in str(prompt_messages[0].content)
    assert result.behavior == ExpectedBehavior.ANSWER
    assert result.usage is not None
    assert result.usage.input_tokens == 100
    assert result.usage.output_tokens == 20
    assert result.usage.estimated_cost_cny == pytest.approx(0.00045)


def test_answer_adapter_does_not_retry_model_failure() -> None:
    context = RetrievedContextStore()
    context.put(
        "eval_001",
        [Document(page_content="资料", metadata={"document_id": "doc-1"})],
    )
    model = Mock()
    model.invoke.side_effect = RuntimeError("provider failed")
    adapter = CurrentQwenAnswerAdapter(
        model,
        context,
        input_price_per_million_cny=2.5,
        output_price_per_million_cny=10.0,
    )

    with pytest.raises(RuntimeError, match="provider failed"):
        adapter.answer(EvaluationQuery("eval_001", "问题", ()), ("doc-1",))
    model.invoke.assert_called_once()


def test_runner_isolates_one_real_answer_adapter_failure() -> None:
    evaluation_set, corpus, categories = load_assets()
    context = RetrievedContextStore()
    vector_search = Mock()
    vector_search.has_documents.return_value = True
    fallback_id = corpus.documents[0].document_id
    vector_search.similarity_search.side_effect = [
        [
            Document(
                page_content="只读测试片段",
                metadata={
                    "document_id": case.expected_source_document_ids[0]
                    if case.expected_source_document_ids
                    else fallback_id
                },
            )
        ]
        for case in evaluation_set.cases
    ]
    model = Mock()
    success = AIMessage(
        content="知识库资料不足，无法根据现有资料回答。",
        usage_metadata={"input_tokens": 10, "output_tokens": 10, "total_tokens": 20},
    )
    model.invoke.side_effect = [RuntimeError("one failure")] + [success] * 39
    retrieval = CurrentChromaRetrievalAdapter(vector_search, context)
    answer = CurrentQwenAnswerAdapter(
        model,
        context,
        input_price_per_million_cny=2.5,
        output_price_per_million_cny=10.0,
    )

    report = run_evaluation(
        evaluation_set=evaluation_set,
        corpus=corpus,
        category_config=categories,
        retrieval_port=retrieval,
        answer_port=answer,
        report_version="test_run_v1",
        run_kind="current_baseline",
    )

    assert report.metrics.failed_case_count == 1
    assert report.metrics.completed_case_count == 39
    assert report.cases[0].error_stage == "answer"
    assert model.invoke.call_count == 40


def test_evaluation_factories_force_zero_retries(monkeypatch, tmp_path: Path) -> None:
    embedding_factory = Mock(return_value=Mock())
    chroma_factory = Mock(return_value=Mock())
    chat_factory = Mock(return_value=Mock())
    monkeypatch.setattr(
        "app.evaluation.current_adapters.DashScopeEmbeddings", embedding_factory
    )
    monkeypatch.setattr("app.evaluation.current_adapters.Chroma", chroma_factory)
    monkeypatch.setattr("app.evaluation.current_adapters.ChatTongyi", chat_factory)
    settings = Settings(
        dashscope_api_key="test-key",
        chroma_persist_dir=tmp_path,
        chroma_collection_name="agent",
    )

    create_current_vector_search(settings)
    create_current_chat_model(settings, max_output_tokens=2048)

    assert embedding_factory.call_args.kwargs["max_retries"] == 0
    assert chat_factory.call_args.kwargs["max_retries"] == 0
    assert chat_factory.call_args.kwargs["model"] == "qwen3-max"
    assert chat_factory.call_args.kwargs["model_kwargs"] == {"max_tokens": 2048}
    assert chroma_factory.call_args.kwargs["collection_name"] == "agent"
    assert chroma_factory.call_args.kwargs["create_collection_if_not_exists"] is False


def test_preflight_checks_checksum_before_chroma_and_accepts_local_config() -> None:
    evaluation_set, corpus, categories = load_assets()
    settings = Settings(dashscope_api_key="test-key")
    reader = Mock(return_value=103)

    report = run_preflight(
        evaluation_set=evaluation_set,
        corpus=corpus,
        category_config=categories,
        settings=settings,
        budget_limits=limits(),
        collection_count_reader=reader,
    )

    assert report.case_count == 40
    assert report.chroma_chunk_count == 103
    assert report.top_k == 4
    assert report.max_retries == 0
    assert report.remote_connectivity_checked is False
    assert report.corpus_snapshot_checked is False
    reader.assert_called_once_with(settings)

    invalid = evaluation_set.model_copy(deep=True)
    invalid.corpus_checksum = "0" * 64
    reader.reset_mock()
    with pytest.raises(EvaluationValidationError):
        run_preflight(
            evaluation_set=invalid,
            corpus=corpus,
            category_config=categories,
            settings=settings,
            budget_limits=limits(),
            collection_count_reader=reader,
        )
    reader.assert_not_called()


def test_budget_stops_runner_immediately_before_second_retrieval() -> None:
    from app.evaluation.fake_adapters import FixedFakeAnswerAdapter, FixedFakeRetrievalAdapter

    evaluation_set, corpus, categories = load_assets()
    retrieval = FixedFakeRetrievalAdapter(evaluation_set)
    answer = FixedFakeAnswerAdapter(evaluation_set)
    budget = EvaluationBudget(limits(max_retrieval_calls=1))
    retrieval.retrieve = Mock(wraps=retrieval.retrieve)
    answer.answer = Mock(wraps=answer.answer)

    with pytest.raises(EvaluationBudgetExceeded, match="retrieval_call_limit"):
        run_evaluation(
            evaluation_set=evaluation_set,
            corpus=corpus,
            category_config=categories,
            retrieval_port=retrieval,
            answer_port=answer,
            report_version="test_run_v1",
            run_kind="current_baseline",
            run_guard=budget,
        )

    assert retrieval.retrieve.call_count == 1
    assert answer.answer.call_count == 1


@pytest.mark.parametrize(
    ("budget", "operation", "reason"),
    [
        (EvaluationBudget(limits(max_total_tokens=500)), "retrieval", "total_token_limit"),
        (
            EvaluationBudget(limits(max_estimated_cost_cny=0.0001)),
            "retrieval",
            "estimated_cost_limit",
        ),
        (EvaluationBudget(limits(max_model_calls=1)), "model", "model_call_limit"),
    ],
)
def test_each_hard_budget_condition_stops_before_an_external_call(
    budget: EvaluationBudget, operation: str, reason: str
) -> None:
    if operation == "model":
        budget.before_answer()
        with pytest.raises(EvaluationBudgetExceeded, match=reason):
            budget.before_answer()
    else:
        with pytest.raises(EvaluationBudgetExceeded, match=reason):
            budget.before_retrieval()


def test_real_adapters_have_no_business_data_dependency() -> None:
    import app.evaluation.current_adapters as module

    source = inspect.getsource(module)
    forbidden = ("app.db", "ConversationService", "MessageRepository", "database_url")
    assert all(value not in source for value in forbidden)
