"""Contratos de plano e ordens de manutenção."""

from datetime import date, datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.maintenance.entities import (
    MaintenanceKind,
    MaintenanceOrderStatus,
    MaintenancePriority,
)


class MaintenancePlanInput(BaseModel):
    interval_days: int = Field(ge=1, le=3650, examples=[90])
    next_due_date: date | None = Field(
        default=None, description="Se omitida, é calculada como hoje + intervalo."
    )


class MaintenancePlanOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    interval_days: int
    next_due_date: date
    last_done_on: date | None


class MaintenanceOrderCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    kind: MaintenanceKind
    priority: MaintenancePriority
    description: str = Field(min_length=3, max_length=1000)
    scheduled_for: date | None = Field(
        default=None, description="Obrigatória para ordens com prioridade 'agendada'."
    )

    @model_validator(mode="after")
    def _scheduled_requires_date(self) -> Self:
        if self.priority is MaintenancePriority.AGENDADA and self.scheduled_for is None:
            raise ValueError("Informe a data para ordens agendadas.")
        return self


class MaintenanceOrderTransition(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    status: MaintenanceOrderStatus = Field(
        description="Novo estado da ordem: em_andamento, concluida ou cancelada."
    )
    resolution_notes: str | None = Field(default=None, max_length=1000)


class MaintenanceOrderOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    equipment_id: UUID
    kind: MaintenanceKind
    priority: MaintenancePriority
    status: MaintenanceOrderStatus
    description: str
    scheduled_for: date | None
    opened_at: datetime
    opened_by: UUID | None
    started_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    closed_by: UUID | None
    resolution_notes: str | None
