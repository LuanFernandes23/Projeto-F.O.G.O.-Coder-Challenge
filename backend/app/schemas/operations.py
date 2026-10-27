"""Contratos da Central de Operações: KPIs, mapa, regiões, alertas, despachos e telemetria."""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.agents.entities import DUTY_STATUS_LABELS, ON_DUTY_STATUSES, AgentRole, DutyStatus
from app.domain.equipment.status import EquipmentStatus
from app.domain.maintenance.entities import MaintenanceNeed
from app.domain.operations.alerts import (
    KIND_LABELS,
    SEVERITY_LABELS,
    AlertKind,
    AlertSeverity,
    AlertStatus,
    AlertView,
)
from app.domain.operations.dispatch import DISPATCH_LABELS, DispatchRecord, DispatchStatus
from app.domain.operations.read_models import (
    MapAgentFeature,
    MapEquipmentFeature,
    OperationsOverview,
)
from app.domain.operations.region_health import HEALTH_LABELS, HealthLevel, RegionHealth
from app.domain.operations.telemetry import Connectivity, connectivity
from app.schemas.location import GeoPointSchema

# ---- indicadores ----------------------------------------------------------------------


class TypeBreakdownOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    type_code: str
    type_name: str
    icon: str
    total: int
    operational: int
    unavailable: int


class OverviewOutput(BaseModel):
    generated_at: datetime
    total_equipment: int
    operational: int
    unavailable: int
    availability_pct: float = Field(
        description="operacional / (operacional + mau funcionamento + em manutenção + furtado)."
    )
    by_status: dict[EquipmentStatus, int]
    online: int
    offline: int
    without_telemetry: int
    agents_active: int
    agents_on_duty: int
    agents_dispatched: int
    alerts_open: int
    alerts_by_severity: dict[AlertSeverity, int]
    alerts_sla_breached: int
    maintenance_immediate: int
    maintenance_due_soon: int
    maintenance_overdue: int
    by_type: list[TypeBreakdownOutput]

    @classmethod
    def from_domain(cls, o: OperationsOverview) -> "OverviewOutput":
        return cls(
            generated_at=o.generated_at,
            total_equipment=o.total_equipment,
            operational=o.operational,
            unavailable=o.unavailable,
            availability_pct=o.availability_pct,
            by_status={s: o.by_status.get(s, 0) for s in EquipmentStatus},
            online=o.connectivity.online,
            offline=o.connectivity.offline,
            without_telemetry=o.connectivity.without_telemetry,
            agents_active=o.agents.active,
            agents_on_duty=o.agents.on_duty,
            agents_dispatched=o.agents.dispatched,
            alerts_open=o.alerts.total,
            alerts_by_severity={s: o.alerts.by_severity.get(s, 0) for s in AlertSeverity},
            alerts_sla_breached=o.alerts.sla_breached,
            maintenance_immediate=o.maintenance.immediate,
            maintenance_due_soon=o.maintenance.due_soon,
            maintenance_overdue=o.maintenance.overdue,
            by_type=[TypeBreakdownOutput.model_validate(t) for t in o.by_type],
        )


# ---- mapa -----------------------------------------------------------------------------


class MapEquipmentOutput(BaseModel):
    id: UUID
    type_code: str
    serial_number: str
    status: EquipmentStatus
    lat: float
    lng: float
    region_id: UUID | None
    organization_id: UUID
    neighborhood: str
    maintenance_need: MaintenanceNeed
    next_maintenance_date: date | None
    connectivity: Connectivity
    last_seen_at: datetime | None
    open_alerts: int
    top_alert_severity: AlertSeverity | None

    @classmethod
    def from_domain(cls, f: MapEquipmentFeature, now: datetime) -> "MapEquipmentOutput":
        return cls(
            id=f.id,
            type_code=f.type_code,
            serial_number=f.serial_number,
            status=f.status,
            lat=f.latitude,
            lng=f.longitude,
            region_id=f.region_id,
            organization_id=f.organization_id,
            neighborhood=f.neighborhood,
            maintenance_need=f.maintenance_need,
            next_maintenance_date=f.next_maintenance_date,
            connectivity=connectivity(f.last_seen_at, now),
            last_seen_at=f.last_seen_at,
            open_alerts=f.open_alerts,
            top_alert_severity=f.top_alert_severity,
        )


