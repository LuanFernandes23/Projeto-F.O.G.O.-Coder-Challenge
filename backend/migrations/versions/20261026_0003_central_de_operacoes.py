"""Central de Operações (Parte 2): telemetria, posições, alertas e despachos

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-26 16:12:25.231511
"""

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0003'
down_revision: str | None = '0002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('telemetry_readings',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('equipment_id', sa.Uuid(), nullable=False),
    sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('metrics', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.ForeignKeyConstraint(['equipment_id'], ['equipment.id'], name=op.f('fk_telemetry_readings_equipment_id_equipment'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_telemetry_readings'))
    )
    op.create_index('ix_telemetry_readings_equipment_recorded', 'telemetry_readings', ['equipment_id', 'recorded_at'], unique=False)
    op.create_index('ix_telemetry_readings_recorded_at', 'telemetry_readings', ['recorded_at'], unique=False)
    op.create_table('agent_positions',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('agent_id', sa.Uuid(), nullable=False),
    sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('location', geoalchemy2.types.Geography(geometry_type='POINT', srid=4326, dimension=2, spatial_index=False, from_text='ST_GeogFromText', name='geography', nullable=False), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], name=op.f('fk_agent_positions_agent_id_agents'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_agent_positions'))
    )
    op.create_index('ix_agent_positions_agent_recorded', 'agent_positions', ['agent_id', 'recorded_at'], unique=False)
    op.create_index('ix_agent_positions_recorded_at', 'agent_positions', ['recorded_at'], unique=False)
    op.create_table('alerts',
    sa.Column('kind', sa.Enum('falha_equipamento', 'furto', 'equipamento_offline', 'manutencao_vencida', 'regiao_degradada', 'bateria_baixa', name='alert_kind', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('severity', sa.Enum('critica', 'alta', 'media', 'baixa', name='alert_severity', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('status', sa.Enum('aberto', 'reconhecido', 'resolvido', name='alert_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('dedup_key', sa.String(length=120), nullable=False),
    sa.Column('equipment_id', sa.Uuid(), nullable=True),
    sa.Column('agent_id', sa.Uuid(), nullable=True),
    sa.Column('region_id', sa.Uuid(), nullable=True),
    sa.Column('opened_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('sla_due_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_occurrence_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('occurrences', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('acknowledged_by', sa.Uuid(), nullable=True),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('resolved_by', sa.Uuid(), nullable=True),
    sa.Column('resolution_note', sa.String(length=500), nullable=True),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.ForeignKeyConstraint(['acknowledged_by'], ['users.id'], name=op.f('fk_alerts_acknowledged_by_users')),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], name=op.f('fk_alerts_agent_id_agents'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['equipment_id'], ['equipment.id'], name=op.f('fk_alerts_equipment_id_equipment'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['region_id'], ['regions.id'], name=op.f('fk_alerts_region_id_regions')),
    sa.ForeignKeyConstraint(['resolved_by'], ['users.id'], name=op.f('fk_alerts_resolved_by_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_alerts'))
    )
    op.create_index('ix_alerts_equipment_id', 'alerts', ['equipment_id'], unique=False)
    op.create_index('ix_alerts_opened_at', 'alerts', ['opened_at'], unique=False)
    op.create_index('ix_alerts_region_id', 'alerts', ['region_id'], unique=False)
    op.create_index('ix_alerts_status_severity', 'alerts', ['status', 'severity'], unique=False)
    op.create_index('uq_alerts_open_dedup_key', 'alerts', ['dedup_key'], unique=True, postgresql_where=sa.text("status <> 'resolvido'"))
    op.create_table('dispatches',
    sa.Column('agent_id', sa.Uuid(), nullable=False),
    sa.Column('equipment_id', sa.Uuid(), nullable=False),
    sa.Column('alert_id', sa.Uuid(), nullable=True),
    sa.Column('status', sa.Enum('designado', 'a_caminho', 'no_local', 'concluido', 'cancelado', name='dispatch_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('target', geoalchemy2.types.Geography(geometry_type='POINT', srid=4326, dimension=2, spatial_index=False, from_text='ST_GeogFromText', name='geography', nullable=False), nullable=False),
    sa.Column('origin', geoalchemy2.types.Geography(geometry_type='POINT', srid=4326, dimension=2, spatial_index=False, from_text='ST_GeogFromText', name='geography', nullable=False), nullable=False),
    sa.Column('distance_m', sa.Float(), nullable=False),
    sa.Column('eta_minutes', sa.Float(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('departed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('arrived_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('notes', sa.String(length=500), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], name=op.f('fk_dispatches_agent_id_agents'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['alert_id'], ['alerts.id'], name=op.f('fk_dispatches_alert_id_alerts'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_dispatches_created_by_users')),
    sa.ForeignKeyConstraint(['equipment_id'], ['equipment.id'], name=op.f('fk_dispatches_equipment_id_equipment'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_dispatches'))
    )
    op.create_index('ix_dispatches_created_at', 'dispatches', ['created_at'], unique=False)
    op.create_index('ix_dispatches_equipment_id', 'dispatches', ['equipment_id'], unique=False)
    op.create_index('uq_dispatches_active_agent', 'dispatches', ['agent_id'], unique=True, postgresql_where=sa.text("status IN ('designado', 'a_caminho', 'no_local')"))
    op.add_column('agents', sa.Column('current_location', geoalchemy2.types.Geography(geometry_type='POINT', srid=4326, dimension=2, spatial_index=False, from_text='ST_GeogFromText', name='geography'), nullable=True))
    op.add_column('agents', sa.Column('last_position_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_agents_current_location', 'agents', ['current_location'], unique=False, postgresql_using='gist')
    op.add_column('equipment', sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('equipment', sa.Column('last_telemetry', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('equipment', sa.Column('last_reading_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_equipment_last_seen_at', 'equipment', ['last_seen_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_equipment_last_seen_at', table_name='equipment')
    op.drop_column('equipment', 'last_reading_at')
    op.drop_column('equipment', 'last_telemetry')
    op.drop_column('equipment', 'last_seen_at')
    op.drop_index('ix_agents_current_location', table_name='agents', postgresql_using='gist')
    op.drop_column('agents', 'last_position_at')
    op.drop_column('agents', 'current_location')
    op.drop_index('uq_dispatches_active_agent', table_name='dispatches', postgresql_where=sa.text("status IN ('designado', 'a_caminho', 'no_local')"))
    op.drop_index('ix_dispatches_equipment_id', table_name='dispatches')
    op.drop_index('ix_dispatches_created_at', table_name='dispatches')
    op.drop_table('dispatches')
    op.drop_index('uq_alerts_open_dedup_key', table_name='alerts', postgresql_where=sa.text("status <> 'resolvido'"))
    op.drop_index('ix_alerts_status_severity', table_name='alerts')
    op.drop_index('ix_alerts_region_id', table_name='alerts')
    op.drop_index('ix_alerts_opened_at', table_name='alerts')
    op.drop_index('ix_alerts_equipment_id', table_name='alerts')
    op.drop_table('alerts')
    op.drop_index('ix_agent_positions_recorded_at', table_name='agent_positions')
    op.drop_index('ix_agent_positions_agent_recorded', table_name='agent_positions')
    op.drop_table('agent_positions')
    op.drop_index('ix_telemetry_readings_recorded_at', table_name='telemetry_readings')
    op.drop_index('ix_telemetry_readings_equipment_recorded', table_name='telemetry_readings')
    op.drop_table('telemetry_readings')
