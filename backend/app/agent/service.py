"""Casos de uso do PROMETHEUS: ciclo de percepção-decisão, aprovação humana e governança."""

import logging
import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from typing import Any
from uuid import UUID

from langgraph.types import Command

from app.agent.graph import PrometheusAgent, situation_to_dict
from app.agent.situations import build_situations
from app.core.clock import Clock
from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError
from app.domain.operations.events import DomainEvent, EventType
from app.domain.prometheus.entities import (
    AutonomyPolicy,
    Decision,
    DecisionStatus,
    PrometheusMode,
    SituationKind,
)
from app.services.ports import UnitOfWork
from app.services.prediction_service import SNAPSHOT_ANOMALIES, SNAPSHOT_CITY

logger = logging.getLogger(__name__)

PROMETHEUS_LOCK_KEY = 7_412_033
MAX_SITUATIONS_PER_CYCLE = 6
# Janela em que a mesma situação não gera nova decisão (evita repetir pedidos).
REPEAT_WINDOW = {
    SituationKind.PRECURSOR_FALHA: timedelta(minutes=45),
    SituationKind.PICO_REGIONAL: timedelta(hours=3),
    SituationKind.RISCO_EQUIPAMENTO: timedelta(hours=24),
    SituationKind.DEFICIT_EFETIVO: timedelta(hours=4),
}
PRIORITY = {
    SituationKind.PRECURSOR_FALHA: 0,
    SituationKind.PICO_REGIONAL: 1,
    SituationKind.DEFICIT_EFETIVO: 2,
    SituationKind.RISCO_EQUIPAMENTO: 3,
}


