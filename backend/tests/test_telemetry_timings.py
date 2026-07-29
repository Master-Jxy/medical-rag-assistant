import pytest
import asyncio

from app.core.exceptions import RagServiceError
from app.modules.rag.ports import GeneratedAnswerChunk, ModelUsage, RetrievedChunk
from app.services.rag_service import RagService


class RecordingTelemetry:
    def __init__(self, *, fail: bool = False) -> None:
        self.events = []
        self.fail = fail

    def emit(self, event) -> None:
        if self.fail:
            raise RuntimeError("telemetry unavailable")
        self.events.append(event)


class Query:
    def build(self, question, history):
        return "query"


class Search:
    def search(self, query, top_k, options=None):
        return [RetrievedChunk("内容", "资料.txt", 1)]


class FailingSearch:
    def search(self, query, top_k, options=None):
        raise TimeoutError("chroma timeout")


class Answer:
    def answer(self, question, history, chunks):
        return "回答"

    def stream_answer(self, question, history, chunks):
        yield GeneratedAnswerChunk("回答", ModelUsage.actual(8, 2))

    async def astream_answer(self, question, history, chunks):
        yield GeneratedAnswerChunk("回答", ModelUsage.actual(8, 2))


def test_rag_records_each_stage_with_non_negative_monotonic_duration() -> None:
    telemetry = RecordingTelemetry()
    service = RagService(Query(), Search(), Answer(), telemetry=telemetry)

    answer, _ = service.ask("问题", 4)

    assert answer == "回答"
    assert [event.stage for event in telemetry.events] == [
        "query_construction",
        "knowledge_retrieval",
        "rerank",
        "model_generation",
    ]
    assert all(event.duration_ms is not None and event.duration_ms >= 0 for event in telemetry.events)
    assert telemetry.events[-1].token_measurement == "unknown"


def test_failed_retrieval_records_error_and_telemetry_failure_is_non_blocking() -> None:
    telemetry = RecordingTelemetry()
    service = RagService(Query(), FailingSearch(), Answer(), telemetry=telemetry)

    with pytest.raises(RagServiceError):
        service.ask("问题", 4)

    assert telemetry.events[-1].stage == "knowledge_retrieval"
    assert telemetry.events[-1].result == "failure"
    assert telemetry.events[-1].error_type == "TimeoutError"

    safe_service = RagService(
        Query(),
        Search(),
        Answer(),
        telemetry=RecordingTelemetry(fail=True),
    )
    assert safe_service.ask("问题", 4)[0] == "回答"


def test_stream_records_actual_usage_and_zero_model_refusal() -> None:
    telemetry = RecordingTelemetry()
    service = RagService(Query(), Search(), Answer(), telemetry=telemetry)

    events = list(service.stream_ask("问题", 4))

    assert events[-2]["event"] == "model_usage"
    assert events[-2]["data"]["measurement"] == "actual"
    generation = telemetry.events[-1]
    assert generation.input_tokens == 8
    assert generation.output_tokens == 2
    assert generation.token_measurement == "actual"

    zero_telemetry = RecordingTelemetry()
    zero_service = RagService(
        Query(),
        type("EmptySearch", (), {"search": lambda self, *args, **kwargs: []})(),
        Answer(),
        telemetry=zero_telemetry,
    )

    zero_events = list(zero_service.stream_ask("问题", 4))

    assert zero_events[0]["data"] == {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "measurement": "not_applicable",
    }
    assert zero_telemetry.events[-1].result == "skipped"
    assert zero_telemetry.events[-1].token_measurement == "not_applicable"


def test_cancelled_async_stream_records_unknown_usage_without_fake_tokens() -> None:
    class SlowAnswer(Answer):
        async def astream_answer(self, question, history, chunks):
            yield GeneratedAnswerChunk("部分回答")
            await asyncio.sleep(60)

    telemetry = RecordingTelemetry()
    service = RagService(Query(), Search(), SlowAnswer(), telemetry=telemetry)

    async def consume_then_cancel() -> None:
        iterator = service.astream_ask("问题", 4)
        first = await anext(iterator)
        assert first["data"]["content"] == "部分回答"
        await iterator.aclose()

    asyncio.run(consume_then_cancel())

    generation = telemetry.events[-1]
    assert generation.result == "stopped"
    assert generation.input_tokens is None
    assert generation.output_tokens is None
    assert generation.token_measurement == "unknown"
