"""No-cost Fake contract evaluation for synthetic chat vision/OCR fixtures."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from app.core.config import Settings
from app.modules.vision.contracts import (
    VisionObservation,
    VisionTextExtraction,
)
from app.modules.vision.quality import VisionQualityGate
from app.modules.vision.router_service import VisionRouterService


DEFAULT_MANIFEST = (
    Path(__file__).resolve().parents[2]
    / "evaluation"
    / "datasets"
    / "vision_ocr_v1"
    / "manifest.json"
)


class _ManifestVisionService:
    def __init__(self, case: dict) -> None:
        self.case = case
        self.overview_calls = 0
        self.ocr_calls = 0
        self.usage_charges = 0
        self.final: VisionObservation | None = None
        self.extraction: VisionTextExtraction | None = None
        self.gate = VisionQualityGate()

    def observe_overview(self, **kwargs) -> VisionObservation:
        del kwargs
        if self.final is not None:
            return self.final
        self.overview_calls += 1
        return self.gate.apply(VisionObservation.model_validate(self.case["overview"]))

    def extract_text(self, **kwargs) -> VisionTextExtraction:
        del kwargs
        if self.extraction is not None:
            return self.extraction
        self.ocr_calls += 1
        self.usage_charges += 1
        self.extraction = VisionTextExtraction.model_validate(
            self.case.get("extraction") or {}
        )
        return self.extraction

    def finalize_overview_route(
        self, *, observation: VisionObservation, **kwargs
    ) -> VisionObservation:
        del kwargs
        self.final = observation
        return observation


def _normalized_text(observation: VisionObservation) -> str:
    parts = [
        *observation.visible_text,
        *(" | ".join(row) for row in observation.table_rows),
        *(
            " ".join(filter(None, (item.name, item.value, item.unit)))
            for item in observation.measurements
        ),
    ]
    return " ".join(parts).casefold()


def _measurement_key(item: dict) -> tuple[str, str, str]:
    return (
        str(item.get("name", "")).strip().casefold(),
        str(item.get("value", "")).strip().casefold(),
        str(item.get("unit") or "").strip().casefold(),
    )


def _validated_manifest(manifest_path: Path) -> tuple[dict, list[tuple[dict, Path]]]:
    manifest_path = Path(manifest_path)
    if manifest_path.is_symlink():
        raise ValueError("vision OCR manifest must not be a symlink")
    try:
        resolved_manifest = manifest_path.resolve(strict=True)
    except OSError as exc:
        raise ValueError("vision OCR manifest is unavailable") from exc
    payload = json.loads(resolved_manifest.read_text(encoding="utf-8"))
    assets = payload.get("assets")
    if (
        payload.get("schema_version") != "vision-ocr-v1"
        or not isinstance(payload.get("automatic_retries"), int)
        or isinstance(payload.get("automatic_retries"), bool)
        or payload.get("automatic_retries") != 0
        or not isinstance(assets, list)
        or not assets
    ):
        raise ValueError("invalid vision OCR Fake contract manifest schema")

    asset_root = resolved_manifest.parent / "assets"
    if asset_root.is_symlink():
        raise ValueError("vision OCR asset directory must not be a symlink")
    try:
        resolved_root = asset_root.resolve(strict=True)
    except OSError as exc:
        raise ValueError("vision OCR asset directory is unavailable") from exc

    seen_case_ids: set[str] = set()
    seen_filenames: set[str] = set()
    seen_hashes: set[str] = set()
    validated: list[tuple[dict, Path]] = []
    for case in assets:
        if not isinstance(case, dict):
            raise ValueError("vision OCR asset entry must be an object")
        case_id = case.get("case_id")
        filename = case.get("filename")
        digest = case.get("sha256")
        if not isinstance(case_id, str) or not case_id.strip():
            raise ValueError("vision OCR case_id is required")
        if (
            not isinstance(filename, str)
            or not filename
            or "/" in filename
            or "\\" in filename
            or Path(filename).is_absolute()
            or Path(filename).name != filename
            or Path(filename).suffix.lower() != ".png"
        ):
            raise ValueError("vision OCR filename must be a PNG basename")
        if not isinstance(digest, str) or not re.fullmatch(
            r"[0-9a-f]{64}", digest
        ):
            raise ValueError("vision OCR sha256 must be lowercase hexadecimal")
        case_key = case_id.casefold()
        filename_key = filename.casefold()
        if case_key in seen_case_ids:
            raise ValueError("vision OCR case_id values must be unique")
        if filename_key in seen_filenames:
            raise ValueError("vision OCR filenames must be unique")
        if digest in seen_hashes:
            raise ValueError("vision OCR hashes must be unique")
        seen_case_ids.add(case_key)
        seen_filenames.add(filename_key)
        seen_hashes.add(digest)
        if case.get("privacy") != "synthetic":
            raise ValueError("vision OCR assets must be explicitly synthetic")
        if case.get("dimensions") != [640, 400]:
            raise ValueError("vision OCR asset dimensions are invalid")
        if case.get("expected_route") not in {
            "overview_only",
            "ocr_mode",
            "reupload_required",
        }:
            raise ValueError("vision OCR expected route is invalid")
        VisionObservation.model_validate(case.get("overview"))
        VisionTextExtraction.model_validate(case.get("extraction") or {})

        asset_path = asset_root / filename
        if asset_path.is_symlink():
            raise ValueError("vision OCR assets must not be symlinks")
        try:
            resolved_asset = asset_path.resolve(strict=True)
            resolved_asset.relative_to(resolved_root)
        except (OSError, ValueError) as exc:
            raise ValueError("vision OCR asset escapes the fixture directory") from exc
        if not resolved_asset.is_file():
            raise ValueError("vision OCR asset must be a regular file")
        validated.append((case, resolved_asset))
    return payload, validated


def run_evaluation(manifest_path: Path = DEFAULT_MANIFEST) -> dict:
    payload, validated_assets = _validated_manifest(manifest_path)
    assets = payload["assets"]

    hash_valid = 0
    schema_valid = 0
    route_correct = 0
    text_expected = 0
    text_matched = 0
    measurement_expected = 0
    measurement_matched = 0
    table_expected = 0
    table_matched = 0
    blank_hallucinations = 0
    duplicate_provider_calls = 0
    duplicate_usage_charges = 0
    fake_usage_total = 0
    fake_usage_calls = 0
    case_results = []
    settings = Settings(
        _env_file=None,
        vision_chat_enabled=True,
        vision_provider="fake",
        vision_ocr_mode_enabled=True,
        vision_ocr_provider="fake",
    )

    for case, asset_path in validated_assets:
        digest = hashlib.sha256(asset_path.read_bytes()).hexdigest()
        case_hash_valid = digest == case.get("sha256")
        hash_valid += int(case_hash_valid)
        schema_valid += 1

        service = _ManifestVisionService(case)
        router = VisionRouterService(service, settings)
        arguments = {
            "user_id": "synthetic-user",
            "asset_id": case["case_id"],
            "user_question": "describe visible facts",
            "surface": "vision_rag",
            "usage_group_id": f"eval:{case['case_id']}",
        }
        first = router.route_overview(**arguments)
        second = router.route_overview(**arguments)
        route = first.quality_summary.route_kind
        case_route_correct = route == case["expected_route"]
        route_correct += int(case_route_correct)
        assert first == second

        expected_ocr_calls = int(case["expected_route"] == "ocr_mode")
        duplicate_provider_calls += max(0, service.overview_calls - 1)
        duplicate_provider_calls += max(0, service.ocr_calls - expected_ocr_calls)
        duplicate_usage_charges += max(
            0, service.usage_charges - expected_ocr_calls
        )
        usage = case.get("fake_usage") or {}
        if expected_ocr_calls:
            fake_usage_total += int(usage.get("input_tokens", 0)) + int(
                usage.get("output_tokens", 0)
            )
            fake_usage_calls += 1

        combined_text = _normalized_text(first)
        for token in case.get("expected_text_tokens", []):
            text_expected += 1
            text_matched += int(token.casefold() in combined_text)

        actual_measurements = {
            _measurement_key(item.model_dump(mode="json"))
            for item in first.measurements
        }
        for item in case.get("expected_measurements", []):
            measurement_expected += 1
            measurement_matched += int(
                _measurement_key(item) in actual_measurements
            )

        actual_rows = {
            tuple(str(cell).strip().casefold() for cell in row)
            for row in first.table_rows
        }
        for row in case.get("expected_table_rows", []):
            table_expected += 1
            table_matched += int(
                tuple(str(cell).strip().casefold() for cell in row) in actual_rows
            )

        if case["case_id"] == "blank":
            blank_hallucinations += len(first.visible_text)
            blank_hallucinations += len(first.measurements)
            blank_hallucinations += len(first.table_rows)
        case_results.append(
            {
                "case_id": case["case_id"],
                "route": route,
                "route_correct": case_route_correct,
                "hash_valid": case_hash_valid,
            }
        )

    count = len(assets)
    return {
        "evaluation_name": "stage26_vision_ocr_fake_contract_v1",
        "mode": "fake_contract",
        "real_model_calls": 0,
        "asset_count": count,
        "hash_validity": hash_valid / count if count else 0,
        "schema_validity": schema_valid / count if count else 0,
        "route_accuracy": route_correct / count if count else 0,
        "visible_text_token_coverage": (
            text_matched / text_expected if text_expected else 1.0
        ),
        "measurement_completeness": (
            measurement_matched / measurement_expected
            if measurement_expected
            else 1.0
        ),
        "table_completeness": (
            table_matched / table_expected if table_expected else 1.0
        ),
        "blank_image_hallucination_count": blank_hallucinations,
        "duplicate_provider_call_count": duplicate_provider_calls,
        "duplicate_usage_charge_count": duplicate_usage_charges,
        "average_fake_token_usage": (
            fake_usage_total / fake_usage_calls if fake_usage_calls else 0
        ),
        "cases": case_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_evaluation(args.manifest)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    passed = (
        report["hash_validity"] == 1
        and report["schema_validity"] == 1
        and report["route_accuracy"] == 1
        and report["visible_text_token_coverage"] == 1
        and report["measurement_completeness"] == 1
        and report["table_completeness"] == 1
        and report["blank_image_hallucination_count"] == 0
        and report["duplicate_provider_call_count"] == 0
        and report["duplicate_usage_charge_count"] == 0
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
