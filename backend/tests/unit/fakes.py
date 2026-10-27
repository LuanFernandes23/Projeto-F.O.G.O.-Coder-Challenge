"""Implementações em memória das portas de persistência (testes unitários sem banco)."""

import itertools
from collections.abc import Sequence
from dataclasses import replace
from datetime import date, datetime
from types import TracebackType
from typing import Any, Self
from uuid import UUID, uuid4

from app.core.exceptions import VersionConflictError
from app.domain.agents.entities import (
    Agent,
    AgentFilters,
    AgentRecord,
    AgentRole,
    AgentStatusChange,
    DutyStatus,
)
from app.domain.equipment.entities import (
    Equipment,
    EquipmentCategory,
    EquipmentRecord,
    EquipmentStatusChange,
    EquipmentType,
    EquipmentTypeSummary,
)
from app.domain.equipment.filters import EquipmentFilters
from app.domain.equipment.status import EquipmentStatus
from app.domain.maintenance.entities import (
    MaintenanceKind,
    MaintenanceOrder,
    MaintenanceOrderStatus,
    MaintenancePlan,
)
from app.domain.operations.alerts import Alert, AlertFilters, AlertKind, AlertRecord
from app.domain.operations.dispatch import Dispatch, DispatchCandidate, DispatchRecord
from app.domain.operations.events import DomainEvent
from app.domain.operations.read_models import MonitoredDevice
from app.domain.operations.region_health import RegionMetrics
from app.domain.operations.telemetry import DeviceState, RegistryAgent, RegistryDevice, battery_of
from app.domain.organizations import (
    Organization,
    OrganizationKind,
    OrganizationSummary,
    OrganizationUsage,
)
from app.domain.regions import Region, RegionSummary
from app.domain.shared import GeoPoint, Page, PageRequest
from app.domain.users import User

EQUIPMENT_TYPES = {
    code: EquipmentType(code, code, EquipmentCategory.OUTRO, "icon", mobile, vehicle, code)
    for code, mobile, vehicle in [
        ("camera", False, False),
        ("radar", False, False),
        ("semaforo", False, False),
        ("patinete", True, False),
        ("moto_agente", True, True),
        ("viatura", True, True),
        ("outro", False, False),
    ]
}


def _page[T](items: list[T], page: PageRequest) -> Page[T]:
    return Page(items[page.offset : page.offset + page.limit], len(items), page.limit, page.offset)


class FakeUsers:
    def __init__(self) -> None:
        self.items: dict[UUID, User] = {}

    async def get(self, user_id: UUID) -> User | None:
        user = self.items.get(user_id)
        return replace(user) if user else None

    async def get_by_email(self, email: str) -> User | None:
        return next((replace(u) for u in self.items.values() if u.email == email.lower()), None)

    async def list_page(self, page: PageRequest) -> Page[User]:
        return _page(list(self.items.values()), page)

    async def list_active_admins(self) -> list[User]:
        return [u for u in self.items.values() if u.role.value == "admin" and u.is_active]

    async def count(self) -> int:
        return len(self.items)

    async def add(self, user: User) -> None:
        self.items[user.id] = replace(user)

    async def update(self, user: User) -> None:
        self.items[user.id] = replace(user)


class FakeOrganizations:
    def __init__(self) -> None:
        self.items: dict[UUID, Organization] = {}
        self.usage_by_id: dict[UUID, OrganizationUsage] = {}

    def seed(self, kind: OrganizationKind, acronym: str = "ORG") -> Organization:
        now = datetime(2026, 1, 1)
        org = Organization(uuid4(), f"Órgão {acronym}", acronym, kind, now, now)
        self.items[org.id] = org
        return org

    async def get(self, organization_id: UUID) -> Organization | None:
        return self.items.get(organization_id)

    async def list_all(self) -> list[Organization]:
        return list(self.items.values())

    async def find_conflicting(
        self, name: str, acronym: str, exclude_id: UUID | None
    ) -> Organization | None:
        return next(
            (
                o
                for o in self.items.values()
                if o.id != exclude_id and (o.name == name or o.acronym == acronym)
            ),
            None,
        )

    async def is_referenced(self, organization_id: UUID) -> bool:
        return self.usage_by_id.get(organization_id, OrganizationUsage()).in_use

    async def usage(self) -> dict[UUID, OrganizationUsage]:
        return dict(self.usage_by_id)

    async def add(self, organization: Organization) -> None:
        self.items[organization.id] = organization

    async def update(self, organization: Organization) -> None:
        self.items[organization.id] = organization

    async def delete(self, organization_id: UUID) -> None:
        self.items.pop(organization_id, None)


