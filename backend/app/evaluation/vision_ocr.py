"""No-cost evaluation for the fixed synthetic chat vision/OCR dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
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


def run_evaluation(manifest_path: Path = DEFAULT_MANIFEST) -> dict:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assets = payload.get("assets")
    if payload.get("schema_version") != "vision-ocr-v1" or not isinstance(
        assets, list
    ):
        raise ValueError("invalid vision OCR manifest schema")

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

    for case in assets:
        asset_path = manifest_path.parent / "assets" / case["filename"]
        digest = hashlib.sha256(asset_path.read_bytes()).hexdigest()
        case_hash_valid = digest == case.get("sha256")
        hash_valid += int(case_hash_valid)
        case_schema_valid = (
            case.get("privacy") == "synthetic"
            and case.get("dimensions") == [640, 400]
            and case.get("expected_route")
            in {"overview_only", "ocr_mode", "reupload_required"}
        )
        VisionObservation.model_validate(case["overview"])
        VisionTextExtraction.model_validate(case.get("extraction") or {})
        schema_valid += int(case_schema_valid)

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
        "mode": "no_cost_fake",
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
