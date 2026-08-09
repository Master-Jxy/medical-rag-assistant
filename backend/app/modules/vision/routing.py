"""Small routing helpers for chat image observations."""

from app.modules.vision.contracts import VisionObservation


def observation_route(observation: VisionObservation) -> str:
    if observation.measurements or observation.image_type == "medical_report":
        return "report"
    if observation.visible_text:
        return "document"
    return "general"
