from datetime import date, datetime
from uuid import uuid4

import pytest

from app.core.exceptions import BusinessRuleError, InvalidStatusTransitionError
from app.domain.equipment.status import EquipmentStatus
from app.domain.maintenance.entities import (
    MaintenanceKind,
    MaintenanceNeed,
    MaintenanceOrder,
    MaintenanceOrderStatus,
    MaintenancePlan,
    MaintenancePriority,
)
from app.domain.maintenance.policy import (
    build_snapshot,
    compute_maintenance_need,
    compute_next_due_date,
    ensure_order_can_be_opened,
    ensure_order_transition_allowed,
    equipment_status_after_order_transition,
)

NOW = datetime(2026, 10, 1, 12)
EQUIPMENT_ID = uuid4()


def _plan(next_due: date) -> MaintenancePlan:
    return MaintenancePlan(EQUIPMENT_ID, 90, next_due, None, NOW, NOW)


def _order(
    priority: MaintenancePriority,
    scheduled_for: date | None = None,
    status: MaintenanceOrderStatus = MaintenanceOrderStatus.ABERTA,
) -> MaintenanceOrder:
    return MaintenanceOrder(
        uuid4(),
        EQUIPMENT_ID,
        MaintenanceKind.CORRETIVA,
        priority,
        status,
        "x",
        scheduled_for,
        NOW,
        None,
    )


def test_need_is_none_without_plan_or_orders() -> None:
    assert compute_maintenance_need(None, [], EquipmentStatus.OPERACIONAL) == (
        MaintenanceNeed.NENHUMA,
        None,
    )


def test_plan_makes_need_scheduled_with_its_due_date() -> None:
    need, next_date = compute_maintenance_need(
        _plan(date(2026, 11, 1)), [], EquipmentStatus.OPERACIONAL
    )
    assert need is MaintenanceNeed.AGENDADA
    assert next_date == date(2026, 11, 1)


def test_immediate_order_wins_over_plan() -> None:
    need, next_date = compute_maintenance_need(
        _plan(date(2026, 11, 1)),
        [_order(MaintenancePriority.IMEDIATA)],
        EquipmentStatus.MAU_FUNCIONAMENTO,
    )
    assert need is MaintenanceNeed.IMEDIATA
    assert next_date == date(2026, 11, 1)


def test_next_date_is_the_earliest_between_plan_and_scheduled_orders() -> None:
    _, next_date = compute_maintenance_need(
        _plan(date(2026, 11, 1)),
        [_order(MaintenancePriority.AGENDADA, date(2026, 10, 15))],
        EquipmentStatus.OPERACIONAL,
    )
    assert next_date == date(2026, 10, 15)


def test_closed_orders_are_ignored() -> None:
    closed = _order(MaintenancePriority.IMEDIATA, status=MaintenanceOrderStatus.CONCLUIDA)
    assert compute_maintenance_need(None, [closed], EquipmentStatus.OPERACIONAL)[0] is (
        MaintenanceNeed.NENHUMA
    )


@pytest.mark.parametrize(
    "status", [EquipmentStatus.FURTADO, EquipmentStatus.DESATIVADO, EquipmentStatus.NAO_INSTALADO]
)
def test_plan_is_suspended_when_equipment_is_not_in_the_field(status: EquipmentStatus) -> None:
    assert compute_maintenance_need(_plan(date(2026, 1, 1)), [], status) == (
        MaintenanceNeed.NENHUMA,
        None,
    )


@pytest.mark.parametrize(
    ("next_date", "overdue", "due_soon"),
    [
        (date(2026, 9, 30), True, False),
        (date(2026, 10, 1), False, True),
        (date(2026, 10, 8), False, True),
        (date(2026, 10, 9), False, False),
        (None, False, False),
    ],
)
def test_snapshot_flags_relative_to_today(
    next_date: date | None, overdue: bool, due_soon: bool
) -> None:
    snapshot = build_snapshot(MaintenanceNeed.AGENDADA, next_date, date(2026, 10, 1), 7)
    assert (snapshot.is_overdue, snapshot.is_due_soon) == (overdue, due_soon)


def test_next_due_date_adds_interval() -> None:
    assert compute_next_due_date(date(2026, 1, 31), 30) == date(2026, 3, 2)


def test_next_due_date_rejects_non_positive_interval() -> None:
    with pytest.raises(BusinessRuleError):
        compute_next_due_date(date(2026, 1, 1), 0)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (MaintenanceOrderStatus.ABERTA, MaintenanceOrderStatus.CONCLUIDA),
        (MaintenanceOrderStatus.CONCLUIDA, MaintenanceOrderStatus.EM_ANDAMENTO),
        (MaintenanceOrderStatus.CANCELADA, MaintenanceOrderStatus.ABERTA),
    ],
)
def test_invalid_order_transitions(
    current: MaintenanceOrderStatus, target: MaintenanceOrderStatus
) -> None:
    with pytest.raises(InvalidStatusTransitionError):
        ensure_order_transition_allowed(current, target)


def test_starting_an_order_puts_equipment_in_maintenance() -> None:
    assert (
        equipment_status_after_order_transition(
            MaintenanceOrderStatus.EM_ANDAMENTO, EquipmentStatus.MAU_FUNCIONAMENTO
        )
        is EquipmentStatus.EM_MANUTENCAO
    )


def test_completing_an_order_returns_equipment_to_operation() -> None:
    assert (
        equipment_status_after_order_transition(
            MaintenanceOrderStatus.CONCLUIDA, EquipmentStatus.EM_MANUTENCAO
        )
        is EquipmentStatus.OPERACIONAL
    )


def test_cancelling_an_order_does_not_change_equipment_status() -> None:
    assert (
        equipment_status_after_order_transition(
            MaintenanceOrderStatus.CANCELADA, EquipmentStatus.EM_MANUTENCAO
        )
        is None
    )


def test_cannot_open_order_for_stolen_equipment() -> None:
    with pytest.raises(BusinessRuleError):
        ensure_order_can_be_opened(EquipmentStatus.FURTADO)
