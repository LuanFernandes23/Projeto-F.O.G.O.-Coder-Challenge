"""Despacho de agentes para ocorrências: elegibilidade, estimativa de chegada e ciclo de vida."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.core.exceptions import BusinessRuleError, InvalidStatusTransitionError
from app.domain.agents.entities import AgentRole, DutyStatus
from app.domain.operations.alerts import AlertKind
from app.domain.shared import GeoPoint


class DispatchStatus(StrEnum):
    DESIGNADO = "designado"
    A_CAMINHO = "a_caminho"
    NO_LOCAL = "no_local"
    CONCLUIDO = "concluido"
    CANCELADO = "cancelado"


DISPATCH_LABELS: Mapping[DispatchStatus, str] = {
    DispatchStatus.DESIGNADO: "Designado",
    DispatchStatus.A_CAMINHO: "A caminho",
    DispatchStatus.NO_LOCAL: "No local",
    DispatchStatus.CONCLUIDO: "Concluído",
    DispatchStatus.CANCELADO: "Cancelado",
}

DISPATCH_TRANSITIONS: Mapping[DispatchStatus, frozenset[DispatchStatus]] = {
    DispatchStatus.DESIGNADO: frozenset(
        {DispatchStatus.A_CAMINHO, DispatchStatus.NO_LOCAL, DispatchStatus.CANCELADO}
    ),
    DispatchStatus.A_CAMINHO: frozenset({DispatchStatus.NO_LOCAL, DispatchStatus.CANCELADO}),
    DispatchStatus.NO_LOCAL: frozenset({DispatchStatus.CONCLUIDO, DispatchStatus.CANCELADO}),
    DispatchStatus.CONCLUIDO: frozenset(),
    DispatchStatus.CANCELADO: frozenset(),
}
ACTIVE_DISPATCH_STATUSES = frozenset(
    {DispatchStatus.DESIGNADO, DispatchStatus.A_CAMINHO, DispatchStatus.NO_LOCAL}
)

# Só quem está em turno e livre pode ser despachado (em ocorrência/pausa não).
DISPATCHABLE_DUTY_STATUSES = frozenset({DutyStatus.DISPONIVEL, DutyStatus.EM_PATRULHA})

ARRIVAL_RADIUS_M = 60.0
DEPARTURE_THRESHOLD_M = 25.0
URBAN_DETOUR_FACTOR = 1.3  # linha reta → percurso real aproximado

_SPEED_KMH: Mapping[str | None, float] = {
    "viatura": 35.0,
    "moto_agente": 40.0,
    None: 5.0,  # a pé
}

_TRAFFIC_EQUIPMENT = frozenset({"semaforo", "radar", "cancela", "balanca"})


def eligible_roles(kind: AlertKind | None, type_code: str) -> tuple[AgentRole, ...]:
    """Cargos aptos à ocorrência, em ordem de preferência."""
    if kind is AlertKind.FURTO:
        return (AgentRole.GUARDA_MUNICIPAL, AgentRole.POLICIAL_MILITAR)
    if type_code in _TRAFFIC_EQUIPMENT:
        return (AgentRole.AGENTE_TRANSITO, AgentRole.GUARDA_MUNICIPAL)
    return (AgentRole.GUARDA_MUNICIPAL, AgentRole.AGENTE_TRANSITO, AgentRole.POLICIAL_MILITAR)


def estimate_eta_minutes(distance_m: float, vehicle_type: str | None) -> float:
    speed_kmh = _SPEED_KMH.get(vehicle_type, _SPEED_KMH[None])
    meters_per_minute = speed_kmh * 1000 / 60
    return round(distance_m * URBAN_DETOUR_FACTOR / meters_per_minute, 1)


def ensure_dispatch_transition(current: DispatchStatus, target: DispatchStatus) -> None:
    if target in DISPATCH_TRANSITIONS[current]:
        return
    raise InvalidStatusTransitionError(
        f"O despacho não pode ir de '{current.value}' para '{target.value}'.",
        extra={
            "current_status": current.value,
            "allowed_transitions": sorted(s.value for s in DISPATCH_TRANSITIONS[current]),
        },
    )


def ensure_agent_dispatchable(
    is_active: bool, duty_status: DutyStatus, role: AgentRole, roles: tuple[AgentRole, ...]
) -> None:
    if not is_active or duty_status not in DISPATCHABLE_DUTY_STATUSES:
        raise BusinessRuleError(
            "O agente precisa estar em serviço e livre (disponível ou em patrulha)."
        )
    if role not in roles:
        raise BusinessRuleError(
            f"O cargo '{role.value}' não atende a este tipo de ocorrência.",
            extra={"eligible_roles": [r.value for r in roles]},
        )


@dataclass(slots=True)
class Dispatch:
    id: UUID
    agent_id: UUID
    equipment_id: UUID
    alert_id: UUID | None
    status: DispatchStatus
    target: GeoPoint
    origin: GeoPoint
    created_at: datetime
    created_by: UUID | None
    distance_m: float
    eta_minutes: float
    departed_at: datetime | None = None
    arrived_at: datetime | None = None
    closed_at: datetime | None = None
    notes: str | None = None

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_DISPATCH_STATUSES


@dataclass(frozen=True, slots=True)
class DispatchCandidate:
    agent_id: UUID
    full_name: str
    role: AgentRole
    organization_acronym: str
    duty_status: DutyStatus
    location: GeoPoint
    distance_m: float
    vehicle_type: str | None


@dataclass(frozen=True, slots=True)
class DispatchSuggestion:
    candidate: DispatchCandidate
    eta_minutes: float
    preference: int  # posição do cargo na ordem de preferência (0 = ideal)


def rank_suggestions(
    candidates: list[DispatchCandidate], roles: tuple[AgentRole, ...], limit: int
) -> list[DispatchSuggestion]:
    """Ordena pelo tempo estimado de chegada; empate favorece o cargo preferido."""
    suggestions = [
        DispatchSuggestion(
            candidate=c,
            eta_minutes=estimate_eta_minutes(c.distance_m, c.vehicle_type),
            preference=roles.index(c.role),
        )
        for c in candidates
        if c.role in roles
    ]
    suggestions.sort(key=lambda s: (s.eta_minutes, s.preference))
    return suggestions[:limit]


@dataclass(frozen=True, slots=True)
class DispatchRecord:
    dispatch: Dispatch
    agent_name: str
    agent_role: AgentRole
    organization_acronym: str
    equipment_serial: str
    equipment_type_code: str
