"""Deterministic public quality summary for structured image observations."""

from app.modules.vision.contracts import VisionObservation, VisionQualitySummary
from app.modules.vision.routing import observation_route


class VisionQualityGate:
    _BLUR_MARKERS = ("blur", "blurry", "模糊", "失焦")
    _CROP_MARKERS = ("crop", "cropped", "截断", "裁切", "不完整")
    _ORIENTATION_MARKERS = ("orientation", "rotate", "旋转", "方向")

    def evaluate(self, observation: VisionObservation) -> VisionQualitySummary:
        route_kind = observation_route(observation)
        codes: list[str] = []
        uncertain = " ".join(observation.uncertain_content).lower()

        if any(marker in uncertain for marker in self._BLUR_MARKERS):
            codes.append("IMAGE_BLURRY")
        if any(marker in uncertain for marker in self._CROP_MARKERS):
            codes.append("IMAGE_CROPPED")
        if any(marker in uncertain for marker in self._ORIENTATION_MARKERS):
            codes.append("IMAGE_ORIENTATION_UNCLEAR")

        if len(observation.summary.strip()) < 8:
            codes.append("SUMMARY_TOO_SHORT")
        if observation.uncertain_content:
            codes.append("UNCERTAIN_CONTENT")
        if not any(
            (
                observation.visible_text,
                observation.measurements,
                observation.objects,
                observation.spatial_notes,
            )
        ):
            codes.append("LOW_STRUCTURED_COVERAGE")
        if route_kind == "report" and not observation.visible_text:
            codes.append("REPORT_TEXT_MISSING")
        if route_kind == "report" and observation.measurements and any(
            not item.unit and not item.reference_range and not item.flag
            for item in observation.measurements
        ):
            codes.append("MEASUREMENT_CONTEXT_INCOMPLETE")

        codes = list(dict.fromkeys(codes))
        retry_codes = {
            "IMAGE_BLURRY",
            "IMAGE_CROPPED",
            "IMAGE_ORIENTATION_UNCLEAR",
        }
        if retry_codes.intersection(codes):
            status = "retry"
        elif codes:
            status = "review"
        else:
            status = "pass"
        return VisionQualitySummary(
            route_kind=route_kind,
            quality_status=status,
            quality_codes=codes,
        )

    def apply(self, observation: VisionObservation) -> VisionObservation:
        return observation.model_copy(
            update={"quality_summary": self.evaluate(observation)}
        )
