"""Legacy stateless RAG endpoints with the same quota and usage guarantees."""

import logging

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.modules.rag.adapters import RAG_SYSTEM_PROMPT
from app.modules.rag.ports import ModelUsage, TokenMeasurement
from app.modules.usage.contracts import QuotaPolicyMode
from app.modules.usage.estimator import (
    ConservativeQuotaReservationEstimator,
    QuotaReservationTooLargeError,
    RagReservationInput,
)
from app.modules.usage.quota_service import build_quota_gate
from app.modules.usage.service import ModelUsageRecorder
from app.services.rag_service import RagService

logger = logging.getLogger(__name__)


class DirectChatApplicationService:
    """Keep legacy endpoints usable without bypassing accounting controls."""

    def __init__(
        self,
        session: Session,
        rag_service: RagService,
        settings: Settings,
        *,
        quota_gate=None,
        usage_recorder: ModelUsageRecorder | None = None,
    ) -> None:
        self.session = session
        self.rag_service = rag_service
        self.settings = settings
        self.quota_gate = quota_gate or build_quota_gate(session, settings)
        self.usage_recorder = usage_recorder or ModelUsageRecorder(session, settings)
        self.estimator = ConservativeQuotaReservationEstimator(
            rag_min_tokens=settings.quota_rag_reserve_tokens,
        )

    def ask(
        self,
        *,
        user_id: str,
        request_id: str,
        question: str,
        top_k: int,
        model_id: str | None,
    ):
        rag_service = self._select_rag(model_id)
        reservation = self._reserve(user_id, request_id, question, top_k)
        finalized = reservation is None
        try:
            ask_with_usage = getattr(rag_service, "ask_with_usage", None)
            if callable(ask_with_usage):
                answer, sources, usage = ask_with_usage(question, top_k)
            else:
                answer, sources = rag_service.ask(question, top_k)
                usage = ModelUsage.unknown()
            settlement = self._record(
                rag_service,
                request_id=request_id,
                user_id=user_id,
                usage=usage,
                status="completed",
            )
            if reservation is not None:
                self.quota_gate.settle(reservation.id, settlement)
                finalized = True
            return answer, sources
        except Exception:
            if not finalized:
                settlement = self._record(
                    rag_service,
                    request_id=request_id,
                    user_id=user_id,
                    usage=ModelUsage.unknown(),
                    status="failed",
                )
                self.quota_gate.settle(reservation.id, settlement)
                finalized = True
            raise
        finally:
            if not finalized:
                self.quota_gate.release(reservation.id)

    def stream(
        self,
        *,
        user_id: str,
        request_id: str,
        question: str,
        top_k: int,
        model_id: str | None,
    ):
        rag_service = self._select_rag(model_id)
        reservation = self._reserve(user_id, request_id, question, top_k)
        usage = ModelUsage.unknown()
        finalized = reservation is None
        try:
            for item in rag_service.stream_ask(question, top_k):
                if item["event"] == "model_usage":
                    data = item["data"]
                    usage = ModelUsage(
                        input_tokens=data.get("input_tokens"),
                        output_tokens=data.get("output_tokens"),
                        total_tokens=data.get("total_tokens"),
                        measurement=TokenMeasurement(data["measurement"]),
                    )
                    continue
                yield item
            settlement = self._record(
                rag_service,
                request_id=request_id,
                user_id=user_id,
                usage=usage,
                status="completed",
            )
            if reservation is not None:
                self.quota_gate.settle(reservation.id, settlement)
                finalized = True
        except GeneratorExit:
            settlement = self._record(
                rag_service,
                request_id=request_id,
                user_id=user_id,
                usage=usage,
                status="cancelled",
            )
            if reservation is not None:
                self.quota_gate.settle(reservation.id, settlement)
                finalized = True
            raise
        except Exception:
            settlement = self._record(
                rag_service,
                request_id=request_id,
                user_id=user_id,
                usage=usage,
                status="failed",
            )
            if reservation is not None:
                self.quota_gate.settle(reservation.id, settlement)
                finalized = True
            raise
        finally:
            if not finalized:
                self.quota_gate.release(reservation.id)

    def _select_rag(self, model_id: str | None):
        selector = getattr(self.rag_service, "for_model", None)
        return selector(model_id) if callable(selector) else self.rag_service

    def _reserve(self, user_id: str, request_id: str, question: str, top_k: int):
        mode = getattr(self.quota_gate, "policy_mode", QuotaPolicyMode.ENFORCE)
        if mode is QuotaPolicyMode.OFF:
            return self.quota_gate.reserve(
                user_id, "rag", f"direct-rag:{request_id}", 0, request_id
            )
        estimate = self.estimator.estimate_rag(
            RagReservationInput(
                system_prompt=RAG_SYSTEM_PROMPT,
                question=question,
                history=(),
                top_k=top_k,
                chunk_char_budget=self.settings.chunk_size,
                source_wrapper_tokens=self.settings.quota_rag_source_wrapper_tokens,
                max_output_tokens=self.settings.quota_rag_max_output_tokens,
            )
        )
        if estimate.exceeds_policy_limit and mode is QuotaPolicyMode.ENFORCE:
            raise QuotaReservationTooLargeError()
        return self.quota_gate.reserve(
            user_id,
            "rag",
            f"direct-rag:{request_id}",
            estimate.requested_tokens,
            request_id,
            estimated_input_tokens=estimate.estimated_input_tokens,
            estimated_output_tokens=estimate.estimated_output_tokens,
            input_price_per_million_tokens_cny=(
                self.settings.chat_input_price_per_million_tokens_cny
            ),
            output_price_per_million_tokens_cny=(
                self.settings.chat_output_price_per_million_tokens_cny
            ),
        )

    def _record(
        self,
        rag_service,
        *,
        request_id: str,
        user_id: str,
        usage: ModelUsage,
        status: str,
    ) -> ModelUsage:
        usages = [usage]
        drain = getattr(rag_service, "drain_auxiliary_model_usages", None)
        for index, item in enumerate(drain() if callable(drain) else [], start=1):
            auxiliary_usage = item.get("usage")
            if not isinstance(auxiliary_usage, ModelUsage):
                auxiliary_usage = ModelUsage.unknown()
            usages.append(auxiliary_usage)
            self._record_one(
                call_id=f"direct-rag:{request_id}:aux:{index}",
                request_id=request_id,
                user_id=user_id,
                surface=str(item.get("surface") or "rag_aux"),
                operation=str(item.get("operation") or "auxiliary"),
                model_name=str(item.get("model_name") or "unknown"),
                usage=auxiliary_usage,
                status=str(item.get("status") or status),
                input_price=item.get("input_price_per_million_tokens_cny"),
                output_price=item.get("output_price_per_million_tokens_cny"),
            )
        self._record_one(
            call_id=f"direct-rag:{request_id}:answer",
            request_id=request_id,
            user_id=user_id,
            surface="rag",
            operation="answer",
            model_name=getattr(rag_service, "model_name", "unknown"),
            usage=usage,
            status=status,
        )
        if any(item.measurement is TokenMeasurement.UNKNOWN for item in usages):
            return ModelUsage.unknown()
        actual = [item for item in usages if item.measurement is TokenMeasurement.ACTUAL]
        if actual:
            return ModelUsage.actual(
                sum(int(item.input_tokens or 0) for item in actual),
                sum(int(item.output_tokens or 0) for item in actual),
            )
        return ModelUsage.not_applicable()

    def _record_one(self, **kwargs) -> None:
        input_price = kwargs.pop("input_price", None)
        output_price = kwargs.pop("output_price", None)
        try:
            self.usage_recorder.record(
                **kwargs,
                usage_group_id=kwargs["request_id"],
                input_price_per_million_tokens_cny=input_price,
                output_price_per_million_tokens_cny=output_price,
            )
        except Exception as exc:
            self.session.rollback()
            logger.warning(
                "model_usage_record_failed surface=%s error_type=%s",
                kwargs.get("surface"),
                type(exc).__name__,
            )
