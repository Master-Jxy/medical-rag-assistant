"""会话普通/SSE 问答的请求幂等测试。"""

from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.core.exceptions import RagServiceError
from app.db.base import Base
from app.db.session import build_engine, get_db_session
from app.main import app
from app.modules.auth.tokens import get_token_service
from app.ports.idempotency import (
    IdempotencyBackendUnavailable,
    IdempotencyRecord,
    IdempotencyStatus,
)
from app.schemas.chat import SourceItem
from app.services.generation_lock_service import get_generation_lock_service
from app.services.idempotency_service import (
    IdempotencyService,
    get_idempotency_service,
)
from app.services.rag_service import get_rag_service
from tests.auth_helpers import TEST_TOKEN_SERVICE, auth_headers, create_test_user


class MemoryIdempotencyBackend:
    def __init__(self) -> None:
        self.records = {}

    def begin_idempotency(self, key, fingerprint, ttl_seconds):
        record = self.records.get(key)
        if record is None:
            self.records[key] = {
                "state": "in_progress",
                "fingerprint": fingerprint,
                "ttl": ttl_seconds,
            }
            return IdempotencyRecord(IdempotencyStatus.STARTED)
        if record["fingerprint"] != fingerprint:
            return IdempotencyRecord(IdempotencyStatus.CONFLICT)
        if record["state"] == "in_progress":
            return IdempotencyRecord(IdempotencyStatus.IN_PROGRESS)
        return IdempotencyRecord(
            IdempotencyStatus.COMPLETED,
            request_id=record["request_id"],
            conversation_id=record["conversation_id"],
            user_message_id=record["user_message_id"],
            assistant_message_id=record["assistant_message_id"],
        )

    def complete_idempotency(self, key, fingerprint, **values):
        record = self.records.get(key)
        if (
            record is None
            or record["fingerprint"] != fingerprint
            or record["state"] != "in_progress"
        ):
            return False
        record.update(values)
        record["ttl"] = values["ttl_seconds"]
        record["state"] = "completed"
        return True

    def clear_idempotency(self, key, fingerprint):
        record = self.records.get(key)
        if record is None or record["fingerprint"] != fingerprint:
            return False
        del self.records[key]
        return True


class AllowingGenerationLock:
    def acquire(self, user_id, conversation_id):
        return object()

    def release(self, lease):
        pass


class CountingRagService:
    def __init__(self) -> None:
        self.ask_calls = 0
        self.stream_calls = 0

    def ask(self, question, top_k, history=None):
        self.ask_calls += 1
        return (
            f"普通回答：{question}",
            [SourceItem(file_name="幂等资料.txt", page=None, content="普通引用")],
        )

    def stream_ask(self, question, top_k, history=None):
        self.stream_calls += 1
        yield {"event": "token", "data": {"content": "流式"}}
        yield {"event": "token", "data": {"content": "回答"}}
        yield {
            "event": "sources",
            "data": {
                "sources": [
                    {
                        "file_name": "幂等资料.txt",
                        "page": None,
                        "content": "流式引用",
                    }
                ]
            },
        }


class FailingOnceRagService(CountingRagService):
    def ask(self, question, top_k, history=None):
        self.ask_calls += 1
        if self.ask_calls == 1:
            raise RagServiceError("首次失败")
        return f"重试成功：{question}", []


def build_dependencies(tmp_path):
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'idempotency.db'}")

    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, _):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_session():
        with factory() as session:
            yield session

    user = create_test_user(factory, "idempotency-user")
    backend = MemoryIdempotencyBackend()
    service = IdempotencyService(backend, Settings(_env_file=None))
    rag = CountingRagService()
    return engine, override_session, user, backend, service, rag


def install_overrides(override_session, service, rag):
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_token_service] = lambda: TEST_TOKEN_SERVICE
    app.dependency_overrides[get_generation_lock_service] = AllowingGenerationLock
    app.dependency_overrides[get_idempotency_service] = lambda: service
    app.dependency_overrides[get_rag_service] = lambda: rag


