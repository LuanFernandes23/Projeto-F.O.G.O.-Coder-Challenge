"""Persistência do PROMETHEUS: modo, políticas de autonomia e trilha de decisões."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.intelligence import (
    AgentDecisionModel,
    AutonomyPolicyModel,
    PrometheusSettingsModel,
)
from app.domain.prometheus.entities import (
    ACTION_RISK,
    DEFAULT_POLICIES,
    ActionType,
    AutonomyPolicy,
    Decision,
    DecisionMode,
    DecisionStatus,
    PrometheusMode,
)


def _to_domain(m: AgentDecisionModel) -> Decision:
    return Decision(
        id=m.id,
        situation_key=m.situation_key,
        situation_kind=m.situation_kind,
        title=m.title,
        summary=m.summary,
        status=m.status,
        mode=m.mode,
        planner=m.planner,
        action_type=m.action_type,
        action_params=m.action_params,
        rationale=m.rationale,
        score=m.score,
        citations=m.citations,
        inputs=m.inputs,
        result=m.result,
        equipment_id=m.equipment_id,
        region_id=m.region_id,
        thread_id=m.thread_id,
        created_at=m.created_at,
        expires_at=m.expires_at,
        decided_at=m.decided_at,
        decided_by=m.decided_by,
        error=m.error,
        tokens=m.tokens,
    )


class SqlPrometheusRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def mode(self) -> tuple[PrometheusMode, int]:
        row = await self._session.get(PrometheusSettingsModel, 1)
        if row is None:
            return PrometheusMode.AUTONOMO, 30
        return row.mode, row.approval_ttl_minutes

    async def set_mode(
        self, mode: PrometheusMode, ttl_minutes: int, actor_id: UUID, at: datetime
    ) -> None:
        row = await self._session.get(PrometheusSettingsModel, 1)
        if row is None:
            row = PrometheusSettingsModel(id=1)
            self._session.add(row)
        row.mode = mode
        row.approval_ttl_minutes = ttl_minutes
        row.updated_by = actor_id
        row.updated_at = at
        await self._session.flush()

    async def policies(self) -> list[AutonomyPolicy]:
        rows = await self._session.execute(select(AutonomyPolicyModel))
        saved = {
            r.action_type: AutonomyPolicy(r.action_type, r.threshold, r.enabled, r.max_per_hour)
            for r in rows.scalars()
        }
        # Ações sem linha salva usam a política padrão (nunca falta política para uma ação).
        return [saved.get(p.action_type, p) for p in DEFAULT_POLICIES]

    async def save_policy(self, policy: AutonomyPolicy, actor_id: UUID, at: datetime) -> None:
        row = await self._session.get(AutonomyPolicyModel, policy.action_type)
        if row is None:
            row = AutonomyPolicyModel(
                action_type=policy.action_type, risk_class=ACTION_RISK[policy.action_type]
            )
            self._session.add(row)
        row.threshold = policy.threshold
        row.enabled = policy.enabled
        row.max_per_hour = policy.max_per_hour
        row.updated_by = actor_id
        row.updated_at = at
        await self._session.flush()

    async def add_decision(self, decision: Decision) -> None:
        self._session.add(
            AgentDecisionModel(
                id=decision.id,
                situation_key=decision.situation_key,
                situation_kind=decision.situation_kind,
                title=decision.title,
                summary=decision.summary,
                status=decision.status,
                mode=decision.mode,
                planner=decision.planner,
                action_type=decision.action_type,
                action_params=decision.action_params,
                rationale=decision.rationale,
                score=decision.score,
                citations=decision.citations,
                inputs=decision.inputs,
                result=decision.result,
                equipment_id=decision.equipment_id,
                region_id=decision.region_id,
                thread_id=decision.thread_id,
                created_at=decision.created_at,
                expires_at=decision.expires_at,
                decided_at=decision.decided_at,
                decided_by=decision.decided_by,
                error=decision.error,
                tokens=decision.tokens,
            )
        )
        await self._session.flush()

    async def update_decision(self, decision: Decision) -> None:
        await self._session.execute(
            update(AgentDecisionModel)
            .where(AgentDecisionModel.id == decision.id)
            .values(
                status=decision.status,
                mode=decision.mode,
                action_params=decision.action_params,
                result=decision.result,
                decided_at=decision.decided_at,
                decided_by=decision.decided_by,
                error=decision.error,
            )
        )

    async def get_decision(self, decision_id: UUID, *, for_update: bool = False) -> Decision | None:
        stmt = select(AgentDecisionModel).where(AgentDecisionModel.id == decision_id)
        if for_update:
            stmt = stmt.with_for_update()
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_domain(row) if row else None

    async def list_decisions(
        self, statuses: Sequence[DecisionStatus] | None, limit: int
    ) -> list[Decision]:
        stmt = select(AgentDecisionModel).order_by(AgentDecisionModel.created_at.desc())
        if statuses:
            stmt = stmt.where(AgentDecisionModel.status.in_(list(statuses)))
        rows = await self._session.execute(stmt.limit(limit))
        return [_to_domain(r) for r in rows.scalars()]

    async def recently_handled(self, situation_key: str, since: datetime) -> bool:
        stmt = select(func.count()).where(
            AgentDecisionModel.situation_key == situation_key,
            AgentDecisionModel.created_at >= since,
        )
        return bool((await self._session.execute(stmt)).scalar_one())

    async def auto_executed_since(self, action: ActionType, since: datetime) -> int:
        stmt = select(func.count()).where(
            AgentDecisionModel.action_type == action,
            AgentDecisionModel.mode == DecisionMode.AUTOMATICA,
            AgentDecisionModel.status == DecisionStatus.EXECUTADA,
            AgentDecisionModel.created_at >= since,
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def expired_pending(self, now: datetime) -> list[Decision]:
        rows = await self._session.execute(
            select(AgentDecisionModel).where(
                AgentDecisionModel.status == DecisionStatus.PENDENTE,
                AgentDecisionModel.expires_at < now,
            )
        )
        return [_to_domain(r) for r in rows.scalars()]

    async def stats(self, since: datetime) -> dict[str, Any]:
        row = (
            await self._session.execute(
                text(
                    """
                    SELECT
                      count(*) FILTER (WHERE status = 'executada' AND mode = 'automatica') AS auto,
                      count(*) FILTER (WHERE status = 'executada' AND mode = 'humana') AS approved,
                      count(*) FILTER (WHERE status = 'rejeitada') AS rejected,
                      count(*) FILTER (WHERE status = 'expirada') AS expired,
                      count(*) FILTER (WHERE status = 'pendente') AS pending,
                      count(*) FILTER (WHERE status = 'falhou') AS failed,
                      count(*) FILTER (WHERE planner = 'llm') AS by_llm,
                      coalesce(sum(tokens), 0) AS tokens
                    FROM agent_decisions WHERE created_at >= :since
                    """
                ),
                {"since": since},
            )
        ).one()
        return {k: int(v) for k, v in row._mapping.items()}
