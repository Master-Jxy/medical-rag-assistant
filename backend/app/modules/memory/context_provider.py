import re
from sqlalchemy.orm import Session

from app.modules.memory.contracts import MemoryContext, MemoryContextItem
from app.modules.memory.repository import MemoryRepository


def _terms(text: str) -> set[str]:
    lowered = text.lower()
    words = set(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", lowered))
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]", lowered))
    words.update(chinese[i:i + 2] for i in range(max(0, len(chinese) - 1)))
    return {item for item in words if item}


class SqlAlchemyMemoryContextProvider:
    def __init__(self, session: Session, *, rag_max_items: int = 4, agent_max_items: int = 6,
                 rag_max_chars: int = 1200, agent_max_chars: int = 1800):
        self.repository = MemoryRepository(session)
        self.limits = {"rag": (rag_max_items, rag_max_chars), "agent": (agent_max_items, agent_max_chars)}

    def search(self, user_id: str, question: str, *, surface: str) -> MemoryContext:
        setting = self.repository.setting(user_id)
        if setting is None or not setting.enabled:
            return MemoryContext([], 0, False)
        query_terms = _terms(question)
        ranked = []
        for memory in self.repository.active(user_id):
            content_terms = _terms(f"{memory.label} {memory.content}")
            overlap = len(query_terms & content_terms)
            explicit = 0.5 if memory.source_type == "manual" else 0
            category = 0.25 if memory.category in ("goal", "ongoing_task", "preference") else 0
            score = overlap + explicit + category
            if score > 0:
                ranked.append((score, memory))
        ranked.sort(key=lambda row: (row[0], row[1].updated_at, row[1].id), reverse=True)
        max_items, max_chars = self.limits.get(surface, self.limits["rag"])
        items, used, truncated = [], 0, False
        for score, memory in ranked:
            if len(items) >= max_items or used + len(memory.content) > max_chars:
                truncated = True
                continue
            items.append(MemoryContextItem(memory.id, memory.category, memory.content, float(score)))
            used += len(memory.content)
        return MemoryContext(items, used, truncated)
