from langchain_core.messages import AIMessage, AIMessageChunk
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.base import Base
from app.db.session import build_engine
from app.infrastructure.agent_model import LangChainAgentModel
from app.models import ModelUsageRecord, User
from app.modules.agent.application import AgentApplicationService
from app.modules.agent.cancellation import AgentCancellationService
from app.modules.agent.graph import BoundedAgentGraph
from app.modules.agent.planner import PlanDecision
from app.modules.agent.policy import AgentPolicy
from app.modules.agent.registry import ToolRegistry
from app.modules.agent.usage import AgentModelUsageCollector
from app.modules.rag.ports import ModelUsage, TokenMeasurement


class FixedChatModel:
    def __init__(self, response: AIMessage) -> None:
        self.response = response

    def bind(self, **kwargs):
        return self

    def invoke(self, messages):
        return self.response

    def stream(self, messages):
        yield AIMessageChunk(content="部分回答")
        yield AIMessageChunk(content="不会读取到这里")


def test_agent_model_uses_vendor_usage_and_missing_usage_is_unknown(
    monkeypatch,
) -> None:
    actual_collector = AgentModelUsageCollector()
    actual_model = FixedChatModel(
        AIMessage(
            content="实际回答",
            usage_metadata={
                "input_tokens": 40,
                "output_tokens": 6,
                "total_tokens": 46,
            },
        )
    )
    monkeypatch.setattr(
        "app.infrastructure.agent_model.create_chat_model",
        lambda settings: actual_model,
    )
    adapter = LangChainAgentModel(
        Settings(_env_file=None),
        actual_collector.add,
    )

    generated = adapter.invoke_text("固定提示")
    actual = actual_collector.drain()

    assert generated.used_tokens == 46
    assert len(actual) == 1
    assert actual[0].operation == "tool_summary"
    assert actual[0].usage == ModelUsage.actual(40, 6)

    unknown_collector = AgentModelUsageCollector()
    missing_model = FixedChatModel(AIMessage(content="很长的回答" * 100))
    monkeypatch.setattr(
        "app.infrastructure.agent_model.create_chat_model",
        lambda settings: missing_model,
    )
    missing_adapter = LangChainAgentModel(
        Settings(_env_file=None),
        unknown_collector.add,
    )

    missing = missing_adapter.invoke_text("固定提示")
    observations = unknown_collector.drain()

    assert missing.used_tokens == 0
    assert missing.estimated_cost_cny == 0
    assert observations[0].usage.measurement is TokenMeasurement.UNKNOWN
    assert observations[0].usage.input_tokens is None
    assert observations[0].usage.output_tokens is None

    cancelled_collector = AgentModelUsageCollector()
    cancelled_adapter = LangChainAgentModel(
        Settings(_env_file=None),
        cancelled_collector.add,
    )
    stream = cancelled_adapter.stream_text("固定提示")
    assert next(stream).content == "部分回答"
    stream.close()
    cancelled = cancelled_collector.drain()
    assert len(cancelled) == 1
    assert cancelled[0].operation == "final_answer"
    assert cancelled[0].usage.measurement is TokenMeasurement.UNKNOWN


def test_agent_json_failure_still_reports_vendor_usage(monkeypatch) -> None:
    collector = AgentModelUsageCollector()
    invalid_model = FixedChatModel(
        AIMessage(
            content="不是JSON",
            usage_metadata={
                "input_tokens": 11,
                "output_tokens": 2,
                "total_tokens": 13,
            },
        )
    )
    monkeypatch.setattr(
        "app.infrastructure.agent_model.create_chat_model",
        lambda settings: invalid_model,
    )
    adapter = LangChainAgentModel(Settings(_env_file=None), collector.add)

    try:
        adapter.invoke_json("固定提示", PlanDecision)
    except ValueError as exc:
        assert str(exc) == "模型没有返回合法JSON"
    else:
        raise AssertionError("非法JSON必须失败")

    observations = collector.drain()
    assert len(observations) == 1
    assert observations[0].operation == "plan"
    assert observations[0].usage == ModelUsage.actual(11, 2)


