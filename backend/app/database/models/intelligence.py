"""Tabelas da Parte 3: calendário, previsões, base de conhecimento, IA e PROMETHEUS."""

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models.base import Base, UuidPrimaryKeyMixin, str_enum
from app.domain.ai_settings import (
    LOCAL_EMBEDDING_DIM,
    PROVIDER_EMBEDDING_DIM,
    AiProvider,
    EmbeddingsProvider,
)
from app.domain.prometheus.entities import (
    ActionType,
    DecisionMode,
    DecisionStatus,
    Planner,
    PrometheusMode,
    RiskClass,
    SituationKind,
)


class CityEventModel(UuidPrimaryKeyMixin, Base):
    """Calendário público (feriados, jogos, shows, feiras): entrada legítima das previsões."""

    __tablename__ = "city_events"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    region_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("regions.id"))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expected_public: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    __table_args__ = (
        Index("ix_city_events_starts_at", "starts_at"),
        CheckConstraint("ends_at > starts_at", name="period"),
    )


class PredictionModelRun(Base):
    """Cada ajuste do modelo: parâmetros, métricas do backtest e calibração (auditável)."""

    __tablename__ = "prediction_models"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    fitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    training_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    training_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    __table_args__ = (Index("ix_prediction_models_kind_fitted", "kind", "fitted_at"),)


class PredictionSnapshotModel(Base):
    """Última previsão calculada de cada tipo (o front lê daqui, sem recalcular)."""

    __tablename__ = "prediction_snapshots"

    kind: Mapped[str] = mapped_column(String(40), primary_key=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    model_id: Mapped[int | None] = mapped_column(ForeignKey("prediction_models.id"))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class AnomalyDetectionModel(Base):
    """Precursores de falha detectados e o desfecho (mede precisão e antecedência ao vivo)."""

    __tablename__ = "anomaly_detections"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    equipment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("equipment.id", ondelete="CASCADE"), nullable=False
    )
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    signals: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # pendente | falhou (acerto) | evitada (acerto + intervenção) | falso_alarme
    outcome: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pendente")
    outcome_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lead_minutes: Mapped[float | None] = mapped_column(Float)

    __table_args__ = (
        Index("ix_anomaly_detections_detected_at", "detected_at"),
        Index(
            "uq_anomaly_detections_open",
            "equipment_id",
            unique=True,
            postgresql_where=text("outcome = 'pendente'"),
        ),
    )


class AvertedFaultModel(Base):
    """Falha que não aconteceu porque houve intervenção a tempo (verdade de campo do simulador)."""

    __tablename__ = "averted_faults"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    equipment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("equipment.id", ondelete="CASCADE"), nullable=False
    )
    averted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    intervention: Mapped[str] = mapped_column(String(40), nullable=False)
    decision_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_decisions.id", ondelete="SET NULL")
    )
    by_prometheus: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    __table_args__ = (Index("ix_averted_faults_averted_at", "averted_at"),)


class KnowledgeDocumentModel(UuidPrimaryKeyMixin, Base):
    __tablename__ = "kb_documents"

    slug: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(40), nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)  # arquivo | tela
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class KnowledgeChunkModel(Base):
    __tablename__ = "kb_chunks"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("kb_documents.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    heading: Mapped[str] = mapped_column(String(300), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    lexemes: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False)
    embedding_local: Mapped[list[float] | None] = mapped_column(Vector(LOCAL_EMBEDDING_DIM))
    embedding_provider: Mapped[list[float] | None] = mapped_column(Vector(PROVIDER_EMBEDDING_DIM))
    provider_model: Mapped[str | None] = mapped_column(String(80))

    __table_args__ = (
        Index("ix_kb_chunks_document", "document_id", "ordinal"),
        Index(
            "ix_kb_chunks_embedding_local",
            "embedding_local",
            postgresql_using="hnsw",
            postgresql_ops={"embedding_local": "vector_cosine_ops"},
        ),
        Index(
            "ix_kb_chunks_embedding_provider",
            "embedding_provider",
            postgresql_using="hnsw",
            postgresql_ops={"embedding_provider": "vector_cosine_ops"},
        ),
    )


class AiSettingsModel(Base):
    """Linha única (id = 1). A chave fica cifrada (Fernet) e nunca sai do servidor."""

    __tablename__ = "ai_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    provider: Mapped[AiProvider] = mapped_column(
        str_enum(AiProvider, "ai_provider"), nullable=False
    )
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(300))
    api_key_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    key_last4: Mapped[str | None] = mapped_column(String(4))
    embeddings_provider: Mapped[EmbeddingsProvider] = mapped_column(
        str_enum(EmbeddingsProvider, "embeddings_provider"), nullable=False
    )
    daily_call_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    daily_token_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))

    __table_args__ = (CheckConstraint("id = 1", name="single_row"),)


class AiUsageModel(Base):
    __tablename__ = "ai_usage"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    feature: Mapped[str] = mapped_column(String(40), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cost_usd: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False, server_default="0")
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error: Mapped[str | None] = mapped_column(String(300))

    __table_args__ = (Index("ix_ai_usage_at", "at"),)


class PrometheusSettingsModel(Base):
    __tablename__ = "prometheus_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mode: Mapped[PrometheusMode] = mapped_column(
        str_enum(PrometheusMode, "prometheus_mode"), nullable=False
    )
    approval_ttl_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))

    __table_args__ = (CheckConstraint("id = 1", name="single_row"),)


class AutonomyPolicyModel(Base):
    __tablename__ = "autonomy_policies"

    action_type: Mapped[ActionType] = mapped_column(
        str_enum(ActionType, "action_type"), primary_key=True
    )
    risk_class: Mapped[RiskClass] = mapped_column(str_enum(RiskClass, "risk_class"), nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    max_per_hour: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))

    __table_args__ = (CheckConstraint("threshold >= 0 AND threshold <= 1", name="threshold"),)


class AgentDecisionModel(UuidPrimaryKeyMixin, Base):
    """Trilha de auditoria de cada decisão do PROMETHEUS (o "porquê" de tudo)."""

    __tablename__ = "agent_decisions"

    situation_key: Mapped[str] = mapped_column(String(160), nullable=False)
    situation_kind: Mapped[SituationKind] = mapped_column(
        str_enum(SituationKind, "situation_kind"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[DecisionStatus] = mapped_column(
        str_enum(DecisionStatus, "decision_status"), nullable=False
    )
    mode: Mapped[DecisionMode | None] = mapped_column(str_enum(DecisionMode, "decision_mode"))
    planner: Mapped[Planner] = mapped_column(str_enum(Planner, "planner"), nullable=False)
    action_type: Mapped[ActionType] = mapped_column(
        str_enum(ActionType, "decision_action_type"), nullable=False
    )
    action_params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    equipment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("equipment.id", ondelete="SET NULL")
    )
    region_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("regions.id"))
    thread_id: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    error: Mapped[str | None] = mapped_column(String(500))
    tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    __table_args__ = (
        Index("ix_agent_decisions_created_at", "created_at"),
        Index("ix_agent_decisions_status", "status"),
        # Uma decisão pendente por situação (o ciclo seguinte não duplica o pedido).
        Index(
            "uq_agent_decisions_pending_situation",
            "situation_key",
            unique=True,
            postgresql_where=text("status = 'pendente'"),
        ),
    )
