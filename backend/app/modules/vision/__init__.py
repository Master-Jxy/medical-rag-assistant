"""Chat-specific structured vision boundary."""

from app.modules.vision.contracts import (
    VisionChatPort,
    VisionObservation,
    VisionQualitySummary,
    VisionResult,
    VisionTextExtraction,
    VisionTextExtractionConsumedError,
    VisionTextExtractionPort,
    VisionTextExtractionRequest,
    VisionTextExtractionResult,
)

__all__ = [
    "VisionChatPort",
    "VisionObservation",
    "VisionQualitySummary",
    "VisionResult",
    "VisionTextExtraction",
    "VisionTextExtractionConsumedError",
    "VisionTextExtractionPort",
    "VisionTextExtractionRequest",
    "VisionTextExtractionResult",
]
