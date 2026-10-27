"""Repositórios e serviços contra PostgreSQL/PostGIS real (banco fogo_test)."""

import os
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import ManualClock
from app.core.config import Settings
from app.core.exceptions import ConflictError, VersionConflictError
from app.domain.equipment.filters import EquipmentFilters, EquipmentSort, RadiusFilter
from app.domain.equipment.status import EquipmentStatus
from app.domain.maintenance.entities import MaintenanceNeed
from app.domain.organizations import OrganizationKind
from app.domain.shared import UF, Address, GeoPoint, PageRequest
from app.repositories.unit_of_work import SqlAlchemyUnitOfWork
from app.schemas.equipment_attributes import ATTRIBUTE_SCHEMAS
from app.seed.marilia_data import REGIONS, offset_point, region_geojson
from app.services.equipment_lifecycle import EquipmentLifecycle
from app.services.equipment_service import EquipmentService, NewEquipment, PlanSpec
from app.services.maintenance_service import MaintenanceService
from app.services.reference_service import OrganizationService
from tests.conftest import BACKEND_DIR

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_database")]

Factory = async_sessionmaker[AsyncSession]
CENTER = GeoPoint(-22.2139, -49.9458)


def _address(neighborhood: str = "Centro") -> Address:
    return Address(
        "17500000", "Avenida Sampaio Vidal", "número 181", neighborhood, "Marília", UF.SP
    )


async def _setup(
    session_factory: Factory, settings: Settings
) -> tuple[EquipmentService, UUID, ManualClock]:
    clock = ManualClock(datetime(2026, 10, 1, 12, tzinfo=UTC), settings.tz)
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        for region in REGIONS:
            await uow.regions.add(region.code, region.name, region_geojson(region))
        await uow.commit()
    org = await OrganizationService(SqlAlchemyUnitOfWork(session_factory), clock).create(
        "Secretaria de Mobilidade", "SEMOB", OrganizationKind.TRANSITO
    )
    service = EquipmentService(
        SqlAlchemyUnitOfWork(session_factory), clock, EquipmentLifecycle(), 7
    )
    return service, org.id, clock


async def _camera(
    service: EquipmentService,
    org_id: UUID,
    point: GeoPoint,
    serial: str | None = None,
    **extra: object,
) -> UUID:
    data: dict[str, object] = {
        "type_code": "camera",
        "serial_number": serial or f"CAM-{uuid4().hex[:8]}",
        "brand": "Intelbras",
        "model": "VIP 5450",
        "organization_id": org_id,
        "status": EquipmentStatus.OPERACIONAL,
        "installed_on": date(2026, 9, 1),
        "address": _address(),
        "location": point,
        "attributes": {"resolution": "4k", "night_vision": True},
        "maintenance_plan": None,
    }
    data.update(extra)
    view = await service.create(NewEquipment(**data), actor_id=None)  # type: ignore[arg-type]
    return view.record.equipment.id


def test_migrations_match_the_orm_models(migrated_database: str) -> None:
    """``alembic check`` falha se algum modelo mudou sem migration correspondente."""
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "check"],
        cwd=BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": migrated_database},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


async def test_every_reference_type_has_an_attribute_schema(session_factory: Factory) -> None:
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        types = await uow.equipment_types.list_all()
    assert len(types) == 12
    assert {t.attributes_schema_key for t in types} <= set(ATTRIBUTE_SCHEMAS)


async def test_region_is_assigned_from_coordinates_with_postgis(
    session_factory: Factory, test_settings: Settings
) -> None:
    service, org_id, _ = await _setup(session_factory, test_settings)
    north_lat, north_lng = offset_point(4.0, 0.0)
    central_id = await _camera(service, org_id, CENTER)
    north_id = await _camera(service, org_id, GeoPoint(north_lat, north_lng))
    central = await service.get(central_id)
    north = await service.get(north_id)
    assert central.record.region is not None
    assert central.record.region.code == "centro"
    assert north.record.region is not None
    assert north.record.region.code == "norte"


async def test_radius_search_orders_by_distance(
    session_factory: Factory, test_settings: Settings
) -> None:
    service, org_id, _ = await _setup(session_factory, test_settings)
    near = await _camera(service, org_id, GeoPoint(*offset_point(0.2, 90)))
    nearer = await _camera(service, org_id, GeoPoint(*offset_point(0.05, 90)))
    await _camera(service, org_id, GeoPoint(*offset_point(3.0, 90)))  # fora do raio

    page = await service.search(
        EquipmentFilters(radius=RadiusFilter(CENTER, 500), sort=EquipmentSort.DISTANCE),
        PageRequest(10, 0),
    )
    assert page.total == 2
    assert [v.record.equipment.id for v in page.items] == [nearer, near]
    distances = [v.record.distance_m for v in page.items]
    assert distances[0] is not None
    assert 40 < distances[0] < 60


