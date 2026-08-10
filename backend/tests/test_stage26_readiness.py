from pathlib import Path

from fastapi.testclient import TestClient

from app.infrastructure.readiness import (
    DatabaseReadinessProbe,
    WritableDirectoryReadinessProbe,
)
from app.core.config import Settings
from app.infrastructure.redis import RedisHealthStatus
from app.main import create_app
from app.services.health_service import ApplicationReadiness
from app.services.health_service import ReadinessService


class FakeRedis:
    def health_status(self) -> RedisHealthStatus:
        return RedisHealthStatus.OK

    def close(self) -> None:
        return None


class FakeReadinessService:
    def __init__(self, result: ApplicationReadiness) -> None:
        self.result = result
        self.inspect_calls = 0
        self.closed = False

    def inspect(self) -> ApplicationReadiness:
        self.inspect_calls += 1
        return self.result

    def close(self) -> None:
        self.closed = True


def test_livez_only_proves_process_liveness() -> None:
    readiness = FakeReadinessService(
        ApplicationReadiness(
            ready=False,
            dependencies={"mysql": "failed"},
            failure_codes=["MYSQL_UNAVAILABLE"],
        )
    )
    with TestClient(
        create_app(redis_infrastructure=FakeRedis(), readiness_service=readiness)
    ) as client:
        response = client.get("/livez")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert readiness.inspect_calls == 0
    assert readiness.closed is True


def test_readyz_reports_all_dependencies_when_ready() -> None:
    readiness = FakeReadinessService(
        ApplicationReadiness(
            ready=True,
            dependencies={
                "mysql": "ok",
                "redis": "ok",
                "chroma": "ok",
                "media": "ok",
            },
            failure_codes=[],
        )
    )
    with TestClient(
        create_app(redis_infrastructure=FakeRedis(), readiness_service=readiness)
    ) as client:
        response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "dependencies": {
            "mysql": "ok",
            "redis": "ok",
            "chroma": "ok",
            "media": "ok",
        },
        "failure_codes": [],
    }


def test_readyz_failure_is_503_with_stable_codes_and_no_sensitive_detail() -> None:
    readiness = FakeReadinessService(
        ApplicationReadiness(
            ready=False,
            dependencies={
                "mysql": "failed",
                "redis": "ok",
                "chroma": "ok",
                "media": "failed",
            },
            failure_codes=["MYSQL_UNAVAILABLE", "MEDIA_DIRECTORY_UNAVAILABLE"],
        )
    )
    with TestClient(
        create_app(redis_infrastructure=FakeRedis(), readiness_service=readiness)
    ) as client:
        response = client.get("/readyz")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["failure_codes"] == [
        "MYSQL_UNAVAILABLE",
        "MEDIA_DIRECTORY_UNAVAILABLE",
    ]
    serialized = response.text.lower()
    assert "password" not in serialized
    assert "mysql://" not in serialized
    assert "\\" not in serialized
    assert "/app/" not in serialized


def test_local_probes_are_bounded_and_do_not_create_missing_directories(
    tmp_path: Path,
) -> None:
    database = DatabaseReadinessProbe("sqlite:///:memory:", timeout_seconds=0.2)
    assert database.check().ok is True
    database.close()

    existing = tmp_path / "existing"
    existing.mkdir()
    assert WritableDirectoryReadinessProbe(existing, "DIR_FAILED").check().ok is True
    missing = tmp_path / "missing"
    result = WritableDirectoryReadinessProbe(missing, "DIR_FAILED").check()
    assert result.ok is False
    assert result.failure_code == "DIR_FAILED"
    assert not missing.exists()


def test_compose_uses_dependency_aware_readyz_for_backend_health() -> None:
    compose = (Path(__file__).resolve().parents[2] / "compose.yaml").read_text(
        encoding="utf-8"
    )
    assert "http://127.0.0.1:8000/readyz" in compose
    assert "http://127.0.0.1:8000/api/v1/health" not in compose
    assert "READINESS_TIMEOUT_SECONDS:" in compose
    root = Path(__file__).resolve().parents[2]
    assert "READINESS_TIMEOUT_SECONDS=1" in (
        root / "backend" / ".env.example"
    ).read_text(encoding="utf-8")
    assert "READINESS_TIMEOUT_SECONDS=1" in (
        root / "deploy" / ".env.example"
    ).read_text(encoding="utf-8")


def test_readyz_blackbox_uses_sqlite_redis_and_runtime_directories(
    tmp_path: Path,
) -> None:
    chroma = tmp_path / "chroma"
    media = tmp_path / "media"
    chroma.mkdir()
    media.mkdir()
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'ready.db'}",
        redis_url="redis://readiness.invalid/0",
        chroma_persist_dir=chroma,
        media_asset_dir=media,
    )
    with TestClient(
        create_app(redis_infrastructure=FakeRedis(), settings=settings)
    ) as client:
        response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json()["dependencies"] == {
        "mysql": "ok",
        "redis": "ok",
        "chroma": "ok",
        "media": "ok",
    }


def test_nginx_exposes_root_probes_in_http_acme_and_https_modes() -> None:
    root = Path(__file__).resolve().parents[2]
    for relative in (
        "deploy/nginx.conf",
        "deploy/nginx.acme.conf.template",
        "deploy/nginx.https.conf.template",
    ):
        config = (root / relative).read_text(encoding="utf-8")
        assert "location ~ ^/(livez|readyz)$" in config
        assert "proxy_connect_timeout 3s;" in config
        assert "proxy_read_timeout 3s;" in config


def test_unexpected_probe_error_is_stable_failure_not_exception_detail() -> None:
    class ExplodingProbe:
        def check(self):
            raise RuntimeError("mysql://user:secret@private-host/database")

        def close(self):
            raise RuntimeError("close secret")

    service = ReadinessService({"mysql": ExplodingProbe()})
    result = service.inspect()
    service.close()
    assert result.ready is False
    assert result.dependencies == {"mysql": "failed"}
    assert result.failure_codes == ["MYSQL_CHECK_FAILED"]
