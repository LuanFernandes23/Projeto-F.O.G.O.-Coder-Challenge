"""Ciclo de vida do equipamento: transições de situação e automações de manutenção.

Componente sem controle de transação: é usado *dentro* da unidade de trabalho de um
serviço (cadastro, mudança de situação, ordens de manutenção, job de preventivas),
garantindo que todas as consequências de um evento sejam gravadas atomicamente.
"""

import uuid
from datetime import date, datetime
from uuid import UUID

from app.core.exceptions import BusinessRuleError
from app.domain.equipment.entities import Equipment
from app.domain.equipment.status import (
    INSTALLED_STATUSES,
    MAINTENANCE_CANCELLING_STATUSES,
    STATUS_LABELS,
    EquipmentStatus,
    ensure_transition_allowed,
)
from app.domain.maintenance.entities import (
    MaintenanceKind,
    MaintenanceOrder,
    MaintenanceOrderStatus,
    MaintenancePlan,
    MaintenancePriority,
)
from app.domain.maintenance.policy import compute_maintenance_need
from app.domain.operations.events import DomainEvent, EventType
from app.services.alert_engine import AlertEngine
from app.services.ports import UnitOfWork


def new_corrective_order(
    equipment_id: UUID, reason: str, opened_by: UUID | None, now: datetime
) -> MaintenanceOrder:
    return MaintenanceOrder(
        id=uuid.uuid4(),
        equipment_id=equipment_id,
        kind=MaintenanceKind.CORRETIVA,
        priority=MaintenancePriority.IMEDIATA,
        status=MaintenanceOrderStatus.ABERTA,
        description=f"Aberta automaticamente por mau funcionamento: {reason}",
        scheduled_for=None,
        opened_at=now,
        opened_by=opened_by,
    )


class EquipmentLifecycle:
    def __init__(self, alerts: AlertEngine | None = None) -> None:
        self._alerts = alerts or AlertEngine()

    @property
    def alerts(self) -> AlertEngine:
        return self._alerts

    async def change_status(
        self,
        uow: UnitOfWork,
        equipment: Equipment,
        target: EquipmentStatus,
        *,
        reason: str,
        actor_id: UUID | None,
        now: datetime,
        today: date,
        installed_on: date | None = None,
    ) -> None:
        """Valida a transição, registra histórico e dispara as automações de manutenção.

        Altera ``equipment`` em memória; quem chama persiste com ``refresh_and_save``.
        """
        ensure_transition_allowed(equipment.status, target)
        self._apply_installation(equipment, target, installed_on, today)

        await uow.equipment_history.add(
            equipment_id=equipment.id,
            from_status=equipment.status,
            to_status=target,
            reason=reason,
            changed_by=actor_id,
            changed_at=now,
        )
        previous = equipment.status
        equipment.status = target
        equipment.updated_at = now
        equipment.updated_by = actor_id

        if target is EquipmentStatus.MAU_FUNCIONAMENTO:
            await self._ensure_corrective_order(uow, equipment, reason, actor_id, now)
        if target in MAINTENANCE_CANCELLING_STATUSES:
            await self._cancel_open_orders(uow, equipment, actor_id, now)
        await self._alerts.on_equipment_status_changed(
            uow, equipment, previous, reason=reason, now=now
        )
        await uow.events.publish(
            DomainEvent(
                EventType.EQUIPMENT_STATUS_CHANGED,
                {
                    "id": str(equipment.id),
                    "status": target.value,
                    "previous_status": previous.value,
                    "type_code": equipment.type_code,
                    "reason": reason,
                },
            )
        )

    async def refresh_and_save(self, uow: UnitOfWork, equipment: Equipment) -> None:
        """Recalcula o retrato de manutenção desnormalizado e persiste o equipamento."""
        plan = await uow.maintenance_plans.get(equipment.id)
        open_orders = await uow.maintenance_orders.list_open(equipment.id)
        self.apply_snapshot(equipment, plan, open_orders)
        equipment.version = await uow.equipment.update(equipment)

    @staticmethod
    def apply_snapshot(
        equipment: Equipment, plan: MaintenancePlan | None, open_orders: list[MaintenanceOrder]
    ) -> None:
        need, next_date = compute_maintenance_need(plan, open_orders, equipment.status)
        equipment.maintenance_need = need
        equipment.next_maintenance_date = next_date

    @staticmethod
    def _apply_installation(
        equipment: Equipment, target: EquipmentStatus, installed_on: date | None, today: date
    ) -> None:
        if target is EquipmentStatus.NAO_INSTALADO:
            equipment.installed_on = None  # recuperado de furto: será reinstalado
            return
        if target in INSTALLED_STATUSES and equipment.installed_on is None:
            chosen = installed_on or today
            if chosen > today:
                raise BusinessRuleError("A data de instalação não pode estar no futuro.")
            equipment.installed_on = chosen

    @staticmethod
    async def _ensure_corrective_order(
        uow: UnitOfWork, equipment: Equipment, reason: str, actor_id: UUID | None, now: datetime
    ) -> None:
        open_orders = await uow.maintenance_orders.list_open(equipment.id)
        if any(order.kind is MaintenanceKind.CORRETIVA for order in open_orders):
            return
        await uow.maintenance_orders.add(new_corrective_order(equipment.id, reason, actor_id, now))

    @staticmethod
    async def _cancel_open_orders(
        uow: UnitOfWork, equipment: Equipment, actor_id: UUID | None, now: datetime
    ) -> None:
        label = STATUS_LABELS[equipment.status].lower()
        for order in await uow.maintenance_orders.list_open(equipment.id):
            order.status = MaintenanceOrderStatus.CANCELADA
            order.cancelled_at = now
            order.closed_by = actor_id
            order.resolution_notes = f"Cancelada automaticamente: equipamento {label}."
            await uow.maintenance_orders.update(order)
