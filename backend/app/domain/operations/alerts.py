"""Alertas operacionais: tipos, criticidade, SLA e ciclo de vida (regras puras)."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID

from app.core.exceptions import ConflictError


class AlertKind(StrEnum):
    FALHA_EQUIPAMENTO = "falha_equipamento"
    FURTO = "furto"
    EQUIPAMENTO_OFFLINE = "equipamento_offline"
    MANUTENCAO_VENCIDA = "manutencao_vencida"
    REGIAO_DEGRADADA = "regiao_degradada"
    BATERIA_BAIXA = "bateria_baixa"
    PREVISAO_RISCO = "previsao_risco"  # Parte 3: risco previsto acima do limiar
    ANOMALIA_DETECTADA = "anomalia_detectada"  # Parte 3: precursor de falha na telemetria


class AlertSeverity(StrEnum):
    CRITICA = "critica"
    ALTA = "alta"
    MEDIA = "media"
    BAIXA = "baixa"

    @property
    def rank(self) -> int:
        """Maior = mais grave (útil para ordenar e escalar)."""
        return _SEVERITY_RANK[self]


class AlertStatus(StrEnum):
    ABERTO = "aberto"
    RECONHECIDO = "reconhecido"
    RESOLVIDO = "resolvido"


_SEVERITY_RANK = {
    AlertSeverity.BAIXA: 1,
    AlertSeverity.MEDIA: 2,
    AlertSeverity.ALTA: 3,
    AlertSeverity.CRITICA: 4,
}
_BY_RANK = {rank: severity for severity, rank in _SEVERITY_RANK.items()}

KIND_LABELS: Mapping[AlertKind, str] = {
    AlertKind.FALHA_EQUIPAMENTO: "Falha de equipamento",
    AlertKind.FURTO: "Furto",
    AlertKind.EQUIPAMENTO_OFFLINE: "Equipamento sem comunicação",
    AlertKind.MANUTENCAO_VENCIDA: "Manutenção vencida",
    AlertKind.REGIAO_DEGRADADA: "Região degradada",
    AlertKind.BATERIA_BAIXA: "Bateria baixa",
    AlertKind.PREVISAO_RISCO: "Risco previsto",
    AlertKind.ANOMALIA_DETECTADA: "Sinais de falha iminente",
}

SEVERITY_LABELS: Mapping[AlertSeverity, str] = {
    AlertSeverity.CRITICA: "Crítica",
    AlertSeverity.ALTA: "Alta",
    AlertSeverity.MEDIA: "Média",
    AlertSeverity.BAIXA: "Baixa",
}

# Prazo para tratar o alerta, contado a partir da abertura.
SLA_BY_SEVERITY: Mapping[AlertSeverity, timedelta] = {
    AlertSeverity.CRITICA: timedelta(hours=1),
    AlertSeverity.ALTA: timedelta(hours=4),
    AlertSeverity.MEDIA: timedelta(hours=24),
    AlertSeverity.BAIXA: timedelta(hours=72),
}

# Criticidade-base da FALHA por tipo: semáforo apagado põe vidas em risco; patinete, não.
_FAILURE_BASE: Mapping[str, AlertSeverity] = {
    "semaforo": AlertSeverity.CRITICA,
    "radar": AlertSeverity.ALTA,
    "camera": AlertSeverity.ALTA,
    "viatura": AlertSeverity.ALTA,
    "moto_agente": AlertSeverity.ALTA,
    "cancela": AlertSeverity.MEDIA,
    "balanca": AlertSeverity.MEDIA,
    "totem_estacionamento": AlertSeverity.MEDIA,
    "veiculo_fiscalizacao_autonomo": AlertSeverity.MEDIA,
    "veiculo_transporte": AlertSeverity.MEDIA,
    "patinete": AlertSeverity.BAIXA,
}
_HIGH_TRAFFIC_REGIONS = frozenset({"centro"})
_THEFT_CRITICAL_TYPES = frozenset({"viatura", "moto_agente", "camera"})


def _shift(severity: AlertSeverity, steps: int) -> AlertSeverity:
    return _BY_RANK[min(4, max(1, severity.rank + steps))]


def failure_severity(type_code: str, region_code: str | None) -> AlertSeverity:
    """Falha: base pelo tipo, +1 nível em região de tráfego intenso (Centro)."""
    base = _FAILURE_BASE.get(type_code, AlertSeverity.BAIXA)
    return _shift(base, 1) if region_code in _HIGH_TRAFFIC_REGIONS else base


def theft_severity(type_code: str) -> AlertSeverity:
    """Furto de viatura/moto/câmera é crítico (segurança pública); demais, alta."""
    return AlertSeverity.CRITICA if type_code in _THEFT_CRITICAL_TYPES else AlertSeverity.ALTA


def offline_severity(type_code: str, region_code: str | None) -> AlertSeverity:
    """Sem comunicação: um nível abaixo da falha (pode ser só o link)."""
    return _shift(failure_severity(type_code, region_code), -1)


def overdue_severity(type_code: str) -> AlertSeverity:
    critical = _FAILURE_BASE.get(type_code, AlertSeverity.BAIXA).rank >= AlertSeverity.ALTA.rank
    return AlertSeverity.MEDIA if critical else AlertSeverity.BAIXA


def anomaly_severity(type_code: str, region_code: str | None) -> AlertSeverity:
    """Precursor de falha: um nível abaixo da falha que ele anuncia (ainda dá para evitar)."""
    return _shift(failure_severity(type_code, region_code), -1)


def sla_due_at(severity: AlertSeverity, opened_at: datetime) -> datetime:
    return opened_at + SLA_BY_SEVERITY[severity]


def dedup_key(kind: AlertKind, subject_id: UUID) -> str:
    """Um alerta aberto por (tipo, sujeito): eventos repetidos atualizam o mesmo alerta."""
    return f"{kind.value}:{subject_id}"


@dataclass(slots=True)
class Alert:
    id: UUID
    kind: AlertKind
    severity: AlertSeverity
    status: AlertStatus
    title: str
    description: str
    dedup_key: str
    opened_at: datetime
    sla_due_at: datetime
    last_occurrence_at: datetime
    occurrences: int = 1
    equipment_id: UUID | None = None
    agent_id: UUID | None = None
    region_id: UUID | None = None
    acknowledged_at: datetime | None = None
    acknowledged_by: UUID | None = None
    resolved_at: datetime | None = None
    resolved_by: UUID | None = None
    resolution_note: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_open(self) -> bool:
        return self.status is not AlertStatus.RESOLVIDO


@dataclass(frozen=True, slots=True)
class SlaState:
    remaining_seconds: int
    breached: bool


def sla_state(alert: Alert, now: datetime) -> SlaState:
    """Tempo restante até o SLA; resolvidos são avaliados no instante da resolução."""
    reference = alert.resolved_at or now
    remaining = int((alert.sla_due_at - reference).total_seconds())
    return SlaState(remaining_seconds=remaining, breached=remaining < 0)


def ensure_can_acknowledge(alert: Alert) -> None:
    if alert.status is not AlertStatus.ABERTO:
        raise ConflictError(
            f"Somente alertas abertos podem ser reconhecidos (atual: {alert.status.value})."
        )


def ensure_can_resolve(alert: Alert) -> None:
    if alert.status is AlertStatus.RESOLVIDO:
        raise ConflictError("O alerta já está resolvido.")


@dataclass(frozen=True, slots=True)
class AlertSubject:
    """Equipamento envolvido num alerta, resumido para exibição."""

    equipment_id: UUID
    type_code: str
    type_name: str
    serial_number: str
    latitude: float
    longitude: float
    street: str
    neighborhood: str


@dataclass(frozen=True, slots=True)
class AlertRecord:
    alert: Alert
    region_name: str | None
    subject: AlertSubject | None


@dataclass(frozen=True, slots=True)
class AlertView:
    """Registro + situação do SLA calculada para o instante da consulta."""

    record: AlertRecord
    sla: SlaState


@dataclass(frozen=True, slots=True)
class AlertFilters:
    statuses: tuple[AlertStatus, ...] = ()
    severities: tuple[AlertSeverity, ...] = ()
    kinds: tuple[AlertKind, ...] = ()
    region_ids: tuple[UUID, ...] = ()
    equipment_id: UUID | None = None
