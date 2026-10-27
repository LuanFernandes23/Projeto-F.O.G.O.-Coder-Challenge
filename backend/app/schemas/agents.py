"""Contratos de agentes de campo."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.agents.entities import (
    DUTY_STATUS_LABELS,
    ON_DUTY_STATUSES,
    AgentRecord,
    AgentRole,
    AgentStatusChange,
    DutyStatus,
)
from app.schemas.location import AddressSchema, GeoPointSchema
from app.schemas.reference import OrganizationSummaryOutput, RegionSummaryOutput


class AgentCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    full_name: str = Field(min_length=3, max_length=120, examples=["Ana Paula Ribeiro"])
    registration_number: str = Field(
        min_length=1, max_length=30, description="Matrícula funcional.", examples=["GCM-0457"]
    )
    role: AgentRole
    organization_id: UUID
    duty_status: DutyStatus = DutyStatus.FORA_DE_SERVICO
    base_address: AddressSchema = Field(description="Endereço da base de lotação.")
    base_location: GeoPointSchema
    assigned_vehicle_id: UUID | None = Field(
        default=None, description="Moto ou viatura do mesmo órgão."
    )


class AgentUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    version: int = Field(ge=1)
    full_name: str | None = Field(default=None, min_length=3, max_length=120)
    registration_number: str | None = Field(default=None, min_length=1, max_length=30)
    role: AgentRole | None = None
    organization_id: UUID | None = None
    is_active: bool | None = None
    base_address: AddressSchema | None = None
    base_location: GeoPointSchema | None = None
    assigned_vehicle_id: UUID | None = None
    unassign_vehicle: bool = Field(default=False, description="true para remover a viatura.")


class AgentStatusChangeInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    to_status: DutyStatus
    reason: str | None = Field(default=None, max_length=500)


class VehicleSummaryOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    type_code: str
    serial_number: str
    model: str
    plate: str | None


class AgentOutput(BaseModel):
    id: UUID
    full_name: str
    registration_number: str
    role: AgentRole
    organization: OrganizationSummaryOutput
    duty_status: DutyStatus
    duty_status_label: str
    on_duty: bool
    is_active: bool
    base_address: AddressSchema
    base_location: GeoPointSchema
    region: RegionSummaryOutput | None
    vehicle: VehicleSummaryOutput | None
    version: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, record: AgentRecord) -> "AgentOutput":
        agent = record.agent
        return cls(
            id=agent.id,
            full_name=agent.full_name,
            registration_number=agent.registration_number,
            role=agent.role,
            organization=OrganizationSummaryOutput.model_validate(record.organization),
            duty_status=agent.duty_status,
            duty_status_label=DUTY_STATUS_LABELS[agent.duty_status],
            on_duty=agent.duty_status in ON_DUTY_STATUSES,
            is_active=agent.is_active,
            base_address=AddressSchema.from_domain(agent.base_address),
            base_location=GeoPointSchema.from_domain(agent.base_location),
            region=RegionSummaryOutput.model_validate(record.region) if record.region else None,
            vehicle=VehicleSummaryOutput.model_validate(record.vehicle) if record.vehicle else None,
            version=agent.version,
            created_at=agent.created_at,
            updated_at=agent.updated_at,
        )


class AgentStatusChangeOutput(BaseModel):
    id: int
    from_status: DutyStatus | None
    to_status: DutyStatus
    to_status_label: str
    reason: str | None
    changed_by: UUID | None
    changed_by_name: str | None
    changed_at: datetime

    @classmethod
    def from_domain(cls, change: AgentStatusChange) -> "AgentStatusChangeOutput":
        return cls(
            id=change.id,
            from_status=change.from_status,
            to_status=change.to_status,
            to_status_label=DUTY_STATUS_LABELS[change.to_status],
            reason=change.reason,
            changed_by=change.changed_by,
            changed_by_name=change.changed_by_name,
            changed_at=change.changed_at,
        )