async def test_filters_by_neighborhood_case_insensitive_and_text_search(
    session_factory: Factory, test_settings: Settings
) -> None:
    service, org_id, _ = await _setup(session_factory, test_settings)
    await _camera(service, org_id, CENTER, serial="ALVO-123", address=_address("Fragata"))
    await _camera(service, org_id, CENTER)
    by_neighborhood = await service.search(
        EquipmentFilters(neighborhood="fragata"), PageRequest(10, 0)
    )
    by_text = await service.search(EquipmentFilters(search="alvo-1"), PageRequest(10, 0))
    assert by_neighborhood.total == 1
    assert by_text.total == 1


async def test_maintenance_filters_use_denormalized_snapshot(
    session_factory: Factory, test_settings: Settings
) -> None:
    service, org_id, clock = await _setup(session_factory, test_settings)
    soon = await _camera(service, org_id, CENTER, maintenance_plan=PlanSpec(5, None))
    await _camera(service, org_id, CENTER, maintenance_plan=PlanSpec(90, None))
    broken = await _camera(service, org_id, CENTER, status=EquipmentStatus.MAU_FUNCIONAMENTO)

    due = await service.search(
        EquipmentFilters(), PageRequest(10, 0), maintenance_due_within_days=7
    )
    immediate = await service.search(
        EquipmentFilters(maintenance_needs=(MaintenanceNeed.IMEDIATA,)), PageRequest(10, 0)
    )
    clock.advance(timedelta(days=6))
    overdue = await service.search(EquipmentFilters(), PageRequest(10, 0), maintenance_overdue=True)

    assert [v.record.equipment.id for v in due.items] == [soon]
    assert [v.record.equipment.id for v in immediate.items] == [broken]
    assert [v.record.equipment.id for v in overdue.items] == [soon]
    assert overdue.items[0].maintenance.is_overdue


async def test_archived_serial_can_be_registered_again(
    session_factory: Factory, test_settings: Settings
) -> None:
    service, org_id, _ = await _setup(session_factory, test_settings)
    first = await _camera(service, org_id, CENTER, serial="DUP-1")
    with pytest.raises(ConflictError):
        await _camera(service, org_id, CENTER, serial="dup-1")
    await service.archive(first, actor_id=None)
    await _camera(service, org_id, CENTER, serial="DUP-1")


async def test_concurrent_update_with_same_version_conflicts(
    session_factory: Factory, test_settings: Settings
) -> None:
    service, org_id, _ = await _setup(session_factory, test_settings)
    equipment_id = await _camera(service, org_id, CENTER)
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        stale = await uow.equipment.get(equipment_id)
    assert stale is not None
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.equipment.update(stale)
        await uow.commit()
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        with pytest.raises(VersionConflictError):
            await uow.equipment.update(stale)


async def test_failed_operation_rolls_back_everything(
    session_factory: Factory, test_settings: Settings
) -> None:
    service, org_id, _ = await _setup(session_factory, test_settings)
    equipment_id = await _camera(service, org_id, CENTER)

    async def fail_midway() -> None:
        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            await uow.equipment_history.add(
                equipment_id=equipment_id,
                from_status=EquipmentStatus.OPERACIONAL,
                to_status=EquipmentStatus.FURTADO,
                reason="não deveria persistir",
                changed_by=None,
                changed_at=datetime.now(UTC),
            )
            raise RuntimeError("falha no meio da operação")

    with pytest.raises(RuntimeError):
        await fail_midway()
    history = await service.status_history(equipment_id, PageRequest(10, 0))
    assert history.total == 1


async def test_preventive_job_against_database(
    session_factory: Factory, test_settings: Settings
) -> None:
    service, org_id, clock = await _setup(session_factory, test_settings)
    due = await _camera(service, org_id, CENTER, maintenance_plan=PlanSpec(3, None))
    stolen = await _camera(service, org_id, CENTER, maintenance_plan=PlanSpec(3, None))
    await service.change_status(stolen, EquipmentStatus.FURTADO, "Furto", None)
    clock.advance(timedelta(days=4))
    job = MaintenanceService(SqlAlchemyUnitOfWork(session_factory), clock, EquipmentLifecycle())

    assert await job.open_due_preventive_orders() == 1
    assert await job.open_due_preventive_orders() == 0
    async with session_factory() as session:
        rows = (
            (
                await session.execute(
                    text("SELECT equipment_id FROM maintenance_orders WHERE kind='preventiva'")
                )
            )
            .scalars()
            .all()
        )
    assert rows == [due]
