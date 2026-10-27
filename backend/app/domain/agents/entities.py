"""Agentes de campo (trânsito, guarda municipal, polícia) e seus modelos de leitura."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domain.organizations import OrganizationSummary
from app.domain.regions import RegionSummary
from app.domain.shared import Address, GeoPoint


class AgentRole(StrEnum):
    AGENTE_TRANSITO = "agente_transito"
    GUARDA_MUNICIPAL = "guarda_municipal"
    POLICIAL_MILITAR = "policial_militar"
    OUTRO = "outro"


class DutyStatus(StrEnum):
    DISPONIVEL = "disponivel"
    EM_PATRULHA = "em_patrulha"
    EM_OCORRENCIA = "em_ocorrencia"
    EM_PAUSA = "em_pausa"
    FORA_DE_SERVICO = "fora_de_servico"
    AFASTADO = "afastado"


DUTY_STATUS_LABELS = {
    DutyStatus.DISPONIVEL: "Disponível",
    DutyStatus.EM_PATRULHA: "Em patrulha",
    DutyStatus.EM_OCORRENCIA: "Atendendo ocorrência",
    DutyStatus.EM_PAUSA: "Em pausa",
    DutyStatus.FORA_DE_SERVICO: "Fora de serviço",
    DutyStatus.AFASTADO: "Afastado",
}

# "Agentes em atividade" (indicador pedido na Parte 2): em turno, mesmo que em pausa.
ON_DUTY_STATUSES = frozenset(
    {
        DutyStatus.DISPONIVEL,
        DutyStatus.EM_PATRULHA,
        DutyStatus.EM_OCORRENCIA,
        DutyStatus.EM_PAUSA,
    }
)


@dataclass(slots=True)
class Agent:
    """Dados mínimos necessários à operação (LGPD: sem CPF, telefone ou endereço pessoal)."""

    id: UUID
    full_name: str
    registration_number: str
    role: AgentRole
    organization_id: UUID
    duty_status: DutyStatus
    is_active: bool
    base_address: Address
    base_location: GeoPoint
    region_id: UUID | None
    assigned_vehicle_id: UUID | None
    version: int
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class VehicleSummary:
    id: UUID
    type_code: str
    serial_number: str
    model: str
    plate: str | None


@dataclass(frozen=True, slots=True)
class AgentRecord:
    agent: Agent
    organization: OrganizationSummary
    region: RegionSummary | None
    vehicle: VehicleSummary | None


@dataclass(frozen=True, slots=True)
class AgentStatusChange:
    id: int
    agent_id: UUID
    from_status: DutyStatus | None
    to_status: DutyStatus
    reason: str | None
    changed_by: UUID | None
    changed_by_name: str | None
    changed_at: datetime


@dataclass(frozen=True, slots=True)
class AgentFilters:
    roles: tuple[AgentRole, ...] = ()
    duty_statuses: tuple[DutyStatus, ...] = ()
    organization_ids: tuple[UUID, ...] = ()
    region_ids: tuple[UUID, ...] = ()
    on_duty: bool | None = None
    is_active: bool | None = None
    search: str | None = None
