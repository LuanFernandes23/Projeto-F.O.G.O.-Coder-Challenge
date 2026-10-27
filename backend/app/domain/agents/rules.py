"""Regras puras de agentes: compatibilidade de cargo com órgão e uso de viaturas."""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from app.core.exceptions import BusinessRuleError, ConflictError
from app.domain.agents.entities import ON_DUTY_STATUSES, AgentRole, DutyStatus
from app.domain.equipment.entities import EquipmentType
from app.domain.equipment.status import EquipmentStatus
from app.domain.organizations import OrganizationKind

ROLE_ALLOWED_ORGANIZATION_KINDS: Mapping[AgentRole, frozenset[OrganizationKind]] = {
    AgentRole.AGENTE_TRANSITO: frozenset({OrganizationKind.TRANSITO}),
    AgentRole.GUARDA_MUNICIPAL: frozenset({OrganizationKind.GUARDA_MUNICIPAL}),
    AgentRole.POLICIAL_MILITAR: frozenset({OrganizationKind.POLICIA_MILITAR}),
    AgentRole.OUTRO: frozenset(OrganizationKind),
}

DEFAULT_CREW_CAPACITY = 1

# Viaturas avariadas, furtadas ou desativadas não podem sair com agentes.
VEHICLE_ASSIGNABLE_STATUSES = frozenset(
    {EquipmentStatus.OPERACIONAL, EquipmentStatus.NAO_INSTALADO}
)


def ensure_role_compatible(role: AgentRole, organization_kind: OrganizationKind) -> None:
    if organization_kind not in ROLE_ALLOWED_ORGANIZATION_KINDS[role]:
        raise BusinessRuleError(
            f"O cargo '{role.value}' não é compatível com um órgão do tipo "
            f"'{organization_kind.value}'."
        )


def vehicle_crew_capacity(attributes: Mapping[str, Any]) -> int:
    capacity = attributes.get("crew_capacity", DEFAULT_CREW_CAPACITY)
    return capacity if isinstance(capacity, int) and capacity > 0 else DEFAULT_CREW_CAPACITY


def ensure_vehicle_assignable(
    *,
    vehicle_type: EquipmentType,
    vehicle_status: EquipmentStatus,
    vehicle_organization_id: UUID,
    vehicle_attributes: Mapping[str, Any],
    agent_organization_id: UUID,
    other_active_crew: int,
) -> None:
    if not vehicle_type.is_vehicle:
        raise BusinessRuleError(
            f"Equipamentos do tipo '{vehicle_type.name}' não podem ser atribuídos a agentes."
        )
    if vehicle_organization_id != agent_organization_id:
        raise BusinessRuleError("A viatura precisa pertencer ao mesmo órgão do agente.")
    if vehicle_status not in VEHICLE_ASSIGNABLE_STATUSES:
        raise BusinessRuleError(
            f"A viatura está na situação '{vehicle_status.value}' e não pode ser atribuída."
        )
    capacity = vehicle_crew_capacity(vehicle_attributes)
    if other_active_crew >= capacity:
        raise ConflictError(
            f"A viatura já está com a tripulação completa ({capacity} agente(s)).",
            extra={"crew_capacity": capacity},
        )


def ensure_duty_change_allowed(is_active: bool, current: DutyStatus, target: DutyStatus) -> None:
    if current is target:
        raise ConflictError(f"O agente já está na situação '{target.value}'.")
    if not is_active and target in ON_DUTY_STATUSES:
        raise BusinessRuleError("Agentes inativos não podem entrar em serviço.")
