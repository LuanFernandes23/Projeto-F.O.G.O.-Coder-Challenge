"""Schema inicial do inventário (Parte 1 do F.O.G.O.)

Revision ID: 0001
Revises:
Create Date: 2026-10-23 00:35:22.703737
"""

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.create_table('equipment_types',
    sa.Column('code', sa.String(length=50), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('category', sa.Enum('fiscalizacao', 'monitoramento', 'controle_trafego', 'controle_acesso', 'transporte', 'micromobilidade', 'atendimento', 'frota_operacional', 'outro', name='equipment_category', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('icon', sa.String(length=40), nullable=False),
    sa.Column('is_mobile', sa.Boolean(), nullable=False),
    sa.Column('is_vehicle', sa.Boolean(), nullable=False),
    sa.Column('attributes_schema_key', sa.String(length=50), nullable=False),
    sa.Column('description', sa.String(length=300), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('code', name=op.f('pk_equipment_types'))
    )
    op.create_table('organizations',
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.Column('acronym', sa.String(length=20), nullable=False),
    sa.Column('kind', sa.Enum('transito', 'guarda_municipal', 'policia_militar', 'concessionaria', 'outro', name='organization_kind', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_organizations'))
    )
    op.create_index('uq_organizations_acronym_lower', 'organizations', [sa.literal_column('lower(acronym)')], unique=True)
    op.create_index('uq_organizations_name_lower', 'organizations', [sa.literal_column('lower(name)')], unique=True)
    op.create_table('regions',
    sa.Column('code', sa.String(length=40), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('geom', geoalchemy2.types.Geometry(geometry_type='MULTIPOLYGON', srid=4326, dimension=2, spatial_index=False, from_text='ST_GeomFromEWKT', name='geometry', nullable=False), nullable=False),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_regions')),
    sa.UniqueConstraint('code', name=op.f('uq_regions_code'))
    )
    op.create_index('ix_regions_geom', 'regions', ['geom'], unique=False, postgresql_using='gist')
    op.create_table('users',
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('full_name', sa.String(length=120), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('role', sa.Enum('admin', 'gestor', 'operador', 'consulta', name='user_role', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users'))
    )
    op.create_index('uq_users_email_lower', 'users', [sa.literal_column('lower(email)')], unique=True)
    op.create_table('equipment',
    sa.Column('type_code', sa.String(length=50), nullable=False),
    sa.Column('serial_number', sa.String(length=80), nullable=False),
    sa.Column('brand', sa.String(length=80), nullable=False),
    sa.Column('model', sa.String(length=80), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.Enum('nao_instalado', 'operacional', 'mau_funcionamento', 'em_manutencao', 'desativado', 'furtado', name='equipment_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('region_id', sa.Uuid(), nullable=True),
    sa.Column('installed_on', sa.Date(), nullable=True),
    sa.Column('attributes', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('maintenance_need', sa.Enum('imediata', 'agendada', 'nenhuma', name='maintenance_need', native_enum=False, create_constraint=True, length=32), server_default='nenhuma', nullable=False),
    sa.Column('next_maintenance_date', sa.Date(), nullable=True),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('cep', sa.String(length=8), nullable=False),
    sa.Column('street', sa.String(length=150), nullable=False),
    sa.Column('address_reference', sa.String(length=150), nullable=True),
    sa.Column('neighborhood', sa.String(length=100), nullable=False),
    sa.Column('city', sa.String(length=100), nullable=False),
    sa.Column('uf', sa.Enum('AC', 'AL', 'AP', 'AM', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MT', 'MS', 'MG', 'PA', 'PB', 'PR', 'PE', 'PI', 'RJ', 'RN', 'RS', 'RO', 'RR', 'SC', 'SP', 'SE', 'TO', name='uf', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('location', geoalchemy2.types.Geography(geometry_type='POINT', srid=4326, dimension=2, spatial_index=False, from_text='ST_GeogFromText', name='geography', nullable=False), nullable=False),
    sa.CheckConstraint('version >= 1', name=op.f('ck_equipment_version_positive')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_equipment_created_by_users')),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_equipment_organization_id_organizations')),
    sa.ForeignKeyConstraint(['region_id'], ['regions.id'], name=op.f('fk_equipment_region_id_regions')),
    sa.ForeignKeyConstraint(['type_code'], ['equipment_types.code'], name=op.f('fk_equipment_type_code_equipment_types')),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], name=op.f('fk_equipment_updated_by_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_equipment'))
    )
    op.create_index('ix_equipment_attributes', 'equipment', ['attributes'], unique=False, postgresql_using='gin')
    op.create_index('ix_equipment_location', 'equipment', ['location'], unique=False, postgresql_using='gist')
    op.create_index('ix_equipment_neighborhood_lower', 'equipment', [sa.literal_column('lower(neighborhood)')], unique=False)
    op.create_index('ix_equipment_next_maintenance_date', 'equipment', ['next_maintenance_date'], unique=False)
    op.create_index('ix_equipment_organization_id', 'equipment', ['organization_id'], unique=False)
    op.create_index('ix_equipment_region_id', 'equipment', ['region_id'], unique=False)
    op.create_index('ix_equipment_status', 'equipment', ['status'], unique=False)
    op.create_index('ix_equipment_type_code', 'equipment', ['type_code'], unique=False)
    op.create_index('uq_equipment_brand_serial_active', 'equipment', [sa.literal_column('lower(brand)'), sa.literal_column('lower(serial_number)')], unique=True, postgresql_where=sa.text('archived_at IS NULL'))
    op.create_table('agents',
    sa.Column('full_name', sa.String(length=120), nullable=False),
    sa.Column('registration_number', sa.String(length=30), nullable=False),
    sa.Column('role', sa.Enum('agente_transito', 'guarda_municipal', 'policial_militar', 'outro', name='agent_role', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('duty_status', sa.Enum('disponivel', 'em_patrulha', 'em_ocorrencia', 'em_pausa', 'fora_de_servico', 'afastado', name='duty_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('region_id', sa.Uuid(), nullable=True),
    sa.Column('assigned_vehicle_id', sa.Uuid(), nullable=True),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('cep', sa.String(length=8), nullable=False),
    sa.Column('street', sa.String(length=150), nullable=False),
    sa.Column('address_reference', sa.String(length=150), nullable=True),
    sa.Column('neighborhood', sa.String(length=100), nullable=False),
    sa.Column('city', sa.String(length=100), nullable=False),
    sa.Column('uf', sa.Enum('AC', 'AL', 'AP', 'AM', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MT', 'MS', 'MG', 'PA', 'PB', 'PR', 'PE', 'PI', 'RJ', 'RN', 'RS', 'RO', 'RR', 'SC', 'SP', 'SE', 'TO', name='uf', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('location', geoalchemy2.types.Geography(geometry_type='POINT', srid=4326, dimension=2, spatial_index=False, from_text='ST_GeogFromText', name='geography', nullable=False), nullable=False),
    sa.CheckConstraint('version >= 1', name=op.f('ck_agents_version_positive')),
    sa.ForeignKeyConstraint(['assigned_vehicle_id'], ['equipment.id'], name=op.f('fk_agents_assigned_vehicle_id_equipment')),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_agents_organization_id_organizations')),
    sa.ForeignKeyConstraint(['region_id'], ['regions.id'], name=op.f('fk_agents_region_id_regions')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_agents'))
    )
    op.create_index('ix_agents_assigned_vehicle_id', 'agents', ['assigned_vehicle_id'], unique=False)
    op.create_index('ix_agents_duty_status', 'agents', ['duty_status'], unique=False)
    op.create_index('ix_agents_location', 'agents', ['location'], unique=False, postgresql_using='gist')
    op.create_index('ix_agents_region_id', 'agents', ['region_id'], unique=False)
    op.create_index('uq_agents_org_registration_active', 'agents', ['organization_id', sa.literal_column('lower(registration_number)')], unique=True, postgresql_where=sa.text('archived_at IS NULL'))
    op.create_table('equipment_status_history',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('equipment_id', sa.Uuid(), nullable=False),
    sa.Column('from_status', sa.Enum('nao_instalado', 'operacional', 'mau_funcionamento', 'em_manutencao', 'desativado', 'furtado', name='from_status', native_enum=False, create_constraint=True, length=32), nullable=True),
    sa.Column('to_status', sa.Enum('nao_instalado', 'operacional', 'mau_funcionamento', 'em_manutencao', 'desativado', 'furtado', name='to_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('reason', sa.String(length=500), nullable=True),
    sa.Column('changed_by', sa.Uuid(), nullable=True),
    sa.Column('changed_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['changed_by'], ['users.id'], name=op.f('fk_equipment_status_history_changed_by_users')),
    sa.ForeignKeyConstraint(['equipment_id'], ['equipment.id'], name=op.f('fk_equipment_status_history_equipment_id_equipment'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_equipment_status_history'))
    )
    op.create_index('ix_equipment_status_history_changed_at', 'equipment_status_history', ['changed_at'], unique=False)
    op.create_index('ix_equipment_status_history_equipment_changed', 'equipment_status_history', ['equipment_id', 'changed_at'], unique=False)
    op.create_table('maintenance_orders',
    sa.Column('equipment_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.Enum('corretiva', 'preventiva', name='maintenance_kind', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('priority', sa.Enum('imediata', 'agendada', name='maintenance_priority', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('status', sa.Enum('aberta', 'em_andamento', 'concluida', 'cancelada', name='maintenance_order_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('scheduled_for', sa.Date(), nullable=True),
    sa.Column('opened_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('opened_by', sa.Uuid(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('closed_by', sa.Uuid(), nullable=True),
    sa.Column('resolution_notes', sa.Text(), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.ForeignKeyConstraint(['closed_by'], ['users.id'], name=op.f('fk_maintenance_orders_closed_by_users')),
    sa.ForeignKeyConstraint(['equipment_id'], ['equipment.id'], name=op.f('fk_maintenance_orders_equipment_id_equipment'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['opened_by'], ['users.id'], name=op.f('fk_maintenance_orders_opened_by_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_maintenance_orders'))
    )
    op.create_index('ix_maintenance_orders_equipment_opened', 'maintenance_orders', ['equipment_id', 'opened_at'], unique=False)
    op.create_index('ix_maintenance_orders_status', 'maintenance_orders', ['status'], unique=False)
    op.create_index('uq_maintenance_orders_open_per_kind', 'maintenance_orders', ['equipment_id', 'kind'], unique=True, postgresql_where=sa.text("status IN ('aberta', 'em_andamento')"))
    op.create_table('maintenance_plans',
    sa.Column('equipment_id', sa.Uuid(), nullable=False),
    sa.Column('interval_days', sa.Integer(), nullable=False),
    sa.Column('next_due_date', sa.Date(), nullable=False),
    sa.Column('last_done_on', sa.Date(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('interval_days > 0', name=op.f('ck_maintenance_plans_interval_positive')),
    sa.ForeignKeyConstraint(['equipment_id'], ['equipment.id'], name=op.f('fk_maintenance_plans_equipment_id_equipment'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('equipment_id', name=op.f('pk_maintenance_plans'))
    )
    op.create_index('ix_maintenance_plans_next_due_date', 'maintenance_plans', ['next_due_date'], unique=False)
    op.create_table('agent_status_history',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('agent_id', sa.Uuid(), nullable=False),
    sa.Column('from_status', sa.Enum('disponivel', 'em_patrulha', 'em_ocorrencia', 'em_pausa', 'fora_de_servico', 'afastado', name='from_status', native_enum=False, create_constraint=True, length=32), nullable=True),
    sa.Column('to_status', sa.Enum('disponivel', 'em_patrulha', 'em_ocorrencia', 'em_pausa', 'fora_de_servico', 'afastado', name='to_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('reason', sa.String(length=500), nullable=True),
    sa.Column('changed_by', sa.Uuid(), nullable=True),
    sa.Column('changed_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], name=op.f('fk_agent_status_history_agent_id_agents'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['changed_by'], ['users.id'], name=op.f('fk_agent_status_history_changed_by_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_agent_status_history'))
    )
    op.create_index('ix_agent_status_history_agent_changed', 'agent_status_history', ['agent_id', 'changed_at'], unique=False)
    op.create_index('ix_agent_status_history_changed_at', 'agent_status_history', ['changed_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_agent_status_history_changed_at', table_name='agent_status_history')
    op.drop_index('ix_agent_status_history_agent_changed', table_name='agent_status_history')
    op.drop_table('agent_status_history')
    op.drop_index('ix_maintenance_plans_next_due_date', table_name='maintenance_plans')
    op.drop_table('maintenance_plans')
    op.drop_index('uq_maintenance_orders_open_per_kind', table_name='maintenance_orders', postgresql_where=sa.text("status IN ('aberta', 'em_andamento')"))
    op.drop_index('ix_maintenance_orders_status', table_name='maintenance_orders')
    op.drop_index('ix_maintenance_orders_equipment_opened', table_name='maintenance_orders')
    op.drop_table('maintenance_orders')
    op.drop_index('ix_equipment_status_history_equipment_changed', table_name='equipment_status_history')
    op.drop_index('ix_equipment_status_history_changed_at', table_name='equipment_status_history')
    op.drop_table('equipment_status_history')
    op.drop_index('uq_agents_org_registration_active', table_name='agents', postgresql_where=sa.text('archived_at IS NULL'))
    op.drop_index('ix_agents_region_id', table_name='agents')
    op.drop_index('ix_agents_location', table_name='agents', postgresql_using='gist')
    op.drop_index('ix_agents_duty_status', table_name='agents')
    op.drop_index('ix_agents_assigned_vehicle_id', table_name='agents')
    op.drop_table('agents')
    op.drop_index('uq_equipment_brand_serial_active', table_name='equipment', postgresql_where=sa.text('archived_at IS NULL'))
    op.drop_index('ix_equipment_type_code', table_name='equipment')
    op.drop_index('ix_equipment_status', table_name='equipment')
    op.drop_index('ix_equipment_region_id', table_name='equipment')
    op.drop_index('ix_equipment_organization_id', table_name='equipment')
    op.drop_index('ix_equipment_next_maintenance_date', table_name='equipment')
    op.drop_index('ix_equipment_neighborhood_lower', table_name='equipment')
    op.drop_index('ix_equipment_location', table_name='equipment', postgresql_using='gist')
    op.drop_index('ix_equipment_attributes', table_name='equipment', postgresql_using='gin')
    op.drop_table('equipment')
    op.drop_index('uq_users_email_lower', table_name='users')
    op.drop_table('users')
    op.drop_index('ix_regions_geom', table_name='regions', postgresql_using='gist')
    op.drop_table('regions')
    op.drop_index('uq_organizations_name_lower', table_name='organizations')
    op.drop_index('uq_organizations_acronym_lower', table_name='organizations')
    op.drop_table('organizations')
    op.drop_table('equipment_types')