class FakeRegions:
    def __init__(self) -> None:
        self.region = RegionSummary(uuid4(), "centro", "Centro")

    async def list_all(self, include_geometry: bool) -> list[Region]:
        return [Region(self.region.id, self.region.code, self.region.name, None)]

    async def find_covering(self, point: GeoPoint) -> UUID | None:
        return self.region.id

    async def code_of(self, region_id: UUID) -> str | None:
        return self.region.code if region_id == self.region.id else None

    async def add(self, code: str, name: str, geometry: dict[str, Any]) -> UUID:
        return uuid4()


class FakeEquipmentTypes:
    async def list_all(self) -> list[EquipmentType]:
        return list(EQUIPMENT_TYPES.values())

    async def get(self, code: str) -> EquipmentType | None:
        return EQUIPMENT_TYPES.get(code)

    async def add(self, equipment_type: EquipmentType) -> None:
        EQUIPMENT_TYPES[equipment_type.code] = equipment_type


class FakeEquipment:
    def __init__(self, uow: "FakeUnitOfWork") -> None:
        self._uow = uow
        self.items: dict[UUID, Equipment] = {}

    async def get(self, equipment_id: UUID, *, for_update: bool = False) -> Equipment | None:
        item = self.items.get(equipment_id)
        return replace(item, attributes=dict(item.attributes)) if item else None

    async def get_record(self, equipment_id: UUID) -> EquipmentRecord | None:
        item = self.items.get(equipment_id)
        return self._record(item) if item else None

    async def list_records(
        self, filters: EquipmentFilters, page: PageRequest
    ) -> Page[EquipmentRecord]:
        items = [
            self._record(e)
            for e in self.items.values()
            if e.archived_at is None and (not filters.statuses or e.status in filters.statuses)
        ]
        return _page(items, page)

    async def exists_brand_serial(
        self, brand: str, serial_number: str, exclude_id: UUID | None
    ) -> bool:
        return any(
            e.brand.lower() == brand.lower()
            and e.serial_number.lower() == serial_number.lower()
            and e.id != exclude_id
            and e.archived_at is None
            for e in self.items.values()
        )

    async def add(self, equipment: Equipment) -> None:
        self.items[equipment.id] = replace(equipment)

    async def update(self, equipment: Equipment) -> int:
        current = self.items[equipment.id]
        if current.version != equipment.version:
            raise VersionConflictError("versão desatualizada")
        self.items[equipment.id] = replace(equipment, version=equipment.version + 1)
        return equipment.version + 1

    async def list_due_for_preventive(
        self, until: date, exempt_statuses: Sequence[EquipmentStatus]
    ) -> list[UUID]:
        plans = self._uow.maintenance_plans.items
        orders = self._uow.maintenance_orders.items.values()
        return [
            e.id
            for e in self.items.values()
            if e.id in plans
            and plans[e.id].next_due_date <= until
            and e.status not in exempt_statuses
            and not any(
                o.equipment_id == e.id and o.kind is MaintenanceKind.PREVENTIVA and o.is_open
                for o in orders
            )
        ]

    def _record(self, equipment: Equipment) -> EquipmentRecord:
        org = self._uow.organizations.items[equipment.organization_id]
        equipment_type = EQUIPMENT_TYPES[equipment.type_code]
        return EquipmentRecord(
            equipment=replace(equipment),
            type=EquipmentTypeSummary(
                equipment_type.code, equipment_type.name, equipment_type.category, "icon"
            ),
            organization=OrganizationSummary(org.id, org.name, org.acronym, org.kind),
            region=self._uow.regions.region,
            maintenance_plan=self._uow.maintenance_plans.items.get(equipment.id),
        )


