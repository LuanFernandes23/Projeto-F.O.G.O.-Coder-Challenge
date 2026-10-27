"""Persistência de telemetria IoT e posições de agentes (operações em lote)."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.tables import (
    AgentModel,
    AgentPositionModel,
    DispatchModel,
    EquipmentModel,
    MaintenanceOrderModel,
    RegionModel,
    TelemetryReadingModel,
)
from app.domain.maintenance.entities import (
    MaintenanceKind,
    MaintenanceOrderStatus,
    MaintenancePriority,
)
from app.domain.operations.dispatch import ACTIVE_DISPATCH_STATUSES, DispatchStatus
from app.domain.operations.telemetry import (
    DeviceState,
    RegistryAgent,
    RegistryDevice,
    battery_of,
)
from app.domain.shared import GeoPoint
from app.repositories.sql_helpers import latitude_of, longitude_of, point_element


class SqlTelemetryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def device_states(self, equipment_ids: Sequence[UUID]) -> list[DeviceState]:
        if not equipment_ids:
            return []
        stmt = (
            select(
                EquipmentModel.id,
                EquipmentModel.type_code,
                EquipmentModel.status,
                EquipmentModel.region_id,
                RegionModel.code,
                EquipmentModel.last_seen_at,
                EquipmentModel.last_reading_at,
                EquipmentModel.last_telemetry,
            )
            .outerjoin(RegionModel, RegionModel.id == EquipmentModel.region_id)
            .where(EquipmentModel.id.in_(equipment_ids), EquipmentModel.archived_at.is_(None))
        )
        return [
            DeviceState(
                equipment_id=row.id,
                type_code=row.type_code,
                status=row.status,
                region_id=row.region_id,
                region_code=row.code,
                last_seen_at=row.last_seen_at,
                last_reading_at=row.last_reading_at,
                battery_pct=battery_of(row.last_telemetry or {}),
            )
            for row in (await self._session.execute(stmt)).all()
        ]

    async def record_heartbeats(self, rows: Sequence[dict[str, Any]]) -> None:
        """``rows``: dicionários com ``id``, ``last_seen_at`` e ``last_telemetry``."""
        if rows:
            await self._session.execute(update(EquipmentModel), list(rows))

    async def add_readings(self, rows: Sequence[tuple[UUID, datetime, dict[str, Any]]]) -> None:
        if not rows:
            return
        await self._session.execute(
            insert(TelemetryReadingModel),
            [{"equipment_id": e, "recorded_at": at, "metrics": m} for e, at, m in rows],
        )
        await self._session.execute(
            update(EquipmentModel),
            [{"id": e, "last_reading_at": at} for e, at, _ in rows],
        )

    async def update_agent_positions(self, rows: Sequence[tuple[UUID, datetime, GeoPoint]]) -> None:
        if rows:
            await self._session.execute(
                update(AgentModel),
                [
                    {"id": a, "last_position_at": at, "current_location": point_element(p)}
                    for a, at, p in rows
                ],
            )

    async def last_sampled_positions(
        self, agent_ids: Sequence[UUID], since: datetime
    ) -> dict[UUID, datetime]:
        if not agent_ids:
            return {}
        stmt = (
            select(AgentPositionModel.agent_id, func.max(AgentPositionModel.recorded_at))
            .where(
                AgentPositionModel.agent_id.in_(agent_ids),
                AgentPositionModel.recorded_at >= since,
            )
            .group_by(AgentPositionModel.agent_id)
        )
        return {row[0]: row[1] for row in (await self._session.execute(stmt)).all()}

    async def add_agent_positions(self, rows: Sequence[tuple[UUID, datetime, GeoPoint]]) -> None:
        if rows:
            await self._session.execute(
                insert(AgentPositionModel),
                [
                    {"agent_id": a, "recorded_at": at, "location": point_element(p)}
                    for a, at, p in rows
                ],
            )

    async def known_agent_ids(self, agent_ids: Sequence[UUID]) -> set[UUID]:
        if not agent_ids:
            return set()
        stmt = select(AgentModel.id).where(
            AgentModel.id.in_(agent_ids), AgentModel.archived_at.is_(None)
        )
        return set((await self._session.execute(stmt)).scalars())

    async def registry_devices(self) -> list[RegistryDevice]:
        # Intervenção em curso: OS preventiva imediata aberta ou equipe despachada no local.
        order_since = (
            select(func.min(MaintenanceOrderModel.opened_at))
            .where(
                MaintenanceOrderModel.equipment_id == EquipmentModel.id,
                MaintenanceOrderModel.kind == MaintenanceKind.PREVENTIVA,
                MaintenanceOrderModel.priority == MaintenancePriority.IMEDIATA,
                MaintenanceOrderModel.status.in_(
                    [MaintenanceOrderStatus.ABERTA, MaintenanceOrderStatus.EM_ANDAMENTO]
                ),
            )
            .scalar_subquery()
        )
        arrived_since = (
            select(func.min(DispatchModel.arrived_at))
            .where(
                DispatchModel.equipment_id == EquipmentModel.id,
                DispatchModel.status == DispatchStatus.NO_LOCAL,
            )
            .scalar_subquery()
        )
        stmt = (
            select(
                EquipmentModel.id,
                EquipmentModel.type_code,
                EquipmentModel.status,
                latitude_of(EquipmentModel.location).label("lat"),
                longitude_of(EquipmentModel.location).label("lng"),
                RegionModel.code,
                func.least(order_since, arrived_since).label("intervention_since"),
            )
            .outerjoin(RegionModel, RegionModel.id == EquipmentModel.region_id)
            .where(EquipmentModel.archived_at.is_(None))
        )
        return [
            RegistryDevice(
                row.id,
                row.type_code,
                row.status,
                GeoPoint(row.lat, row.lng),
                row.code,
                row.intervention_since,
            )
            for row in (await self._session.execute(stmt)).all()
        ]

    async def registry_agents(self) -> list[RegistryAgent]:
        vehicle = EquipmentModel.__table__.alias("vehicle")
        stmt = (
            select(
                AgentModel.id,
                AgentModel.duty_status,
                AgentModel.is_active,
                RegionModel.code,
                latitude_of(AgentModel.location).label("base_lat"),
                longitude_of(AgentModel.location).label("base_lng"),
                latitude_of(AgentModel.current_location).label("cur_lat"),
                longitude_of(AgentModel.current_location).label("cur_lng"),
                vehicle.c.type_code.label("vehicle_type"),
                latitude_of(DispatchModel.target).label("target_lat"),
                longitude_of(DispatchModel.target).label("target_lng"),
            )
            .outerjoin(RegionModel, RegionModel.id == AgentModel.region_id)
            .outerjoin(vehicle, vehicle.c.id == AgentModel.assigned_vehicle_id)
            .outerjoin(
                DispatchModel,
                (DispatchModel.agent_id == AgentModel.id)
                & DispatchModel.status.in_(ACTIVE_DISPATCH_STATUSES),
            )
            .where(AgentModel.archived_at.is_(None))
        )
        return [
            RegistryAgent(
                agent_id=row.id,
                duty_status=row.duty_status,
                is_active=row.is_active,
                region_code=row.code,
                base=GeoPoint(row.base_lat, row.base_lng),
                current=GeoPoint(row.cur_lat, row.cur_lng) if row.cur_lat is not None else None,
                vehicle_type=row.vehicle_type,
                dispatch_target=(
                    GeoPoint(row.target_lat, row.target_lng) if row.target_lat is not None else None
                ),
            )
            for row in (await self._session.execute(stmt)).all()
        ]

    async def purge_older_than(self, cutoff: datetime) -> int:
        readings = await self._session.execute(
            delete(TelemetryReadingModel).where(TelemetryReadingModel.recorded_at < cutoff)
        )
        positions = await self._session.execute(
            delete(AgentPositionModel).where(AgentPositionModel.recorded_at < cutoff)
        )
        return int(readings.rowcount or 0) + int(positions.rowcount or 0)  # type: ignore[attr-defined]
