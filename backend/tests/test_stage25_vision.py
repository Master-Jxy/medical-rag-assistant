"""Stage 25.2 structured vision, policy, usage and quota behavior."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, Lock
from time import sleep
from types import SimpleNamespace

import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.core.exceptions import VisionPolicyError, VisionUnavailableError
from app.db.base import Base
from app.db.session import build_engine
from app import models as _models  # noqa: F401 - register all metadata dependencies
from app.modules.media.models import MediaAsset
from app.modules.media.storage import PrivateMediaStorage
from app.modules.usage.models import ModelUsageRecord, QuotaPeriod, QuotaReservation
from app.modules.usage.contracts import ModelUsage
from app.modules.vision.contracts import VisionObservation, VisionResult
from app.modules.vision.models import VisionObservationRecord
from app.modules.vision.quality import VisionQualityGate
from app.modules.vision.service import VisionChatService, build_vision_adapter
from app.infrastructure.dashscope_vision import DashScopeVisionChatAdapter
from tests.auth_helpers import create_test_user


class SequenceVisionAdapter:
    def __init__(self, summaries: list[str], *, fail: bool = False) -> None:
        self.summaries = summaries
        self.fail = fail
        self.calls = 0

    def observe(self, **kwargs) -> VisionResult:
        del kwargs
        self.calls += 1
        if self.fail:
            raise VisionUnavailableError("fake unavailable")
        return VisionResult(
            observation=VisionObservation(image_type="medical_report", summary=self.summaries[self.calls - 1], visible_text=[f"value-{self.calls}"]),
            usage=ModelUsage.actual(100, 20), model_name="fake-vision",
        )


class BlockingVisionAdapter:
    def __init__(self) -> None:
        self.calls = 0
        self.started = Event()
        self.release = Event()
        self.lock = Lock()

    def observe(self, **kwargs) -> VisionResult:
        del kwargs
        with self.lock:
            self.calls += 1
        self.started.set()
        assert self.release.wait(timeout=5)
        return VisionResult(
            observation=VisionObservation(
                image_type="document",
                summary="并发请求共享同一结构化观察",
                visible_text=["固定无隐私文本"],
            ),
            usage=ModelUsage.actual(30, 10),
            model_name="blocking-fake",
        )


def setup(tmp_path, *, quota_mode="shadow"):
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'vision.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    user = create_test_user(factory, "vision-user")
    settings = Settings(
        _env_file=None, media_asset_dir=tmp_path / "media",
        vision_chat_enabled=True, vision_provider="fake", quota_policy_mode=quota_mode,
    )
    source = tmp_path / "source.png"
    Image.new("RGB", (20, 12), "white").save(source)
    stored = PrivateMediaStorage(settings).store(original_name="source.png", claimed_mime="image/png", data=source.read_bytes())
    with factory() as session:
        asset = MediaAsset(
            user_id=user.id, original_name="source.png", mime_type=stored.mime_type,
            byte_size=stored.byte_size, width=stored.width, height=stored.height,
            sha256=stored.sha256, storage_key=stored.storage_key,
            expires_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc) + __import__("datetime").timedelta(days=30),
        )
        session.add(asset); session.commit(); asset_id = asset.id
    return engine, factory, user.id, asset_id, settings


def test_default_factory_is_disabled_and_never_calls_provider() -> None:
    settings = Settings(_env_file=None)
    assert settings.vision_model == "qwen3-vl-plus"
    with pytest.raises(VisionUnavailableError):
        build_vision_adapter(settings).observe()


def test_compose_exposes_bounded_vision_settings() -> None:
    compose_text = (Path(__file__).resolve().parents[2] / "compose.yaml").read_text(encoding="utf-8")
    for expected in (
        "MEDIA_ASSET_DIR: /app/data/media",
        "VISION_CHAT_ENABLED: ${VISION_CHAT_ENABLED:-false}",
        "VISION_PROVIDER: ${VISION_PROVIDER:-dashscope}",
        "VISION_MODEL: ${VISION_MODEL:-qwen3-vl-plus}",
        "VISION_MAX_CALLS_PER_IMAGE: ${VISION_MAX_CALLS_PER_IMAGE:-3}",
        "VISION_AUTOMATIC_RETRIES: ${VISION_AUTOMATIC_RETRIES:-0}",
    ):
        assert expected in compose_text


def test_empty_optional_vision_prices_are_normalized() -> None:
    settings = Settings(
        _env_file=None,
        vision_input_price_per_million_tokens_cny="",
        vision_output_price_per_million_tokens_cny="  ",
    )
    assert settings.vision_input_price_per_million_tokens_cny is None
    assert settings.vision_output_price_per_million_tokens_cny is None


def test_dashscope_adapter_normalizes_provider_shape_drift(monkeypatch) -> None:
    content = """```json
{"image_type":"document","summary":"visible facts","visible_text":"标题","measurements":[{"name":"值","value":12.5}],"objects":[{"name":"rectangle","type":"shape"}],"spatial_notes":[],"uncertain_content":[],"safety_flags":[]}
```"""
    response = SimpleNamespace(
        status_code=200,
        output={"choices": [{"message": {"content": [{"text": content}]}}]},
        usage={"input_tokens": 120, "output_tokens": 30},
        request_id="vision-request",
    )
    monkeypatch.setattr(
        "app.infrastructure.dashscope_vision.MultiModalConversation.call",
        lambda **kwargs: response,
    )
    result = DashScopeVisionChatAdapter(
        Settings(_env_file=None, dashscope_api_key="test-key", vision_model="qwen3-vl-plus")
    ).observe(
        image_bytes=b"image",
        mime_type="image/png",
        user_question="describe",
        focus_instruction=None,
    )
    assert result.observation.visible_text == ["标题"]
    assert '"name": "rectangle"' in result.observation.objects[0]
    assert result.observation.measurements[0].value == "12.5"
    assert result.usage.total_tokens == 150


def test_overview_is_idempotent_and_settles_usage(tmp_path) -> None:
    engine, factory, user_id, asset_id, settings = setup(tmp_path)
    adapter = SequenceVisionAdapter(["overview"])
    try:
        with factory() as session:
            service = VisionChatService(session, settings, adapter=adapter)
            first = service.observe_overview(user_id=user_id, asset_id=asset_id, user_question="请读取报告", surface="vision_rag", usage_group_id="answer-1")
            second = service.observe_overview(user_id=user_id, asset_id=asset_id, user_question="重复网络请求", surface="vision_rag", usage_group_id="answer-1")
            assert first == second and adapter.calls == 1
            assert len(list(session.scalars(select(VisionObservationRecord)))) == 1
            usage = session.scalar(select(ModelUsageRecord))
            reservation = session.scalar(select(QuotaReservation))
            period = session.scalar(select(QuotaPeriod))
            assert usage.surface == "vision_rag" and usage.total_tokens == 120
            assert reservation.status == "settled" and reservation.charged_tokens == 120
            assert period.used_tokens == 120 and period.reserved_tokens == 0
            assert first.quality_summary is not None
            assert first.quality_summary.route_kind == "report"
            record = session.scalar(select(VisionObservationRecord))
            assert record.observation_scope_id == "answer-1"
            assert record.assistant_message_id == "answer-1"
            assert record.run_id is None
            assert record.provider_call_count == 1
            assert record.route_kind == "report"
            assert record.quality_status == "pass"
            assert record.quality_codes == []
    finally:
        engine.dispose()


def test_focused_observation_is_bounded_and_duplicate_target_rejected(tmp_path) -> None:
    engine, factory, user_id, asset_id, settings = setup(tmp_path)
    adapter = SequenceVisionAdapter(["overview", "focus one", "focus two"])
    try:
        with factory() as session:
            service = VisionChatService(session, settings, adapter=adapter)
            service.observe_overview(user_id=user_id, asset_id=asset_id, user_question="问题", surface="vision_agent", usage_group_id="answer-1", run_id="run-1")
            service.inspect(user_id=user_id, asset_id=asset_id, user_question="问题", focus_instruction="读取右上角", surface="vision_agent", usage_group_id="answer-1", run_id="run-1")
            with pytest.raises(VisionPolicyError):
                service.inspect(user_id=user_id, asset_id=asset_id, user_question="问题", focus_instruction=" 读取右上角 ", surface="vision_agent", usage_group_id="answer-2", run_id="run-2")
            service.inspect(user_id=user_id, asset_id=asset_id, user_question="问题", focus_instruction="读取下方指标", surface="vision_agent", usage_group_id="answer-1", run_id="run-1")
            with pytest.raises(VisionPolicyError):
                service.inspect(user_id=user_id, asset_id=asset_id, user_question="问题", focus_instruction="再读取左侧", surface="vision_agent", usage_group_id="answer-1", run_id="run-1")
            assert adapter.calls == 3
            records = list(session.scalars(select(VisionObservationRecord)))
            assert sum(item.provider_call_count for item in records) == 3
            assert {
                item.observation_scope_id for item in records if item.provider_call_count
            } == {"run-1"}
    finally:
        engine.dispose()


def test_provider_failure_releases_quota_and_records_no_body(tmp_path) -> None:
    engine, factory, user_id, asset_id, settings = setup(tmp_path)
    adapter = SequenceVisionAdapter(["unused"], fail=True)
    try:
        with factory() as session:
            service = VisionChatService(session, settings, adapter=adapter)
            with pytest.raises(VisionUnavailableError):
                service.observe_overview(user_id=user_id, asset_id=asset_id, user_question="敏感问题正文", surface="vision_rag", usage_group_id="answer-fail")
            observation = session.scalar(select(VisionObservationRecord))
            reservation = session.scalar(select(QuotaReservation))
            assert observation.status == "failed" and observation.observation_json is None
            assert observation.provider_call_count == 1
            assert observation.quality_status == "failed"
            assert reservation.status == "released"
            assert session.scalar(select(ModelUsageRecord)) is None
            with pytest.raises(VisionUnavailableError):
                service.observe_overview(user_id=user_id, asset_id=asset_id, user_question="再次包含敏感正文", surface="vision_rag", usage_group_id="answer-fail")
            assert adapter.calls == 1
            assert "敏感问题正文" not in repr(observation.__dict__)
    finally:
        engine.dispose()


def test_quality_gate_returns_public_deterministic_summary() -> None:
    gate = VisionQualityGate()
    complete = gate.apply(
        VisionObservation(
            image_type="medical_report",
            summary="一份结构清晰的无隐私检查报告",
            visible_text=["指标 A 12.3"],
            measurements=[
                {"name": "指标 A", "value": "12.3", "unit": "x", "flag": "high"}
            ],
        )
    )
    assert complete.quality_summary.model_dump() == {
        "route_kind": "report",
        "quality_status": "pass",
        "quality_codes": [],
    }

    retry = gate.apply(
        VisionObservation(
            image_type="document",
            summary="截图中的文字区域无法可靠读取",
            uncertain_content=["图片模糊且右侧被裁切"],
        )
    )
    assert retry.quality_summary.quality_status == "retry"
    assert retry.quality_summary.quality_codes == [
        "IMAGE_BLURRY",
        "IMAGE_CROPPED",
        "UNCERTAIN_CONTENT",
        "LOW_STRUCTURED_COVERAGE",
    ]


def test_concurrent_duplicate_scope_calls_provider_and_quota_once(tmp_path) -> None:
    engine, factory, user_id, asset_id, settings = setup(tmp_path)
    adapter = BlockingVisionAdapter()

    def observe_once():
        with factory() as session:
            return VisionChatService(session, settings, adapter=adapter).observe_overview(
                user_id=user_id,
                asset_id=asset_id,
                user_question="固定并发测试问题",
                surface="vision_rag",
                usage_group_id="concurrent-answer",
            )

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first_future = pool.submit(observe_once)
            assert adapter.started.wait(timeout=5)
            second_future = pool.submit(observe_once)
            sleep(0.1)
            assert adapter.calls == 1
            adapter.release.set()
            first = first_future.result(timeout=5)
            second = second_future.result(timeout=5)
        assert first == second
        with factory() as session:
            assert len(list(session.scalars(select(VisionObservationRecord)))) == 1
            assert len(list(session.scalars(select(ModelUsageRecord)))) == 1
            assert len(list(session.scalars(select(QuotaReservation)))) == 1
            period = session.scalar(select(QuotaPeriod))
            assert period.used_tokens == 40
            assert period.reserved_tokens == 0
    finally:
        adapter.release.set()
        engine.dispose()