class FakeEquipmentHistory:
    def __init__(self) -> None:
        self.entries: list[EquipmentStatusChange] = []
        self._ids = itertools.count(1)

    async def add(
        self,
        *,
        equipment_id: UUID,
        from_status: EquipmentStatus | None,
        to_status: EquipmentStatus,
        reason: str | None,
        changed_by: UUID | None,
        changed_at: datetime,
    ) -> None:
        self.entries.append(
            EquipmentStatusChange(
                next(self._ids),
                equipment_id,
                from_status,
                to_status,
                reason,
                changed_by,
                None,
                changed_at,
            )
        )

    async def list_for_equipment(
        self, equipment_id: UUID, page: PageRequest
    ) -> Page[EquipmentStatusChange]:
        items = [e for e in reversed(self.entries) if e.equipment_id == equipment_id]
        return _page(items, page)


class FakeMaintenancePlans:
    def __init__(self) -> None:
        self.items: dict[UUID, MaintenancePlan] = {}

    async def get(self, equipment_id: UUID) -> MaintenancePlan | None:
        plan = self.items.get(equipment_id)
        return replace(plan) if plan else None

    async def upsert(self, plan: MaintenancePlan) -> None:
        self.items[plan.equipment_id] = replace(plan)

    async def delete(self, equipment_id: UUID) -> None:
        self.items.pop(equipment_id, None)


class FakeMaintenanceOrders:
    def __init__(self) -> None:
        self.items: dict[UUID, MaintenanceOrder] = {}

    async def get(self, order_id: UUID, *, for_update: bool = False) -> MaintenanceOrder | None:
        order = self.items.get(order_id)
        return replace(order) if order else None

    async def list_open(self, equipment_id: UUID) -> list[MaintenanceOrder]:
        return [
            replace(o) for o in self.items.values() if o.equipment_id == equipment_id and o.is_open
        ]

    async def list_by_equipment(
        self,
        equipment_id: UUID,
        statuses: Sequence[MaintenanceOrderStatus],
        page: PageRequest,
    ) -> Page[MaintenanceOrder]:
        items = [
            o
            for o in self.items.values()
            if o.equipment_id == equipment_id and (not statuses or o.status in statuses)
        ]
        return _page(items, page)

    async def add(self, order: MaintenanceOrder) -> None:
        self.items[order.id] = replace(order)

    async def update(self, order: MaintenanceOrder) -> None:
        self.items[order.id] = replace(order)


class FakeAgents:
    def __init__(self, uow: "FakeUnitOfWork") -> None:
        self._uow = uow
        self.items: dict[UUID, Agent] = {}
        self.positions: dict[UUID, GeoPoint] = {}

    async def get(self, agent_id: UUID, *, for_update: bool = False) -> Agent | None:
        agent = self.items.get(agent_id)
        return replace(agent) if agent else None

    async def get_record(self, agent_id: UUID) -> AgentRecord | None:
        agent = self.items.get(agent_id)
        if agent is None:
            return None
        org = self._uow.organizations.items[agent.organization_id]
        return AgentRecord(
            replace(agent),
            OrganizationSummary(org.id, org.name, org.acronym, org.kind),
            self._uow.regions.region,
            None,
        )

    async def list_records(self, filters: AgentFilters, page: PageRequest) -> Page[AgentRecord]:
        records = [await self.get_record(a) for a in self.items]
        return _page([r for r in records if r is not None], page)

    async def exists_registration(
        self, organization_id: UUID, registration_number: str, exclude_id: UUID | None
    ) -> bool:
        return any(
            a.organization_id == organization_id
            and a.registration_number.lower() == registration_number.lower()
            and a.id != exclude_id
            and a.archived_at is None
            for a in self.items.values()
        )

    async def current_position(self, agent_id: UUID) -> GeoPoint | None:
        agent = self.items.get(agent_id)
        return self.positions.get(agent_id) or (agent.base_location if agent else None)

    async def count_active_crew(self, vehicle_id: UUID, exclude_agent_id: UUID | None) -> int:
        return sum(
            1
            for a in self.items.values()
            if a.assigned_vehicle_id == vehicle_id
            and a.is_active
            and a.archived_at is None
            and a.id != exclude_agent_id
        )

    async def add(self, agent: Agent) -> None:
        self.items[agent.id] = replace(agent)

    async def update(self, agent: Agent) -> int:
        if self.items[agent.id].version != agent.version:
            raise VersionConflictError("versão desatualizada")
        self.items[agent.id] = replace(agent, version=agent.version + 1)
        return agent.version + 1


