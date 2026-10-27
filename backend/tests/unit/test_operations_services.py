"""Orquestração da Central com repositórios em memória: alertas, telemetria e despacho."""

from datetime import date, datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest

from app.core.clock import ManualClock
from app.core.exceptions import BusinessRuleError, ConflictError
from app.domain.agents.entities import AgentRole, DutyStatus
from app.domain.equipment.status import EquipmentStatus
from app.domain.operations.alerts import AlertKind, AlertSeverity, AlertStatus
from app.domain.operations.dispatch import DispatchCandidate, DispatchStatus
from app.domain.operations.read_models import MonitoredDevice
from app.domain.operations.region_health import RegionMetrics
from app.domain.operations.telemetry import AgentPositionReport, EquipmentHeartbeat
from app.domain.organizations import OrganizationKind
from app.domain.shared import UF, Address, GeoPoint
from app.services.agent_service import AgentService, NewAgent
from app.services.alert_service import AlertService
from app.services.dispatch_service import DispatchService
from app.services.equipment_lifecycle import EquipmentLifecycle
from app.services.equipment_service import EquipmentService, NewEquipment
from app.services.telemetry_service import TelemetryService
from tests.unit.fakes import FakeUnitOfWork

TZ = ZoneInfo("America/Sao_Paulo")
ADDRESS = Address("17500000", "Avenida Sampaio Vidal", "181", "Centro", "Marília", UF.SP)
CAMERA_POINT = GeoPoint(-22.2139, -49.9458)


@pytest.fixture
def uow() -> FakeUnitOfWork:
    return FakeUnitOfWork()


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock(datetime(2026, 10, 26, 14, tzinfo=TZ), TZ)


@pytest.fixture
def equipment_service(uow: FakeUnitOfWork, clock: ManualClock) -> EquipmentService:
    return EquipmentService(uow, clock, EquipmentLifecycle(), due_soon_days=7)


async def _camera(service: EquipmentService, uow: FakeUnitOfWork, serial: str = "CAM-1") -> UUID:
    org = uow.organizations.seed(OrganizationKind.GUARDA_MUNICIPAL, f"GCM{serial}")
    view = await service.create(
        NewEquipment(
            type_code="camera",
            serial_number=serial,
            brand="Intelbras",
            model="VIP",
            organization_id=org.id,
            status=EquipmentStatus.OPERACIONAL,
            installed_on=date(2026, 9, 1),
            address=ADDRESS,
            location=CAMERA_POINT,
            attributes={"resolution": "4k", "night_vision": True},
            maintenance_plan=None,
        ),
        actor_id=None,
    )
    return view.record.equipment.id


class TestAlertRulesOnStatusChange:
    async def test_failure_opens_critical_alert_in_downtown_and_publishes_events(
        self, equipment_service: EquipmentService, uow: FakeUnitOfWork
    ) -> None:
        camera = await _camera(equipment_service, uow)
        await equipment_service.change_status(
            camera, EquipmentStatus.MAU_FUNCIONAMENTO, "Sem imagem", None
        )

        alert = next(iter(uow.alerts.items.values()))
        assert alert.kind is AlertKind.FALHA_EQUIPAMENTO
        assert alert.severity is AlertSeverity.CRITICA  # câmera no Centro
        assert "equipment.status_changed" in uow.events.types()
        assert "alert.opened" in uow.events.types()

    async def test_repair_resolves_the_failure_alert(
        self, equipment_service: EquipmentService, uow: FakeUnitOfWork
    ) -> None:
        camera = await _camera(equipment_service, uow)
        await equipment_service.change_status(
            camera, EquipmentStatus.MAU_FUNCIONAMENTO, "Sem imagem", None
        )
        await equipment_service.change_status(
            camera, EquipmentStatus.OPERACIONAL, "Reiniciado", None
        )
        assert uow.alerts.open_kinds(camera) == set()

    async def test_theft_replaces_failure_with_theft_alert(
        self, equipment_service: EquipmentService, uow: FakeUnitOfWork
    ) -> None:
        camera = await _camera(equipment_service, uow)
        await equipment_service.change_status(
            camera, EquipmentStatus.MAU_FUNCIONAMENTO, "Sem imagem", None
        )
        await equipment_service.change_status(camera, EquipmentStatus.FURTADO, "B.O. 123", None)
        assert uow.alerts.open_kinds(camera) == {AlertKind.FURTO}

    async def test_repeated_failure_counts_occurrences_instead_of_duplicating(
        self, equipment_service: EquipmentService, uow: FakeUnitOfWork
    ) -> None:
        camera = await _camera(equipment_service, uow)
        await equipment_service.change_status(camera, EquipmentStatus.MAU_FUNCIONAMENTO, "A", None)
        await equipment_service.change_status(camera, EquipmentStatus.EM_MANUTENCAO, "B", None)
        await equipment_service.change_status(camera, EquipmentStatus.MAU_FUNCIONAMENTO, "C", None)
        open_alerts = [a for a in uow.alerts.items.values() if a.is_open]
        assert len(open_alerts) == 1
        assert open_alerts[0].occurrences == 2


