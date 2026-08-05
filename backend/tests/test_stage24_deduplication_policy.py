"""Stage 24.6 duplicate fingerprint policy tests."""

from app.modules.knowledge.deduplication import (
    MAX_NORMALIZED_TEXT_CHARS,
    DuplicatePolicy,
    hamming_distance,
    normalize_text,
)


def test_normalized_hash_is_versioned_and_stable_for_whitespace_and_width() -> None:
    left = DuplicatePolicy.fingerprint_text("糖尿病  指南\nA１")
    right = DuplicatePolicy.fingerprint_text("糖尿病 指南 A1")

    assert left.normalized_text_hash == right.normalized_text_hash
    assert left.normalized_text_hash_version == "normalized_text_sha256_v1"
    assert left.near_duplicate_fingerprint_version == "simhash64_v1"


def test_normalization_has_a_deterministic_resource_cap() -> None:
    text = "表格 行 " * (MAX_NORMALIZED_TEXT_CHARS // 3)
    normalized = normalize_text(text)

    assert len(normalized) <= MAX_NORMALIZED_TEXT_CHARS
    assert "\x00" not in normalize_text("abc\x00def")


def test_near_duplicate_simhash_separates_close_and_distant_text() -> None:
    baseline = DuplicatePolicy.fingerprint_text("心力衰竭 随访 用药 复查 血压 心率")
    close = DuplicatePolicy.fingerprint_text("心力衰竭 随访 用药 复查 血压")
    distant = DuplicatePolicy.fingerprint_text("糖尿病 饮食 胰岛素 血糖 足部护理")

    assert hamming_distance(
        int(baseline.near_duplicate_fingerprint, 16),
        int(close.near_duplicate_fingerprint, 16),
    ) < hamming_distance(
        int(baseline.near_duplicate_fingerprint, 16),
        int(distant.near_duplicate_fingerprint, 16),
    )
