"""Persistência de dados de referência: órgãos, regiões e tipos de equipamento."""

import json
from typing import Any
from uuid import UUID

from sqlalchemy import delete, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.tables import (
    AgentModel,
    EquipmentModel,
    EquipmentTypeModel,
    OrganizationModel,
    RegionModel,
)
from app.domain.equipment.entities import EquipmentType
from app.domain.organizations import Organization, OrganizationUsage
from app.domain.regions import Region
from app.domain.shared import GeoPoint
from app.repositories.sql_helpers import geography_point_literal


def _organization_to_domain(model: OrganizationModel) -> Organization:
    return Organization(
        id=model.id,
        name=model.name,
        acronym=model.acronym,
        kind=model.kind,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _type_to_domain(model: EquipmentTypeModel) -> EquipmentType:
    return EquipmentType(
        code=model.code,
        name=model.name,
        category=model.category,
        icon=model.icon,
        is_mobile=model.is_mobile,
        is_vehicle=model.is_vehicle,
        attributes_schema_key=model.attributes_schema_key,
        description=model.description,
    )


class SqlOrganizationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, organization_id: UUID) -> Organization | None:
        model = await self._session.get(OrganizationModel, organization_id)
        return _organization_to_domain(model) if model else None

    async def list_all(self) -> list[Organization]:
        stmt = select(OrganizationModel).order_by(OrganizationModel.name)
        return [_organization_to_domain(m) for m in (await self._session.execute(stmt)).scalars()]

    async def find_conflicting(
        self, name: str, acronym: str, exclude_id: UUID | None
    ) -> Organization | None:
        stmt = select(OrganizationModel).where(
            or_(
                func.lower(OrganizationModel.name) == name.lower(),
                func.lower(OrganizationModel.acronym) == acronym.lower(),
            )
        )
        if exclude_id is not None:
            stmt = stmt.where(OrganizationModel.id != exclude_id)
        model = (await self._session.execute(stmt.limit(1))).scalar_one_or_none()
        return _organization_to_domain(model) if model else None

    async def is_referenced(self, organization_id: UUID) -> bool:
        stmt = select(
            exists().where(EquipmentModel.organization_id == organization_id)
            | exists().where(AgentModel.organization_id == organization_id)
        )
        return bool((await self._session.execute(stmt)).scalar_one())

    async def usage(self) -> dict[UUID, OrganizationUsage]:
        equipment = (
            select(EquipmentModel.organization_id, func.count().label("n"))
            .group_by(EquipmentModel.organization_id)
            .subquery()
        )
        agents = (
            select(AgentModel.organization_id, func.count().label("n"))
            .group_by(AgentModel.organization_id)
            .subquery()
        )
        stmt = (
            select(
                OrganizationModel.id,
                func.coalesce(equipment.c.n, 0),
                func.coalesce(agents.c.n, 0),
            )
            .outerjoin(equipment, equipment.c.organization_id == OrganizationModel.id)
            .outerjoin(agents, agents.c.organization_id == OrganizationModel.id)
        )
        rows = (await self._session.execute(stmt)).all()
        return {org_id: OrganizationUsage(int(eq), int(ag)) for org_id, eq, ag in rows}

    async def add(self, organization: Organization) -> None:
        self._session.add(
            OrganizationModel(
                id=organization.id,
                name=organization.name,
                acronym=organization.acronym,
                kind=organization.kind,
                created_at=organization.created_at,
                updated_at=organization.updated_at,
            )
        )
        await self._session.flush()

    async def update(self, organization: Organization) -> None:
        await self._session.execute(
            update(OrganizationModel)
            .where(OrganizationModel.id == organization.id)
            .values(
                name=organization.name,
                acronym=organization.acronym,
                kind=organization.kind,
                updated_at=organization.updated_at,
            )
        )

    async def delete(self, organization_id: UUID) -> None:
        await self._session.execute(
            delete(OrganizationModel).where(OrganizationModel.id == organization_id)
        )


class SqlRegionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_all(self, include_geometry: bool) -> list[Region]:
        geometry = func.ST_AsGeoJSON(RegionModel.geom, 6) if include_geometry else None
        columns: list[Any] = [RegionModel.id, RegionModel.code, RegionModel.name]
        if geometry is not None:
            columns.append(geometry.label("geojson"))
        rows = (await self._session.execute(select(*columns).order_by(RegionModel.name))).all()
        return [
            Region(
                id=row.id,
                code=row.code,
                name=row.name,
                geometry=json.loads(row.geojson) if include_geometry else None,
            )
            for row in rows
        ]

    async def find_covering(self, point: GeoPoint) -> UUID | None:
        stmt = (
            select(RegionModel.id)
            .where(func.ST_Covers(RegionModel.geom, geography_point_literal(point)))
            .order_by(func.ST_Area(RegionModel.geom))  # a menor região que contém o ponto
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def code_of(self, region_id: UUID) -> str | None:
        stmt = select(RegionModel.code).where(RegionModel.id == region_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def add(self, code: str, name: str, geometry: dict[str, Any]) -> UUID:
        model = RegionModel(
            code=code,
            name=name,
            geom=func.ST_Multi(
                func.ST_SetSRID(func.ST_GeomFromGeoJSON(json.dumps(geometry)), 4326)
            ),
        )
        self._session.add(model)
        await self._session.flush()
        return model.id


class SqlEquipmentTypeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_all(self) -> list[EquipmentType]:
        stmt = select(EquipmentTypeModel).order_by(EquipmentTypeModel.name)
        return [_type_to_domain(m) for m in (await self._session.execute(stmt)).scalars()]

    async def get(self, code: str) -> EquipmentType | None:
        model = await self._session.get(EquipmentTypeModel, code)
        return _type_to_domain(model) if model else None

    async def add(self, equipment_type: EquipmentType) -> None:
        self._session.add(
            EquipmentTypeModel(
                code=equipment_type.code,
                name=equipment_type.name,
                category=equipment_type.category,
                icon=equipment_type.icon,
                is_mobile=equipment_type.is_mobile,
                is_vehicle=equipment_type.is_vehicle,
                attributes_schema_key=equipment_type.attributes_schema_key,
                description=equipment_type.description,
            )
        )
        await self._session.flush()
