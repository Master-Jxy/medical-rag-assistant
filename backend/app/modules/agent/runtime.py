"""Agent运行时装配；业务图只接收Port与白名单工具。"""

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.infrastructure.agent_model import (
    LangChainAgentContentGenerator,
    LangChainAgentModel,
    LangChainAgentPlanner,
)
from app.modules.agent.cancellation import AgentCancellationService
from app.modules.agent.graph import BoundedAgentGraph
from app.modules.agent.knowledge_tools import create_read_only_knowledge_registry
from app.modules.knowledge.public_catalog import PublishedKnowledgeCatalogService
from app.modules.rag.hybrid_search import create_current_knowledge_search
from app.modules.agent.usage import AgentModelCallBudget, AgentModelUsageCollector


def create_agent_graph_factory(
    *,
    session: Session,
    settings: Settings,
    cancellation: AgentCancellationService,
):
    def factory(user_id: str, run_id: str) -> BoundedAgentGraph:
        # 查询历史和停止运行不应初始化Chroma或模型；只在真正执行时装配。
        search = create_current_knowledge_search(settings)
        catalog = PublishedKnowledgeCatalogService(session, settings=settings)
        usage_collector = AgentModelUsageCollector()
        call_budget = AgentModelCallBudget(settings.agent_max_model_calls)
        model = LangChainAgentModel(
            settings,
            usage_collector.add,
            call_budget=call_budget,
        )
        generator = LangChainAgentContentGenerator(model)
        registry = create_read_only_knowledge_registry(search, catalog, generator)
        planner = LangChainAgentPlanner(model, registry)
        return BoundedAgentGraph(
            planner=planner,
            registry=registry,
            stop_requested=lambda: cancellation.is_requested(user_id, run_id),
            usage_collector=usage_collector,
        )

    return factory
