"""Despacho inteligente: sugere e designa o agente mais adequado para uma ocorrência."""

import logging
import uuid
from datetime import datetime
from uuid import UUID

from app.core.clock import Clock
from app.core.exceptions import ConflictError, NotFoundError
from app.domain.agents.entities import Agent, DutyStatus
from app.domain.equipment.entities import Equipment
from app.domain.equipment.status import EquipmentStatus
from app.domain.operations.alerts import AlertKind, AlertStatus, dedup_key
from app.domain.operations.dispatch import (
    DISPATCHABLE_DUTY_STATUSES,
    Dispatch,
    DispatchRecord,
    DispatchStatus,
    DispatchSuggestion,
    eligible_roles,
    ensure_agent_dispatchable,
    ensure_dispatch_transition,
    estimate_eta_minutes,
    rank_suggestions,
)
from app.domain.operations.events import DomainEvent, EventType
from app.domain.operations.telemetry import distance_m
from app.services.alert_engine import alert_event_data
from app.services.ports import UnitOfWork

logger = logging.getLogger(__name__)

_CANDIDATE_POOL = 15
_SUGGESTIONS = 5


def _occurrence_kind(equipment: Equipment) -> AlertKind:
    if equipment.status is EquipmentStatus.FURTADO:
        return AlertKind.FURTO
    return AlertKind.FALHA_EQUIPAMENTO


