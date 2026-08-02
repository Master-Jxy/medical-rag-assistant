"""Model catalog exposes only configured public metadata to authenticated users."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.session import build_engine, get_db_session
from app.main import app
from app.modules.auth.tokens import get_token_service
from tests.auth_helpers import TEST_TOKEN_SERVICE, auth_headers, create_test_user


def test_model_catalog_lists_active_and_testing_models(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'models.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    user = create_test_user(factory, "model-catalog")
    settings = Settings(
        _env_file=None,
        chat_model_name="qwen3-max",
        chat_input_price_per_million_tokens_cny=2.5,
        chat_output_price_per_million_tokens_cny=10,
        agent_input_price_per_million_tokens_cny=3,
        agent_output_price_per_million_tokens_cny=12,
    )

    def override_session():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_token_service] = lambda: TEST_TOKEN_SERVICE
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        with TestClient(app) as client:
            assert client.get("/api/v1/models").status_code == 401
            rag = client.get("/api/v1/models?surface=rag", headers=auth_headers(user.id))
            assert rag.status_code == 200
            assert rag.json()["active_model_id"] == "qwen"
            assert rag.json()["options"][0] == {
                "id": "qwen",
                "label": "通义千问",
                "provider": "DashScope",
                "model_name": "qwen3-max",
                "enabled": True,
                "status": "available",
                "input_price_per_million_tokens_cny": 2.5,
                "output_price_per_million_tokens_cny": 10.0,
            }
            assert [item["enabled"] for item in rag.json()["options"]] == [True, False, False]

            agent = client.get("/api/v1/models?surface=agent", headers=auth_headers(user.id))
            assert agent.json()["options"][0]["input_price_per_million_tokens_cny"] == 3
            assert agent.json()["options"][0]["output_price_per_million_tokens_cny"] == 12
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
