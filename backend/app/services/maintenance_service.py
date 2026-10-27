"""Casos de uso de manutenção: plano periódico, ordens e preventivas automáticas."""

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from app.core.clock import Clock
from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError
from app.domain.equipment.entities import Equipment
from app.domain.equipment.status import PREVENTIVE_EXEMPT_STATUSES
from app.domain.maintenance.entities import (
    MaintenanceKind,
    MaintenanceOrder,
    MaintenanceOrderStatus,
    MaintenancePlan,
    MaintenancePriority,
)
from app.domain.maintenance.policy import (
    compute_next_due_date,
    ensure_order_can_be_opened,
    ensure_order_transition_allowed,
    equipment_status_after_order_transition,
)
from app.domain.operations.events import DomainEvent, EventType
from app.domain.shared import Page, PageRequest
from app.services.equipment_lifecycle import EquipmentLifecycle
from app.services.ports import UnitOfWork

logger = logging.getLogger(__name__)

# Chave do lock consultivo do job de preventivas (constante arbitrária e estável).
PREVENTIVE_JOB_LOCK_KEY = 7_412_026


@dataclass(frozen=True, slots=True)
class NewMaintenanceOrder:
    kind: MaintenanceKind
    priority: MaintenancePriority
    description: str
    scheduled_for: date | None