class MapAgentOutput(BaseModel):
    id: UUID
    full_name: str
    role: AgentRole
    organization_id: UUID
    duty_status: DutyStatus
    duty_status_label: str
    on_duty: bool
    lat: float
    lng: float
    region_id: UUID | None
    live: bool = Field(description="Posição de GPS recente (senão, exibida na base).")
    last_position_at: datetime | None
    vehicle_type: str | None
    dispatch_id: UUID | None
    dispatch_status: DispatchStatus | None

    @classmethod
    def from_domain(cls, f: MapAgentFeature, now: datetime) -> "MapAgentOutput":
        return cls(
            id=f.id,
            full_name=f.full_name,
            role=f.role,
            organization_id=f.organization_id,
            duty_status=f.duty_status,
            duty_status_label=DUTY_STATUS_LABELS[f.duty_status],
            on_duty=f.duty_status in ON_DUTY_STATUSES,
            lat=f.latitude,
            lng=f.longitude,
            region_id=f.region_id,
            live=connectivity(f.last_position_at, now) is Connectivity.ONLINE,
            last_position_at=f.last_position_at,
            vehicle_type=f.vehicle_type,
            dispatch_id=f.dispatch_id,
            dispatch_status=f.dispatch_status,
        )


class MapFeaturesOutput(BaseModel):
    generated_at: datetime
    equipment: list[MapEquipmentOutput]
    agents: list[MapAgentOutput]


# ---- regiões, calor e tendências ----------------------------------------------------------


class RegionHealthOutput(BaseModel):
    region_id: UUID
    code: str
    name: str
    score: float
    level: HealthLevel
    level_label: str
    availability_pct: float
    operational: int
    unavailable: int
    offline: int
    immediate_maintenance: int
    overdue_maintenance: int
    agents_on_duty: int
    open_alerts: dict[AlertSeverity, int]
    acknowledged_alerts: dict[AlertSeverity, int]
    reasons: list[str]

    @classmethod
    def from_domain(cls, h: RegionHealth) -> "RegionHealthOutput":
        m = h.metrics
        return cls(
            region_id=m.region_id,
            code=m.code,
            name=m.name,
            score=h.score,
            level=h.level,
            level_label=HEALTH_LABELS[h.level],
            availability_pct=h.availability_pct,
            operational=m.operational,
            unavailable=m.unavailable,
            offline=m.offline,
            immediate_maintenance=m.immediate_maintenance,
            overdue_maintenance=m.overdue_maintenance,
            agents_on_duty=m.agents_on_duty,
            open_alerts={s: m.open_alerts.get(s, 0) for s in AlertSeverity},
            acknowledged_alerts={s: m.acknowledged_alerts.get(s, 0) for s in AlertSeverity},
            reasons=list(h.reasons),
        )


class HeatPointOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    latitude: float
    longitude: float
    weight: int


class TrendPointOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    day: date
    failures: int
    repairs: int
    mttr_hours: float | None


# ---- alertas ---------------------------------------------------------------------------


class AlertSubjectOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    equipment_id: UUID
    type_code: str
    type_name: str
    serial_number: str
    latitude: float
    longitude: float
    street: str
    neighborhood: str


class AlertOutput(BaseModel):
    id: UUID
    kind: AlertKind
    kind_label: str
    severity: AlertSeverity
    severity_label: str
    status: AlertStatus
    title: str
    description: str
    equipment: AlertSubjectOutput | None
    region_id: UUID | None
    region_name: str | None
    opened_at: datetime
    last_occurrence_at: datetime
    occurrences: int
    sla_due_at: datetime
    sla_remaining_seconds: int
    sla_breached: bool
    acknowledged_at: datetime | None
    acknowledged_by: UUID | None
    resolved_at: datetime | None
    resolution_note: str | None
    metadata: dict[str, Any]

    @classmethod
    def from_view(cls, view: AlertView) -> "AlertOutput":
        alert = view.record.alert
        subject = view.record.subject
        return cls(
            id=alert.id,
            kind=alert.kind,
            kind_label=KIND_LABELS[alert.kind],
            severity=alert.severity,
            severity_label=SEVERITY_LABELS[alert.severity],
            status=alert.status,
            title=alert.title,
            description=alert.description,
            equipment=AlertSubjectOutput.model_validate(subject) if subject else None,
            region_id=alert.region_id,
            region_name=view.record.region_name,
            opened_at=alert.opened_at,
            last_occurrence_at=alert.last_occurrence_at,
            occurrences=alert.occurrences,
            sla_due_at=alert.sla_due_at,
            sla_remaining_seconds=view.sla.remaining_seconds,
            sla_breached=view.sla.breached,
            acknowledged_at=alert.acknowledged_at,
            acknowledged_by=alert.acknowledged_by,
            resolved_at=alert.resolved_at,
            resolution_note=alert.resolution_note,
            metadata=alert.metadata,
        )


class AlertResolveInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    note: str = Field(min_length=3, max_length=500)


# ---- despacho --------------------------------------------------------------------------


class DispatchSuggestionOutput(BaseModel):
    agent_id: UUID
    full_name: str
    role: AgentRole
    organization_acronym: str
    duty_status: DutyStatus
    location: GeoPointSchema
    distance_m: float
    eta_minutes: float
    vehicle_type: str | None
    recommended: bool = Field(description="Primeira opção sugerida.")


class DispatchCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    equipment_id: UUID
    agent_id: UUID
    notes: str | None = Field(default=None, max_length=500)


class DispatchTransition(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    status: DispatchStatus
    notes: str | None = Field(default=None, max_length=500)


class DispatchOutput(BaseModel):
    id: UUID
    status: DispatchStatus
    status_label: str
    agent_id: UUID
    agent_name: str
    agent_role: AgentRole
    organization_acronym: str
    equipment_id: UUID
    equipment_serial: str
    equipment_type_code: str
    alert_id: UUID | None
    target: GeoPointSchema
    origin: GeoPointSchema
    distance_m: float
    eta_minutes: float
    created_at: datetime
    departed_at: datetime | None
    arrived_at: datetime | None
    closed_at: datetime | None
    notes: str | None

    @classmethod
    def from_record(cls, r: DispatchRecord) -> "DispatchOutput":
        d = r.dispatch
        return cls(
            id=d.id,
            status=d.status,
            status_label=DISPATCH_LABELS[d.status],
            agent_id=d.agent_id,
            agent_name=r.agent_name,
            agent_role=r.agent_role,
            organization_acronym=r.organization_acronym,
            equipment_id=d.equipment_id,
            equipment_serial=r.equipment_serial,
            equipment_type_code=r.equipment_type_code,
            alert_id=d.alert_id,
            target=GeoPointSchema.from_domain(d.target),
            origin=GeoPointSchema.from_domain(d.origin),
            distance_m=d.distance_m,
            eta_minutes=d.eta_minutes,
            created_at=d.created_at,
            departed_at=d.departed_at,
            arrived_at=d.arrived_at,
            closed_at=d.closed_at,
            notes=d.notes,
        )


# ---- telemetria (gateway IoT) ---------------------------------------------------------------


class HeartbeatInput(BaseModel):
    equipment_id: UUID
    recorded_at: datetime
    metrics: dict[str, float | int | str | bool | None] = Field(default_factory=dict)
    fault: str | None = Field(
        default=None, max_length=200, description="Falha autodetectada pelo dispositivo."
    )
    fault_averted: str | None = Field(
        default=None,
        max_length=60,
        description="Falha iminente que não ocorreu por causa de uma intervenção a tempo.",
    )


class HeartbeatBatchInput(BaseModel):
    heartbeats: list[HeartbeatInput] = Field(min_length=1, max_length=1000)


class AgentPositionInput(BaseModel):
    agent_id: UUID
    recorded_at: datetime
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class AgentPositionBatchInput(BaseModel):
    positions: list[AgentPositionInput] = Field(min_length=1, max_length=1000)


class IngestOutput(BaseModel):
    accepted: int
    unknown: int
    faults_registered: int = 0
    arrivals: int = 0


class RegistryDeviceOutput(BaseModel):
    equipment_id: UUID
    type_code: str
    status: EquipmentStatus
    lat: float
    lng: float
    region_code: str | None
    intervention_since: datetime | None = None


class RegistryAgentOutput(BaseModel):
    agent_id: UUID
    duty_status: DutyStatus
    is_active: bool
    region_code: str | None
    base: GeoPointSchema
    current: GeoPointSchema | None
    vehicle_type: str | None
    dispatch_target: GeoPointSchema | None


class RegistryOutput(BaseModel):
    devices: list[RegistryDeviceOutput]
    agents: list[RegistryAgentOutput]
