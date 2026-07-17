"""上传保护测试：拒绝无副作用、用户隔离和所有结束路径安全释放。"""

import asyncio
from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import UploadFile
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.infrastructure.local_concurrency_limit import (
    BoundedLocalConcurrencyLimitAdapter,
)
from app.infrastructure.local_rate_limit import BoundedLocalRateLimitAdapter
from app.main import app
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.schemas import UserResponse
from app.ports.concurrency_limit import ConcurrencyLimitBackendUnavailable
from app.ports.rate_limit import RateLimitBackendUnavailable
from app.services.concurrency_limit_service import ConcurrencyLimitService
from app.services.admin_document_service import (
    AdminDocumentService,
    get_admin_document_service,
)
from app.services.document_service import DocumentService, get_document_service
from app.services.rate_limit_service import RateLimitService
from app.services.upload_protection_service import (
    ADMIN_UPLOAD_POLICY,
    UploadConcurrencyExceededError,
    UploadProtectionService,
    UploadRateLimitExceededError,
)


class UnavailableRateBackend:
    def consume(self, key, limit, window_seconds):
        raise RateLimitBackendUnavailable()


class UnavailableConcurrencyBackend:
    def acquire(self, key, owner_token, limit, ttl_seconds):
        raise ConcurrencyLimitBackendUnavailable()

    def release(self, key, owner_token):
        raise ConcurrencyLimitBackendUnavailable()


class NeverCalledLifecycle:
    def __init__(self) -> None:
        self.called = False

    async def create_document(self, *args, **kwargs):
        self.called = True
        raise AssertionError("受保护拒绝不应进入文档生命周期")

    async def replace_system_document(self, *args, **kwargs):
        self.called = True
        raise AssertionError("受保护拒绝不应进入文档替换生命周期")


class RecordingLifecycle:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def create_document(self, upload_file, *args, **kwargs):
        self.calls.append("create")
        return self._record("created", upload_file.filename)

    async def replace_system_document(self, _document_id, upload_file):
        self.calls.append("replace")
        return self._record("replaced", upload_file.filename)

    @staticmethod
    def _record(document_id: str, file_name: str):
        return SimpleNamespace(
            id=document_id,
            original_name=file_name,
            size_bytes=7,
            chunk_count=1,
            status="ready",
            is_system=True,
            created_at=datetime.now(timezone.utc),
        )


TEST_USER = UserResponse(
    id="upload-protection-user",
    email="upload-protection@example.com",
    display_name="上传保护测试用户",
    is_active=True,
    role="user",
    created_at=datetime.now(timezone.utc),
    updated_at=datetime.now(timezone.utc),
)

ADMIN_USER = TEST_USER.model_copy(
    update={
        "id": "upload-protection-admin",
        "email": "upload-protection-admin@example.com",
        "role": "admin",
    }
)


def build_protection(
    *,
    rate_limit: int = 5,
    concurrency_limit: int = 1,
    clock=lambda: 100.0,
) -> tuple[UploadProtectionService, ConcurrencyLimitService]:
    settings = Settings(
        _env_file=None,
        upload_rate_limit=rate_limit,
        upload_rate_window_seconds=3600,
        upload_concurrency_limit=concurrency_limit,
        upload_concurrency_ttl_seconds=600,
    )
    rate_limiter = RateLimitService(
        UnavailableRateBackend(),
        BoundedLocalRateLimitAdapter(32, clock=clock),
    )
    concurrency_limiter = ConcurrencyLimitService(
        UnavailableConcurrencyBackend(),
        BoundedLocalConcurrencyLimitAdapter(32, clock=clock),
    )
    return (
        UploadProtectionService(rate_limiter, concurrency_limiter, settings),
        concurrency_limiter,
    )


def test_frequency_rejection_happens_before_lifecycle_and_closes_upload() -> None:
    protection, _ = build_protection(rate_limit=1)
    asyncio.run(protection.execute("user-a", lambda: asyncio.sleep(0)))
    lifecycle = NeverCalledLifecycle()
    service = DocumentService(
        session=object(),
        settings=protection.settings,
        vector_store=object(),
        upload_protection=protection,
    )
    service.lifecycle = lifecycle
    upload = UploadFile(filename="资料.txt", file=BytesIO(b"content"))

    with pytest.raises(UploadRateLimitExceededError) as caught:
        asyncio.run(service.process_upload("user-a", upload))

    assert caught.value.headers == {"Retry-After": "3600"}
    assert lifecycle.called is False
    assert upload.file.closed is True


def test_concurrency_rejection_happens_before_operation() -> None:
    protection, concurrency = build_protection()
    held = concurrency.acquire("upload:concurrency", "user-a", 1, 600)
    called = False

    async def operation():
        nonlocal called
        called = True

    try:
        with pytest.raises(UploadConcurrencyExceededError) as caught:
            asyncio.run(protection.execute("user-a", operation))
        assert caught.value.headers == {"Retry-After": "600"}
        assert called is False
    finally:
        assert held.lease is not None
        concurrency.release(held.lease)


