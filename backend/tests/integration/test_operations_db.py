"""Central de Operações contra PostGIS real: NOTIFY transacional, KNN, agregados."""

import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import ManualClock
from app.core.config import Settings
from app.domain.agents.entities import AgentRole, DutyStatus
from app.domain.equipment.status import EquipmentStatus
from app.domain.operations.events import DomainEvent, EventType
from app.domain.operations.telemetry import AgentPositionReport, EquipmentHeartbeat
from app.domain.organizations import OrganizationKind
from app.domain.shared import UF, Address, GeoPoint
from app.realtime.broker import EventBroker
from app.repositories.unit_of_work import SqlAlchemyUnitOfWork
from app.seed.marilia_data import REGIONS, offset_point, region_geojson
from app.services.agent_service import AgentService, NewAgent
from app.services.alert_service import AlertService
from app.services.dispatch_service import DispatchService
from app.services.equipment_lifecycle import EquipmentLifecycle
from app.services.equipment_service import EquipmentService, NewEquipment
from app.services.operations_service import HeatmapKind, OperationsQueryService
from app.services.reference_service import OrganizationService
from app.services.telemetry_service import TelemetryService

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_database")]

Factory = async_sessionmaker[AsyncSession]
CENTER = GeoPoint(-22.2139, -49.9458)
ADDRESS = Address("17500000", "Avenida Sampaio Vidal", "181", "Centro", "Marília", UF.SP)


class City:
    def __init__(self, session_factory: Factory, settings: Settings) -> None:
        self.factory = session_factory
        self.settings = settings
        self.clock = ManualClock(datetime.now(UTC), settings.tz)

    def uow(self) -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(self.factory)

    async def setup(self) -> None:
        async with self.uow() as uow:
            for region in REGIONS:
                await uow.regions.add(region.code, region.name, region_geojson(region))
            await uow.commit()
        orgs = OrganizationService(self.uow(), self.clock)
        self.gcm = (await orgs.create("Guarda Civil", "GCM", OrganizationKind.GUARDA_MUNICIPAL)).id
        self.equipment = EquipmentService(self.uow(), self.clock, EquipmentLifecycle(), 7)

    async def camera(self, serial: str, point: GeoPoint = CENTER) -> UUID:
        view = await self.equipment.create(
            NewEquipment(
                "camera",
                serial,
                "Intelbras",
                "VIP",
                self.gcm,
                EquipmentStatus.OPERACIONAL,
                date(2026, 9, 1),
                ADDRESS,
                point,
                {"resolution": "4k", "night_vision": True},
                None,
            ),
            None,
        )
        return view.record.equipment.id

    async def guard(
        self, name: str, point: GeoPoint, status: DutyStatus = DutyStatus.DISPONIVEL
    ) -> UUID:
        record = await AgentService(self.uow(), self.clock).create(
            NewAgent(
                name, name, AgentRole.GUARDA_MUNICIPAL, self.gcm, status, ADDRESS, point, None
            ),
            None,
        )
        return record.agent.id


@pytest.fixture
async def city(session_factory: Factory, test_settings: Settings) -> City:
    instance = City(session_factory, test_settings)
    await instance.setup()
    return instance


async def test_notify_is_delivered_only_after_commit(city: City, migrated_database: str) -> None:
    broker = EventBroker(migrated_database.replace("+psycopg", ""), queue_size=50)
    broker.start()
    try:
        for _ in range(50):  # aguarda o LISTEN
            if broker.connected:
                break
            await asyncio.sleep(0.05)
        async with broker.subscribe() as subscription:
            async with city.uow() as uow:
                await uow.events.publish(DomainEvent(EventType.ALERT_OPENED, {"id": "rollback"}))
                await uow.rollback()
            async with city.uow() as uow:
                await uow.events.publish(DomainEvent(EventType.ALERT_OPENED, {"id": "commit"}))
                await uow.commit()
            payload = await asyncio.wait_for(subscription.queue.get(), timeout=5)
            assert json.loads(payload)["data"]["id"] == "commit"
            assert subscription.queue.empty()
    finally:
        await broker.stop()


