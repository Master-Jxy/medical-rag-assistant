"""Deterministic overview/OCR routing for private chat images."""

import re

from app.core.config import Settings
from app.modules.vision.contracts import (
    VisionMeasurement,
    VisionObservation,
    VisionQualitySummary,
    VisionTextExtraction,
)
from app.modules.vision.service import VisionChatService


FINAL_ROUTE_KINDS = {"overview_only", "ocr_mode", "reupload_required"}
REUPLOAD_CODES = {
    "IMAGE_BLURRY",
    "IMAGE_CROPPED",
    "IMAGE_ORIENTATION_UNCLEAR",
}
OCR_TRIGGER_CODES = {
    "REPORT_TEXT_MISSING",
    "MEASUREMENT_CONTEXT_INCOMPLETE",
    "UNCERTAIN_CONTENT",
    "LOW_STRUCTURED_COVERAGE",
}


class VisionRouterService:
    def __init__(
        self,
        vision: VisionChatService,
        settings: Settings,
    ) -> None:
        self.vision = vision
        self.settings = settings

    def route_overview(
        self,
        *,
        user_id: str,
        asset_id: str,
        user_question: str,
        surface: str,
        usage_group_id: str,
        run_id: str | None = None,
    ) -> VisionObservation:
        overview = self.vision.observe_overview(
            user_id=user_id,
            asset_id=asset_id,
            user_question=user_question,
            surface=surface,
            usage_group_id=usage_group_id,
            run_id=run_id,
        )
        quality = overview.quality_summary
        if quality is None:
            raise ValueError("overview requires deterministic quality summary")
        if quality.route_kind in FINAL_ROUTE_KINDS:
            return overview

        codes = set(quality.quality_codes)
        if codes.intersection(REUPLOAD_CODES) or self._is_blank(overview):
            final = self._with_route(
                overview,
                route_kind="reupload_required",
                quality_status="retry",
                extra_codes=["REUPLOAD_REQUIRED"],
            )
        elif self._needs_ocr(overview):
            if not self.settings.vision_ocr_mode_enabled:
                final = self._with_route(
                    overview,
                    route_kind="overview_only",
                    quality_status="review",
                    extra_codes=["OCR_MODE_DISABLED"],
                )
            else:
                extraction = self.vision.extract_text(
                    user_id=user_id,
                    asset_id=asset_id,
                    surface=surface,
                    usage_group_id=usage_group_id,
                    run_id=run_id,
                )
                final = merge_vision_extraction(overview, extraction)
        else:
            final = self._with_route(
                overview,
                route_kind="overview_only",
                quality_status=quality.quality_status,
            )
        return self.vision.finalize_overview_route(
            user_id=user_id,
            asset_id=asset_id,
            surface=surface,
            usage_group_id=usage_group_id,
            run_id=run_id,
            observation=final,
        )

    def inspect(self, **kwargs) -> VisionObservation:
        return self.vision.inspect(**kwargs)

    @staticmethod
    def _is_blank(observation: VisionObservation) -> bool:
        return not any(
            (
                observation.visible_text,
                observation.measurements,
                observation.table_rows,
                observation.objects,
                observation.spatial_notes,
            )
        ) and observation.image_type.lower() in {"blank", "empty", "unknown"}

    @staticmethod
    def _needs_ocr(observation: VisionObservation) -> bool:
        quality = observation.quality_summary
        if quality is None or quality.route_kind not in {"document", "report"}:
            return False
        return quality.quality_status == "review" and bool(
            set(quality.quality_codes).intersection(OCR_TRIGGER_CODES)
        )

    @staticmethod
    def _with_route(
        observation: VisionObservation,
        *,
        route_kind: str,
        quality_status: str,
        extra_codes: list[str] | None = None,
    ) -> VisionObservation:
        current = observation.quality_summary
        codes = list(current.quality_codes if current else [])
        for code in extra_codes or []:
            if code not in codes:
                codes.append(code)
        return observation.model_copy(
            update={
                "quality_summary": VisionQualitySummary(
                    route_kind=route_kind,
                    quality_status=quality_status,
                    quality_codes=codes,
                )
            }
        )


