import pytest

from app.core.exceptions import RagServiceError
from app.modules.rag.ports import RetrievedChunk
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
        yield "回答"

    async def astream_answer(self, question, history, chunks):
        yield "回答"


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
