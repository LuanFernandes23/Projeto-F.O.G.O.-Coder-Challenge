"""parte 3: cidade preditiva e PROMETHEUS

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-27 00:34:39.337963
"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0004'
down_revision: str | None = '0003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_ALERT_KINDS_OLD = (
    "'falha_equipamento', 'furto', 'equipamento_offline', 'manutencao_vencida', "
    "'regiao_degradada', 'bateria_baixa'"
)
_ALERT_KINDS_NEW = _ALERT_KINDS_OLD + ", 'previsao_risco', 'anomalia_detectada'"

_POLICIES = (
    ("abrir_os_preventiva", "baixo", 0.55, True, 6),
    ("alerta_preventivo", "baixo", 0.45, True, 10),
    ("despachar_inspecao", "medio", 0.75, True, 3),
    ("reforcar_regiao", "alto", 0.95, False, 1),
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.drop_constraint(op.f("ck_alerts_alert_kind"), "alerts", type_="check")
    op.create_check_constraint(op.f("ck_alerts_alert_kind"), "alerts", f"kind IN ({_ALERT_KINDS_NEW})")
    op.create_table('ai_usage',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('provider', sa.String(length=32), nullable=False),
    sa.Column('model', sa.String(length=120), nullable=False),
    sa.Column('feature', sa.String(length=40), nullable=False),
    sa.Column('input_tokens', sa.Integer(), server_default='0', nullable=False),
    sa.Column('output_tokens', sa.Integer(), server_default='0', nullable=False),
    sa.Column('cost_usd', sa.Numeric(precision=12, scale=6), server_default='0', nullable=False),
    sa.Column('ok', sa.Boolean(), nullable=False),
    sa.Column('error', sa.String(length=300), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_usage'))
    )
    op.create_index('ix_ai_usage_at', 'ai_usage', ['at'], unique=False)
    op.create_table('prediction_models',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('kind', sa.String(length=40), nullable=False),
    sa.Column('fitted_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('training_from', sa.DateTime(timezone=True), nullable=False),
    sa.Column('training_to', sa.DateTime(timezone=True), nullable=False),
    sa.Column('params', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('metrics', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_prediction_models'))
    )
    op.create_index('ix_prediction_models_kind_fitted', 'prediction_models', ['kind', 'fitted_at'], unique=False)
    op.create_table('ai_settings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('provider', sa.Enum('openai', 'anthropic', 'gemini', 'openai_compatible', name='ai_provider', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('model', sa.String(length=120), nullable=False),
    sa.Column('base_url', sa.String(length=300), nullable=True),
    sa.Column('api_key_encrypted', sa.LargeBinary(), nullable=True),
    sa.Column('key_last4', sa.String(length=4), nullable=True),
    sa.Column('embeddings_provider', sa.Enum('local', 'openai', 'gemini', name='embeddings_provider', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('daily_call_limit', sa.Integer(), nullable=False),
    sa.Column('daily_token_limit', sa.Integer(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.CheckConstraint('id = 1', name=op.f('ck_ai_settings_single_row')),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], name=op.f('fk_ai_settings_updated_by_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_settings'))
    )
    op.create_table('autonomy_policies',
    sa.Column('action_type', sa.Enum('abrir_os_preventiva', 'alerta_preventivo', 'despachar_inspecao', 'reforcar_regiao', name='action_type', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('risk_class', sa.Enum('baixo', 'medio', 'alto', name='risk_class', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('threshold', sa.Float(), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('max_per_hour', sa.Integer(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.CheckConstraint('threshold >= 0 AND threshold <= 1', name=op.f('ck_autonomy_policies_threshold')),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], name=op.f('fk_autonomy_policies_updated_by_users')),
    sa.PrimaryKeyConstraint('action_type', name=op.f('pk_autonomy_policies'))
    )
    op.create_table('city_events',
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('region_id', sa.Uuid(), nullable=True),
    sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ends_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expected_public', sa.Integer(), server_default='0', nullable=False),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.CheckConstraint('ends_at > starts_at', name=op.f('ck_city_events_period')),
    sa.ForeignKeyConstraint(['region_id'], ['regions.id'], name=op.f('fk_city_events_region_id_regions')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_city_events'))
    )
    op.create_index('ix_city_events_starts_at', 'city_events', ['starts_at'], unique=False)
    op.create_table('kb_documents',
    sa.Column('slug', sa.String(length=120), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('doc_type', sa.String(length=40), nullable=False),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], name=op.f('fk_kb_documents_updated_by_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_kb_documents')),
    sa.UniqueConstraint('slug', name=op.f('uq_kb_documents_slug'))
    )
    op.create_table('prediction_snapshots',
    sa.Column('kind', sa.String(length=40), nullable=False),
    sa.Column('generated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('model_id', sa.BigInteger(), nullable=True),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.ForeignKeyConstraint(['model_id'], ['prediction_models.id'], name=op.f('fk_prediction_snapshots_model_id_prediction_models')),
    sa.PrimaryKeyConstraint('kind', name=op.f('pk_prediction_snapshots'))
    )
    op.create_table('prometheus_settings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('mode', sa.Enum('autonomo', 'sugestao', 'pausado', name='prometheus_mode', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('approval_ttl_minutes', sa.Integer(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.CheckConstraint('id = 1', name=op.f('ck_prometheus_settings_single_row')),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], name=op.f('fk_prometheus_settings_updated_by_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_prometheus_settings'))
    )
    op.create_table('agent_decisions',
    sa.Column('situation_key', sa.String(length=160), nullable=False),
    sa.Column('situation_kind', sa.Enum('precursor_falha', 'risco_equipamento', 'pico_regional', 'deficit_efetivo', name='situation_kind', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('status', sa.Enum('pendente', 'executada', 'rejeitada', 'expirada', 'falhou', name='decision_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('mode', sa.Enum('automatica', 'humana', name='decision_mode', native_enum=False, create_constraint=True, length=32), nullable=True),
    sa.Column('planner', sa.Enum('llm', 'deterministico', name='planner', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('action_type', sa.Enum('abrir_os_preventiva', 'alerta_preventivo', 'despachar_inspecao', 'reforcar_regiao', name='decision_action_type', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('action_params', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('rationale', sa.Text(), nullable=False),
    sa.Column('score', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('citations', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('inputs', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('equipment_id', sa.Uuid(), nullable=True),
    sa.Column('region_id', sa.Uuid(), nullable=True),
    sa.Column('thread_id', sa.String(length=80), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('decided_by', sa.Uuid(), nullable=True),
    sa.Column('error', sa.String(length=500), nullable=True),
    sa.Column('tokens', sa.Integer(), server_default='0', nullable=False),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.ForeignKeyConstraint(['decided_by'], ['users.id'], name=op.f('fk_agent_decisions_decided_by_users')),
    sa.ForeignKeyConstraint(['equipment_id'], ['equipment.id'], name=op.f('fk_agent_decisions_equipment_id_equipment'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['region_id'], ['regions.id'], name=op.f('fk_agent_decisions_region_id_regions')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_agent_decisions'))
    )
    op.create_index('ix_agent_decisions_created_at', 'agent_decisions', ['created_at'], unique=False)
    op.create_index('ix_agent_decisions_status', 'agent_decisions', ['status'], unique=False)
    op.create_index('uq_agent_decisions_pending_situation', 'agent_decisions', ['situation_key'], unique=True, postgresql_where=sa.text("status = 'pendente'"))
    op.create_table('anomaly_detections',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('equipment_id', sa.Uuid(), nullable=False),
    sa.Column('detected_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('score', sa.Float(), nullable=False),
    sa.Column('signals', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('outcome', sa.String(length=20), server_default='pendente', nullable=False),
    sa.Column('outcome_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('lead_minutes', sa.Float(), nullable=True),
    sa.ForeignKeyConstraint(['equipment_id'], ['equipment.id'], name=op.f('fk_anomaly_detections_equipment_id_equipment'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_anomaly_detections'))
    )
    op.create_index('ix_anomaly_detections_detected_at', 'anomaly_detections', ['detected_at'], unique=False)
    op.create_index('uq_anomaly_detections_open', 'anomaly_detections', ['equipment_id'], unique=True, postgresql_where=sa.text("outcome = 'pendente'"))
    op.create_table('kb_chunks',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('document_id', sa.Uuid(), nullable=False),
    sa.Column('ordinal', sa.Integer(), nullable=False),
    sa.Column('heading', sa.String(length=300), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('lexemes', postgresql.ARRAY(sa.String()), nullable=False),
    sa.Column('embedding_local', pgvector.sqlalchemy.vector.VECTOR(dim=384), nullable=True),
    sa.Column('embedding_provider', pgvector.sqlalchemy.vector.VECTOR(dim=768), nullable=True),
    sa.Column('provider_model', sa.String(length=80), nullable=True),
    sa.ForeignKeyConstraint(['document_id'], ['kb_documents.id'], name=op.f('fk_kb_chunks_document_id_kb_documents'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_kb_chunks'))
    )
    op.create_index('ix_kb_chunks_document', 'kb_chunks', ['document_id', 'ordinal'], unique=False)
    op.create_index('ix_kb_chunks_embedding_local', 'kb_chunks', ['embedding_local'], unique=False, postgresql_using='hnsw', postgresql_ops={'embedding_local': 'vector_cosine_ops'})
    op.create_index('ix_kb_chunks_embedding_provider', 'kb_chunks', ['embedding_provider'], unique=False, postgresql_using='hnsw', postgresql_ops={'embedding_provider': 'vector_cosine_ops'})
    op.create_table('averted_faults',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('equipment_id', sa.Uuid(), nullable=False),
    sa.Column('averted_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('intervention', sa.String(length=40), nullable=False),
    sa.Column('decision_id', sa.Uuid(), nullable=True),
    sa.Column('by_prometheus', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['decision_id'], ['agent_decisions.id'], name=op.f('fk_averted_faults_decision_id_agent_decisions'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['equipment_id'], ['equipment.id'], name=op.f('fk_averted_faults_equipment_id_equipment'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_averted_faults'))
    )
    op.create_index('ix_averted_faults_averted_at', 'averted_faults', ['averted_at'], unique=False)
    op.execute(
        "INSERT INTO ai_settings (id, enabled, provider, model, embeddings_provider, "
        "daily_call_limit, daily_token_limit) "
        "VALUES (1, false, 'openai', 'gpt-4.1-mini', 'local', 200, 200000)"
    )
    op.execute(
        "INSERT INTO prometheus_settings (id, mode, approval_ttl_minutes) "
        "VALUES (1, 'autonomo', 30)"
    )
    for action, risk, threshold, enabled, per_hour in _POLICIES:
        op.execute(
            "INSERT INTO autonomy_policies (action_type, risk_class, threshold, enabled, "
            f"max_per_hour) VALUES ('{action}', '{risk}', {threshold}, {enabled}, {per_hour})"
        )


def downgrade() -> None:
    op.execute("DELETE FROM alerts WHERE kind IN ('previsao_risco', 'anomalia_detectada')")
    op.drop_constraint(op.f("ck_alerts_alert_kind"), "alerts", type_="check")
    op.create_check_constraint(op.f("ck_alerts_alert_kind"), "alerts", f"kind IN ({_ALERT_KINDS_OLD})")
    op.drop_index('ix_averted_faults_averted_at', table_name='averted_faults')
    op.drop_table('averted_faults')
    op.drop_index('ix_kb_chunks_embedding_provider', table_name='kb_chunks', postgresql_using='hnsw', postgresql_ops={'embedding_provider': 'vector_cosine_ops'})
    op.drop_index('ix_kb_chunks_embedding_local', table_name='kb_chunks', postgresql_using='hnsw', postgresql_ops={'embedding_local': 'vector_cosine_ops'})
    op.drop_index('ix_kb_chunks_document', table_name='kb_chunks')
    op.drop_table('kb_chunks')
    op.drop_index('uq_anomaly_detections_open', table_name='anomaly_detections', postgresql_where=sa.text("outcome = 'pendente'"))
    op.drop_index('ix_anomaly_detections_detected_at', table_name='anomaly_detections')
    op.drop_table('anomaly_detections')
    op.drop_index('uq_agent_decisions_pending_situation', table_name='agent_decisions', postgresql_where=sa.text("status = 'pendente'"))
    op.drop_index('ix_agent_decisions_status', table_name='agent_decisions')
    op.drop_index('ix_agent_decisions_created_at', table_name='agent_decisions')
    op.drop_table('agent_decisions')
    op.drop_table('prometheus_settings')
    op.drop_table('prediction_snapshots')
    op.drop_table('kb_documents')
    op.drop_index('ix_city_events_starts_at', table_name='city_events')
    op.drop_table('city_events')
    op.drop_table('autonomy_policies')
    op.drop_table('ai_settings')
    op.drop_index('ix_prediction_models_kind_fitted', table_name='prediction_models')
    op.drop_table('prediction_models')
    op.drop_index('ix_ai_usage_at', table_name='ai_usage')
    op.drop_table('ai_usage')