def test_repeated_normal_request_reuses_mysql_result_without_second_model_call(
    tmp_path,
) -> None:
    engine, override_session, user, backend, service, rag = build_dependencies(tmp_path)
    install_overrides(override_session, service, rag)
    headers = {**auth_headers(user.id), "Idempotency-Key": "same-normal-request"}
    try:
        with TestClient(app) as client:
            conversation_id = client.post(
                "/api/v1/conversations",
                json={"title": "新对话"},
                headers=auth_headers(user.id),
            ).json()["id"]
            url = f"/api/v1/conversations/{conversation_id}/chat"
            payload = {"question": "重复普通问题", "top_k": 2}

            first = client.post(url, json=payload, headers=headers)
            second = client.post(url, json=payload, headers=headers)

            assert first.status_code == second.status_code == 200
            assert second.json() == first.json()
            assert rag.ask_calls == 1
            stored_key = next(iter(backend.records))
            assert stored_key.startswith("idempotency:conversation-chat:")
            assert user.id not in stored_key
            assert "same-normal-request" not in stored_key
            assert backend.records[stored_key]["ttl"] == 86400
            detail = client.get(
                f"/api/v1/conversations/{conversation_id}",
                headers=auth_headers(user.id),
            ).json()
            assert detail["message_count"] == 2
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_reusing_key_with_changed_payload_returns_conflict_without_model_call(
    tmp_path,
) -> None:
    engine, override_session, user, _, service, rag = build_dependencies(tmp_path)
    install_overrides(override_session, service, rag)
    headers = {**auth_headers(user.id), "Idempotency-Key": "reused-key"}
    try:
        with TestClient(app) as client:
            conversation_id = client.post(
                "/api/v1/conversations",
                json={"title": "新对话"},
                headers=auth_headers(user.id),
            ).json()["id"]
            url = f"/api/v1/conversations/{conversation_id}/chat"
            first = client.post(
                url,
                json={"question": "第一个问题", "top_k": 2},
                headers=headers,
            )
            conflict = client.post(
                url,
                json={"question": "被替换的问题", "top_k": 2},
                headers=headers,
            )

            assert first.status_code == 200
            assert conflict.status_code == 409
            assert conflict.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
            assert conflict.json()["request_id"]
            assert rag.ask_calls == 1
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_repeated_stream_replays_completed_mysql_answer_without_second_stream(
    tmp_path,
) -> None:
    engine, override_session, user, _, service, rag = build_dependencies(tmp_path)
    install_overrides(override_session, service, rag)
    headers = {**auth_headers(user.id), "Idempotency-Key": "same-stream-request"}
    try:
        with TestClient(app) as client:
            conversation_id = client.post(
                "/api/v1/conversations",
                json={"title": "新对话"},
                headers=auth_headers(user.id),
            ).json()["id"]
            url = f"/api/v1/conversations/{conversation_id}/chat/stream"
            payload = {"question": "重复流式问题", "top_k": 2}

            first = client.post(url, json=payload, headers=headers)
            second = client.post(url, json=payload, headers=headers)

            assert first.status_code == second.status_code == 200
            assert first.text.count("event: token") == 2
            assert second.text.count("event: token") == 1
            assert "流式回答" in second.text
            assert "event: sources" in second.text
            assert "event: done" in second.text
            assert rag.stream_calls == 1
            detail = client.get(
                f"/api/v1/conversations/{conversation_id}",
                headers=auth_headers(user.id),
            ).json()
            assert detail["message_count"] == 2
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_missing_or_invalid_idempotency_key_is_rejected_before_model(tmp_path) -> None:
    engine, override_session, user, _, service, rag = build_dependencies(tmp_path)
    install_overrides(override_session, service, rag)
    try:
        with TestClient(app) as client:
            conversation_id = client.post(
                "/api/v1/conversations",
                json={"title": "新对话"},
                headers=auth_headers(user.id),
            ).json()["id"]
            url = f"/api/v1/conversations/{conversation_id}/chat"
            payload = {"question": "缺少请求键", "top_k": 2}

            missing = client.post(url, json=payload, headers=auth_headers(user.id))
            invalid = client.post(
                url,
                json=payload,
                headers={**auth_headers(user.id), "Idempotency-Key": "contains space"},
            )

            assert missing.status_code == invalid.status_code == 422
            assert rag.ask_calls == 0
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_in_progress_and_backend_failure_fail_before_model(tmp_path) -> None:
    engine, override_session, user, backend, service, rag = build_dependencies(tmp_path)
    install_overrides(override_session, service, rag)
    try:
        with TestClient(app) as client:
            conversation_id = client.post(
                "/api/v1/conversations",
                json={"title": "新对话"},
                headers=auth_headers(user.id),
            ).json()["id"]
            url = f"/api/v1/conversations/{conversation_id}/chat"
            payload = {"question": "正在处理", "top_k": 2}
            headers = {**auth_headers(user.id), "Idempotency-Key": "in-progress"}
            service.begin(
                user.id, "chat", "in-progress", conversation_id, "正在处理", 2
            )

            pending = client.post(url, json=payload, headers=headers)
            assert pending.status_code == 409
            assert pending.json()["error"]["code"] == "IDEMPOTENCY_REQUEST_IN_PROGRESS"

            def unavailable(*args, **kwargs):
                raise IdempotencyBackendUnavailable("offline")

            backend.begin_idempotency = unavailable
            unavailable_response = client.post(
                url,
                json=payload,
                headers={**auth_headers(user.id), "Idempotency-Key": "offline"},
            )
            assert unavailable_response.status_code == 503
            assert unavailable_response.json()["error"]["code"] == "IDEMPOTENCY_UNAVAILABLE"
            assert rag.ask_calls == 0
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_failed_request_clears_in_progress_record_so_same_key_can_retry(
    tmp_path,
) -> None:
    engine, override_session, user, backend, service, _ = build_dependencies(tmp_path)
    rag = FailingOnceRagService()
    install_overrides(override_session, service, rag)
    headers = {**auth_headers(user.id), "Idempotency-Key": "retry-after-failure"}
    try:
        with TestClient(app) as client:
            conversation_id = client.post(
                "/api/v1/conversations",
                json={"title": "新对话"},
                headers=auth_headers(user.id),
            ).json()["id"]
            url = f"/api/v1/conversations/{conversation_id}/chat"
            payload = {"question": "允许重试", "top_k": 2}

            failed = client.post(url, json=payload, headers=headers)
            retried = client.post(url, json=payload, headers=headers)

            assert failed.status_code == 503
            assert retried.status_code == 200
            assert retried.json()["answer"] == "重试成功：允许重试"
            assert rag.ask_calls == 2
            assert len(backend.records) == 1
            assert next(iter(backend.records.values()))["state"] == "completed"
            detail = client.get(
                f"/api/v1/conversations/{conversation_id}",
                headers=auth_headers(user.id),
            ).json()
            assert detail["message_count"] == 4
            assert [message["status"] for message in detail["messages"]] == [
                "completed",
                "failed",
                "completed",
                "completed",
            ]
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_result_store_failure_keeps_bounded_in_progress_guard_after_db_commit(
    tmp_path,
) -> None:
    engine, override_session, user, backend, service, rag = build_dependencies(tmp_path)
    install_overrides(override_session, service, rag)
    original_complete = backend.complete_idempotency

    def unavailable_complete(*args, **kwargs):
        raise IdempotencyBackendUnavailable("completion unavailable")

    backend.complete_idempotency = unavailable_complete
    headers = {**auth_headers(user.id), "Idempotency-Key": "completion-failed"}
    try:
        with TestClient(app) as client:
            conversation_id = client.post(
                "/api/v1/conversations",
                json={"title": "新对话"},
                headers=auth_headers(user.id),
            ).json()["id"]
            url = f"/api/v1/conversations/{conversation_id}/chat"
            payload = {"question": "结果登记失败", "top_k": 2}

            failed_completion = client.post(url, json=payload, headers=headers)
            backend.complete_idempotency = original_complete
            guarded_retry = client.post(url, json=payload, headers=headers)

            assert failed_completion.status_code == 503
            assert failed_completion.json()["error"]["code"] == "IDEMPOTENCY_UNAVAILABLE"
            assert guarded_retry.status_code == 409
            assert guarded_retry.json()["error"]["code"] == "IDEMPOTENCY_REQUEST_IN_PROGRESS"
            assert rag.ask_calls == 1
            assert next(iter(backend.records.values()))["state"] == "in_progress"
            detail = client.get(
                f"/api/v1/conversations/{conversation_id}",
                headers=auth_headers(user.id),
            ).json()
            assert detail["message_count"] == 2
            assert detail["messages"][1]["status"] == "completed"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