class TestTelemetryIngestion:
    async def test_device_reported_fault_drives_the_whole_chain(
        self, equipment_service: EquipmentService, uow: FakeUnitOfWork, clock: ManualClock
    ) -> None:
        camera = await _camera(equipment_service, uow)
        service = TelemetryService(uow, clock, EquipmentLifecycle())
        result = await service.ingest_equipment(
            [EquipmentHeartbeat(camera, clock.now(), {"signal_dbm": -70}, fault="Sem imagem")]
        )
        assert result.faults_registered == 1
        assert uow.equipment.items[camera].status is EquipmentStatus.MAU_FUNCIONAMENTO
        assert len(uow.maintenance_orders.items) == 1  # ordem corretiva automática
        assert uow.alerts.open_kinds(camera) == {AlertKind.FALHA_EQUIPAMENTO}

    async def test_heartbeat_after_silence_resolves_offline_alert(
        self, equipment_service: EquipmentService, uow: FakeUnitOfWork, clock: ManualClock
    ) -> None:
        camera = await _camera(equipment_service, uow)
        service = TelemetryService(uow, clock, EquipmentLifecycle())
        await service.ingest_equipment([EquipmentHeartbeat(camera, clock.now(), {})])
        clock.advance(timedelta(minutes=10))
        uow.operations.offline = [
            MonitoredDevice(camera, "camera", "CAM-1", None, "centro", clock.now(), None)
        ]
        await AlertService(uow, clock).sweep(7)
        assert uow.alerts.open_kinds(camera) == {AlertKind.EQUIPAMENTO_OFFLINE}

        await service.ingest_equipment([EquipmentHeartbeat(camera, clock.now(), {})])
        assert uow.alerts.open_kinds(camera) == set()

    async def test_unknown_devices_are_reported_not_rejected(
        self, uow: FakeUnitOfWork, clock: ManualClock
    ) -> None:
        service = TelemetryService(uow, clock, EquipmentLifecycle())
        result = await service.ingest_equipment([EquipmentHeartbeat(uuid4(), clock.now(), {})])
        assert (result.accepted, result.unknown) == (0, 1)


class TestSweep:
    async def test_region_alert_follows_current_health(
        self, uow: FakeUnitOfWork, clock: ManualClock
    ) -> None:
        region = uow.regions.region
        degraded = RegionMetrics(
            region.id,
            region.code,
            region.name,
            60,
            40,
            10,
            10,
            0,
            2,
            {AlertSeverity.CRITICA: 3},
        )
        uow.operations.regions = [degraded]
        service = AlertService(uow, clock)
        await service.sweep(7)
        alert = next(iter(uow.alerts.items.values()))
        assert (alert.kind, alert.severity) == (AlertKind.REGIAO_DEGRADADA, AlertSeverity.ALTA)

        uow.operations.regions = [
            RegionMetrics(region.id, region.code, region.name, 100, 0, 0, 0, 0, 2)
        ]
        await service.sweep(7)
        assert next(iter(uow.alerts.items.values())).status is AlertStatus.RESOLVIDO

    async def test_sweep_skips_when_another_instance_holds_the_lock(
        self, uow: FakeUnitOfWork, clock: ManualClock
    ) -> None:
        uow.job_locks.available = False
        result = await AlertService(uow, clock).sweep(7)
        assert (result.opened_or_updated, result.resolved) == (0, 0)


