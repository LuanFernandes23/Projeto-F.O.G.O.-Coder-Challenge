"""Contratos da Parte 3: configuração de IA, base de conhecimento e PROMETHEUS."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.domain.ai_settings import (
    DEFAULT_MODELS,
    PROVIDER_LABELS,
    AiProvider,
    AiSettings,
    EmbeddingsProvider,
)
from app.domain.prometheus.entities import (
    ACTION_LABELS,
    ACTION_RISK,
    SITUATION_LABELS,
    ActionType,
    AutonomyPolicy,
    Decision,
    DecisionMode,
    DecisionStatus,
    Planner,
    PrometheusMode,
    RiskClass,
    SituationKind,
)

# ---- IA (BYOK) ---------------------------------------------------------------------------


class ProviderOption(BaseModel):
    code: AiProvider
    label: str
    default_model: str
    needs_key: bool
    needs_base_url: bool
    supports_embeddings: bool


class AiSettingsOutput(BaseModel):
    enabled: bool
    usable: bool
    provider: AiProvider
    model: str
    base_url: str | None
    has_key: bool
    key_hint: str | None = Field(description="Só os 4 últimos caracteres da chave.")
    embeddings_provider: EmbeddingsProvider
    provider_embeddings_active: bool
    daily_call_limit: int
    daily_token_limit: int
    updated_at: datetime | None
    providers: list[ProviderOption]

    @classmethod
    def from_domain(cls, s: AiSettings) -> "AiSettingsOutput":
        return cls(
            enabled=s.enabled,
            usable=s.usable,
            provider=s.provider,
            model=s.model,
            base_url=s.base_url,
            has_key=s.has_key,
            key_hint=f"…{s.key_last4}" if s.key_last4 else None,
            embeddings_provider=s.embeddings_provider,
            provider_embeddings_active=s.provider_embeddings_active,
            daily_call_limit=s.daily_call_limit,
            daily_token_limit=s.daily_token_limit,
            updated_at=s.updated_at,
            providers=[
                ProviderOption(
                    code=p,
                    label=PROVIDER_LABELS[p],
                    default_model=DEFAULT_MODELS[p],
                    needs_key=p is not AiProvider.OPENAI_COMPATIBLE,
                    needs_base_url=p is AiProvider.OPENAI_COMPATIBLE,
                    supports_embeddings=p in (AiProvider.OPENAI, AiProvider.GEMINI),
                )
                for p in AiProvider
            ],
        )


class AiSettingsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    enabled: bool
    provider: AiProvider
    model: str = Field(min_length=1, max_length=120)
    base_url: str | None = Field(default=None, max_length=300)
    api_key: SecretStr | None = Field(
        default=None, description="Só de escrita. Omitido = manter a chave atual."
    )
    clear_key: bool = False
    embeddings_provider: EmbeddingsProvider = EmbeddingsProvider.LOCAL
    daily_call_limit: int = Field(default=200, ge=1, le=100_000)
    daily_token_limit: int = Field(default=200_000, ge=1_000, le=50_000_000)


class AiCandidateInput(BaseModel):
    """Configuração a testar/listar ANTES de salvar (chave opcional: usa a salva)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    provider: AiProvider
    model: str = Field(default="", max_length=120)
    base_url: str | None = Field(default=None, max_length=300)
    api_key: SecretStr | None = None


class AiTestOutput(BaseModel):
    ok: bool
    latency_ms: int
    reply: str
    input_tokens: int
    output_tokens: int
    error: str | None


class AiUsageOutput(BaseModel):
    day: str
    feature: str
    calls: int
    errors: int
    input_tokens: int
    output_tokens: int
    cost_usd: float


class AiSaveOutput(BaseModel):
    settings: AiSettingsOutput
    reindexed_chunks: int | None = None


# ---- Base de conhecimento --------------------------------------------------------------


class KnowledgeDocumentOutput(BaseModel):
    id: UUID
    slug: str
    title: str
    doc_type: str
    metadata: dict[str, Any]
    source: str
    updated_at: datetime
    chunks: int = 0


class KnowledgeChunkOutput(BaseModel):
    id: int
    ordinal: int
    heading: str
    content: str
    has_provider_embedding: bool


class KnowledgeDocumentDetail(KnowledgeDocumentOutput):
    content: str
    chunk_list: list[KnowledgeChunkOutput]


class KnowledgeDocumentInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    slug: str | None = Field(default=None, pattern=r"^[a-z0-9-]{3,120}$")
    title: str = Field(min_length=3, max_length=200)
    doc_type: str = Field(min_length=3, max_length=40)
    situations: list[SituationKind] = Field(default_factory=list)
    allowed_actions: list[ActionType] = Field(default_factory=list)
    default_action: ActionType | None = None
    max_autonomy: RiskClass = RiskClass.BAIXO
    equipment_types: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    body: str = Field(min_length=20, max_length=50_000)

    def metadata(self) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "situacoes": [s.value for s in self.situations],
            "acoes_permitidas": [a.value for a in self.allowed_actions],
            "autonomia_max": self.max_autonomy.value,
        }
        if self.default_action:
            meta["acao_padrao"] = self.default_action.value
        if self.equipment_types:
            meta["tipos_equipamento"] = self.equipment_types
        if self.regions:
            meta["regioes"] = self.regions
        return meta


class KnowledgeSearchInput(BaseModel):
    query: str = Field(min_length=3, max_length=500)
    situation: SituationKind | None = None
    limit: int = Field(default=5, ge=1, le=20)


class KnowledgeHitOutput(BaseModel):
    chunk_id: int
    document_id: str
    slug: str
    title: str
    doc_type: str
    heading: str
    content: str
    rrf: float
    ranks: dict[str, int]
    similarity: float
    evidence: float


# ---- PROMETHEUS --------------------------------------------------------------------------


class DecisionOutput(BaseModel):
    id: UUID
    situation_key: str
    situation_kind: SituationKind
    situation_label: str
    title: str
    summary: str
    status: DecisionStatus
    mode: DecisionMode | None
    planner: Planner
    action_type: ActionType
    action_label: str
    action_risk: RiskClass
    action_params: dict[str, Any]
    rationale: str
    score: dict[str, Any]
    citations: list[dict[str, Any]]
    inputs: dict[str, Any]
    result: dict[str, Any] | None
    equipment_id: UUID | None
    region_id: UUID | None
    created_at: datetime
    expires_at: datetime | None
    decided_at: datetime | None
    decided_by: UUID | None
    error: str | None
    tokens: int

    @classmethod
    def from_domain(cls, d: Decision) -> "DecisionOutput":
        return cls(
            id=d.id,
            situation_key=d.situation_key,
            situation_kind=d.situation_kind,
            situation_label=SITUATION_LABELS[d.situation_kind],
            title=d.title,
            summary=d.summary,
            status=d.status,
            mode=d.mode,
            planner=d.planner,
            action_type=d.action_type,
            action_label=ACTION_LABELS[d.action_type],
            action_risk=ACTION_RISK[d.action_type],
            action_params=d.action_params,
            rationale=d.rationale,
            score=d.score,
            citations=d.citations,
            inputs=d.inputs,
            result=d.result,
            equipment_id=d.equipment_id,
            region_id=d.region_id,
            created_at=d.created_at,
            expires_at=d.expires_at,
            decided_at=d.decided_at,
            decided_by=d.decided_by,
            error=d.error,
            tokens=d.tokens,
        )


class DecisionAnswerInput(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class PolicyOutput(BaseModel):
    action_type: ActionType
    action_label: str
    risk_class: RiskClass
    threshold: float = Field(ge=0, le=1)
    enabled: bool
    max_per_hour: int = Field(ge=0, le=100)

    @classmethod
    def from_domain(cls, p: AutonomyPolicy) -> "PolicyOutput":
        return cls(
            action_type=p.action_type,
            action_label=ACTION_LABELS[p.action_type],
            risk_class=ACTION_RISK[p.action_type],
            threshold=p.threshold,
            enabled=p.enabled,
            max_per_hour=p.max_per_hour,
        )


class PolicyInput(BaseModel):
    action_type: ActionType
    threshold: float = Field(ge=0, le=1)
    enabled: bool
    max_per_hour: int = Field(ge=0, le=100)


class PrometheusSettingsOutput(BaseModel):
    mode: PrometheusMode
    approval_ttl_minutes: int
    policies: list[PolicyOutput]


class PrometheusSettingsInput(BaseModel):
    mode: PrometheusMode
    approval_ttl_minutes: int = Field(ge=5, le=24 * 60)
    policies: list[PolicyInput]


class PrometheusStatsOutput(BaseModel):
    hours: int
    mode: PrometheusMode
    approval_ttl_minutes: int
    decisions: dict[str, int]
    averted: dict[str, int]
    detection_quality: dict[str, Any] | None


class ChatMessageInput(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=4000)


class ChatInput(BaseModel):
    messages: list[ChatMessageInput] = Field(min_length=1, max_length=20)
