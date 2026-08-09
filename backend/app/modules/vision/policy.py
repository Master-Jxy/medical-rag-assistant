"""Deterministic limits for overview and focused image observations."""

import hashlib

from app.core.exceptions import VisionPolicyError


OVERVIEW_HASH = "overview"


def normalize_focus(value: str) -> str:
    cleaned = " ".join(value.strip().split())
    if not cleaned or len(cleaned) > 500:
        raise VisionPolicyError("定向观察目标必须为 1 到 500 个字符")
    return cleaned


def focus_hash(value: str | None) -> str:
    if value is None:
        return OVERVIEW_HASH
    return hashlib.sha256(normalize_focus(value).encode("utf-8")).hexdigest()


def assert_call_allowed(*, completed_hashes: list[str], requested_hash: str, max_calls: int) -> None:
    if requested_hash in completed_hashes:
        raise VisionPolicyError("相同图片观察目标不能重复执行")
    if len(completed_hashes) >= max_calls:
        raise VisionPolicyError("该图片已达到最多 3 次观察上限，请上传更清晰的图片")
    focused_count = sum(item != OVERVIEW_HASH for item in completed_hashes)
    if requested_hash != OVERVIEW_HASH and focused_count >= 2:
        raise VisionPolicyError("该图片已达到最多 2 次定向观察上限")
