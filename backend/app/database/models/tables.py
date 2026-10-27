"""Tabelas do banco (estrutura de persistência, sem regra de negócio).

Os repositórios convertem estes modelos em objetos de domínio (padrão Data Mapper).
"""

import uuid
from datetime import date, datetime
from typing import Any

from geoalchemy2 import Geography, Geometry
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.permissions import Role
from app.database.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin, str_enum
from app.domain.agents.entities import AgentRole, DutyStatus
from app.domain.equipment.entities import EquipmentCategory
from app.domain.equipment.status import EquipmentStatus
from app.domain.maintenance.entities import (
    MaintenanceKind,
    MaintenanceNeed,
    MaintenanceOrderStatus,
    MaintenancePriority,
)
from app.domain.operations.alerts import AlertKind, AlertSeverity, AlertStatus
from app.domain.operations.dispatch import DispatchStatus
from app.domain.organizations import OrganizationKind
from app.domain.shared import UF

_OPEN_ORDER_SQL = "status IN ('aberta', 'em_andamento')"


class UserModel(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(254), nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[Role] = mapped_column(str_enum(Role, "user_role"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    __table_args__ = (Index("uq_users_email_lower", func.lower(text("email")), unique=True),)


class OrganizationModel(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    acronym: Mapped[str] = mapped_column(String(20), nullable=False)
    kind: Mapped[OrganizationKind] = mapped_column(
        str_enum(OrganizationKind, "organization_kind"), nullable=False
    )

    __table_args__ = (
        Index("uq_organizations_name_lower", func.lower(text("name")), unique=True),
        Index("uq_organizations_acronym_lower", func.lower(text("acronym")), unique=True),
    )


class RegionModel(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "regions"

    code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    geom: Mapped[Any] = mapped_column(
        Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=False), nullable=False
    )

    __table_args__ = (Index("ix_regions_geom", "geom", postgresql_using="gist"),)


class EquipmentTypeModel(Base):
    __tablename__ = "equipment_types"

    code: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[EquipmentCategory] = mapped_column(
        str_enum(EquipmentCategory, "equipment_category"), nullable=False
    )
    icon: Mapped[str] = mapped_column(String(40), nullable=False)
    is_mobile: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_vehicle: Mapped[bool] = mapped_column(Boolean, nullable=False)
    attributes_schema_key: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AddressColumnsMixin:
    cep: Mapped[str] = mapped_column(String(8), nullable=False)
    street: Mapped[str] = mapped_column(String(150), nullable=False)
    address_reference: Mapped[str | None] = mapped_column(String(150))
    neighborhood: Mapped[str] = mapped_column(String(100), nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    uf: Mapped[UF] = mapped_column(str_enum(UF, "uf"), nullable=False)
    location: Mapped[Any] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False), nullable=False
    )


class EquipmentModel(UuidPrimaryKeyMixin, TimestampMixin, AddressColumnsMixin, Base):
    __tablename__ = "equipment"

    type_code: Mapped[str] = mapped_column(ForeignKey("equipment_types.code"), nullable=False)
    serial_number: Mapped[str] = mapped_column(String(80), nullable=False)
    brand: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False
    )
    status: Mapped[EquipmentStatus] = mapped_column(
        str_enum(EquipmentStatus, "equipment_status"), nullable=False
    )
    region_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("regions.id"))
    installed_on: Mapped[date | None] = mapped_column(Date)
    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    # Retrato de manutenção desnormalizado pelo serviço (mesma transação) para permitir
    # filtrar e ordenar por necessidade/data no banco, com índice.
    maintenance_need: Mapped[MaintenanceNeed] = mapped_column(
        str_enum(MaintenanceNeed, "maintenance_need"), nullable=False, server_default="nenhuma"
    )
    next_maintenance_date: Mapped[date | None] = mapped_column(Date)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Telemetria (Parte 2): último contato do dispositivo e últimas métricas recebidas.
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_telemetry: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    last_reading_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index(
            "uq_equipment_brand_serial_active",
            func.lower(text("brand")),
            func.lower(text("serial_number")),
            unique=True,
            postgresql_where=text("archived_at IS NULL"),
        ),
        Index("ix_equipment_location", "location", postgresql_using="gist"),
        Index("ix_equipment_status", "status"),
        Index("ix_equipment_type_code", "type_code"),
        Index("ix_equipment_organization_id", "organization_id"),
        Index("ix_equipment_region_id", "region_id"),
        Index("ix_equipment_neighborhood_lower", func.lower(text("neighborhood"))),
        Index("ix_equipment_next_maintenance_date", "next_maintenance_date"),
        Index("ix_equipment_attributes", "attributes", postgresql_using="gin"),
        Index("ix_equipment_last_seen_at", "last_seen_at"),
        CheckConstraint("version >= 1", name="version_positive"),
    )


