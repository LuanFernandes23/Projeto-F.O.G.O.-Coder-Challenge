"""PROMETHEUS: situações, ações, decisões e a política de autonomia (regras puras)."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class PrometheusMode(StrEnum):
    AUTONOMO = "autonomo"  # executa sozinho o que passar na política; o resto pede aprovação
    SUGESTAO = "sugestao"  # nunca executa sozinho: tudo vira pedido de aprovação
    PAUSADO = "pausado"  # não abre novas decisões


class RiskClass(StrEnum):
    BAIXO = "baixo"
    MEDIO = "medio"
    ALTO = "alto"


RISK_ORDER = {RiskClass.BAIXO: 1, RiskClass.MEDIO: 2, RiskClass.ALTO: 3}


class ActionType(StrEnum):
    ABRIR_OS_PREVENTIVA = "abrir_os_preventiva"
    ALERTA_PREVENTIVO = "alerta_preventivo"
    DESPACHAR_INSPECAO = "despachar_inspecao"
    REFORCAR_REGIAO = "reforcar_regiao"


ACTION_RISK: dict[ActionType, RiskClass] = {
    ActionType.ABRIR_OS_PREVENTIVA: RiskClass.BAIXO,
    ActionType.ALERTA_PREVENTIVO: RiskClass.BAIXO,
    ActionType.DESPACHAR_INSPECAO: RiskClass.MEDIO,
    ActionType.REFORCAR_REGIAO: RiskClass.ALTO,
}

ACTION_LABELS: dict[ActionType, str] = {
    ActionType.ABRIR_OS_PREVENTIVA: "Abrir ordem de manutenção preventiva",
    ActionType.ALERTA_PREVENTIVO: "Emitir alerta preventivo",
    ActionType.DESPACHAR_INSPECAO: "Despachar agente para inspeção preventiva",
    ActionType.REFORCAR_REGIAO: "Remanejar agentes para reforçar a região",
}


class SituationKind(StrEnum):
    PRECURSOR_FALHA = "precursor_falha"  # telemetria fora do padrão: falha iminente
    RISCO_EQUIPAMENTO = "risco_equipamento"  # chance alta de falhar nas próximas 72 h
    PICO_REGIONAL = "pico_regional"  # ocorrências acima do esperado numa região
    DEFICIT_EFETIVO = "deficit_efetivo"  # demanda prevista maior que o efetivo escalado


SITUATION_LABELS: dict[SituationKind, str] = {
    SituationKind.PRECURSOR_FALHA: "Sinais de falha iminente",
    SituationKind.RISCO_EQUIPAMENTO: "Risco alto de falha em 72 h",
    SituationKind.PICO_REGIONAL: "Pico de ocorrências fora do padrão",
    SituationKind.DEFICIT_EFETIVO: "Déficit de efetivo previsto",
}


class DecisionStatus(StrEnum):
    PENDENTE = "pendente"  # aguardando aprovação humana (grafo pausado no interrupt)
    EXECUTADA = "executada"
    REJEITADA = "rejeitada"
    EXPIRADA = "expirada"
    FALHOU = "falhou"


class DecisionMode(StrEnum):
    AUTOMATICA = "automatica"
    HUMANA = "humana"


class Planner(StrEnum):
    LLM = "llm"
    DETERMINISTICO = "deterministico"


@dataclass(frozen=True, slots=True)
class Situation:
    """Algo que PROMETHEUS percebeu e que pode pedir uma ação."""

    key: str  # deduplicação: uma decisão aberta por situação
    kind: SituationKind
    title: str
    summary: str
    confidence: float  # probabilidade calibrada pelo backtest (0-1)
    equipment_id: UUID | None = None
    region_id: UUID | None = None
    region_code: str | None = None
    type_code: str | None = None
    facts: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AutonomyPolicy:
    action_type: ActionType
    threshold: float  # score mínimo para executar sem humano
    enabled: bool  # False = esta ação sempre pede aprovação
    max_per_hour: int  # teto de execuções automáticas por hora


@dataclass(frozen=True, slots=True)
class ScoreBreakdown:
    confidence: float
    evidence: float
    score: float
    threshold: float
    action_risk: RiskClass
    allowed_risk: RiskClass
    auto: bool
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "confidence": round(self.confidence, 3),
            "evidence": round(self.evidence, 3),
            "score": round(self.score, 3),
            "threshold": self.threshold,
            "action_risk": self.action_risk.value,
            "allowed_risk": self.allowed_risk.value,
            "auto": self.auto,
            "reasons": list(self.reasons),
        }


def autonomy_decision(
    *,
    action: ActionType,
    confidence: float,
    evidence: float,
    allowed_risk: RiskClass,
    policy: AutonomyPolicy,
    mode: PrometheusMode,
    auto_executed_last_hour: int,
    plan_valid: bool,
) -> ScoreBreakdown:
    """Decide se PROMETHEUS age sozinho. A decisão é do código, nunca do LLM.

    score = confiança calibrada × evidência da base de conhecimento. Executa sozinho só se
    TODAS as condições valerem; cada uma que falhar vira um motivo legível.
    """
    score = max(0.0, min(1.0, confidence)) * max(0.0, min(1.0, evidence))
    action_risk = ACTION_RISK[action]
    reasons: list[str] = []
    if mode is not PrometheusMode.AUTONOMO:
        reasons.append("Modo de sugestão: toda ação passa por um humano.")
    if not plan_valid:
        reasons.append("O plano não passou na validação automática.")
    if action_risk is RiskClass.ALTO:
        reasons.append("Ação de risco alto sempre exige aprovação humana.")
    if RISK_ORDER[action_risk] > RISK_ORDER[allowed_risk]:
        reasons.append(f"O procedimento só autoriza ações de risco até '{allowed_risk.value}'.")
    if not policy.enabled:
        reasons.append("A execução automática desta ação está desligada na política.")
    if score < policy.threshold:
        reasons.append(f"Score {score:.2f} abaixo do limiar {policy.threshold:.2f}.")
    if auto_executed_last_hour >= policy.max_per_hour:
        reasons.append(f"Teto de {policy.max_per_hour} execuções automáticas por hora atingido.")
    return ScoreBreakdown(
        confidence=confidence,
        evidence=evidence,
        score=score,
        threshold=policy.threshold,
        action_risk=action_risk,
        allowed_risk=allowed_risk,
        auto=not reasons,
        reasons=tuple(reasons),
    )


DEFAULT_POLICIES: tuple[AutonomyPolicy, ...] = (
    AutonomyPolicy(ActionType.ABRIR_OS_PREVENTIVA, threshold=0.55, enabled=True, max_per_hour=6),
    AutonomyPolicy(ActionType.ALERTA_PREVENTIVO, threshold=0.45, enabled=True, max_per_hour=10),
    AutonomyPolicy(ActionType.DESPACHAR_INSPECAO, threshold=0.75, enabled=True, max_per_hour=3),
    AutonomyPolicy(ActionType.REFORCAR_REGIAO, threshold=0.95, enabled=False, max_per_hour=1),
)


@dataclass(slots=True)
class Decision:
    id: UUID
    situation_key: str
    situation_kind: SituationKind
    title: str
    summary: str
    status: DecisionStatus
    mode: DecisionMode | None
    planner: Planner
    action_type: ActionType
    action_params: dict[str, Any]
    rationale: str
    score: dict[str, Any]
    citations: list[dict[str, Any]]
    inputs: dict[str, Any]
    result: dict[str, Any] | None
    equipment_id: UUID | None
    region_id: UUID | None
    thread_id: str
    created_at: datetime
    expires_at: datetime | None
    decided_at: datetime | None = None
    decided_by: UUID | None = None
    error: str | None = None
    tokens: int = 0