async def test_knn_suggests_nearest_free_agents(city: City) -> None:
    camera = await city.camera("CAM-KNN")
    near = await city.guard("Perto", GeoPoint(*offset_point(0.3, 90)))
    far = await city.guard("Longe", GeoPoint(*offset_point(2.5, 90)))
    await city.guard("Folga", GeoPoint(*offset_point(0.1, 90)), DutyStatus.FORA_DE_SERVICO)

    suggestions = await DispatchService(city.uow(), city.clock).suggestions(camera)
    assert [s.candidate.agent_id for s in suggestions] == [near, far]
    assert suggestions[0].candidate.distance_m == pytest.approx(300, abs=30)


async def test_live_gps_position_is_preferred_over_base(city: City) -> None:
    camera = await city.camera("CAM-GPS")
    based_far = await city.guard("Base longe", GeoPoint(*offset_point(4, 90)))
    await city.guard("Base perto", GeoPoint(*offset_point(1, 90)))
    await TelemetryService(city.uow(), city.clock, EquipmentLifecycle()).ingest_agent_positions(
        [_report(based_far, city.clock.now(), GeoPoint(*offset_point(0.2, 90)))]
    )
    suggestions = await DispatchService(city.uow(), city.clock).suggestions(camera)
    assert suggestions[0].candidate.agent_id == based_far


def _report(agent_id: UUID, at: datetime, point: GeoPoint) -> AgentPositionReport:
    return AgentPositionReport(agent_id, at, point)


async def test_overview_regions_map_and_heatmap(city: City) -> None:
    ok = await city.camera("CAM-OK")
    broken = await city.camera("CAM-BROKEN", GeoPoint(*offset_point(4, 0)))  # Zona Norte
    await city.equipment.change_status(
        broken, EquipmentStatus.MAU_FUNCIONAMENTO, "Sem imagem", None
    )
    await city.guard("Em turno", CENTER)

    queries = OperationsQueryService(city.uow(), city.clock, 7, city.settings.timezone)
    overview = await queries.overview()
    assert (overview.total_equipment, overview.operational, overview.unavailable) == (2, 1, 1)
    assert overview.availability_pct == 50.0
    assert overview.agents.on_duty == 1
    assert overview.alerts.total == 1
    assert overview.connectivity.without_telemetry == 2

    regions = {r.metrics.code: r for r in await queries.regions()}
    assert regions["norte"].metrics.unavailable == 1
    assert regions["norte"].score < regions["centro"].score

    snapshot = await queries.map_snapshot()
    features = {f.id: f for f in snapshot.equipment}
    assert features[broken].open_alerts == 1
    assert features[broken].top_alert_severity is not None
    assert features[ok].open_alerts == 0

    heat = await queries.heatmap(HeatmapKind.FALHAS, days=30)
    assert len(heat) == 1
    assert heat[0].weight == 1

    trends = await queries.trends(days=7)
    assert len(trends) == 7
    assert trends[-1].failures == 1


async def test_offline_sweep_and_reconnection(city: City) -> None:
    camera = await city.camera("CAM-NET")
    telemetry = TelemetryService(city.uow(), city.clock, EquipmentLifecycle())
    await telemetry.ingest_equipment(
        [EquipmentHeartbeat(camera, city.clock.now(), {"signal_dbm": -70})]
    )
    city.clock.advance(timedelta(minutes=7))
    sweep = AlertService(city.uow(), city.clock)
    await sweep.sweep(7)
    await sweep.sweep(7)  # idempotente

    async with city.uow() as uow:
        offline = await uow.alerts.list_open_by_prefix("equipamento_offline:")
    assert [a.equipment_id for a in offline] == [camera]
    assert offline[0].occurrences == 1

    await telemetry.ingest_equipment([EquipmentHeartbeat(camera, city.clock.now(), {})])
    async with city.uow() as uow:
        assert await uow.alerts.list_open_by_prefix("equipamento_offline:") == []


async def test_region_alert_does_not_feed_back_into_region_score(city: City) -> None:
    broken = [await city.camera(f"CAM-F{i}") for i in range(3)]
    await city.camera("CAM-OK1")
    for camera in broken:
        await city.equipment.change_status(camera, EquipmentStatus.MAU_FUNCIONAMENTO, "x", None)
    queries = OperationsQueryService(city.uow(), city.clock, 7, city.settings.timezone)
    before = {r.metrics.code: r.score for r in await queries.regions()}["centro"]

    await AlertService(city.uow(), city.clock).sweep(7)  # abre "região degradada" no Centro
    async with city.uow() as uow:
        assert await uow.alerts.list_open_by_prefix("regiao_degradada:")
    after = {r.metrics.code: r.score for r in await queries.regions()}["centro"]
    assert after == before