class PrometheusService:
    def __init__(
        self, uow_factory: Callable[[], UnitOfWork], clock: Clock, agent: PrometheusAgent
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._agent = agent

    async def cycle(self) -> dict[str, Any]:
        """Percebe situações novas e decide cada uma (executa ou pede aprovação)."""
        now = self._clock.now()
        async with self._uow_factory() as uow:
            if not await uow.job_locks.try_acquire(PROMETHEUS_LOCK_KEY):
                return {"skipped": True}
            mode, _ = await uow.prometheus.mode()
            if mode is PrometheusMode.PAUSADO:
                return {"paused": True}
            city = await uow.predictions.get_snapshot(SNAPSHOT_CITY)
            anomalies = await uow.predictions.get_snapshot(SNAPSHOT_ANOMALIES)
            regions = await uow.predictions.region_codes()
            situations = build_situations(
                city.payload if city else None,
                anomalies.payload if anomalies else None,
                {code: rid for rid, code, _ in regions},
                {code: name for _, code, name in regions},
            )
            # Equipamento que já tem OS preventiva aberta já está sendo tratado.
            handled = await uow.predictions.equipment_with_open_preventive()
            situations = [
                s
                for s in situations
                if not (
                    s.kind in (SituationKind.PRECURSOR_FALHA, SituationKind.RISCO_EQUIPAMENTO)
                    and s.equipment_id in handled
                )
            ]
            fresh = []
            for situation in sorted(situations, key=lambda s: PRIORITY[s.kind]):
                window = REPEAT_WINDOW[situation.kind]
                if not await uow.prometheus.recently_handled(situation.key, now - window):
                    fresh.append(situation)
            await uow.commit()  # libera o lock de transação; o ciclo é curto e sequencial
        outcomes: dict[str, int] = {}
        for situation in fresh[:MAX_SITUATIONS_PER_CYCLE]:
            thread_id = f"prometheus-{uuid.uuid4()}"
            payload = {**situation_to_dict(situation), "thread_id": thread_id}
            try:
                state = await self._agent.graph.ainvoke(
                    {"situation": payload}, {"configurable": {"thread_id": thread_id}}
                )
            except Exception:
                logger.exception("Falha ao decidir situação", extra={"key": situation.key})
                outcomes["erro"] = outcomes.get("erro", 0) + 1
                continue
            label = (
                "aguardando_aprovacao"
                if "__interrupt__" in state
                else ("executada" if (state.get("outcome") or {}).get("ok") else "sem_acao")
            )
            outcomes[label] = outcomes.get(label, 0) + 1
        return {"situations": len(situations), "new": len(fresh), **outcomes}

    async def decide(
        self,
        decision_id: UUID,
        *,
        approved: bool,
        user_id: UUID,
        note: str | None,
    ) -> Decision:
        """Retoma o grafo pausado com a resposta humana (Command(resume=...))."""
        async with self._uow_factory() as uow:
            decision = await uow.prometheus.get_decision(decision_id, for_update=True)
            if decision is None:
                raise NotFoundError("Decisão não encontrada.")
            if decision.status is not DecisionStatus.PENDENTE:
                raise ConflictError(f"Esta decisão já está '{decision.status.value}'.")
            if decision.expires_at and decision.expires_at < self._clock.now():
                raise BusinessRuleError("O pedido de aprovação expirou.")
        answer = {"approved": approved, "user_id": str(user_id), "note": note}
        await self._agent.graph.ainvoke(
            Command(resume=answer), {"configurable": {"thread_id": decision.thread_id}}
        )
        async with self._uow_factory() as uow:
            updated = await uow.prometheus.get_decision(decision_id)
        if updated is None:
            raise NotFoundError("Decisão não encontrada.")
        return updated

    async def expire_pending(self) -> int:
        now = self._clock.now()
        async with self._uow_factory() as uow:
            expired = await uow.prometheus.expired_pending(now)
            for decision in expired:
                await uow.prometheus.update_decision(
                    replace(
                        decision,
                        status=DecisionStatus.EXPIRADA,
                        decided_at=now,
                        error="Sem resposta humana no prazo; nenhuma ação executada.",
                    )
                )
                await uow.events.publish(
                    DomainEvent(
                        EventType.PROMETHEUS_DECISION,
                        {"id": str(decision.id), "status": DecisionStatus.EXPIRADA.value},
                    )
                )
            await uow.commit()
        return len(expired)

    # ---- consulta e governança -----------------------------------------------------------------

    async def decisions(self, statuses: list[DecisionStatus] | None, limit: int) -> list[Decision]:
        async with self._uow_factory() as uow:
            return await uow.prometheus.list_decisions(statuses, limit)

    async def get(self, decision_id: UUID) -> Decision:
        async with self._uow_factory() as uow:
            decision = await uow.prometheus.get_decision(decision_id)
        if decision is None:
            raise NotFoundError("Decisão não encontrada.")
        return decision

    async def stats(self, hours: int) -> dict[str, Any]:
        since = self._clock.now() - timedelta(hours=hours)
        async with self._uow_factory() as uow:
            decisions = await uow.prometheus.stats(since)
            averted = await uow.predictions.averted_counts(since)
            quality = await uow.predictions.get_snapshot(SNAPSHOT_ANOMALIES)
            mode, ttl = await uow.prometheus.mode()
        return {
            "hours": hours,
            "mode": mode.value,
            "approval_ttl_minutes": ttl,
            "decisions": decisions,
            "averted": averted,
            "detection_quality": (quality.payload.get("quality") if quality else None),
        }

    async def settings(self) -> tuple[PrometheusMode, int, list[AutonomyPolicy]]:
        async with self._uow_factory() as uow:
            mode, ttl = await uow.prometheus.mode()
            return mode, ttl, await uow.prometheus.policies()

    async def update_settings(
        self,
        mode: PrometheusMode,
        ttl_minutes: int,
        policies: list[AutonomyPolicy],
        actor_id: UUID,
    ) -> None:
        now = self._clock.now()
        async with self._uow_factory() as uow:
            await uow.prometheus.set_mode(mode, ttl_minutes, actor_id, now)
            for policy in policies:
                await uow.prometheus.save_policy(policy, actor_id, now)
            await uow.commit()
        logger.info(
            "Governança do PROMETHEUS alterada",
            extra={"actor_id": str(actor_id), "mode": mode.value},
        )
