"""Índice de saúde por região: transforma números da operação em um nível de atenção."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID

from app.domain.operations.alerts import AlertSeverity


class HealthLevel(StrEnum):
    NORMAL = "normal"
    ATENCAO = "atencao"
    CRITICO = "critico"


HEALTH_LABELS: Mapping[HealthLevel, str] = {
    HealthLevel.NORMAL: "Operando normalmente",
    HealthLevel.ATENCAO: "Exige atenção",
    HealthLevel.CRITICO: "Situação crítica",
}

NORMAL_THRESHOLD = 85.0
ATTENTION_THRESHOLD = 70.0

# Peso de cada alerta aberto na nota (teto para não zerar só por alertas).
_ALERT_PENALTY: Mapping[AlertSeverity, float] = {
    AlertSeverity.CRITICA: 8.0,
    AlertSeverity.ALTA: 4.0,
    AlertSeverity.MEDIA: 1.5,
    AlertSeverity.BAIXA: 0.5,
}
_MAX_ALERT_PENALTY = 40.0
# Alerta reconhecido já tem alguém tratando: pesa só o risco residual (1/4).
# A indisponibilidade do equipamento já desconta na disponibilidade (evita dupla punição).
_ACKNOWLEDGED_WEIGHT = 0.25
_OFFLINE_WEIGHT = 30.0
_IMMEDIATE_WEIGHT = 20.0


@dataclass(frozen=True, slots=True)
class RegionMetrics:
    region_id: UUID
    code: str
    name: str
    operational: int
    unavailable: int  # instalados, mas fora de operação (defeito, manutenção, furto)
    offline: int
    immediate_maintenance: int
    overdue_maintenance: int
    agents_on_duty: int
    open_alerts: Mapping[AlertSeverity, int] = field(default_factory=dict)  # ainda sem dono
    acknowledged_alerts: Mapping[AlertSeverity, int] = field(default_factory=dict)  # em tratamento

    @property
    def in_service_base(self) -> int:
        return self.operational + self.unavailable


@dataclass(frozen=True, slots=True)
class RegionHealth:
    metrics: RegionMetrics
    availability_pct: float
    score: float
    level: HealthLevel
    reasons: tuple[str, ...]


def classify(score: float) -> HealthLevel:
    if score >= NORMAL_THRESHOLD:
        return HealthLevel.NORMAL
    if score >= ATTENTION_THRESHOLD:
        return HealthLevel.ATENCAO
    return HealthLevel.CRITICO


def compute_region_health(metrics: RegionMetrics) -> RegionHealth:
    """Nota 0–100 = disponibilidade − penalidades, com os motivos em linguagem simples."""
    base = metrics.in_service_base
    availability = metrics.operational / base if base else 1.0
    offline_ratio = metrics.offline / base if base else 0.0
    immediate_ratio = metrics.immediate_maintenance / base if base else 0.0
    alert_penalty = min(
        _MAX_ALERT_PENALTY,
        sum(_ALERT_PENALTY[sev] * count for sev, count in metrics.open_alerts.items())
        + _ACKNOWLEDGED_WEIGHT
        * sum(_ALERT_PENALTY[sev] * count for sev, count in metrics.acknowledged_alerts.items()),
    )
    score = (
        100.0 * availability
        - alert_penalty
        - _OFFLINE_WEIGHT * offline_ratio
        - _IMMEDIATE_WEIGHT * immediate_ratio
    )
    score = round(max(0.0, min(100.0, score)), 1)

    reasons: list[str] = []
    if availability < 0.95:
        reasons.append(f"Disponibilidade de {availability:.0%}")
    critical = metrics.open_alerts.get(AlertSeverity.CRITICA, 0)
    high = metrics.open_alerts.get(AlertSeverity.ALTA, 0)
    if critical:
        reasons.append(f"{critical} alerta(s) crítico(s) sem tratamento")
    if high:
        reasons.append(f"{high} alerta(s) de prioridade alta sem tratamento")
    if offline_ratio >= 0.05:
        reasons.append(f"{offline_ratio:.0%} dos equipamentos sem comunicação")
    if metrics.immediate_maintenance:
        reasons.append(f"{metrics.immediate_maintenance} equipamento(s) aguardando reparo")
    if metrics.overdue_maintenance:
        reasons.append(f"{metrics.overdue_maintenance} manutenção(ões) vencida(s)")
    if not reasons:
        reasons.append("Sem ocorrências relevantes")

    return RegionHealth(
        metrics=metrics,
        availability_pct=round(availability * 100, 1),
        score=score,
        level=classify(score),
        reasons=tuple(reasons),
    )