@pytest.mark.parametrize("failure", [None, RuntimeError("failed"), asyncio.CancelledError()])
def test_concurrency_lease_releases_after_success_failure_and_cancellation(
    failure: BaseException | None,
) -> None:
    protection, _ = build_protection(rate_limit=20)

    async def operation():
        if failure is not None:
            raise failure
        return "ok"

    if failure is None:
        assert asyncio.run(protection.execute("user-a", operation)) == "ok"
    else:
        with pytest.raises(type(failure)):
            asyncio.run(protection.execute("user-a", operation))

    assert asyncio.run(protection.execute("user-a", lambda: asyncio.sleep(0))) is None


def test_local_concurrency_release_requires_matching_owner_and_users_are_independent() -> None:
    adapter = BoundedLocalConcurrencyLimitAdapter(8, clock=lambda: 10.0)

    assert adapter.acquire("user-a", "owner-a", 1, 60).acquired is True
    assert adapter.acquire("user-b", "owner-b", 1, 60).acquired is True
    assert adapter.release("user-a", "wrong-owner") is False
    assert adapter.acquire("user-a", "owner-c", 1, 60).acquired is False
    assert adapter.release("user-a", "owner-a") is True
    assert adapter.acquire("user-a", "owner-c", 1, 60).acquired is True


def test_upload_api_returns_stable_429_without_starting_document_lifecycle() -> None:
    protection, _ = build_protection(rate_limit=1)
    asyncio.run(protection.execute(TEST_USER.id, lambda: asyncio.sleep(0)))
    lifecycle = NeverCalledLifecycle()
    service = DocumentService(
        session=object(),
        settings=protection.settings,
        vector_store=object(),
        upload_protection=protection,
    )
    service.lifecycle = lifecycle
    app.dependency_overrides[get_current_user] = lambda: TEST_USER
    app.dependency_overrides[get_document_service] = lambda: service
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/documents",
                files={"file": ("资料.txt", b"content", "text/plain")},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 429
    assert response.headers["retry-after"] == "3600"
    assert response.json()["error"] == {
        "code": "UPLOAD_RATE_LIMITED",
        "message": "上传请求过于频繁，请稍后再试",
    }
    assert response.json()["request_id"]
    assert lifecycle.called is False


def test_admin_create_and_replace_skip_frequency_limit() -> None:
    protection, _ = build_protection(rate_limit=1)
    asyncio.run(protection.execute(ADMIN_USER.id, lambda: asyncio.sleep(0)))
    lifecycle = RecordingLifecycle()
    service = AdminDocumentService(
        session=object(),
        settings=protection.settings,
        vector_store=object(),
        upload_protection=protection,
    )
    service.lifecycle = lifecycle
    app.dependency_overrides[get_current_user] = lambda: ADMIN_USER
    app.dependency_overrides[get_admin_document_service] = lambda: service
    try:
        with TestClient(app) as client:
            responses = [
                client.post(
                    "/api/v1/admin/documents",
                    files={"file": ("系统.txt", b"content", "text/plain")},
                ),
                client.put(
                    "/api/v1/admin/documents/document-id/replace",
                    files={"file": ("系统新版.txt", b"content", "text/plain")},
                ),
            ]
    finally:
        app.dependency_overrides.clear()

    assert [response.status_code for response in responses] == [201, 200]
    assert lifecycle.calls == ["create", "replace"]


def test_admin_uploads_still_enforce_concurrency_limit() -> None:
    protection, concurrency = build_protection(rate_limit=1)
    held = concurrency.acquire("upload:concurrency", ADMIN_USER.id, 1, 600)
    lifecycle = NeverCalledLifecycle()
    service = AdminDocumentService(
        session=object(),
        settings=protection.settings,
        vector_store=object(),
        upload_protection=protection,
    )
    service.lifecycle = lifecycle
    app.dependency_overrides[get_current_user] = lambda: ADMIN_USER
    app.dependency_overrides[get_admin_document_service] = lambda: service
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/admin/documents",
                files={"file": ("系统.txt", b"content", "text/plain")},
            )
    finally:
        app.dependency_overrides.clear()
        assert held.lease is not None
        concurrency.release(held.lease)

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "UPLOAD_CONCURRENCY_LIMITED"
    assert lifecycle.called is False


def test_admin_policy_only_skips_frequency_check() -> None:
    protection, concurrency = build_protection(rate_limit=1)
    asyncio.run(protection.execute("admin-a", lambda: asyncio.sleep(0)))

    assert (
        asyncio.run(
            protection.execute(
                "admin-a",
                lambda: asyncio.sleep(0, result="uploaded"),
                policy=ADMIN_UPLOAD_POLICY,
            )
        )
        == "uploaded"
    )

    held = concurrency.acquire("upload:concurrency", "admin-a", 1, 600)
    try:
        with pytest.raises(UploadConcurrencyExceededError):
            asyncio.run(
                protection.execute(
                    "admin-a",
                    lambda: asyncio.sleep(0),
                    policy=ADMIN_UPLOAD_POLICY,
                )
            )
    finally:
        assert held.lease is not None
        concurrency.release(held.lease)
