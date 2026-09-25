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
from app.modules.knowledge.retrieval_eligibility import (
    EligibilityFilteredKnowledgeSearch,
    SqlAlchemyDocumentRetrievalEligibility,
)
from app.modules.rag.hybrid_search import create_current_knowledge_search
from app.modules.agent.usage import AgentModelCallBudget, AgentModelUsageCollector
from app.modules.agent.repository import AgentRepository
from app.modules.agent.thread_models import AgentMessage
from app.modules.agent.vision_tools import InspectImageTool, ObserveImageTool
from app.modules.media.repository import MediaRepository
from app.modules.vision.service import VisionChatService
from app.modules.vision.router_service import VisionRouterService


def create_agent_graph_factory(
    *,
    session: Session,
    settings: Settings,
    cancellation: AgentCancellationService,
):
    def factory(user_id: str, run_id: str) -> BoundedAgentGraph:
        # 查询历史和停止运行不应初始化Chroma或模型；只在真正执行时装配。
        search = EligibilityFilteredKnowledgeSearch(
            create_current_knowledge_search(settings),
            SqlAlchemyDocumentRetrievalEligibility(session),
        )
        catalog = PublishedKnowledgeCatalogService(session, settings=settings)
        usage_collector = AgentModelUsageCollector()
        call_budget = AgentModelCallBudget(settings.agent_max_model_calls)
        run = AgentRepository(session).get_run(user_id, run_id)
        trigger_message = session.get(AgentMessage, run.trigger_message_id)
        selected_model_id = None
        if trigger_message is not None:
            raw_model_id = (trigger_message.message_metadata or {}).get("model_id")
            if isinstance(raw_model_id, str) and raw_model_id:
                selected_model_id = raw_model_id
        model = LangChainAgentModel(
            settings,
            usage_collector.add,
            call_budget=call_budget,
            model_id=selected_model_id,
        )
        generator = LangChainAgentContentGenerator(model)
        registry = create_read_only_knowledge_registry(search, catalog, generator)
        media_repository = MediaRepository(session)
        allowed_asset_ids = media_repository.asset_ids_for_agent_message(
            run.trigger_message_id
        )
        if not allowed_asset_ids and trigger_message is not None:
            allowed_asset_ids = [
                str(value)
                for value in (trigger_message.message_metadata or {}).get(
                    "attachment_ids", []
                )
                if value and media_repository.owned(user_id, str(value)) is not None
            ]
        if allowed_asset_ids:
            vision = VisionRouterService(VisionChatService(session, settings), settings)
            usage_group_id = run.response_message_id or run.id
            registry.register(ObserveImageTool(
                vision, allowed_asset_ids=allowed_asset_ids,
                run_id=run.id, usage_group_id=usage_group_id,
            ))
            registry.register(InspectImageTool(
                vision, allowed_asset_ids=allowed_asset_ids,
                run_id=run.id, usage_group_id=usage_group_id,
            ))
        planner = LangChainAgentPlanner(model, registry)
        return BoundedAgentGraph(
            planner=planner,
            registry=registry,
            stop_requested=lambda: cancellation.is_requested(user_id, run_id),
            usage_collector=usage_collector,
        )

    return factory