class EquipmentStatusHistoryModel(Base):
    __tablename__ = "equipment_status_history"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    equipment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("equipment.id", ondelete="CASCADE"), nullable=False
    )
    from_status: Mapped[EquipmentStatus | None] = mapped_column(
        str_enum(EquipmentStatus, "from_status")
    )
    to_status: Mapped[EquipmentStatus] = mapped_column(
        str_enum(EquipmentStatus, "to_status"), nullable=False
    )
    reason: Mapped[str | None] = mapped_column(String(500))
    changed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_equipment_status_history_equipment_changed", "equipment_id", "changed_at"),
        Index("ix_equipment_status_history_changed_at", "changed_at"),
    )


class MaintenancePlanModel(TimestampMixin, Base):
    __tablename__ = "maintenance_plans"

    equipment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("equipment.id", ondelete="CASCADE"), primary_key=True
    )
    interval_days: Mapped[int] = mapped_column(Integer, nullable=False)
    next_due_date: Mapped[date] = mapped_column(Date, nullable=False)
    last_done_on: Mapped[date | None] = mapped_column(Date)

    __table_args__ = (
        CheckConstraint("interval_days > 0", name="interval_positive"),
        Index("ix_maintenance_plans_next_due_date", "next_due_date"),
    )


class MaintenanceOrderModel(UuidPrimaryKeyMixin, Base):
    __tablename__ = "maintenance_orders"

    equipment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("equipment.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[MaintenanceKind] = mapped_column(
        str_enum(MaintenanceKind, "maintenance_kind"), nullable=False
    )
    priority: Mapped[MaintenancePriority] = mapped_column(
        str_enum(MaintenancePriority, "maintenance_priority"), nullable=False
    )
    status: Mapped[MaintenanceOrderStatus] = mapped_column(
        str_enum(MaintenanceOrderStatus, "maintenance_order_status"), nullable=False
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    scheduled_for: Mapped[date | None] = mapped_column(Date)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    opened_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    resolution_notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        # No máximo uma ordem aberta por equipamento e tipo: torna idempotentes a
        # abertura automática por defeito e o job de preventivas.
        Index(
            "uq_maintenance_orders_open_per_kind",
            "equipment_id",
            "kind",
            unique=True,
            postgresql_where=text(_OPEN_ORDER_SQL),
        ),
        Index("ix_maintenance_orders_equipment_opened", "equipment_id", "opened_at"),
        Index("ix_maintenance_orders_status", "status"),
    )


class AgentModel(UuidPrimaryKeyMixin, TimestampMixin, AddressColumnsMixin, Base):
    """Agente; as colunas de endereço/``location`` representam a base de lotação."""

    __tablename__ = "agents"

    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    registration_number: Mapped[str] = mapped_column(String(30), nullable=False)
    role: Mapped[AgentRole] = mapped_column(str_enum(AgentRole, "agent_role"), nullable=False)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False
    )
    duty_status: Mapped[DutyStatus] = mapped_column(
        str_enum(DutyStatus, "duty_status"), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    region_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("regions.id"))
    assigned_vehicle_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("equipment.id"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Posição em tempo real (GPS); a coluna ``location`` continua sendo a base de lotação.
    current_location: Mapped[Any | None] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False)
    )
    last_position_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index(
            "uq_agents_org_registration_active",
            "organization_id",
            func.lower(text("registration_number")),
            unique=True,
            postgresql_where=text("archived_at IS NULL"),
        ),
        Index("ix_agents_location", "location", postgresql_using="gist"),
        Index("ix_agents_duty_status", "duty_status"),
        Index("ix_agents_region_id", "region_id"),
        Index("ix_agents_assigned_vehicle_id", "assigned_vehicle_id"),
        Index("ix_agents_current_location", "current_location", postgresql_using="gist"),
        CheckConstraint("version >= 1", name="version_positive"),
    )


