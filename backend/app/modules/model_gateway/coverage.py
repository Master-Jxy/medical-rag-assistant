"""Auditable accounting contract for every model-backed application surface."""

from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class SurfaceAccountingRule:
    surface: str
    route_id: str
    ledger_surface: str
    quota_mode: str
    note: str


SURFACE_ACCOUNTING_RULES = (
    SurfaceAccountingRule("rag", "qwen", "rag", "parent_reservation", "RAG answer usage settles the answer reservation."),
    SurfaceAccountingRule("agent", "qwen", "agent", "parent_reservation", "All bounded Agent model calls share one response usage group."),
    SurfaceAccountingRule("vision_rag", "qwen-vision", "vision_rag", "own_reservation", "Each overview/focused/OCR call is reserved and settled independently."),
    SurfaceAccountingRule("vision_agent", "qwen-vision", "vision_agent", "own_reservation", "Each overview/focused/OCR call is reserved and settled independently."),
    SurfaceAccountingRule("vision_ocr", "qwen-vision", "vision_rag|vision_agent", "own_reservation", "OCR is distinguished by operation=report_extract on its owning chat surface."),
    SurfaceAccountingRule("rerank", "qwen-rerank", "rerank", "parent_rag_reservation", "Rerank usage is recorded separately and added to the RAG settlement usage."),
    SurfaceAccountingRule("memory", "qwen", "memory", "system_cost_nonbillable", "Automatic memory extraction is visible to administrators without silently charging users."),
    SurfaceAccountingRule("knowledge", "qwen-vision", "knowledge", "own_reservation", "Approved enrichment reserves before invoking bounded OCR/Vision ports."),
)


def accounting_contracts() -> list[dict[str, str]]:
    return [asdict(rule) for rule in SURFACE_ACCOUNTING_RULES]
