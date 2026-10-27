"""Persistência de despachos de agentes."""

from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.tables import AgentModel, DispatchModel, EquipmentModel, OrganizationModel
from app.domain.operations.dispatch import (
    ACTIVE_DISPATCH_STATUSES,
    Dispatch,
    DispatchRecord,
)
from app.domain.shared import GeoPoint
from app.repositories.sql_helpers import latitude_of, longitude_of, point_element

_COLUMNS = (
    DispatchModel,
    latitude_of(DispatchModel.target).label("target_lat"),
    longitude_of(DispatchModel.target).label("target_lng"),
    latitude_of(DispatchModel.origin).label("origin_lat"),
    longitude_of(DispatchModel.origin).label("origin_lng"),
)


def _from_row(row: Any) -> Dispatch:
    model: DispatchModel = row.DispatchModel
    return Dispatch(
        id=model.id,
        agent_id=model.agent_id,
        equipment_id=model.equipment_id,
        alert_id=model.alert_id,
        status=model.status,
        target=GeoPoint(row.target_lat, row.target_lng),
        origin=GeoPoint(row.origin_lat, row.origin_lng),
        created_at=model.created_at,
        created_by=model.created_by,
        distance_m=model.distance_m,
        eta_minutes=model.eta_minutes,
        departed_at=model.departed_at,
        arrived_at=model.arrived_at,
        closed_at=model.closed_at,
        notes=model.notes,
    )


class SqlDispatchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, dispatch_id: UUID, *, for_update: bool = False) -> Dispatch | None:
        stmt = select(*_COLUMNS).where(DispatchModel.id == dispatch_id)
        if for_update:
            stmt = stmt.with_for_update(of=DispatchModel)
        row = (await self._session.execute(stmt)).one_or_none()
        return _from_row(row) if row else None

    async def active_for_agent(self, agent_id: UUID) -> Dispatch | None:
        stmt = select(*_COLUMNS).where(
            DispatchModel.agent_id == agent_id,
            DispatchModel.status.in_(ACTIVE_DISPATCH_STATUSES),
        )
        row = (await self._session.execute(stmt)).one_or_none()
        return _from_row(row) if row else None

    async def list_active(self) -> list[Dispatch]:
        stmt = select(*_COLUMNS).where(DispatchModel.status.in_(ACTIVE_DISPATCH_STATUSES))
        return [_from_row(r) for r in (await self._session.execute(stmt)).all()]

    async def get_record(self, dispatch_id: UUID) -> DispatchRecord | None:
        records = await self._records(DispatchModel.id == dispatch_id, limit=1)
        return records[0] if records else None

    async def list_records(self, active_only: bool, limit: int) -> list[DispatchRecord]:
        condition = DispatchModel.status.in_(ACTIVE_DISPATCH_STATUSES) if active_only else None
        return await self._records(condition, limit)

    async def _records(self, condition: Any, limit: int) -> list[DispatchRecord]:
        stmt = (
            select(
                *_COLUMNS,
                AgentModel.full_name,
                AgentModel.role,
                OrganizationModel.acronym,
                EquipmentModel.serial_number,
                EquipmentModel.type_code,
            )
            .join(AgentModel, AgentModel.id == DispatchModel.agent_id)
            .join(OrganizationModel, OrganizationModel.id == AgentModel.organization_id)
            .join(EquipmentModel, EquipmentModel.id == DispatchModel.equipment_id)
            .order_by(DispatchModel.created_at.desc())
            .limit(limit)
        )
        if condition is not None:
            stmt = stmt.where(condition)
        return [
            DispatchRecord(
                dispatch=_from_row(row),
                agent_name=row.full_name,
                agent_role=row.role,
                organization_acronym=row.acronym,
                equipment_serial=row.serial_number,
                equipment_type_code=row.type_code,
            )
            for row in (await self._session.execute(stmt)).all()
        ]

    async def add(self, dispatch: Dispatch) -> None:
        self._session.add(
            DispatchModel(
                id=dispatch.id,
                agent_id=dispatch.agent_id,
                equipment_id=dispatch.equipment_id,
                alert_id=dispatch.alert_id,
                status=dispatch.status,
                target=point_element(dispatch.target),
                origin=point_element(dispatch.origin),
                distance_m=dispatch.distance_m,
                eta_minutes=dispatch.eta_minutes,
                created_at=dispatch.created_at,
                created_by=dispatch.created_by,
            )
        )
        await self._session.flush()

    async def update(self, dispatch: Dispatch) -> None:
        await self._session.execute(
            update(DispatchModel)
            .where(DispatchModel.id == dispatch.id)
            .values(
                status=dispatch.status,
                departed_at=dispatch.departed_at,
                arrived_at=dispatch.arrived_at,
                closed_at=dispatch.closed_at,
                notes=dispatch.notes,
            )
        )
