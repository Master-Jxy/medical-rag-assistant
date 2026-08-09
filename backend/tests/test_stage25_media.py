"""Stage 25.1 private media security and lifecycle tests (no provider calls)."""

from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.session import build_engine, get_db_session
from app.main import app
from app.modules.auth.tokens import get_token_service
from app.modules.media.models import MediaAsset
from app.modules.media.service import MediaAssetService
from app.modules.media.storage import PrivateMediaStorage
from tests.auth_helpers import TEST_TOKEN_SERVICE, auth_headers, create_test_user


def image_bytes(image_format: str = "PNG", *, exif: bool = False) -> bytes:
    output = BytesIO()
    image = Image.new("RGB", (24, 16), (110, 140, 180))
    metadata = Image.Exif()
    if exif:
        metadata[0x010E] = "sensitive description"
    image.save(output, format=image_format, exif=metadata)
    return output.getvalue()


def build_client(tmp_path):
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'media.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    owner = create_test_user(factory, "media-owner")
    other = create_test_user(factory, "media-other")
    settings = Settings(_env_file=None, media_asset_dir=tmp_path / "private-media")

    def override_session():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_token_service] = lambda: TEST_TOKEN_SERVICE
    return engine, factory, owner, other, settings


def test_upload_reencodes_strips_exif_and_enforces_owner_preview(tmp_path) -> None:
    engine, factory, owner, other, settings = build_client(tmp_path)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/media/assets",
                files={"file": ("report.jpg", image_bytes("JPEG", exif=True), "image/jpeg")},
                headers=auth_headers(owner.id),
            )
            assert response.status_code == 201
            payload = response.json()
            assert payload["mime_type"] == "image/jpeg"
            assert payload["width"] == 24 and payload["height"] == 16
            assert client.get(payload["preview_url"], headers=auth_headers(other.id)).status_code == 404
            preview = client.get(payload["preview_url"], headers=auth_headers(owner.id))
            assert preview.status_code == 200
            assert preview.headers["cache-control"] == "private, no-store"
            with factory() as session:
                asset = session.get(MediaAsset, payload["id"])
                stored = PrivateMediaStorage(settings).resolve(asset.storage_key)
                with Image.open(stored) as image:
                    assert len(image.getexif()) == 0
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_rejects_spoofed_mime_extension_and_traversal_name(tmp_path) -> None:
    engine, _factory, owner, _other, _settings = build_client(tmp_path)
    try:
        with TestClient(app) as client:
            png = image_bytes("PNG")
            spoofed = client.post(
                "/api/v1/media/assets",
                files={"file": ("scan.jpg", png, "image/jpeg")},
                headers=auth_headers(owner.id),
            )
            assert spoofed.status_code == 422
            traversal = client.post(
                "/api/v1/media/assets",
                files={"file": ("../scan.png", png, "image/png")},
                headers=auth_headers(owner.id),
            )
            assert traversal.status_code == 422
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_delete_unattached_asset_removes_private_file(tmp_path) -> None:
    engine, factory, owner, _other, settings = build_client(tmp_path)
    try:
        with TestClient(app) as client:
            uploaded = client.post(
                "/api/v1/media/assets",
                files={"file": ("scan.webp", image_bytes("WEBP"), "image/webp")},
                headers=auth_headers(owner.id),
            ).json()
            with factory() as session:
                asset = session.get(MediaAsset, uploaded["id"])
                stored = PrivateMediaStorage(settings).resolve(asset.storage_key)
                assert stored.exists()
            deleted = client.delete(f"/api/v1/media/assets/{uploaded['id']}", headers=auth_headers(owner.id))
            assert deleted.status_code == 200
            assert not stored.exists()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_cleanup_reclaims_orphaned_attached_asset(tmp_path) -> None:
    engine, factory, owner, _other, settings = build_client(tmp_path)
    try:
        with TestClient(app) as client:
            uploaded = client.post(
                "/api/v1/media/assets",
                files={"file": ("scan.png", image_bytes("PNG"), "image/png")},
                headers=auth_headers(owner.id),
            ).json()
        with factory() as session:
            asset = session.get(MediaAsset, uploaded["id"])
            stored = PrivateMediaStorage(settings).resolve(asset.storage_key)
            asset.status = "attached"
            session.commit()
            assert MediaAssetService(session, settings).cleanup_expired() == 1
            assert asset.status == "expired"
            assert not stored.exists()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
