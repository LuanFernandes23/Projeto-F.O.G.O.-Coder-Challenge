"""Contratos de entrada e saída de equipamentos, situação e histórico."""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.equipment.entities import EquipmentStatusChange, EquipmentView
from app.domain.equipment.status import STATUS_LABELS, EquipmentStatus
from app.domain.maintenance.entities import MaintenanceNeed
from app.schemas.location import AddressSchema, GeoPointSchema
from app.schemas.maintenance import MaintenancePlanInput, MaintenancePlanOutput
from app.schemas.reference import (
    EquipmentTypeSummaryOutput,
    OrganizationSummaryOutput,
    RegionSummaryOutput,
)


class EquipmentCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    type_code: str = Field(examples=["camera"])
    serial_number: str = Field(min_length=1, max_length=80, examples=["HKV-2026-000123"])
    brand: str = Field(min_length=1, max_length=80, examples=["Hikvision"])
    model: str = Field(min_length=1, max_length=80, examples=["DS-2CD2T47G2"])
    organization_id: UUID
    status: EquipmentStatus = Field(
        default=EquipmentStatus.NAO_INSTALADO,
        description="Inicial: nao_instalado, operacional, mau_funcionamento ou desativado.",
    )
    installed_on: date | None = Field(
        default=None, description="Obrigatória quando o equipamento já está instalado."
    )
    address: AddressSchema
    location: GeoPointSchema = Field(
        description="Ponto de instalação (ou da base, para equipamentos móveis)."
    )
    attributes: dict[str, Any] = Field(
        default_factory=dict,
        description="Características específicas do tipo (ver JSON Schema em /equipment-types).",
    )
    maintenance_plan: MaintenancePlanInput | None = Field(
        default=None, description="Plano de manutenção periódica opcional."
    )


class EquipmentUpdate(BaseModel):
    """Atualização parcial. Situação muda apenas por ``/status-changes`` (gera histórico)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    version: int = Field(ge=1, description="Versão lida; protege contra edição concorrente.")
    serial_number: str | None = Field(default=None, min_length=1, max_length=80)
    brand: str | None = Field(default=None, min_length=1, max_length=80)
    model: str | None = Field(default=None, min_length=1, max_length=80)
    organization_id: UUID | None = None
    installed_on: date | None = None
    address: AddressSchema | None = None
    location: GeoPointSchema | None = None
    attributes: dict[str, Any] | None = None


class StatusChangeInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    to_status: EquipmentStatus
    reason: str = Field(min_length=3, max_length=500, examples=["Lente danificada por vandalismo"])
    installed_on: date | None = Field(
        default=None, description="Data de instalação, ao instalar um equipamento pela 1ª vez."
    )


class MaintenanceSummaryOutput(BaseModel):
    need: MaintenanceNeed
    next_maintenance_date: date | None
    is_overdue: bool
    is_due_soon: bool
    plan: MaintenancePlanOutput | None


class EquipmentOutput(BaseModel):
    id: UUID
    type: EquipmentTypeSummaryOutput
    serial_number: str
    brand: str
    model: str
    organization: OrganizationSummaryOutput
    status: EquipmentStatus
    status_label: str
    installed_on: date | None
    address: AddressSchema
    location: GeoPointSchema
    region: RegionSummaryOutput | None
    attributes: dict[str, Any]
    maintenance: MaintenanceSummaryOutput
    distance_m: float | None = Field(
        default=None, description="Distância até o ponto da busca por raio."
    )
    version: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_view(cls, view: EquipmentView) -> "EquipmentOutput":
        record = view.record
        equipment = record.equipment
        plan = record.maintenance_plan
        return cls(
            id=equipment.id,
            type=EquipmentTypeSummaryOutput.model_validate(record.type),
            serial_number=equipment.serial_number,
            brand=equipment.brand,
            model=equipment.model,
            organization=OrganizationSummaryOutput.model_validate(record.organization),
            status=equipment.status,
            status_label=view.status_label,
            installed_on=equipment.installed_on,
            address=AddressSchema.from_domain(equipment.address),
            location=GeoPointSchema.from_domain(equipment.location),
            region=RegionSummaryOutput.model_validate(record.region) if record.region else None,
            attributes=equipment.attributes,
            maintenance=MaintenanceSummaryOutput(
                need=view.maintenance.need,
                next_maintenance_date=view.maintenance.next_maintenance_date,
                is_overdue=view.maintenance.is_overdue,
                is_due_soon=view.maintenance.is_due_soon,
                plan=MaintenancePlanOutput.model_validate(plan) if plan else None,
            ),
            distance_m=round(record.distance_m, 1) if record.distance_m is not None else None,
            version=equipment.version,
            created_at=equipment.created_at,
            updated_at=equipment.updated_at,
        )


class StatusChangeOutput(BaseModel):
    id: int
    from_status: EquipmentStatus | None
    from_status_label: str | None
    to_status: EquipmentStatus
    to_status_label: str
    reason: str | None
    changed_by: UUID | None
    changed_by_name: str | None
    changed_at: datetime

    @classmethod
    def from_domain(cls, change: EquipmentStatusChange) -> "StatusChangeOutput":
        return cls(
            id=change.id,
            from_status=change.from_status,
            from_status_label=STATUS_LABELS[change.from_status] if change.from_status else None,
            to_status=change.to_status,
            to_status_label=STATUS_LABELS[change.to_status],
            reason=change.reason,
            changed_by=change.changed_by,
            changed_by_name=change.changed_by_name,
            changed_at=change.changed_at,
        )
