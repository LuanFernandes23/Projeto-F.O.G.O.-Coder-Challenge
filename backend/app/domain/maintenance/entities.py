"""Plano de manutenção, ordens de manutenção e o retrato derivado da necessidade."""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID


class MaintenanceNeed(StrEnum):
    IMEDIATA = "imediata"
    AGENDADA = "agendada"
    NENHUMA = "nenhuma"


class MaintenanceKind(StrEnum):
    CORRETIVA = "corretiva"
    PREVENTIVA = "preventiva"


class MaintenancePriority(StrEnum):
    IMEDIATA = "imediata"
    AGENDADA = "agendada"


class MaintenanceOrderStatus(StrEnum):
    ABERTA = "aberta"
    EM_ANDAMENTO = "em_andamento"
    CONCLUIDA = "concluida"
    CANCELADA = "cancelada"


OPEN_ORDER_STATUSES = frozenset(
    {MaintenanceOrderStatus.ABERTA, MaintenanceOrderStatus.EM_ANDAMENTO}
)


@dataclass(slots=True)
class MaintenancePlan:
    """Manutenção periódica: a cada ``interval_days`` dias a partir da última realizada."""

    equipment_id: UUID
    interval_days: int
    next_due_date: date
    last_done_on: date | None
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class MaintenanceOrder:
    id: UUID
    equipment_id: UUID
    kind: MaintenanceKind
    priority: MaintenancePriority
    status: MaintenanceOrderStatus
    description: str
    scheduled_for: date | None
    opened_at: datetime
    opened_by: UUID | None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None
    closed_by: UUID | None = None
    resolution_notes: str | None = None

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_ORDER_STATUSES


@dataclass(frozen=True, slots=True)
class MaintenanceSnapshot:
    need: MaintenanceNeed
    next_maintenance_date: date | None
    is_overdue: bool
    is_due_soon: bool
