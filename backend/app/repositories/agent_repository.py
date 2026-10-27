"""Persistência de agentes e do histórico de situação de serviço."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Select, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.exceptions import VersionConflictError
from app.database.models.tables import (
    AgentModel,
    AgentStatusHistoryModel,
    EquipmentModel,
    OrganizationModel,
    RegionModel,
    UserModel,
)
from app.domain.agents.entities import (
    ON_DUTY_STATUSES,
    Agent,
    AgentFilters,
    AgentRecord,
    AgentStatusChange,
    DutyStatus,
    VehicleSummary,
)
from app.domain.organizations import OrganizationSummary
from app.domain.regions import RegionSummary
from app.domain.shared import GeoPoint, Page, PageRequest
from app.repositories.sql_helpers import (
    address_columns,
    address_from_row,
    latitude_of,
    like_pattern,
    longitude_of,
    point_element,
)

_LAT = latitude_of(AgentModel.location).label("latitude")
_LNG = longitude_of(AgentModel.location).label("longitude")
_Vehicle = aliased(EquipmentModel, name="vehicle")


def _agent_from_row(model: AgentModel, latitude: float, longitude: float) -> Agent:
    return Agent(
        id=model.id,
        full_name=model.full_name,
        registration_number=model.registration_number,
        role=model.role,
        organization_id=model.organization_id,
        duty_status=model.duty_status,
        is_active=model.is_active,
        base_address=address_from_row(model),
        base_location=GeoPoint(latitude=latitude, longitude=longitude),
        region_id=model.region_id,
        assigned_vehicle_id=model.assigned_vehicle_id,
        version=model.version,
        created_at=model.created_at,
        updated_at=model.updated_at,
        archived_at=model.archived_at,
    )


class SqlAgentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, agent_id: UUID, *, for_update: bool = False) -> Agent | None:
        stmt = select(AgentModel, _LAT, _LNG).where(AgentModel.id == agent_id)
        if for_update:
            stmt = stmt.with_for_update(of=AgentModel)
        row = (await self._session.execute(stmt)).one_or_none()
        return _agent_from_row(row[0], row.latitude, row.longitude) if row else None

    async def get_record(self, agent_id: UUID) -> AgentRecord | None:
        row = (
            await self._session.execute(self._record_select().where(AgentModel.id == agent_id))
        ).one_or_none()
        return self._record_from_row(row) if row else None

    async def list_records(self, filters: AgentFilters, page: PageRequest) -> Page[AgentRecord]:
        conditions = self._conditions(filters)
        total = (
            await self._session.execute(select(func.count(AgentModel.id)).where(*conditions))
        ).scalar_one()
        stmt = (
            self._record_select()
            .where(*conditions)
            .order_by(AgentModel.full_name, AgentModel.id)
            .limit(page.limit)
            .offset(page.offset)
        )
        rows = (await self._session.execute(stmt)).all()
        return Page([self._record_from_row(r) for r in rows], total, page.limit, page.offset)

    async def current_position(self, agent_id: UUID) -> GeoPoint | None:
        """Posição GPS atual ou, na falta dela, a base de lotação."""
        position = func.coalesce(AgentModel.current_location, AgentModel.location)
        stmt = select(latitude_of(position), longitude_of(position)).where(
            AgentModel.id == agent_id
        )
        row = (await self._session.execute(stmt)).one_or_none()
        return GeoPoint(row[0], row[1]) if row else None

    async def exists_registration(
        self, organization_id: UUID, registration_number: str, exclude_id: UUID | None
    ) -> bool:
        stmt = select(AgentModel.id).where(
            AgentModel.organization_id == organization_id,
            func.lower(AgentModel.registration_number) == registration_number.lower(),
            AgentModel.archived_at.is_(None),
        )
        if exclude_id is not None:
            stmt = stmt.where(AgentModel.id != exclude_id)
        return (await self._session.execute(stmt.limit(1))).first() is not None

    async def count_active_crew(self, vehicle_id: UUID, exclude_agent_id: UUID | None) -> int:
        stmt = select(func.count(AgentModel.id)).where(
            AgentModel.assigned_vehicle_id == vehicle_id,
            AgentModel.is_active.is_(True),
            AgentModel.archived_at.is_(None),
        )
        if exclude_agent_id is not None:
            stmt = stmt.where(AgentModel.id != exclude_agent_id)
        return (await self._session.execute(stmt)).scalar_one()

    async def add(self, agent: Agent) -> None:
        self._session.add(
            AgentModel(
                id=agent.id,
                full_name=agent.full_name,
                registration_number=agent.registration_number,
                role=agent.role,
                organization_id=agent.organization_id,
                duty_status=agent.duty_status,
                is_active=agent.is_active,
                location=point_element(agent.base_location),
                region_id=agent.region_id,
                assigned_vehicle_id=agent.assigned_vehicle_id,
                version=agent.version,
                created_at=agent.created_at,
                updated_at=agent.updated_at,
                **address_columns(agent.base_address),
            )
        )
        await self._session.flush()

    async def update(self, agent: Agent) -> int:
        stmt = (
            update(AgentModel)
            .where(AgentModel.id == agent.id, AgentModel.version == agent.version)
            .values(
                full_name=agent.full_name,
                registration_number=agent.registration_number,
                role=agent.role,
                organization_id=agent.organization_id,
                duty_status=agent.duty_status,
                is_active=agent.is_active,
                location=point_element(agent.base_location),
                region_id=agent.region_id,
                assigned_vehicle_id=agent.assigned_vehicle_id,
                updated_at=agent.updated_at,
                archived_at=agent.archived_at,
                version=AgentModel.version + 1,
                **address_columns(agent.base_address),
            )
            .returning(AgentModel.version)
        )
        new_version = (await self._session.execute(stmt)).scalar_one_or_none()
        if new_version is None:
            raise VersionConflictError(
                "O agente foi alterado por outra operação. Recarregue e tente novamente.",
                extra={"expected_version": agent.version},
            )
        return new_version

    @staticmethod
    def _record_select() -> Select[Any]:
        return (
            select(
                AgentModel,
                _LAT,
                _LNG,
                OrganizationModel,
                RegionModel.id.label("region_id_"),
                RegionModel.code.label("region_code"),
                RegionModel.name.label("region_name"),
                _Vehicle.id.label("vehicle_id"),
                _Vehicle.type_code.label("vehicle_type_code"),
                _Vehicle.serial_number.label("vehicle_serial"),
                _Vehicle.model.label("vehicle_model"),
                _Vehicle.attributes["plate"].astext.label("vehicle_plate"),
            )
            .join(OrganizationModel, OrganizationModel.id == AgentModel.organization_id)
            .outerjoin(RegionModel, RegionModel.id == AgentModel.region_id)
            .outerjoin(_Vehicle, _Vehicle.id == AgentModel.assigned_vehicle_id)
        )

    @staticmethod
    def _record_from_row(row: Any) -> AgentRecord:
        org: OrganizationModel = row.OrganizationModel
        return AgentRecord(
            agent=_agent_from_row(row.AgentModel, row.latitude, row.longitude),
            organization=OrganizationSummary(
                id=org.id, name=org.name, acronym=org.acronym, kind=org.kind
            ),
            region=(
                RegionSummary(id=row.region_id_, code=row.region_code, name=row.region_name)
                if row.region_id_
                else None
            ),
            vehicle=(
                VehicleSummary(
                    id=row.vehicle_id,
                    type_code=row.vehicle_type_code,
                    serial_number=row.vehicle_serial,
                    model=row.vehicle_model,
                    plate=row.vehicle_plate,
                )
                if row.vehicle_id
                else None
            ),
        )

    @staticmethod
    def _conditions(filters: AgentFilters) -> list[Any]:
        conditions: list[Any] = [AgentModel.archived_at.is_(None)]
        if filters.roles:
            conditions.append(AgentModel.role.in_(filters.roles))
        if filters.duty_statuses:
            conditions.append(AgentModel.duty_status.in_(filters.duty_statuses))
        if filters.organization_ids:
            conditions.append(AgentModel.organization_id.in_(filters.organization_ids))
        if filters.region_ids:
            conditions.append(AgentModel.region_id.in_(filters.region_ids))
        if filters.on_duty is not None:
            on_duty = AgentModel.duty_status.in_(ON_DUTY_STATUSES)
            conditions.append(on_duty if filters.on_duty else ~on_duty)
        if filters.is_active is not None:
            conditions.append(AgentModel.is_active.is_(filters.is_active))
        if filters.search:
            pattern = like_pattern(filters.search)
            conditions.append(
                or_(
                    AgentModel.full_name.ilike(pattern, escape="\\"),
                    AgentModel.registration_number.ilike(pattern, escape="\\"),
                )
            )
        return conditions


class SqlAgentStatusHistoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

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
        self._session.add(
            AgentStatusHistoryModel(
                agent_id=agent_id,
                from_status=from_status,
                to_status=to_status,
                reason=reason,
                changed_by=changed_by,
                changed_at=changed_at,
            )
        )
        await self._session.flush()

    async def list_for_agent(self, agent_id: UUID, page: PageRequest) -> Page[AgentStatusChange]:
        history = AgentStatusHistoryModel
        total = (
            await self._session.execute(
                select(func.count(history.id)).where(history.agent_id == agent_id)
            )
        ).scalar_one()
        stmt = (
            select(history, UserModel.full_name)
            .outerjoin(UserModel, UserModel.id == history.changed_by)
            .where(history.agent_id == agent_id)
            .order_by(history.changed_at.desc(), history.id.desc())
            .limit(page.limit)
            .offset(page.offset)
        )
        rows = (await self._session.execute(stmt)).all()
        items = [
            AgentStatusChange(
                id=row[0].id,
                agent_id=row[0].agent_id,
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
