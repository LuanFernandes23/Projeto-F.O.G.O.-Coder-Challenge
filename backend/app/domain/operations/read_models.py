"""Modelos de leitura da Central de Operações (agregados prontos para o painel)."""

from dataclasses import dataclass, field
from datetime import date, datetime
from uuid import UUID

from app.domain.agents.entities import AgentRole, DutyStatus
from app.domain.equipment.status import EquipmentStatus
from app.domain.maintenance.entities import MaintenanceNeed
from app.domain.operations.alerts import AlertSeverity
from app.domain.operations.dispatch import DispatchStatus


@dataclass(frozen=True, slots=True)
class TypeBreakdown:
    type_code: str
    type_name: str
    icon: str
    total: int
    operational: int
    unavailable: int


@dataclass(frozen=True, slots=True)
class ConnectivityCounts:
    online: int
    offline: int
    without_telemetry: int


@dataclass(frozen=True, slots=True)
class MaintenanceCounts:
    immediate: int
    due_soon: int
    overdue: int


@dataclass(frozen=True, slots=True)
class AgentCounts:
    active: int
    on_duty: int
    dispatched: int


@dataclass(frozen=True, slots=True)
class AlertCounts:
    by_severity: dict[AlertSeverity, int]
    sla_breached: int

    @property
    def total(self) -> int:
        return sum(self.by_severity.values())


@dataclass(frozen=True, slots=True)
class OperationsOverview:
    generated_at: datetime
    by_status: dict[EquipmentStatus, int]
    connectivity: ConnectivityCounts
    maintenance: MaintenanceCounts
    agents: AgentCounts
    alerts: AlertCounts
    by_type: list[TypeBreakdown] = field(default_factory=list)

    @property
    def total_equipment(self) -> int:
        return sum(self.by_status.values())

    @property
    def operational(self) -> int:
        return self.by_status.get(EquipmentStatus.OPERACIONAL, 0)

    @property
    def unavailable(self) -> int:
        """Instalados, mas fora de operação (base do indicador de disponibilidade)."""
        return sum(
            self.by_status.get(s, 0)
            for s in (
                EquipmentStatus.MAU_FUNCIONAMENTO,
                EquipmentStatus.EM_MANUTENCAO,
                EquipmentStatus.FURTADO,
            )
        )

    @property
    def availability_pct(self) -> float:
        base = self.operational + self.unavailable
        return round(100 * self.operational / base, 1) if base else 100.0


@dataclass(frozen=True, slots=True)
class MapEquipmentFeature:
    id: UUID
    type_code: str
    serial_number: str
    status: EquipmentStatus
    latitude: float
    longitude: float
    region_id: UUID | None
    organization_id: UUID
    neighborhood: str
    maintenance_need: MaintenanceNeed
    next_maintenance_date: date | None
    last_seen_at: datetime | None
    open_alerts: int
    top_alert_severity: AlertSeverity | None


@dataclass(frozen=True, slots=True)
class MapAgentFeature:
    id: UUID
    full_name: str
    role: AgentRole
    organization_id: UUID
    duty_status: DutyStatus
    latitude: float
    longitude: float
    region_id: UUID | None
    last_position_at: datetime | None
    vehicle_type: str | None
    dispatch_id: UUID | None
    dispatch_status: DispatchStatus | None


@dataclass(frozen=True, slots=True)
class HeatPoint:
    latitude: float
    longitude: float
    weight: int


@dataclass(frozen=True, slots=True)
class TrendPoint:
    day: date
    failures: int
    repairs: int
    mttr_hours: float | None


@dataclass(frozen=True, slots=True)
class MonitoredDevice:
    """Equipamento candidato a alerta pelo job de varredura."""

    equipment_id: UUID
    type_code: str
    serial_number: str
    region_id: UUID | None
    region_code: str | None
    reference_at: datetime | None  # último contato (offline) ou None
    next_maintenance_date: date | None