class MaintenanceService:
    def __init__(self, uow: UnitOfWork, clock: Clock, lifecycle: EquipmentLifecycle) -> None:
        self._uow = uow
        self._clock = clock
        self._lifecycle = lifecycle

    async def set_plan(
        self, equipment_id: UUID, interval_days: int, next_due_date: date | None
    ) -> MaintenancePlan:
        now, today = self._clock.now(), self._clock.today()
        async with self._uow as uow:
            equipment = await self._require_equipment(uow, equipment_id)
            current = await uow.maintenance_plans.get(equipment_id)
            plan = MaintenancePlan(
                equipment_id=equipment_id,
                interval_days=interval_days,
                next_due_date=next_due_date or compute_next_due_date(today, interval_days),
                last_done_on=current.last_done_on if current else None,
                created_at=current.created_at if current else now,
                updated_at=now,
            )
            await uow.maintenance_plans.upsert(plan)
            await self._lifecycle.refresh_and_save(uow, equipment)
            await uow.commit()
            return plan

    async def remove_plan(self, equipment_id: UUID) -> None:
        async with self._uow as uow:
            equipment = await self._require_equipment(uow, equipment_id)
            if await uow.maintenance_plans.get(equipment_id) is None:
                raise NotFoundError("O equipamento não possui plano de manutenção.")
            await uow.maintenance_plans.delete(equipment_id)
            await self._lifecycle.refresh_and_save(uow, equipment)
            await uow.commit()

    async def list_orders(
        self,
        equipment_id: UUID,
        statuses: Sequence[MaintenanceOrderStatus],
        page: PageRequest,
    ) -> Page[MaintenanceOrder]:
        async with self._uow as uow:
            await self._require_equipment(uow, equipment_id, for_update=False)
            return await uow.maintenance_orders.list_by_equipment(equipment_id, statuses, page)

    async def open_order(
        self, equipment_id: UUID, data: NewMaintenanceOrder, actor_id: UUID | None
    ) -> MaintenanceOrder:
        now, today = self._clock.now(), self._clock.today()
        if data.scheduled_for is not None and data.scheduled_for < today:
            raise BusinessRuleError("A data agendada não pode estar no passado.")
        async with self._uow as uow:
            equipment = await self._require_equipment(uow, equipment_id)
            ensure_order_can_be_opened(equipment.status)
            await self._ensure_no_open_order_of_kind(uow, equipment_id, data.kind)
            order = MaintenanceOrder(
                id=uuid.uuid4(),
                equipment_id=equipment_id,
                kind=data.kind,
                priority=data.priority,
                status=MaintenanceOrderStatus.ABERTA,
                description=data.description,
                scheduled_for=data.scheduled_for,
                opened_at=now,
                opened_by=actor_id,
            )
            await uow.maintenance_orders.add(order)
            await self._lifecycle.refresh_and_save(uow, equipment)
            await self._publish_order(uow, order)
            await uow.commit()
            return order

    async def transition_order(
        self,
        order_id: UUID,
        target: MaintenanceOrderStatus,
        resolution_notes: str | None,
        actor_id: UUID | None,
    ) -> MaintenanceOrder:
        now, today = self._clock.now(), self._clock.today()
        async with self._uow as uow:
            order = await uow.maintenance_orders.get(order_id, for_update=True)
            if order is None:
                raise NotFoundError("Ordem de manutenção não encontrada.")
            equipment = await self._require_equipment(uow, order.equipment_id)
            ensure_order_transition_allowed(order.status, target)
            self._stamp_order(order, target, resolution_notes, actor_id, now)
            await uow.maintenance_orders.update(order)

            new_status = equipment_status_after_order_transition(target, equipment.status)
            if new_status is not None and not await self._other_work_in_progress(uow, order):
                await self._lifecycle.change_status(
                    uow,
                    equipment,
                    new_status,
                    reason=f"Ordem de manutenção {target.value.replace('_', ' ')}",
                    actor_id=actor_id,
                    now=now,
                    today=today,
                )
            if target is MaintenanceOrderStatus.CONCLUIDA:
                await self._advance_plan(uow, order, today, now)
            await self._lifecycle.refresh_and_save(uow, equipment)
            await self._publish_order(uow, order)
            await uow.commit()
            logger.info(
                "Ordem de manutenção atualizada",
                extra={"order_id": str(order_id), "to_status": target.value},
            )
            return order

    async def open_due_preventive_orders(self) -> int:
        """Abre ordens preventivas para planos vencendo hoje (idempotente e com lock)."""
        now, today = self._clock.now(), self._clock.today()
        async with self._uow as uow:
            if not await uow.job_locks.try_acquire(PREVENTIVE_JOB_LOCK_KEY):
                logger.warning("Job de preventivas já em execução em outra instância")
                return 0
            due_ids = await uow.equipment.list_due_for_preventive(
                today, sorted(PREVENTIVE_EXEMPT_STATUSES)
            )
            for equipment_id in due_ids:
                equipment = await self._require_equipment(uow, equipment_id)
                plan = await uow.maintenance_plans.get(equipment_id)
                await uow.maintenance_orders.add(
                    MaintenanceOrder(
                        id=uuid.uuid4(),
                        equipment_id=equipment_id,
                        kind=MaintenanceKind.PREVENTIVA,
                        priority=MaintenancePriority.AGENDADA,
                        status=MaintenanceOrderStatus.ABERTA,
                        description="Manutenção preventiva periódica (aberta automaticamente).",
                        scheduled_for=plan.next_due_date if plan else today,
                        opened_at=now,
                        opened_by=None,
                    )
                )
                await self._lifecycle.refresh_and_save(uow, equipment)
            await uow.commit()
            return len(due_ids)

    @staticmethod
    async def _publish_order(uow: UnitOfWork, order: MaintenanceOrder) -> None:
        await uow.events.publish(
            DomainEvent(
                EventType.MAINTENANCE_ORDER_CHANGED,
                {
                    "id": str(order.id),
                    "equipment_id": str(order.equipment_id),
                    "status": order.status.value,
                    "kind": order.kind.value,
                },
            )
        )

    @staticmethod
    def _stamp_order(
        order: MaintenanceOrder,
        target: MaintenanceOrderStatus,
        notes: str | None,
        actor_id: UUID | None,
        now: datetime,
    ) -> None:
        order.status = target
        if target is MaintenanceOrderStatus.EM_ANDAMENTO:
            order.started_at = now
        elif target is MaintenanceOrderStatus.CONCLUIDA:
            order.completed_at = now
            order.closed_by = actor_id
        elif target is MaintenanceOrderStatus.CANCELADA:
            order.cancelled_at = now
            order.closed_by = actor_id
        if notes:
            order.resolution_notes = notes

    @staticmethod
    async def _other_work_in_progress(uow: UnitOfWork, order: MaintenanceOrder) -> bool:
        """Concluir uma ordem não libera o equipamento se outra ainda está em andamento."""
        if order.status is not MaintenanceOrderStatus.CONCLUIDA:
            return False
        open_orders = await uow.maintenance_orders.list_open(order.equipment_id)
        return any(
            o.id != order.id and o.status is MaintenanceOrderStatus.EM_ANDAMENTO
            for o in open_orders
        )

    @staticmethod
    async def _advance_plan(
        uow: UnitOfWork, order: MaintenanceOrder, today: date, now: datetime
    ) -> None:
        plan = await uow.maintenance_plans.get(order.equipment_id)
        if plan is None or order.kind is not MaintenanceKind.PREVENTIVA:
            return
        plan.last_done_on = today
        plan.next_due_date = compute_next_due_date(today, plan.interval_days)
        plan.updated_at = now
        await uow.maintenance_plans.upsert(plan)

    @staticmethod
    async def _ensure_no_open_order_of_kind(
        uow: UnitOfWork, equipment_id: UUID, kind: MaintenanceKind
    ) -> None:
        if any(o.kind is kind for o in await uow.maintenance_orders.list_open(equipment_id)):
            raise ConflictError(f"Já existe uma ordem {kind.value} aberta para este equipamento.")

    @staticmethod
    async def _require_equipment(
        uow: UnitOfWork, equipment_id: UUID, *, for_update: bool = True
    ) -> Equipment:
        equipment = await uow.equipment.get(equipment_id, for_update=for_update)
        if equipment is None or equipment.is_archived:
            raise NotFoundError("Equipamento não encontrado.")
        return equipment
