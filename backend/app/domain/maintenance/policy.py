"""Regras puras de manutenção: necessidade, prazos e ciclo de vida das ordens."""

from collections.abc import Iterable, Mapping
from datetime import date, timedelta

from app.core.exceptions import BusinessRuleError, InvalidStatusTransitionError
from app.domain.equipment.status import PREVENTIVE_EXEMPT_STATUSES, EquipmentStatus
from app.domain.maintenance.entities import (
    MaintenanceNeed,
    MaintenanceOrder,
    MaintenanceOrderStatus,
    MaintenancePlan,
    MaintenancePriority,
    MaintenanceSnapshot,
)

ORDER_TRANSITIONS: Mapping[MaintenanceOrderStatus, frozenset[MaintenanceOrderStatus]] = {
    MaintenanceOrderStatus.ABERTA: frozenset(
        {MaintenanceOrderStatus.EM_ANDAMENTO, MaintenanceOrderStatus.CANCELADA}
    ),
    MaintenanceOrderStatus.EM_ANDAMENTO: frozenset(
        {MaintenanceOrderStatus.CONCLUIDA, MaintenanceOrderStatus.CANCELADA}
    ),
    MaintenanceOrderStatus.CONCLUIDA: frozenset(),
    MaintenanceOrderStatus.CANCELADA: frozenset(),
}


def compute_next_due_date(reference: date, interval_days: int) -> date:
    if interval_days <= 0:
        raise BusinessRuleError("O intervalo da manutenção periódica deve ser positivo.")
    return reference + timedelta(days=interval_days)


def compute_maintenance_need(
    plan: MaintenancePlan | None,
    open_orders: Iterable[MaintenanceOrder],
    equipment_status: EquipmentStatus,
) -> tuple[MaintenanceNeed, date | None]:
    """Necessidade consolidada e a próxima data de manutenção conhecida.

    Imediata vence agendada: um defeito aberto importa mais do que a próxima preventiva.
    O plano periódico fica suspenso enquanto o equipamento não está em campo (não
    instalado, desativado ou furtado): um item furtado não tem "preventiva vencida".
    """
    orders = [order for order in open_orders if order.is_open]
    candidate_dates = [o.scheduled_for for o in orders if o.scheduled_for is not None]
    if plan is not None and equipment_status not in PREVENTIVE_EXEMPT_STATUSES:
        candidate_dates.append(plan.next_due_date)
    next_date = min(candidate_dates, default=None)

    if any(order.priority is MaintenancePriority.IMEDIATA for order in orders):
        return MaintenanceNeed.IMEDIATA, next_date
    if next_date is not None or orders:
        return MaintenanceNeed.AGENDADA, next_date
    return MaintenanceNeed.NENHUMA, None


def build_snapshot(
    need: MaintenanceNeed, next_date: date | None, today: date, due_soon_days: int
) -> MaintenanceSnapshot:
    is_overdue = next_date is not None and next_date < today
    is_due_soon = next_date is not None and today <= next_date <= today + timedelta(
        days=due_soon_days
    )
    return MaintenanceSnapshot(need, next_date, is_overdue, is_due_soon)


def ensure_order_transition_allowed(
    current: MaintenanceOrderStatus, target: MaintenanceOrderStatus
) -> None:
    if target in ORDER_TRANSITIONS[current]:
        return
    raise InvalidStatusTransitionError(
        f"A ordem de manutenção não pode ir de '{current.value}' para '{target.value}'.",
        extra={
            "current_status": current.value,
            "allowed_transitions": sorted(s.value for s in ORDER_TRANSITIONS[current]),
        },
    )


def equipment_status_after_order_transition(
    order_target: MaintenanceOrderStatus, equipment_status: EquipmentStatus
) -> EquipmentStatus | None:
    """Efeito de uma ordem sobre a situação do equipamento (``None`` = sem efeito).

    Iniciar o serviço coloca o equipamento "em manutenção"; concluir devolve a
    "operacional" se ele estava em manutenção. Cancelar não altera a situação.
    """
    if order_target is MaintenanceOrderStatus.EM_ANDAMENTO and equipment_status in {
        EquipmentStatus.OPERACIONAL,
        EquipmentStatus.MAU_FUNCIONAMENTO,
        EquipmentStatus.DESATIVADO,
    }:
        return EquipmentStatus.EM_MANUTENCAO
    if (
        order_target is MaintenanceOrderStatus.CONCLUIDA
        and equipment_status is EquipmentStatus.EM_MANUTENCAO
    ):
        return EquipmentStatus.OPERACIONAL
    return None


def ensure_order_can_be_opened(equipment_status: EquipmentStatus) -> None:
    if equipment_status in {EquipmentStatus.FURTADO, EquipmentStatus.NAO_INSTALADO}:
        raise BusinessRuleError(
            "Não é possível abrir ordem de manutenção para equipamento furtado ou não instalado."
        )
