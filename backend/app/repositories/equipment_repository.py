"""Persistência de equipamentos e histórico de situação (consultas espaciais via PostGIS)."""

from collections.abc import Sequence
from datetime import date, datetime
from typing import Any
from uuid import UUID

from geoalchemy2 import Geography
from sqlalchemy import Select, and_, cast, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import VersionConflictError
from app.database.models.tables import (
    EquipmentModel,
    EquipmentStatusHistoryModel,
    EquipmentTypeModel,
    MaintenanceOrderModel,
    MaintenancePlanModel,
    OrganizationModel,
    RegionModel,
    UserModel,
)
from app.domain.equipment.entities import (
    Equipment,
    EquipmentRecord,
    EquipmentStatusChange,
    EquipmentTypeSummary,
)
from app.domain.equipment.filters import EquipmentFilters, EquipmentSort
from app.domain.equipment.status import EquipmentStatus
from app.domain.maintenance.entities import MaintenanceKind, MaintenanceOrderStatus, MaintenancePlan
from app.domain.organizations import OrganizationSummary
from app.domain.regions import RegionSummary
from app.domain.shared import GeoPoint, Page, PageRequest
from app.repositories.sql_helpers import (
    address_columns,
    address_from_row,
    geography_point_literal,
    latitude_of,
    like_pattern,
    longitude_of,
    point_element,
)

_LAT = latitude_of(EquipmentModel.location).label("latitude")
_LNG = longitude_of(EquipmentModel.location).label("longitude")


def _equipment_from_row(model: EquipmentModel, latitude: float, longitude: float) -> Equipment:
    return Equipment(
        id=model.id,
        type_code=model.type_code,
        serial_number=model.serial_number,
        brand=model.brand,
        model=model.model,
        organization_id=model.organization_id,
        status=model.status,
        address=address_from_row(model),
        location=GeoPoint(latitude=latitude, longitude=longitude),
        region_id=model.region_id,
        installed_on=model.installed_on,
        attributes=dict(model.attributes),
        maintenance_need=model.maintenance_need,
        next_maintenance_date=model.next_maintenance_date,
        version=model.version,
        created_at=model.created_at,
        updated_at=model.updated_at,
        created_by=model.created_by,
        updated_by=model.updated_by,
        archived_at=model.archived_at,
    )


