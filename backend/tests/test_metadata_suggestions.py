"""Stage 24.5 metadata suggestion governance tests."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.api.admin_reviews import get_review_service
from app.core.config import Settings
from app.db.base import Base
from app.db.session import build_engine, get_db_session
from app.main import app
from app.models import (
    AuditEvent,
    DocumentVersion,
    KnowledgeDocument,
    KnowledgeSubmission,
    MetadataSuggestion,
)
from app.modules.audit.repository import SqlAlchemyAuditRecorder
from app.modules.auth.tokens import get_token_service
from app.modules.jobs.service import SqlAlchemyJobService
from app.modules.knowledge.lifecycle import DocumentLifecycleService
from app.modules.knowledge.metadata_suggestions import (
    FakeMetadataSuggestionPort,
    MetadataSuggestionDecisionRequest,
    MetadataSuggestionResult,
    MetadataSuggestionService,
    create_metadata_suggestion_port,
)
from app.modules.knowledge.review_service import KnowledgeReviewService
from tests.auth_helpers import TEST_TOKEN_SERVICE, auth_headers, create_test_user
from tests.test_admin_reviews_api import add_submission
from tests.test_document_service import FakeVectorStore


class NoisySuggestionPort:
    def suggest(self, request):
        del request
        return MetadataSuggestionResult(
            fields={"department": "cardiology", "disease_topics": ["heart"]},
            evidence=[
                {
                    "field": "department",
                    "snippet": "x" * 500,
                    "confidence": 0.7,
                }
                for _ in range(20)
            ],
            confidence={"department": 1.5, "bad": 0.5},
            parse_warnings=["w" * 300 for _ in range(20)],
            suggestion_source="evil-provider",
        )


class FailingSuggestionPort:
    def suggest(self, request):
        del request
        raise RuntimeError("provider should not leak")


class FailingAudit:
    def record(self, event):
        del event
        raise RuntimeError("audit failed")


class CountingSuggestionPort:
    def __init__(self):
        self.calls = 0

    def suggest(self, request):
        self.calls += 1
        return MetadataSuggestionResult(
            fields={"source": "manual"},
            suggestion_source="manual",
            evidence=[{"snippet": request.file_name}],
        )


def build_client(tmp_path, *, port=None, metadata_mode="disabled"):
    tmp_path.mkdir(parents=True, exist_ok=True)
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'metadata.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    submitter = create_test_user(factory, "metadata-submitter")
    admin = create_test_user(factory, "metadata-admin", role="admin")
    normal = create_test_user(factory, "metadata-normal")
    settings = Settings(
        _env_file=None,
        submission_dir=tmp_path / "isolated",
        upload_dir=tmp_path / "published",
        document_asset_dir=tmp_path / "assets",
        chunk_size=40,
        chunk_overlap=5,
        metadata_suggestion_mode=metadata_mode,
    )
    vectors = FakeVectorStore()

    def override_session():
        with factory() as session:
            yield session

    def override_review_service():
        with factory() as session:
            audit = SqlAlchemyAuditRecorder(session)
            metadata_service = MetadataSuggestionService(
                session,
                audit,
                port or (
                    FakeMetadataSuggestionPort()
                    if metadata_mode == "fake"
                    else None
                ),
            )
            yield KnowledgeReviewService(
                session,
                settings,
                DocumentLifecycleService(session, settings, vectors),
                audit,
                SqlAlchemyJobService(session),
                metadata_suggestions=metadata_service,
            )

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_token_service] = lambda: TEST_TOKEN_SERVICE
    app.dependency_overrides[get_review_service] = override_review_service
    return engine, factory, settings, vectors, submitter, admin, normal


def teardown(engine):
    app.dependency_overrides.clear()
    engine.dispose()


def test_get_reviews_is_read_only_and_generate_is_explicit_idempotent(tmp_path):
    engine, factory, settings, vectors, submitter, admin, normal = build_client(tmp_path)
    submission_id = add_submission(factory, settings, submitter.id, "m")
    try:
        with TestClient(app) as client:
            forbidden = client.post(
                f"/api/v1/admin/reviews/{submission_id}/metadata-suggestion/accept",
                json={"revision": 1},
                headers=auth_headers(normal.id),
            )
            assert forbidden.status_code == 403

            with factory() as session:
                before = session.scalar(
                    select(func.count()).select_from(MetadataSuggestion)
                )
            listed = client.get(
                "/api/v1/admin/reviews",
                headers=auth_headers(admin.id),
            )
            assert listed.status_code == 200
            assert listed.json()["items"][0]["metadata_suggestion"] is None
            detail = client.get(
                f"/api/v1/admin/reviews/{submission_id}",
                headers=auth_headers(admin.id),
            )
            assert detail.status_code == 200
            assert detail.json()["metadata_suggestion"] is None
            with factory() as session:
                after = session.scalar(
                    select(func.count()).select_from(MetadataSuggestion)
                )
            assert after == before == 0

            missing = client.post(
                f"/api/v1/admin/reviews/{submission_id}/metadata-suggestion/accept",
                json={"revision": 1},
                headers=auth_headers(admin.id),
            )
            assert missing.status_code == 404

            generated = client.post(
                f"/api/v1/admin/reviews/{submission_id}/metadata-suggestion/generate",
                headers=auth_headers(admin.id),
            )
            assert generated.status_code == 200
            suggestion = generated.json()
            assert suggestion["suggestion_source"] == "disabled"
            assert suggestion["status"] == "suggested"
            generated_again = client.post(
                f"/api/v1/admin/reviews/{submission_id}/metadata-suggestion/generate",
                headers=auth_headers(admin.id),
            )
            assert generated_again.status_code == 200
            assert generated_again.json()["id"] == suggestion["id"]
            with factory() as session:
                assert session.scalar(
                    select(func.count()).select_from(MetadataSuggestion)
                ) == 1

            approved = client.post(
                f"/api/v1/admin/reviews/{submission_id}/approve",
                headers=auth_headers(admin.id),
            )
            assert approved.status_code == 200

        with factory() as session:
            submission = session.get(KnowledgeSubmission, submission_id)
            version = session.scalar(
                select(DocumentVersion).where(
                    DocumentVersion.document_id == submission.document_id
                )
            )
            assert version.document_type is None
            assert version.disease_topics in (None, [])
            assert session.scalar(select(MetadataSuggestion)).status == "suggested"
        assert vectors.entries
    finally:
        teardown(engine)


def test_admin_can_edit_accept_and_publish_confirmed_metadata(tmp_path):
    engine, factory, settings, vectors, submitter, admin, _normal = build_client(tmp_path)
    submission_id = add_submission(factory, settings, submitter.id, "n")
    try:
        with TestClient(app) as client:
            suggestion = client.post(
                f"/api/v1/admin/reviews/{submission_id}/metadata-suggestion/generate",
                headers=auth_headers(admin.id),
            ).json()

            accepted = client.post(
                f"/api/v1/admin/reviews/{submission_id}/metadata-suggestion/accept",
                json={
                    "revision": suggestion["revision"],
                    "fields": {
                        "department": "cardiology",
                        "disease_topics": ["heart failure"],
                        "document_type": "guideline",
                        "published_year": 2025,
                        "source": "journal",
                        "review_due_at": "2030-01-01T00:00:00Z",
                    },
                },
                headers=auth_headers(admin.id),
            )
            assert accepted.status_code == 200
            assert accepted.json()["status"] == "edited"

            duplicate = client.post(
                f"/api/v1/admin/reviews/{submission_id}/metadata-suggestion/accept",
                json={"revision": suggestion["revision"]},
                headers=auth_headers(admin.id),
            )
            assert duplicate.status_code == 409

            approved = client.post(
                f"/api/v1/admin/reviews/{submission_id}/approve",
                headers=auth_headers(admin.id),
            )
            assert approved.status_code == 200

        with factory() as session:
            submission = session.get(KnowledgeSubmission, submission_id)
            version = session.scalar(
                select(DocumentVersion).where(
                    DocumentVersion.document_id == submission.document_id
                )
            )
            assert version.department == "cardiology"
            assert version.disease_topics == ["heart failure"]
            assert version.document_type == "guideline"
            assert version.published_year == 2025
            assert version.source == "journal"
            actions = set(session.scalars(select(AuditEvent.action)).all())
            assert "metadata_suggestion.edited" in actions
            assert "knowledge_submission.published" in actions
    finally:
        teardown(engine)


def test_fake_suggestion_can_be_accepted_without_editing(tmp_path):
    engine, factory, settings, _vectors, submitter, admin, _normal = build_client(
        tmp_path, metadata_mode="fake"
    )
    submission_id = add_submission(factory, settings, submitter.id, "f")
    try:
        with TestClient(app) as client:
            suggestion = client.post(
                f"/api/v1/admin/reviews/{submission_id}/metadata-suggestion/generate",
                headers=auth_headers(admin.id),
            ).json()
            assert suggestion["suggestion_source"] == "fake"
            accepted = client.post(
                f"/api/v1/admin/reviews/{submission_id}/metadata-suggestion/accept",
                json={"revision": suggestion["revision"]},
                headers=auth_headers(admin.id),
            )
            assert accepted.status_code == 200
            assert accepted.json()["status"] == "accepted"
    finally:
        teardown(engine)


def test_reject_and_invalid_fields_are_stable(tmp_path):
    engine, factory, settings, _vectors, submitter, admin, _normal = build_client(tmp_path)
    submission_id = add_submission(factory, settings, submitter.id, "r")
    try:
        with TestClient(app) as client:
            suggestion = client.post(
                f"/api/v1/admin/reviews/{submission_id}/metadata-suggestion/generate",
                headers=auth_headers(admin.id),
            ).json()
            invalid = client.post(
                f"/api/v1/admin/reviews/{submission_id}/metadata-suggestion/accept",
                json={
                    "revision": suggestion["revision"],
                    "fields": {"published_year": 1800, "unexpected": "x"},
                },
                headers=auth_headers(admin.id),
            )
            assert invalid.status_code == 422

            rejected = client.post(
                f"/api/v1/admin/reviews/{submission_id}/metadata-suggestion/reject",
                json={"revision": suggestion["revision"], "reason": "not useful"},
                headers=auth_headers(admin.id),
            )
            assert rejected.status_code == 200
            assert rejected.json()["status"] == "rejected"
    finally:
        teardown(engine)


def test_suggestion_failure_and_evidence_limits_do_not_block_review(tmp_path):
    engine, factory, settings, _vectors, submitter, admin, _normal = build_client(
        tmp_path, port=FailingSuggestionPort()
    )
    submission_id = add_submission(factory, settings, submitter.id, "x")
    try:
        with TestClient(app) as client:
            item = client.post(
                f"/api/v1/admin/reviews/{submission_id}/metadata-suggestion/generate",
                headers=auth_headers(admin.id),
            ).json()
            assert item["failure_reason"] == "RuntimeError"
            approved = client.post(
                f"/api/v1/admin/reviews/{submission_id}/approve",
                headers=auth_headers(admin.id),
            )
            assert approved.status_code == 200
    finally:
        teardown(engine)

    engine, factory, settings, _vectors, submitter, admin, _normal = build_client(
        tmp_path / "limits", port=NoisySuggestionPort()
    )
    submission_id = add_submission(factory, settings, submitter.id, "y")
    try:
        with TestClient(app) as client:
            suggestion = client.post(
                f"/api/v1/admin/reviews/{submission_id}/metadata-suggestion/generate",
                headers=auth_headers(admin.id),
            ).json()
            assert len(suggestion["evidence"]) == 8
            assert all(len(evidence["snippet"]) <= 240 for evidence in suggestion["evidence"])
            assert suggestion["confidence"] == {"department": 1.0}
            assert len(suggestion["parse_warnings"]) <= 12
            assert suggestion["suggestion_source"] == "disabled"
    finally:
        teardown(engine)


def test_metadata_suggestion_factory_and_source_are_strict() -> None:
    assert create_metadata_suggestion_port("disabled").suggest is not None
    assert create_metadata_suggestion_port("fake").suggest is not None
    with pytest.raises(Exception):
        create_metadata_suggestion_port("surprise")


def test_two_sessions_accept_conflict_uses_expected_revision(tmp_path) -> None:
    engine, factory, settings, _vectors, submitter, admin, _normal = build_client(tmp_path)
    submission_id = add_submission(factory, settings, submitter.id, "c")
    try:
        with TestClient(app) as client:
            suggestion = client.post(
                f"/api/v1/admin/reviews/{submission_id}/metadata-suggestion/generate",
                headers=auth_headers(admin.id),
            ).json()

        first = factory()
        second = factory()
        try:
            first_service = MetadataSuggestionService(
                first, SqlAlchemyAuditRecorder(first), FakeMetadataSuggestionPort()
            )
            second_service = MetadataSuggestionService(
                second, SqlAlchemyAuditRecorder(second), FakeMetadataSuggestionPort()
            )
            payload = MetadataSuggestionDecisionRequest(revision=suggestion["revision"])
            accepted = first_service.accept(
                submission_id,
                payload,
                actor_user_id=admin.id,
                request_id=None,
            )
            assert accepted.revision == 2
            with pytest.raises(Exception):
                second_service.accept(
                    submission_id,
                    payload,
                    actor_user_id=admin.id,
                    request_id=None,
                )
            second.rollback()
            saved = second.get(MetadataSuggestion, suggestion["id"])
            assert saved.status == "accepted"
            assert saved.revision == 2
        finally:
            first.close()
            second.close()
    finally:
        teardown(engine)


def test_generate_and_accept_rollback_on_audit_failure(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'rollback.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    submitter = create_test_user(factory, "rollback-submitter")
    admin = create_test_user(factory, "rollback-admin", role="admin")
    settings = Settings(_env_file=None, submission_dir=tmp_path / "isolated")
    submission_id = add_submission(factory, settings, submitter.id, "z")
    try:
        with factory() as session:
            service = MetadataSuggestionService(
                session,
                FailingAudit(),
                FakeMetadataSuggestionPort(),
            )
            with pytest.raises(RuntimeError):
                service.generate(
                    submission_id,
                    actor_user_id=admin.id,
                    request_id="request",
                )
            assert session.scalar(select(MetadataSuggestion)) is None

        with factory() as session:
            service = MetadataSuggestionService(
                session,
                SqlAlchemyAuditRecorder(session),
                FakeMetadataSuggestionPort(),
            )
            suggestion = service.generate(
                submission_id,
                actor_user_id=admin.id,
                request_id=None,
            )

        with factory() as session:
            service = MetadataSuggestionService(
                session,
                FailingAudit(),
                FakeMetadataSuggestionPort(),
            )
            with pytest.raises(RuntimeError):
                service.accept(
                    submission_id,
                    MetadataSuggestionDecisionRequest(revision=suggestion.revision),
                    actor_user_id=admin.id,
                    request_id="request",
                )
            saved = session.get(MetadataSuggestion, suggestion.id)
            assert saved.status == "suggested"
            assert saved.revision == 1
            assert saved.reviewed_by is None
            actions = set(session.scalars(select(AuditEvent.action)).all())
            assert actions == {"metadata_suggestion.generated"}

        with factory() as session:
            document = KnowledgeDocument(
                id="published-doc",
                original_name="published.txt",
                stored_name="published.txt",
                content_hash="c" * 64,
                size_bytes=10,
                chunk_count=1,
                chunk_ids=["published-doc:0"],
                uploader_id=submitter.id,
                is_system=False,
                status="published",
            )
            submission = session.get(KnowledgeSubmission, submission_id)
            submission.document_id = document.id
            session.add(document)
            session.add(
                DocumentVersion(
                    id="published-version",
                    document_id=document.id,
                    version=1,
                    source="user_submission",
                    tags=[],
                )
            )
            session.commit()

        with factory() as session:
            service = MetadataSuggestionService(
                session,
                FailingAudit(),
                FakeMetadataSuggestionPort(),
            )
            with pytest.raises(RuntimeError):
                service.accept(
                    submission_id,
                    MetadataSuggestionDecisionRequest(
                        revision=suggestion.revision,
                        fields={"department": "cardiology"},
                    ),
                    actor_user_id=admin.id,
                    request_id="request",
                )
            saved = session.get(MetadataSuggestion, suggestion.id)
            version = session.get(DocumentVersion, "published-version")
            assert saved.status == "suggested"
            assert saved.revision == 1
            assert version.department is None
    finally:
        engine.dispose()


def test_generate_does_not_call_port_when_existing(tmp_path) -> None:
    port = CountingSuggestionPort()
    engine, factory, settings, _vectors, submitter, admin, _normal = build_client(
        tmp_path, port=port
    )
    submission_id = add_submission(factory, settings, submitter.id, "i")
    try:
        with TestClient(app) as client:
            first = client.post(
                f"/api/v1/admin/reviews/{submission_id}/metadata-suggestion/generate",
                headers=auth_headers(admin.id),
            )
            second = client.post(
                f"/api/v1/admin/reviews/{submission_id}/metadata-suggestion/generate",
                headers=auth_headers(admin.id),
            )
            assert first.status_code == 200
            assert second.status_code == 200
            assert first.json()["id"] == second.json()["id"]
            assert port.calls == 1
    finally:
        teardown(engine)


def test_generate_integrity_race_returns_existing_suggestion(tmp_path, monkeypatch) -> None:
    engine, factory, settings, _vectors, submitter, admin, _normal = build_client(
        tmp_path, port=CountingSuggestionPort()
    )
    submission_id = add_submission(factory, settings, submitter.id, "u")
    try:
        with factory() as session:
            service = MetadataSuggestionService(
                session,
                SqlAlchemyAuditRecorder(session),
                FakeMetadataSuggestionPort(),
            )
            existing = service.generate(
                submission_id,
                actor_user_id=admin.id,
                request_id=None,
            )

        with factory() as session:
            service = MetadataSuggestionService(
                session,
                SqlAlchemyAuditRecorder(session),
                FakeMetadataSuggestionPort(),
            )
            original_scalar = session.scalar
            calls = {"count": 0}

            def hide_existing_once(statement, *args, **kwargs):
                calls["count"] += 1
                if calls["count"] == 1:
                    return None
                return original_scalar(statement, *args, **kwargs)

            monkeypatch.setattr(session, "scalar", hide_existing_once)
            returned = service.generate(
                submission_id,
                actor_user_id=admin.id,
                request_id=None,
            )
            assert returned.id == existing.id
            assert session.scalar(
                select(func.count()).select_from(MetadataSuggestion)
            ) == 1
    finally:
        teardown(engine)