class FakeAgentHistory:
    def __init__(self) -> None:
        self.entries: list[AgentStatusChange] = []
        self._ids = itertools.count(1)

    async def add(
        self,
        *,
        agent_id: UUID,
        from_status: DutyStatus | None,
        to_status: DutyStatus,
        reason: str | None,
        changed_by: UUID | None,
        changed_at: datetime,
    ) -> None:
        self.entries.append(
            AgentStatusChange(
                next(self._ids),
                agent_id,
                from_status,
                to_status,
                reason,
                changed_by,
                None,
                changed_at,
            )
        )

    async def list_for_agent(self, agent_id: UUID, page: PageRequest) -> Page[AgentStatusChange]:
        return _page([e for e in self.entries if e.agent_id == agent_id], page)


class FakeAlerts:
    def __init__(self) -> None:
        self.items: dict[UUID, Alert] = {}

    async def get(self, alert_id: UUID, *, for_update: bool = False) -> Alert | None:
        alert = self.items.get(alert_id)
        return replace(alert) if alert else None

    async def get_open_by_dedup(self, dedup_key: str) -> Alert | None:
        return next(
            (replace(a) for a in self.items.values() if a.dedup_key == dedup_key and a.is_open),
            None,
        )

    async def list_open_by_prefix(self, prefix: str) -> list[Alert]:
        return [
            replace(a) for a in self.items.values() if a.dedup_key.startswith(prefix) and a.is_open
        ]

    async def add(self, alert: Alert) -> None:
        self.items[alert.id] = replace(alert)

    async def update(self, alert: Alert) -> None:
        self.items[alert.id] = replace(alert)

    async def get_record(self, alert_id: UUID) -> AlertRecord | None:
        alert = self.items.get(alert_id)
        return AlertRecord(replace(alert), None, None) if alert else None

    async def list_records(self, filters: AlertFilters, page: PageRequest) -> Page[AlertRecord]:
        items = [
            AlertRecord(replace(a), None, None)
            for a in self.items.values()
            if not filters.statuses or a.status in filters.statuses
        ]
        return _page(items, page)

    def open_kinds(self, subject_id: UUID) -> set[AlertKind]:
        return {
            a.kind
            for a in self.items.values()
            if a.is_open and a.dedup_key.endswith(str(subject_id))
        }


class FakeDispatches:
    def __init__(self) -> None:
        self.items: dict[UUID, Dispatch] = {}

    async def get(self, dispatch_id: UUID, *, for_update: bool = False) -> Dispatch | None:
        dispatch = self.items.get(dispatch_id)
        return replace(dispatch) if dispatch else None

    async def active_for_agent(self, agent_id: UUID) -> Dispatch | None:
        return next(
            (replace(d) for d in self.items.values() if d.agent_id == agent_id and d.is_active),
            None,
        )

    async def list_active(self) -> list[Dispatch]:
        return [replace(d) for d in self.items.values() if d.is_active]

    async def get_record(self, dispatch_id: UUID) -> DispatchRecord | None:
        dispatch = self.items.get(dispatch_id)
        if dispatch is None:
            return None
        return DispatchRecord(
            replace(dispatch), "Agente", AgentRole.OUTRO, "ORG", "SERIE", "camera"
        )

    async def list_records(self, active_only: bool, limit: int) -> list[DispatchRecord]:
        records = [await self.get_record(d) for d in self.items]
        return [r for r in records if r and (not active_only or r.dispatch.is_active)][:limit]

    async def add(self, dispatch: Dispatch) -> None:
        self.items[dispatch.id] = replace(dispatch)

    async def update(self, dispatch: Dispatch) -> None:
        self.items[dispatch.id] = replace(dispatch)


class FakeEvents:
    def __init__(self) -> None:
        self.published: list[DomainEvent] = []

    async def publish(self, event: DomainEvent) -> None:
        self.published.append(event)

    def types(self) -> list[str]:
        return [e.type.value for e in self.published]


class FakeOperations:
    """Somente o necessário aos testes unitários; consultas agregadas são testadas no banco."""

    def __init__(self) -> None:
        self.candidates: list[DispatchCandidate] = []
        self.offline: list[MonitoredDevice] = []
        self.overdue: list[MonitoredDevice] = []
        self.regions: list[RegionMetrics] = []

    async def dispatch_candidates(
        self,
        target: GeoPoint,
        roles: Sequence[AgentRole],
        duty_statuses: Sequence[DutyStatus],
        limit: int,
    ) -> list[DispatchCandidate]:
        return [c for c in self.candidates if c.role in roles][:limit]

    async def offline_devices(self, now: datetime) -> list[MonitoredDevice]:
        return list(self.offline)

    async def overdue_devices(self, today: date) -> list[MonitoredDevice]:
        return list(self.overdue)

    async def region_metrics(self, now: datetime, today: date) -> list[RegionMetrics]:
        return list(self.regions)