def _plan_from_model(model: MaintenancePlanModel | None) -> MaintenancePlan | None:
    if model is None:
        return None
    return MaintenancePlan(
        equipment_id=model.equipment_id,
        interval_days=model.interval_days,
        next_due_date=model.next_due_date,
        last_done_on=model.last_done_on,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


class SqlEquipmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, equipment_id: UUID, *, for_update: bool = False) -> Equipment | None:
        stmt = select(EquipmentModel, _LAT, _LNG).where(EquipmentModel.id == equipment_id)
        if for_update:
            stmt = stmt.with_for_update(of=EquipmentModel)
        row = (await self._session.execute(stmt)).one_or_none()
        return _equipment_from_row(row[0], row.latitude, row.longitude) if row else None

    async def get_record(self, equipment_id: UUID) -> EquipmentRecord | None:
        stmt = self._record_select(None).where(EquipmentModel.id == equipment_id)
        row = (await self._session.execute(stmt)).one_or_none()
        return self._record_from_row(row) if row else None

    async def list_records(
        self, filters: EquipmentFilters, page: PageRequest
    ) -> Page[EquipmentRecord]:
        conditions = self._conditions(filters)
        count_stmt = select(func.count(EquipmentModel.id)).where(*conditions)
        total = (await self._session.execute(count_stmt)).scalar_one()

        center = geography_point_literal(filters.radius.center) if filters.radius else None
        stmt = self._record_select(center).where(*conditions)
        stmt = stmt.order_by(*self._ordering(filters.sort, center), EquipmentModel.id)
        rows = (await self._session.execute(stmt.limit(page.limit).offset(page.offset))).all()
        return Page([self._record_from_row(r) for r in rows], total, page.limit, page.offset)

    async def exists_brand_serial(
        self, brand: str, serial_number: str, exclude_id: UUID | None
    ) -> bool:
        stmt = select(EquipmentModel.id).where(
            func.lower(EquipmentModel.brand) == brand.lower(),
            func.lower(EquipmentModel.serial_number) == serial_number.lower(),
            EquipmentModel.archived_at.is_(None),
        )
        if exclude_id is not None:
            stmt = stmt.where(EquipmentModel.id != exclude_id)
        return (await self._session.execute(stmt.limit(1))).first() is not None

    async def add(self, equipment: Equipment) -> None:
        self._session.add(
            EquipmentModel(
                id=equipment.id,
                type_code=equipment.type_code,
                serial_number=equipment.serial_number,
                brand=equipment.brand,
                model=equipment.model,
                organization_id=equipment.organization_id,
                status=equipment.status,
                location=point_element(equipment.location),
                region_id=equipment.region_id,
                installed_on=equipment.installed_on,
                attributes=equipment.attributes,
                maintenance_need=equipment.maintenance_need,
                next_maintenance_date=equipment.next_maintenance_date,
                version=equipment.version,
                created_by=equipment.created_by,
                updated_by=equipment.updated_by,
                created_at=equipment.created_at,
                updated_at=equipment.updated_at,
                **address_columns(equipment.address),
            )
        )
        await self._session.flush()

    async def update(self, equipment: Equipment) -> int:
        stmt = (
            update(EquipmentModel)
            .where(EquipmentModel.id == equipment.id, EquipmentModel.version == equipment.version)
            .values(
                serial_number=equipment.serial_number,
                brand=equipment.brand,
                model=equipment.model,
                organization_id=equipment.organization_id,
                status=equipment.status,
                location=point_element(equipment.location),
                region_id=equipment.region_id,
                installed_on=equipment.installed_on,
                attributes=equipment.attributes,
                maintenance_need=equipment.maintenance_need,
                next_maintenance_date=equipment.next_maintenance_date,
                updated_by=equipment.updated_by,
                updated_at=equipment.updated_at,
                archived_at=equipment.archived_at,
                version=EquipmentModel.version + 1,
                **address_columns(equipment.address),
            )
            .returning(EquipmentModel.version)
        )
        new_version = (await self._session.execute(stmt)).scalar_one_or_none()
        if new_version is None:
            raise VersionConflictError(
                "O equipamento foi alterado por outra operação. Recarregue e tente novamente.",
                extra={"expected_version": equipment.version},
            )
        return new_version

    async def list_due_for_preventive(
        self, until: date, exempt_statuses: Sequence[EquipmentStatus]
    ) -> list[UUID]:
        open_preventive = (
            select(MaintenanceOrderModel.id)
            .where(
                MaintenanceOrderModel.equipment_id == EquipmentModel.id,
                MaintenanceOrderModel.kind == MaintenanceKind.PREVENTIVA,
                MaintenanceOrderModel.status.in_(
                    [MaintenanceOrderStatus.ABERTA, MaintenanceOrderStatus.EM_ANDAMENTO]
                ),
            )
            .exists()
        )
        stmt = (
            select(EquipmentModel.id)
            .join(MaintenancePlanModel, MaintenancePlanModel.equipment_id == EquipmentModel.id)
            .where(
                MaintenancePlanModel.next_due_date <= until,
                EquipmentModel.archived_at.is_(None),
                EquipmentModel.status.not_in(list(exempt_statuses)),
                ~open_preventive,
            )
            .order_by(MaintenancePlanModel.next_due_date)
        )
        return list((await self._session.execute(stmt)).scalars())

    @staticmethod
    def _record_select(center: Any | None) -> Select[Any]:
        columns: list[Any] = [
            EquipmentModel,
            _LAT,
            _LNG,
            EquipmentTypeModel,
            OrganizationModel,
            RegionModel.id.label("region_id_"),
            RegionModel.code.label("region_code"),
            RegionModel.name.label("region_name"),
            MaintenancePlanModel,
        ]
        if center is not None:
            columns.append(
                func.ST_Distance(EquipmentModel.location, cast(center, Geography)).label("distance")
            )
        return (
            select(*columns)
            .join(EquipmentTypeModel, EquipmentTypeModel.code == EquipmentModel.type_code)
            .join(OrganizationModel, OrganizationModel.id == EquipmentModel.organization_id)
            .outerjoin(RegionModel, RegionModel.id == EquipmentModel.region_id)
            .outerjoin(MaintenancePlanModel, MaintenancePlanModel.equipment_id == EquipmentModel.id)
        )

    @staticmethod
    def _record_from_row(row: Any) -> EquipmentRecord:
        type_model: EquipmentTypeModel = row.EquipmentTypeModel
        org: OrganizationModel = row.OrganizationModel
        return EquipmentRecord(
            equipment=_equipment_from_row(row.EquipmentModel, row.latitude, row.longitude),
            type=EquipmentTypeSummary(
                code=type_model.code,
                name=type_model.name,
                category=type_model.category,
                icon=type_model.icon,
            ),
            organization=OrganizationSummary(
                id=org.id, name=org.name, acronym=org.acronym, kind=org.kind
            ),
            region=(
                RegionSummary(id=row.region_id_, code=row.region_code, name=row.region_name)
                if row.region_id_
                else None
            ),
            maintenance_plan=_plan_from_model(row.MaintenancePlanModel),
            distance_m=getattr(row, "distance", None),
        )

    @staticmethod
    def _conditions(filters: EquipmentFilters) -> list[Any]:
        conditions: list[Any] = [EquipmentModel.archived_at.is_(None)]
        if filters.type_codes:
            conditions.append(EquipmentModel.type_code.in_(filters.type_codes))
        if filters.statuses:
            conditions.append(EquipmentModel.status.in_(filters.statuses))
        if filters.organization_ids:
            conditions.append(EquipmentModel.organization_id.in_(filters.organization_ids))
        if filters.region_ids:
            conditions.append(EquipmentModel.region_id.in_(filters.region_ids))
        if filters.neighborhood:
            conditions.append(
                func.lower(EquipmentModel.neighborhood) == filters.neighborhood.lower()
            )
        if filters.city:
            conditions.append(func.lower(EquipmentModel.city) == filters.city.lower())
        if filters.maintenance_needs:
            conditions.append(EquipmentModel.maintenance_need.in_(filters.maintenance_needs))
        if filters.next_maintenance_until:
            conditions.append(
                EquipmentModel.next_maintenance_date <= filters.next_maintenance_until
            )
        if filters.search:
            pattern = like_pattern(filters.search)
            conditions.append(
                or_(
                    EquipmentModel.serial_number.ilike(pattern, escape="\\"),
                    EquipmentModel.brand.ilike(pattern, escape="\\"),
                    EquipmentModel.model.ilike(pattern, escape="\\"),
                    EquipmentModel.street.ilike(pattern, escape="\\"),
                )
            )
        if filters.radius:
            center = cast(geography_point_literal(filters.radius.center), Geography)
            conditions.append(
                func.ST_DWithin(EquipmentModel.location, center, filters.radius.radius_m)
            )
        return conditions

    @staticmethod
    def _ordering(sort: EquipmentSort, center: Any | None) -> list[Any]:
        match sort:
            case EquipmentSort.CREATED_AT:
                return [EquipmentModel.created_at.asc()]
            case EquipmentSort.NEXT_MAINTENANCE:
                return [EquipmentModel.next_maintenance_date.asc().nulls_last()]
            case EquipmentSort.SERIAL_NUMBER:
                return [EquipmentModel.serial_number.asc()]
            case EquipmentSort.DISTANCE if center is not None:
                return [func.ST_Distance(EquipmentModel.location, cast(center, Geography))]
            case _:
                return [EquipmentModel.created_at.desc()]


class SqlEquipmentStatusHistoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

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
        self._session.add(
            EquipmentStatusHistoryModel(
                equipment_id=equipment_id,
                from_status=from_status,
                to_status=to_status,
                reason=reason,
                changed_by=changed_by,
                changed_at=changed_at,
            )
        )
        await self._session.flush()

    async def list_for_equipment(
        self, equipment_id: UUID, page: PageRequest
    ) -> Page[EquipmentStatusChange]:
        history = EquipmentStatusHistoryModel
        total = (
            await self._session.execute(
                select(func.count(history.id)).where(history.equipment_id == equipment_id)
            )
        ).scalar_one()
        stmt = (
            select(history, UserModel.full_name)
            .outerjoin(UserModel, and_(UserModel.id == history.changed_by))
            .where(history.equipment_id == equipment_id)
            .order_by(history.changed_at.desc(), history.id.desc())
            .limit(page.limit)
            .offset(page.offset)
        )
        rows = (await self._session.execute(stmt)).all()
        items = [
            EquipmentStatusChange(
                id=row[0].id,
                equipment_id=row[0].equipment_id,
                from_status=row[0].from_status,
                to_status=row[0].to_status,
                reason=row[0].reason,
                changed_by=row[0].changed_by,
                changed_by_name=row.full_name,
                changed_at=row[0].changed_at,
            )
            for row in rows
        ]
        return Page(items, total, page.limit, page.offset)