class AgentStatusHistoryModel(Base):
    __tablename__ = "agent_status_history"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    from_status: Mapped[DutyStatus | None] = mapped_column(str_enum(DutyStatus, "from_status"))
    to_status: Mapped[DutyStatus] = mapped_column(str_enum(DutyStatus, "to_status"), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500))
    changed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_agent_status_history_agent_changed", "agent_id", "changed_at"),
        Index("ix_agent_status_history_changed_at", "changed_at"),
    )


class TelemetryReadingModel(Base):
    """Série temporal amostrada de métricas dos dispositivos (insumo da Parte 3)."""

    __tablename__ = "telemetry_readings"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    equipment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("equipment.id", ondelete="CASCADE"), nullable=False
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        Index("ix_telemetry_readings_equipment_recorded", "equipment_id", "recorded_at"),
        Index("ix_telemetry_readings_recorded_at", "recorded_at"),
    )


class AgentPositionModel(Base):
    __tablename__ = "agent_positions"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    location: Mapped[Any] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False), nullable=False
    )

    __table_args__ = (
        Index("ix_agent_positions_agent_recorded", "agent_id", "recorded_at"),
        Index("ix_agent_positions_recorded_at", "recorded_at"),
    )


class AlertModel(UuidPrimaryKeyMixin, Base):
    __tablename__ = "alerts"

    kind: Mapped[AlertKind] = mapped_column(str_enum(AlertKind, "alert_kind"), nullable=False)
    severity: Mapped[AlertSeverity] = mapped_column(
        str_enum(AlertSeverity, "alert_severity"), nullable=False
    )
    status: Mapped[AlertStatus] = mapped_column(
        str_enum(AlertStatus, "alert_status"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    dedup_key: Mapped[str] = mapped_column(String(120), nullable=False)
    equipment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("equipment.id", ondelete="CASCADE")
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    region_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("regions.id"))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sla_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_occurrence_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    occurrences: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    resolution_note: Mapped[str | None] = mapped_column(String(500))
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (
        # Um único alerta aberto por (tipo, sujeito): repetições só atualizam a ocorrência.
        Index(
            "uq_alerts_open_dedup_key",
            "dedup_key",
            unique=True,
            postgresql_where=text("status <> 'resolvido'"),
        ),
        Index("ix_alerts_status_severity", "status", "severity"),
        Index("ix_alerts_opened_at", "opened_at"),
        Index("ix_alerts_equipment_id", "equipment_id"),
        Index("ix_alerts_region_id", "region_id"),
    )


class DispatchModel(UuidPrimaryKeyMixin, Base):
    __tablename__ = "dispatches"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    equipment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("equipment.id", ondelete="CASCADE"), nullable=False
    )
    alert_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("alerts.id", ondelete="SET NULL"))
    status: Mapped[DispatchStatus] = mapped_column(
        str_enum(DispatchStatus, "dispatch_status"), nullable=False
    )
    target: Mapped[Any] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False), nullable=False
    )
    origin: Mapped[Any] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False), nullable=False
    )
    distance_m: Mapped[float] = mapped_column(Float, nullable=False)
    eta_minutes: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    departed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    arrived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(String(500))

    __table_args__ = (
        # Um agente atende uma ocorrência por vez.
        Index(
            "uq_dispatches_active_agent",
            "agent_id",
            unique=True,
            postgresql_where=text("status IN ('designado', 'a_caminho', 'no_local')"),
        ),
        Index("ix_dispatches_equipment_id", "equipment_id"),
        Index("ix_dispatches_created_at", "created_at"),
    )