class FakeTelemetry:
    def __init__(self, uow: "FakeUnitOfWork") -> None:
        self._uow = uow
        self.last_seen: dict[UUID, datetime] = {}
        self.telemetry: dict[UUID, dict[str, Any]] = {}
        self.readings: list[tuple[UUID, datetime, dict[str, Any]]] = []
        self.positions: list[tuple[UUID, datetime, GeoPoint]] = []

    async def device_states(self, equipment_ids: Sequence[UUID]) -> list[DeviceState]:
        states = []
        for equipment_id in equipment_ids:
            equipment = self._uow.equipment.items.get(equipment_id)
            if equipment is None:
                continue
            states.append(
                DeviceState(
                    equipment_id=equipment_id,
                    type_code=equipment.type_code,
                    status=equipment.status,
                    region_id=equipment.region_id,
                    region_code=self._uow.regions.region.code,
                    last_seen_at=self.last_seen.get(equipment_id),
                    last_reading_at=None,
                    battery_pct=battery_of(self.telemetry.get(equipment_id, {})),
                )
            )
        return states

    async def record_heartbeats(self, rows: Sequence[dict[str, Any]]) -> None:
        for row in rows:
            self.last_seen[row["id"]] = row["last_seen_at"]
            self.telemetry[row["id"]] = row["last_telemetry"]

    async def add_readings(self, rows: Sequence[tuple[UUID, datetime, dict[str, Any]]]) -> None:
        self.readings.extend(rows)

    async def update_agent_positions(self, rows: Sequence[tuple[UUID, datetime, GeoPoint]]) -> None:
        for agent_id, _, point in rows:
            self._uow.agents.positions[agent_id] = point

    async def last_sampled_positions(
        self, agent_ids: Sequence[UUID], since: datetime
    ) -> dict[UUID, datetime]:
        return {}

    async def add_agent_positions(self, rows: Sequence[tuple[UUID, datetime, GeoPoint]]) -> None:
        self.positions.extend(rows)

    async def known_agent_ids(self, agent_ids: Sequence[UUID]) -> set[UUID]:
        return {a for a in agent_ids if a in self._uow.agents.items}

    async def registry_devices(self) -> list[RegistryDevice]:
        return []

    async def registry_agents(self) -> list[RegistryAgent]:
        return []

    async def purge_older_than(self, cutoff: datetime) -> int:
        return 0


class FakeJobLocks:
    def __init__(self) -> None:
        self.available = True

    async def try_acquire(self, lock_key: int) -> bool:
        return self.available


class FakePredictions:
    """Só o necessário para a ingestão de telemetria (desfechos de precursores)."""

    def __init__(self) -> None:
        self.closed: list[tuple[UUID, str]] = []
        self.averted: list[tuple[UUID, str]] = []
        self.open: set[UUID] = set()

    async def close_detection(self, equipment_id: UUID, outcome: str, at: datetime) -> bool:
        if equipment_id not in self.open:
            return False
        self.open.discard(equipment_id)
        self.closed.append((equipment_id, outcome))
        return True

    async def record_averted(self, equipment_id: UUID, at: datetime, intervention: str) -> None:
        self.averted.append((equipment_id, intervention))


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.users = FakeUsers()
        self.organizations = FakeOrganizations()
        self.regions = FakeRegions()
        self.equipment_types = FakeEquipmentTypes()
        self.equipment = FakeEquipment(self)
        self.equipment_history = FakeEquipmentHistory()
        self.maintenance_plans = FakeMaintenancePlans()
        self.maintenance_orders = FakeMaintenanceOrders()
        self.agents = FakeAgents(self)
        self.agent_history = FakeAgentHistory()
        self.job_locks = FakeJobLocks()
        self.alerts = FakeAlerts()
        self.dispatches = FakeDispatches()
        self.events = FakeEvents()
        self.operations = FakeOperations()
        self.telemetry = FakeTelemetry(self)
        self.predictions = FakePredictions()
        self.commits = 0

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        return None
