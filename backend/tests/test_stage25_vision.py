"""Stage 25.2 structured vision, policy, usage and quota behavior."""

from pathlib import Path

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
from app.modules.vision.service import VisionChatService, build_vision_adapter
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
    finally:
        engine.dispose()


def test_focused_observation_is_bounded_and_duplicate_target_rejected(tmp_path) -> None:
    engine, factory, user_id, asset_id, settings = setup(tmp_path)
    adapter = SequenceVisionAdapter(["overview", "focus one", "focus two"])
    try:
        with factory() as session:
            service = VisionChatService(session, settings, adapter=adapter)
            service.observe_overview(user_id=user_id, asset_id=asset_id, user_question="问题", surface="vision_agent", usage_group_id="run-1")
            service.inspect(user_id=user_id, asset_id=asset_id, user_question="问题", focus_instruction="读取右上角", surface="vision_agent", usage_group_id="run-1")
            with pytest.raises(VisionPolicyError):
                service.inspect(user_id=user_id, asset_id=asset_id, user_question="问题", focus_instruction=" 读取右上角 ", surface="vision_agent", usage_group_id="run-2")
            service.inspect(user_id=user_id, asset_id=asset_id, user_question="问题", focus_instruction="读取下方指标", surface="vision_agent", usage_group_id="run-1")
            with pytest.raises(VisionPolicyError):
                service.inspect(user_id=user_id, asset_id=asset_id, user_question="问题", focus_instruction="再读取左侧", surface="vision_agent", usage_group_id="run-1")
            assert adapter.calls == 3
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
            assert reservation.status == "released"
            assert session.scalar(select(ModelUsageRecord)) is None
    finally:
        engine.dispose()
