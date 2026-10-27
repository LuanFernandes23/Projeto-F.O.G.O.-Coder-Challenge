"""Agregado Equipamento, seus tipos e objetos de leitura."""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from app.core.exceptions import BusinessRuleError
from app.domain.equipment.status import INSTALLED_STATUSES, STATUS_LABELS, EquipmentStatus
from app.domain.maintenance.entities import MaintenanceNeed, MaintenancePlan, MaintenanceSnapshot
from app.domain.organizations import OrganizationSummary
from app.domain.regions import RegionSummary
from app.domain.shared import Address, GeoPoint


class EquipmentCategory(StrEnum):
    FISCALIZACAO = "fiscalizacao"
    MONITORAMENTO = "monitoramento"
    CONTROLE_TRAFEGO = "controle_trafego"
    CONTROLE_ACESSO = "controle_acesso"
    TRANSPORTE = "transporte"
    MICROMOBILIDADE = "micromobilidade"
    ATENDIMENTO = "atendimento"
    FROTA_OPERACIONAL = "frota_operacional"
    OUTRO = "outro"


@dataclass(frozen=True, slots=True)
class EquipmentType:
    """Tipo de equipamento (dado de referência).

    ``is_mobile``: a localização cadastrada é a da base (veículos, patinetes).
    ``is_vehicle``: pode ser atribuído a agentes (motos e viaturas).
    ``attributes_schema_key``: qual schema valida as características específicas.
    """

    code: str
    name: str
    category: EquipmentCategory
    icon: str
    is_mobile: bool
    is_vehicle: bool
    attributes_schema_key: str
    description: str | None = None


@dataclass(slots=True)
class Equipment:
    id: UUID
    type_code: str
    serial_number: str
    brand: str
    model: str
    organization_id: UUID
    status: EquipmentStatus
    address: Address
    location: GeoPoint
    region_id: UUID | None
    installed_on: date | None
    attributes: dict[str, Any]
    maintenance_need: MaintenanceNeed
    next_maintenance_date: date | None
    version: int
    created_at: datetime
    updated_at: datetime
    created_by: UUID | None = None
    updated_by: UUID | None = None
    archived_at: datetime | None = None

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None


@dataclass(frozen=True, slots=True)
class EquipmentStatusChange:
    id: int
    equipment_id: UUID
    from_status: EquipmentStatus | None
    to_status: EquipmentStatus
    reason: str | None
    changed_by: UUID | None
    changed_by_name: str | None
    changed_at: datetime


@dataclass(frozen=True, slots=True)
class EquipmentTypeSummary:
    code: str
    name: str
    category: EquipmentCategory
    icon: str


@dataclass(frozen=True, slots=True)
class EquipmentRecord:
    """Modelo de leitura persistido: equipamento com dados relacionados já resolvidos."""

    equipment: Equipment
    type: EquipmentTypeSummary
    organization: OrganizationSummary
    region: RegionSummary | None
    maintenance_plan: MaintenancePlan | None
    distance_m: float | None = None


@dataclass(frozen=True, slots=True)
class EquipmentView:
    """Registro + retrato de manutenção calculado para a data de hoje."""

    record: EquipmentRecord
    maintenance: MaintenanceSnapshot

    @property
    def status_label(self) -> str:
        return STATUS_LABELS[self.record.equipment.status]


def ensure_installation_consistency(
    status: EquipmentStatus, installed_on: date | None, today: date
) -> None:
    if installed_on is not None and installed_on > today:
        raise BusinessRuleError("A data de instalação não pode estar no futuro.")
    if status in INSTALLED_STATUSES and installed_on is None:
        raise BusinessRuleError(
            f"Equipamentos na situação '{STATUS_LABELS[status]}' precisam da data de instalação."
        )