def merge_vision_extraction(
    overview: VisionObservation,
    extraction: VisionTextExtraction,
) -> VisionObservation:
    visible_text = _dedupe_strings(
        [*overview.visible_text, *extraction.visible_text]
    )
    table_rows = _dedupe_rows([*overview.table_rows, *extraction.table_rows])
    measurements, conflicts = _merge_measurements(
        overview.measurements,
        extraction.measurements,
    )
    uncertain = _dedupe_strings(
        [*overview.uncertain_content, *extraction.uncertain_content, *conflicts]
    )
    original_codes = list(
        overview.quality_summary.quality_codes
        if overview.quality_summary is not None
        else []
    )
    resolved_codes = {
        "REPORT_TEXT_MISSING" if visible_text else "",
        "LOW_STRUCTURED_COVERAGE"
        if any((visible_text, measurements, table_rows))
        else "",
        "MEASUREMENT_CONTEXT_INCOMPLETE"
        if measurements
        and all(item.unit or item.reference_range or item.flag for item in measurements)
        else "",
    }
    codes = [code for code in original_codes if code not in resolved_codes]
    if "OCR_MODE_APPLIED" not in codes:
        codes.append("OCR_MODE_APPLIED")
    if conflicts and "MEASUREMENT_CONFLICT" not in codes:
        codes.append("MEASUREMENT_CONFLICT")
    has_content = bool(visible_text or measurements or table_rows)
    if not has_content and "OCR_NO_TEXT" not in codes:
        codes.append("OCR_NO_TEXT")
    status = "review" if uncertain or not has_content else "pass"
    return overview.model_copy(
        update={
            "visible_text": visible_text,
            "measurements": measurements,
            "table_rows": table_rows,
            "uncertain_content": uncertain,
            "quality_summary": VisionQualitySummary(
                route_kind="ocr_mode",
                quality_status=status,
                quality_codes=codes,
            ),
        }
    )


def _normalize(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip()).casefold()


def _dedupe_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = _normalize(value)
        if key and key not in seen:
            seen.add(key)
            result.append(" ".join(value.strip().split()))
    return result


def _dedupe_rows(rows: list[list[str]]) -> list[list[str]]:
    result: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    for row in rows:
        cleaned = [" ".join(str(cell).strip().split()) for cell in row]
        key = tuple(_normalize(cell) for cell in cleaned)
        if any(key) and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def _merge_measurements(
    overview: list[VisionMeasurement],
    extracted: list[VisionMeasurement],
) -> tuple[list[VisionMeasurement], list[str]]:
    result = [item.model_copy() for item in overview]
    exact = {
        (_normalize(item.name), _normalize(item.value), _normalize(item.unit))
        for item in result
    }
    by_name_unit = {
        (_normalize(item.name), _normalize(item.unit)): item for item in result
    }
    conflicts: list[str] = []
    for item in extracted:
        exact_key = (
            _normalize(item.name),
            _normalize(item.value),
            _normalize(item.unit),
        )
        if exact_key in exact:
            existing = by_name_unit[exact_key[::2]]
            updates = {
                "reference_range": existing.reference_range or item.reference_range,
                "flag": existing.flag or item.flag,
            }
            index = result.index(existing)
            result[index] = existing.model_copy(update=updates)
            by_name_unit[exact_key[::2]] = result[index]
            continue
        name_unit_key = (_normalize(item.name), _normalize(item.unit))
        existing = by_name_unit.get(name_unit_key)
        if existing is not None and _normalize(existing.value) != _normalize(item.value):
            conflicts.append(f"测量值冲突：{existing.name}")
        result.append(item.model_copy())
        exact.add(exact_key)
        by_name_unit.setdefault(name_unit_key, result[-1])
    return result, conflicts
