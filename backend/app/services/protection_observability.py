"""Redis 保护功能的故障矩阵、去重日志和进程内状态快照。"""

import logging
from dataclasses import dataclass
from threading import Lock

from fastapi import Request

from app.infrastructure.redis import RedisHealthStatus

logger = logging.getLogger(__name__)

RATE_LIMIT = "rate_limit"
UPLOAD_CONCURRENCY = "upload_concurrency"
GENERATION_LOCK = "generation_lock"
IDEMPOTENCY = "idempotency"

FALLBACK_POLICY = "local_fallback"
FAIL_CLOSED_POLICY = "fail_closed"


@dataclass(frozen=True)
class ProtectionSnapshot:
    policy: str
    mode: str
    success_events: int
    failure_events: int
    recovery_events: int
    last_error_type: str | None


@dataclass
class _MutableProtectionState:
    policy: str
    mode: str
    success_events: int = 0
    failure_events: int = 0
    recovery_events: int = 0
    last_error_type: str | None = None


class ProtectionObservability:
    """记录短期运行状态；不保存用户、请求或业务正文。"""

    def __init__(self, *, redis_configured: bool) -> None:
        fallback_mode = "redis" if redis_configured else "local_fallback"
        strict_mode = "available" if redis_configured else "unavailable"
        self._states = {
            RATE_LIMIT: _MutableProtectionState(FALLBACK_POLICY, fallback_mode),
            UPLOAD_CONCURRENCY: _MutableProtectionState(
                FALLBACK_POLICY, fallback_mode
            ),
            GENERATION_LOCK: _MutableProtectionState(FAIL_CLOSED_POLICY, strict_mode),
            IDEMPOTENCY: _MutableProtectionState(FAIL_CLOSED_POLICY, strict_mode),
        }
        self._lock = Lock()

    def record_success(self, feature: str) -> None:
        with self._lock:
            state = self._states[feature]
            target_mode = (
                "redis" if state.policy == FALLBACK_POLICY else "available"
            )
            recovered = state.mode != target_mode
            state.mode = target_mode
            state.success_events += 1
            state.last_error_type = None
            if recovered:
                state.recovery_events += 1
            policy = state.policy
        if recovered:
            logger.info(
                "Redis protection recovered",
                extra={
                    "protection_feature": feature,
                    "protection_policy": policy,
                    "protection_mode": target_mode,
                },
            )

    def record_failure(self, feature: str, error_type: str) -> None:
        with self._lock:
            state = self._states[feature]
            target_mode = (
                "local_fallback"
                if state.policy == FALLBACK_POLICY
                else "unavailable"
            )
            transitioned = state.mode != target_mode
            state.mode = target_mode
            state.failure_events += 1
            state.last_error_type = error_type
            policy = state.policy
        if transitioned:
            logger.warning(
                "Redis protection degraded",
                extra={
                    "protection_feature": feature,
                    "protection_policy": policy,
                    "protection_mode": target_mode,
                    "protection_error_type": error_type,
                },
            )

    def snapshot(
        self, redis_status: RedisHealthStatus
    ) -> dict[str, ProtectionSnapshot]:
        with self._lock:
            snapshots = {
                feature: ProtectionSnapshot(
                    policy=state.policy,
                    mode=state.mode,
                    success_events=state.success_events,
                    failure_events=state.failure_events,
                    recovery_events=state.recovery_events,
                    last_error_type=state.last_error_type,
                )
                for feature, state in self._states.items()
            }
        if redis_status is RedisHealthStatus.OK:
            return snapshots
        return {
            feature: ProtectionSnapshot(
                policy=item.policy,
                mode=(
                    "local_fallback"
                    if item.policy == FALLBACK_POLICY
                    else "unavailable"
                ),
                success_events=item.success_events,
                failure_events=item.failure_events,
                recovery_events=item.recovery_events,
                last_error_type=item.last_error_type,
            )
            for feature, item in snapshots.items()
        }


def get_protection_observability(request: Request) -> ProtectionObservability:
    return request.app.state.protection_observability