class DispatchService:
    def __init__(self, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def suggestions(self, equipment_id: UUID) -> list[DispatchSuggestion]:
        async with self._uow as uow:
            equipment = await self._require_equipment(uow, equipment_id)
            roles = eligible_roles(_occurrence_kind(equipment), equipment.type_code)
            candidates = await uow.operations.dispatch_candidates(
                equipment.location, roles, sorted(DISPATCHABLE_DUTY_STATUSES), _CANDIDATE_POOL
            )
        return rank_suggestions(candidates, roles, _SUGGESTIONS)

    async def create(
        self, equipment_id: UUID, agent_id: UUID, notes: str | None, actor_id: UUID
    ) -> DispatchRecord:
        now = self._clock.now()
        async with self._uow as uow:
            equipment = await self._require_equipment(uow, equipment_id)
            agent = await uow.agents.get(agent_id, for_update=True)
            if agent is None or agent.archived_at is not None:
                raise NotFoundError("Agente não encontrado.")
            kind = _occurrence_kind(equipment)
            ensure_agent_dispatchable(
                agent.is_active,
                agent.duty_status,
                agent.role,
                eligible_roles(kind, equipment.type_code),
            )
            if await uow.dispatches.active_for_agent(agent_id) is not None:
                raise ConflictError("O agente já está atendendo outra ocorrência.")

            origin = await uow.agents.current_position(agent_id) or agent.base_location
            vehicle_type = await self._vehicle_type(uow, agent)
            distance = distance_m(origin, equipment.location)
            alert = await uow.alerts.get_open_by_dedup(dedup_key(kind, equipment_id))
            dispatch = Dispatch(
                id=uuid.uuid4(),
                agent_id=agent_id,
                equipment_id=equipment_id,
                alert_id=alert.id if alert else None,
                status=DispatchStatus.DESIGNADO,
                target=equipment.location,
                origin=origin,
                created_at=now,
                created_by=actor_id,
                distance_m=round(distance, 1),
                eta_minutes=estimate_eta_minutes(distance, vehicle_type),
                notes=notes,
            )
            await uow.dispatches.add(dispatch)
            await self._set_duty(
                uow,
                agent,
                DutyStatus.EM_OCORRENCIA,
                f"Despachado para {equipment.serial_number}",
                actor_id,
                now,
            )
            if alert is not None and alert.status is AlertStatus.ABERTO:
                # Despachar alguém é reconhecer o alerta: o operador já está agindo.
                alert.status = AlertStatus.RECONHECIDO
                alert.acknowledged_at = now
                alert.acknowledged_by = actor_id
                await uow.alerts.update(alert)
                await uow.events.publish(
                    DomainEvent(EventType.ALERT_UPDATED, alert_event_data(alert))
                )
            await self._publish(uow, dispatch)
            await uow.commit()
            logger.info(
                "Agente despachado",
                extra={"dispatch_id": str(dispatch.id), "eta_minutes": dispatch.eta_minutes},
            )
            return await self._record(uow, dispatch.id)

    async def transition(
        self, dispatch_id: UUID, target: DispatchStatus, notes: str | None, actor_id: UUID
    ) -> DispatchRecord:
        now = self._clock.now()
        async with self._uow as uow:
            dispatch = await uow.dispatches.get(dispatch_id, for_update=True)
            if dispatch is None:
                raise NotFoundError("Despacho não encontrado.")
            ensure_dispatch_transition(dispatch.status, target)
            dispatch.status = target
            if notes:
                dispatch.notes = notes
            if target is DispatchStatus.A_CAMINHO:
                dispatch.departed_at = now
            elif target is DispatchStatus.NO_LOCAL:
                dispatch.arrived_at = now
            else:
                dispatch.closed_at = now
                agent = await uow.agents.get(dispatch.agent_id, for_update=True)
                if agent is not None and agent.duty_status is DutyStatus.EM_OCORRENCIA:
                    label = "concluído" if target is DispatchStatus.CONCLUIDO else "cancelado"
                    await self._set_duty(
                        uow, agent, DutyStatus.DISPONIVEL, f"Atendimento {label}", actor_id, now
                    )
            await uow.dispatches.update(dispatch)
            await self._publish(uow, dispatch)
            await uow.commit()
            return await self._record(uow, dispatch_id)

    async def search(self, active_only: bool, limit: int) -> list[DispatchRecord]:
        async with self._uow as uow:
            return await uow.dispatches.list_records(active_only, limit)

    @staticmethod
    async def _set_duty(
        uow: UnitOfWork,
        agent: Agent,
        target: DutyStatus,
        reason: str,
        actor_id: UUID | None,
        now: datetime,
    ) -> None:
        await uow.agent_history.add(
            agent_id=agent.id,
            from_status=agent.duty_status,
            to_status=target,
            reason=reason,
            changed_by=actor_id,
            changed_at=now,
        )
        agent.duty_status = target
        agent.updated_at = now
        agent.version = await uow.agents.update(agent)
        await uow.events.publish(
            DomainEvent(
                EventType.AGENT_STATUS_CHANGED,
                {"id": str(agent.id), "duty_status": target.value},
            )
        )

    @staticmethod
    async def _vehicle_type(uow: UnitOfWork, agent: Agent) -> str | None:
        if agent.assigned_vehicle_id is None:
            return None
        vehicle = await uow.equipment.get(agent.assigned_vehicle_id)
        return vehicle.type_code if vehicle else None

    @staticmethod
    async def _publish(uow: UnitOfWork, dispatch: Dispatch) -> None:
        await uow.events.publish(
            DomainEvent(
                EventType.DISPATCH_UPDATED,
                {
                    "id": str(dispatch.id),
                    "status": dispatch.status.value,
                    "agent_id": str(dispatch.agent_id),
                    "equipment_id": str(dispatch.equipment_id),
                },
            )
        )

    @staticmethod
    async def _record(uow: UnitOfWork, dispatch_id: UUID) -> DispatchRecord:
        record = await uow.dispatches.get_record(dispatch_id)
        if record is None:
            raise NotFoundError("Despacho não encontrado.")
        return record

    @staticmethod
    async def _require_equipment(uow: UnitOfWork, equipment_id: UUID) -> Equipment:
        equipment = await uow.equipment.get(equipment_id)
        if equipment is None or equipment.is_archived:
            raise NotFoundError("Equipamento não encontrado.")
        return equipment
