"""Safe canonical storage for private chat images."""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4
import warnings

from PIL import Image, UnidentifiedImageError

from app.core.config import Settings
from app.core.exceptions import MediaValidationError


ALLOWED = {
    "image/jpeg": ({".jpg", ".jpeg"}, ".jpg", "JPEG"),
    "image/png": ({".png"}, ".png", "PNG"),
    "image/webp": ({".webp"}, ".webp", "WEBP"),
}


@dataclass(frozen=True, slots=True)
class StoredImage:
    storage_key: str
    mime_type: str
    byte_size: int
    width: int
    height: int
    sha256: str


class PrivateMediaStorage:
    def __init__(self, settings: Settings) -> None:
        self.base_dir = settings.media_asset_dir
        self.max_bytes = settings.vision_max_image_bytes
        self.max_pixels = settings.vision_max_image_pixels

    def store(self, *, original_name: str, claimed_mime: str | None, data: bytes) -> StoredImage:
        if not data:
            raise MediaValidationError("图片不能为空")
        if len(data) > self.max_bytes:
            raise MediaValidationError("单张图片不能超过 10 MiB")
        safe_name = Path(original_name or "image").name
        if safe_name != (original_name or "image") or safe_name in {".", ".."}:
            raise MediaValidationError("图片文件名无效")
        suffix = Path(safe_name).suffix.lower()
        magic_mime = self._magic_mime(data)
        if magic_mime not in ALLOWED:
            raise MediaValidationError("仅支持 JPG、PNG、WEBP 图片")
        extensions, canonical_suffix, image_format = ALLOWED[magic_mime]
        if suffix not in extensions or claimed_mime != magic_mime:
            raise MediaValidationError("图片扩展名、MIME 与文件内容不一致")
        canonical, width, height = self._canonicalize(data, magic_mime, image_format)
        storage_key = f"assets/{uuid4().hex[:2]}/{uuid4().hex}{canonical_suffix}"
        target = self.resolve(storage_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_bytes(canonical)
        temporary.replace(target)
        return StoredImage(storage_key, magic_mime, len(canonical), width, height, hashlib.sha256(canonical).hexdigest())

    def resolve(self, storage_key: str) -> Path:
        if "\\" in storage_key or storage_key.startswith("/") or ".." in storage_key.split("/"):
            raise MediaValidationError("图片存储引用无效")
        target = (self.base_dir / storage_key).resolve()
        base = self.base_dir.resolve()
        if base == target or base not in target.parents:
            raise MediaValidationError("图片存储引用无效")
        return target

    def delete(self, storage_key: str) -> None:
        target = self.resolve(storage_key)
        if target.is_symlink():
            raise MediaValidationError("图片存储引用无效")
        target.unlink(missing_ok=True)

    def _canonicalize(self, data: bytes, mime_type: str, image_format: str) -> tuple[bytes, int, int]:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(data)) as image:
                    image.load()
                    width, height = image.size
                    if width <= 0 or height <= 0 or width * height > self.max_pixels:
                        raise MediaValidationError("图片像素尺寸超出安全限制")
                    if image.get_format_mimetype() != mime_type or getattr(image, "n_frames", 1) != 1:
                        raise MediaValidationError("图片结构或格式无效")
                    mode = "RGBA" if mime_type in {"image/png", "image/webp"} and "A" in image.getbands() else "RGB"
                    pixels = image.convert(mode)
                    clean = Image.new(mode, pixels.size)
                    clean.paste(pixels)
                    output = io.BytesIO()
                    kwargs = {"format": image_format}
                    if image_format == "JPEG":
                        kwargs.update(quality=90, optimize=True)
                    elif image_format == "WEBP":
                        kwargs.update(lossless=True, method=4)
                    else:
                        kwargs.update(optimize=True)
                    clean.save(output, **kwargs)
                    return output.getvalue(), width, height
        except MediaValidationError:
            raise
        except (Image.DecompressionBombError, Image.DecompressionBombWarning, UnidentifiedImageError, OSError, ValueError) as exc:
            raise MediaValidationError("图片结构无效或存在解压炸弹风险") from exc

    @staticmethod
    def _magic_mime(data: bytes) -> str | None:
        if data.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return "image/webp"
        return None