class DirectPlanner:
    def classify_and_plan(self, state):
        return PlanDecision(
            route="direct_reply",
            plan=[],
            response_message="确定性回答",
        )


def test_agent_usage_collector_writes_each_operation_and_marks_unknown_run(
    tmp_path,
) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'agent-usage.db'}")
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    user = User(
        id="agent-usage-user",
        email="agent-usage@example.com",
        password_hash="hash",
    )
    session.add(user)
    session.commit()
    collector = AgentModelUsageCollector()
    collector.add("plan", ModelUsage.actual(20, 4))
    collector.add("tool_summary", ModelUsage.unknown())
    collector.add("final_answer", ModelUsage.actual(10, 3))
    service = AgentApplicationService(
        session,
        policy=AgentPolicy(enabled=True),
        graph_factory=lambda *_: BoundedAgentGraph(
            planner=DirectPlanner(),
            registry=ToolRegistry([]),
            usage_collector=collector,
        ),
        cancellation=AgentCancellationService(),
        model_name="fake-agent",
        input_price_per_million_tokens_cny=2.5,
        output_price_per_million_tokens_cny=10,
    )
    run = service.create_run(user.id, "你好")

    list(service.stream_run(user.id, run.id))

    stored_run = service.repository.get_run(user.id, run.id)
    records = (
        session.query(ModelUsageRecord)
        .filter(ModelUsageRecord.surface == "agent")
        .order_by(ModelUsageRecord.call_id)
        .all()
    )
    assert stored_run.token_measurement == "unknown"
    assert len(records) == 3
    assert {record.operation for record in records} == {
        "plan",
        "tool_summary",
        "final_answer",
    }
    assert sum(
        record.input_tokens or 0 for record in records
    ) == 30
    assert any(record.token_measurement == "unknown" for record in records)
    session.close()
    engine.dispose()


def test_deterministic_agent_reply_records_zero_model_call(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'agent-zero.db'}")
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    user = User(
        id="agent-zero-user",
        email="agent-zero@example.com",
        password_hash="hash",
    )
    session.add(user)
    session.commit()
    service = AgentApplicationService(
        session,
        policy=AgentPolicy(enabled=True),
        graph_factory=lambda *_: BoundedAgentGraph(
            planner=DirectPlanner(),
            registry=ToolRegistry([]),
        ),
        cancellation=AgentCancellationService(),
        model_name="fake-agent",
    )
    run = service.create_run(user.id, "你好")

    list(service.stream_run(user.id, run.id))

    stored_run = service.repository.get_run(user.id, run.id)
    record = session.query(ModelUsageRecord).one()
    assert stored_run.token_measurement == "not_applicable"
    assert stored_run.used_tokens == 0
    assert stored_run.estimated_cost_cny == 0
    assert record.token_measurement == "not_applicable"
    assert record.input_tokens == record.output_tokens == 0
    assert record.estimated_cost_cny == 0
    session.close()
    engine.dispose()


def test_agent_answer_completes_when_usage_ledger_write_fails(tmp_path) -> None:
    class FailingUsageRecorder:
        def record(self, **kwargs):
            raise RuntimeError("fake-ledger-failure")

    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'agent-ledger-fail.db'}")
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    user = User(
        id="agent-ledger-fail-user",
        email="agent-ledger-fail@example.com",
        password_hash="hash",
    )
    session.add(user)
    session.commit()
    service = AgentApplicationService(
        session,
        policy=AgentPolicy(enabled=True),
        graph_factory=lambda *_: BoundedAgentGraph(
            planner=DirectPlanner(),
            registry=ToolRegistry([]),
        ),
        cancellation=AgentCancellationService(),
        model_name="fake-agent",
        usage_recorder=FailingUsageRecorder(),
    )
    run = service.create_run(user.id, "你好")

    events = list(service.stream_run(user.id, run.id))
    stored_run = service.repository.get_run(user.id, run.id)

    assert any(event["event"] == "run_completed" for event in events)
    assert stored_run.status == "completed"
    assert stored_run.token_measurement == "unknown"
    session.close()
    engine.dispose()