class TestDispatchFlow:
    async def _agent(
        self, uow: FakeUnitOfWork, clock: ManualClock, role: AgentRole = AgentRole.GUARDA_MUNICIPAL
    ) -> UUID:
        kind = (
            OrganizationKind.GUARDA_MUNICIPAL
            if role is AgentRole.GUARDA_MUNICIPAL
            else OrganizationKind.TRANSITO
        )
        org = uow.organizations.seed(kind, f"O{len(uow.organizations.items)}")
        service = AgentService(uow, clock)
        record = await service.create(
            NewAgent(
                "Ana Ribeiro",
                f"M-{len(uow.agents.items)}",
                role,
                org.id,
                DutyStatus.DISPONIVEL,
                ADDRESS,
                GeoPoint(-22.2239, -49.9458),
                None,
            ),
            None,
        )
        return record.agent.id

    async def test_dispatch_puts_agent_in_occurrence_and_acknowledges_alert(
        self, equipment_service: EquipmentService, uow: FakeUnitOfWork, clock: ManualClock
    ) -> None:
        camera = await _camera(equipment_service, uow)
        await equipment_service.change_status(
            camera, EquipmentStatus.MAU_FUNCIONAMENTO, "Sem imagem", None
        )
        agent = await self._agent(uow, clock)
        service = DispatchService(uow, clock)
        record = await service.create(camera, agent, None, actor_id=agent)

        assert record.dispatch.status is DispatchStatus.DESIGNADO
        assert record.dispatch.distance_m == pytest.approx(1112, abs=5)
        assert uow.agents.items[agent].duty_status is DutyStatus.EM_OCORRENCIA
        assert next(iter(uow.alerts.items.values())).status is AlertStatus.RECONHECIDO

    async def test_gps_geofence_detects_departure_and_arrival(
        self, equipment_service: EquipmentService, uow: FakeUnitOfWork, clock: ManualClock
    ) -> None:
        camera = await _camera(equipment_service, uow)
        agent = await self._agent(uow, clock)
        dispatch = await DispatchService(uow, clock).create(camera, agent, None, actor_id=agent)
        telemetry = TelemetryService(uow, clock, EquipmentLifecycle())

        await telemetry.ingest_agent_positions(
            [AgentPositionReport(agent, clock.now(), GeoPoint(-22.2189, -49.9458))]
        )
        assert uow.dispatches.items[dispatch.dispatch.id].status is DispatchStatus.A_CAMINHO

        result = await telemetry.ingest_agent_positions(
            [AgentPositionReport(agent, clock.now(), GeoPoint(-22.2142, -49.9458))]
        )
        assert result.arrivals == 1
        assert uow.dispatches.items[dispatch.dispatch.id].status is DispatchStatus.NO_LOCAL

    async def test_closing_dispatch_frees_the_agent(
        self, equipment_service: EquipmentService, uow: FakeUnitOfWork, clock: ManualClock
    ) -> None:
        camera = await _camera(equipment_service, uow)
        agent = await self._agent(uow, clock)
        service = DispatchService(uow, clock)
        dispatch = await service.create(camera, agent, None, actor_id=agent)
        await service.transition(dispatch.dispatch.id, DispatchStatus.NO_LOCAL, None, agent)
        await service.transition(dispatch.dispatch.id, DispatchStatus.CONCLUIDO, "ok", agent)
        assert uow.agents.items[agent].duty_status is DutyStatus.DISPONIVEL

    async def test_agent_cannot_take_two_occurrences(
        self, equipment_service: EquipmentService, uow: FakeUnitOfWork, clock: ManualClock
    ) -> None:
        first = await _camera(equipment_service, uow, "CAM-1")
        second = await _camera(equipment_service, uow, "CAM-2")
        agent = await self._agent(uow, clock)
        service = DispatchService(uow, clock)
        await service.create(first, agent, None, actor_id=agent)
        with pytest.raises(BusinessRuleError):  # agora está em ocorrência
            await service.create(second, agent, None, actor_id=agent)

    async def test_theft_cannot_be_assigned_to_traffic_agent(
        self, equipment_service: EquipmentService, uow: FakeUnitOfWork, clock: ManualClock
    ) -> None:
        camera = await _camera(equipment_service, uow)
        await equipment_service.change_status(camera, EquipmentStatus.FURTADO, "Furto", None)
        traffic_agent = await self._agent(uow, clock, AgentRole.AGENTE_TRANSITO)
        with pytest.raises(BusinessRuleError):
            await DispatchService(uow, clock).create(
                camera, traffic_agent, None, actor_id=traffic_agent
            )

    async def test_suggestions_filter_roles_for_the_occurrence(
        self, equipment_service: EquipmentService, uow: FakeUnitOfWork, clock: ManualClock
    ) -> None:
        camera = await _camera(equipment_service, uow)
        await equipment_service.change_status(camera, EquipmentStatus.FURTADO, "Furto", None)

        def candidate(role: AgentRole, distance: float) -> DispatchCandidate:
            return DispatchCandidate(
                uuid4(),
                role.value,
                role,
                "X",
                DutyStatus.DISPONIVEL,
                CAMERA_POINT,
                distance,
                "viatura",
            )

        uow.operations.candidates = [
            candidate(AgentRole.AGENTE_TRANSITO, 100),
            candidate(AgentRole.POLICIAL_MILITAR, 900),
        ]
        suggestions = await DispatchService(uow, clock).suggestions(camera)
        assert [s.candidate.role for s in suggestions] == [AgentRole.POLICIAL_MILITAR]


async def test_acknowledging_twice_is_a_conflict(
    equipment_service: EquipmentService, uow: FakeUnitOfWork, clock: ManualClock
) -> None:
    camera = await _camera(equipment_service, uow)
    await equipment_service.change_status(camera, EquipmentStatus.MAU_FUNCIONAMENTO, "x", None)
    alert_id = next(iter(uow.alerts.items))
    service = AlertService(uow, clock)
    await service.acknowledge(alert_id, camera)
    with pytest.raises(ConflictError):
        await service.acknowledge(alert_id, camera)
