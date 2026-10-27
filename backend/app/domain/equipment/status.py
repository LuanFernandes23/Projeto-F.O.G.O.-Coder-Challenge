"""Situações possíveis de um equipamento e a máquina de estados que as governa."""

from collections.abc import Mapping
from enum import StrEnum

from app.core.exceptions import BusinessRuleError, InvalidStatusTransitionError


class EquipmentStatus(StrEnum):
    NAO_INSTALADO = "nao_instalado"
    OPERACIONAL = "operacional"
    MAU_FUNCIONAMENTO = "mau_funcionamento"
    EM_MANUTENCAO = "em_manutencao"
    DESATIVADO = "desativado"
    FURTADO = "furtado"


STATUS_LABELS: Mapping[EquipmentStatus, str] = {
    EquipmentStatus.NAO_INSTALADO: "Ainda não instalado",
    EquipmentStatus.OPERACIONAL: "Operacional",
    EquipmentStatus.MAU_FUNCIONAMENTO: "Mau funcionamento",
    EquipmentStatus.EM_MANUTENCAO: "Em manutenção",
    EquipmentStatus.DESATIVADO: "Desativado",
    EquipmentStatus.FURTADO: "Furtado",
}

# Transições explícitas: qualquer par ausente é proibido.
# Ex.: um equipamento furtado não volta direto a "operacional"; ele precisa ser
# recuperado ("nao_instalado") e reinstalado, deixando rastro no histórico.
STATUS_TRANSITIONS: Mapping[EquipmentStatus, frozenset[EquipmentStatus]] = {
    EquipmentStatus.NAO_INSTALADO: frozenset(
        {EquipmentStatus.OPERACIONAL, EquipmentStatus.DESATIVADO}
    ),
    EquipmentStatus.OPERACIONAL: frozenset(
        {
            EquipmentStatus.MAU_FUNCIONAMENTO,
            EquipmentStatus.EM_MANUTENCAO,
            EquipmentStatus.DESATIVADO,
            EquipmentStatus.FURTADO,
        }
    ),
    EquipmentStatus.MAU_FUNCIONAMENTO: frozenset(
        {
            EquipmentStatus.EM_MANUTENCAO,
            EquipmentStatus.OPERACIONAL,
            EquipmentStatus.DESATIVADO,
            EquipmentStatus.FURTADO,
        }
    ),
    EquipmentStatus.EM_MANUTENCAO: frozenset(
        {
            EquipmentStatus.OPERACIONAL,
            EquipmentStatus.MAU_FUNCIONAMENTO,
            EquipmentStatus.DESATIVADO,
        }
    ),
    EquipmentStatus.DESATIVADO: frozenset(
        {EquipmentStatus.EM_MANUTENCAO, EquipmentStatus.OPERACIONAL}
    ),
    EquipmentStatus.FURTADO: frozenset({EquipmentStatus.NAO_INSTALADO, EquipmentStatus.DESATIVADO}),
}

# Situações em que o equipamento está fisicamente instalado na via.
INSTALLED_STATUSES = frozenset(
    {
        EquipmentStatus.OPERACIONAL,
        EquipmentStatus.MAU_FUNCIONAMENTO,
        EquipmentStatus.EM_MANUTENCAO,
    }
)

# Situações aceitas no cadastro inicial: o inventário pode começar com equipamentos
# já em campo (inclusive com defeito), mas não "nascer" furtado ou em manutenção.
INITIAL_STATUSES = frozenset(
    {
        EquipmentStatus.NAO_INSTALADO,
        EquipmentStatus.OPERACIONAL,
        EquipmentStatus.MAU_FUNCIONAMENTO,
        EquipmentStatus.DESATIVADO,
    }
)

# Situações que encerram o ciclo de manutenção (ordens abertas são canceladas).
MAINTENANCE_CANCELLING_STATUSES = frozenset({EquipmentStatus.DESATIVADO, EquipmentStatus.FURTADO})

# Situações que não devem receber manutenção preventiva automática.
PREVENTIVE_EXEMPT_STATUSES = frozenset(
    {EquipmentStatus.NAO_INSTALADO, EquipmentStatus.DESATIVADO, EquipmentStatus.FURTADO}
)


def allowed_transitions(current: EquipmentStatus) -> frozenset[EquipmentStatus]:
    return STATUS_TRANSITIONS[current]


def ensure_transition_allowed(current: EquipmentStatus, target: EquipmentStatus) -> None:
    if target in STATUS_TRANSITIONS[current]:
        return
    allowed = sorted(status.value for status in STATUS_TRANSITIONS[current])
    raise InvalidStatusTransitionError(
        f"Não é permitido mudar de '{STATUS_LABELS[current]}' para '{STATUS_LABELS[target]}'.",
        extra={"current_status": current.value, "allowed_transitions": allowed},
    )


def ensure_initial_status(status: EquipmentStatus) -> None:
    if status not in INITIAL_STATUSES:
        allowed = sorted(s.value for s in INITIAL_STATUSES)
        raise BusinessRuleError(
            f"Um equipamento não pode ser cadastrado como '{STATUS_LABELS[status]}'.",
            extra={"allowed_initial_statuses": allowed},
        )
