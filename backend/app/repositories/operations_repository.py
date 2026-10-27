"""Consultas agregadas da Central de Operações (SQL direto e otimizado, só leitura)."""

from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from geoalchemy2 import Geography, Geometry
from sqlalchemy import and_, cast, func, literal_column, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.tables import (
    AgentModel,
    AlertModel,
    DispatchModel,
    EquipmentModel,
    EquipmentStatusHistoryModel,
    EquipmentTypeModel,
    OrganizationModel,
    RegionModel,
)
from app.domain.agents.entities import ON_DUTY_STATUSES, AgentRole, DutyStatus
from app.domain.equipment.status import EquipmentStatus
from app.domain.maintenance.entities import (
    MaintenanceKind,
    MaintenanceNeed,
    MaintenanceOrderStatus,
)
from app.domain.operations.alerts import AlertKind, AlertSeverity, AlertStatus
from app.domain.operations.dispatch import ACTIVE_DISPATCH_STATUSES, DispatchCandidate
from app.domain.operations.read_models import (
    AgentCounts,
    AlertCounts,
    ConnectivityCounts,
    HeatPoint,
    MaintenanceCounts,
    MapAgentFeature,
    MapEquipmentFeature,
    MonitoredDevice,
    TrendPoint,
    TypeBreakdown,
)
from app.domain.operations.region_health import RegionMetrics
from app.domain.operations.telemetry import CONNECTIVITY_MONITORED_STATUSES, OFFLINE_AFTER
from app.domain.shared import GeoPoint
from app.repositories.sql_helpers import geography_point_literal, latitude_of, longitude_of

_UNAVAILABLE = (
    EquipmentStatus.MAU_FUNCIONAMENTO,
    EquipmentStatus.EM_MANUTENCAO,
    EquipmentStatus.FURTADO,
)
_MONITORED = tuple(CONNECTIVITY_MONITORED_STATUSES)
_OPEN_ALERT = AlertModel.status != AlertStatus.RESOLVIDO
_ACTIVE_EQUIPMENT = EquipmentModel.archived_at.is_(None)
_AGENT_POSITION = func.coalesce(AgentModel.current_location, AgentModel.location)


class SqlOperationsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ---- indicadores gerais ---------------------------------------------------------

    async def status_counts(self) -> dict[EquipmentStatus, int]:
        stmt = (
            select(EquipmentModel.status, func.count())
            .where(_ACTIVE_EQUIPMENT)
            .group_by(EquipmentModel.status)
        )
        return {row[0]: row[1] for row in (await self._session.execute(stmt)).all()}

    async def connectivity_counts(self, now: datetime) -> ConnectivityCounts:
        threshold = now - OFFLINE_AFTER
        monitored = and_(_ACTIVE_EQUIPMENT, EquipmentModel.status.in_(_MONITORED))
        stmt = select(
            func.count().filter(EquipmentModel.last_seen_at >= threshold),
            func.count().filter(EquipmentModel.last_seen_at < threshold),
            func.count().filter(EquipmentModel.last_seen_at.is_(None)),
        ).where(monitored)
        online, offline, unknown = (await self._session.execute(stmt)).one()
        return ConnectivityCounts(online, offline, unknown)

    async def maintenance_counts(self, today: date, due_soon_days: int) -> MaintenanceCounts:
        next_date = EquipmentModel.next_maintenance_date
        stmt = select(
            func.count().filter(EquipmentModel.maintenance_need == MaintenanceNeed.IMEDIATA),
            func.count().filter(
                next_date >= today, next_date <= today + timedelta(days=due_soon_days)
            ),
            func.count().filter(next_date < today),
        ).where(_ACTIVE_EQUIPMENT)
        immediate, due_soon, overdue = (await self._session.execute(stmt)).one()
        return MaintenanceCounts(immediate, due_soon, overdue)

    async def agent_counts(self) -> AgentCounts:
        active = and_(AgentModel.archived_at.is_(None), AgentModel.is_active.is_(True))
        stmt = select(
            func.count(),
            func.count().filter(AgentModel.duty_status.in_(ON_DUTY_STATUSES)),
        ).where(active)
        total, on_duty = (await self._session.execute(stmt)).one()
        dispatched = (
            await self._session.execute(
                select(func.count()).where(DispatchModel.status.in_(ACTIVE_DISPATCH_STATUSES))
            )
        ).scalar_one()
        return AgentCounts(total, on_duty, dispatched)

    async def alert_counts(self, now: datetime) -> AlertCounts:
        stmt = (
            select(AlertModel.severity, func.count())
            .where(_OPEN_ALERT)
            .group_by(AlertModel.severity)
        )
        by_severity = {row[0]: row[1] for row in (await self._session.execute(stmt)).all()}
        breached = (
            await self._session.execute(
                select(func.count()).where(_OPEN_ALERT, AlertModel.sla_due_at < now)
            )
        ).scalar_one()
        return AlertCounts(by_severity, breached)

    async def type_breakdown(self) -> list[TypeBreakdown]:
        stmt = (
            select(
                EquipmentTypeModel.code,
                EquipmentTypeModel.name,
                EquipmentTypeModel.icon,
                func.count(EquipmentModel.id),
                func.count(EquipmentModel.id).filter(
                    EquipmentModel.status == EquipmentStatus.OPERACIONAL
                ),
                func.count(EquipmentModel.id).filter(EquipmentModel.status.in_(_UNAVAILABLE)),
            )
            .join(
                EquipmentModel,
                and_(EquipmentModel.type_code == EquipmentTypeModel.code, _ACTIVE_EQUIPMENT),
            )
            .group_by(EquipmentTypeModel.code)
            .order_by(func.count(EquipmentModel.id).desc())
        )
        return [TypeBreakdown(*row) for row in (await self._session.execute(stmt)).all()]

    # ---- mapa -----------------------------------------------------------------------

    async def map_equipment(self) -> list[MapEquipmentFeature]:
        alerts = (
            select(
                AlertModel.equipment_id.label("equipment_id"),
                func.count().label("open_alerts"),
                func.max(
                    func.array_position(
                        literal_column("ARRAY['baixa','media','alta','critica']::varchar[]"),
                        AlertModel.severity,
                    )
                ).label("top_rank"),
            )
            .where(_OPEN_ALERT, AlertModel.equipment_id.is_not(None))
            .group_by(AlertModel.equipment_id)
            .subquery()
        )
        stmt = (
            select(
                EquipmentModel.id,
                EquipmentModel.type_code,
                EquipmentModel.serial_number,
                EquipmentModel.status,
                latitude_of(EquipmentModel.location).label("lat"),
                longitude_of(EquipmentModel.location).label("lng"),
                EquipmentModel.region_id,
                EquipmentModel.organization_id,
                EquipmentModel.neighborhood,
                EquipmentModel.maintenance_need,
                EquipmentModel.next_maintenance_date,
                EquipmentModel.last_seen_at,
                func.coalesce(alerts.c.open_alerts, 0).label("open_alerts"),
                alerts.c.top_rank,
            )
            .outerjoin(alerts, alerts.c.equipment_id == EquipmentModel.id)
            .where(_ACTIVE_EQUIPMENT)
        )
        ranks = [
            AlertSeverity.BAIXA,
            AlertSeverity.MEDIA,
            AlertSeverity.ALTA,
            AlertSeverity.CRITICA,
        ]
        return [
            MapEquipmentFeature(
                id=row.id,
                type_code=row.type_code,
                serial_number=row.serial_number,
                status=row.status,
                latitude=row.lat,
                longitude=row.lng,
                region_id=row.region_id,
                organization_id=row.organization_id,
                neighborhood=row.neighborhood,
                maintenance_need=row.maintenance_need,
                next_maintenance_date=row.next_maintenance_date,
                last_seen_at=row.last_seen_at,
                open_alerts=row.open_alerts,
                top_alert_severity=ranks[row.top_rank - 1] if row.top_rank else None,
            )
            for row in (await self._session.execute(stmt)).all()
        ]

    async def map_agents(self) -> list[MapAgentFeature]:
        vehicle = EquipmentModel.__table__.alias("vehicle")
        stmt = (
            select(
                AgentModel.id,
                AgentModel.full_name,
                AgentModel.role,
                AgentModel.organization_id,
                AgentModel.duty_status,
                latitude_of(_AGENT_POSITION).label("lat"),
                longitude_of(_AGENT_POSITION).label("lng"),
                AgentModel.region_id,
                AgentModel.last_position_at,
                vehicle.c.type_code.label("vehicle_type"),
                DispatchModel.id.label("dispatch_id"),
                DispatchModel.status.label("dispatch_status"),
            )
            .outerjoin(vehicle, vehicle.c.id == AgentModel.assigned_vehicle_id)
            .outerjoin(
                DispatchModel,
                and_(
                    DispatchModel.agent_id == AgentModel.id,
                    DispatchModel.status.in_(ACTIVE_DISPATCH_STATUSES),
                ),
            )
            .where(AgentModel.archived_at.is_(None), AgentModel.is_active.is_(True))
        )
        return [
            MapAgentFeature(
                id=row.id,
                full_name=row.full_name,
                role=row.role,
                organization_id=row.organization_id,
                duty_status=row.duty_status,
                latitude=row.lat,
                longitude=row.lng,
                region_id=row.region_id,
                last_position_at=row.last_position_at,
                vehicle_type=row.vehicle_type,
                dispatch_id=row.dispatch_id,
                dispatch_status=row.dispatch_status,
            )
            for row in (await self._session.execute(stmt)).all()
        ]

    # ---- regiões --------------------------------------------------------------------

    async def region_metrics(self, now: datetime, today: date) -> list[RegionMetrics]:
        threshold = now - OFFLINE_AFTER
        eq = EquipmentModel
        counts = (
            select(
                RegionModel.id,
                RegionModel.code,
                RegionModel.name,
                func.count(eq.id).filter(eq.status == EquipmentStatus.OPERACIONAL),
                func.count(eq.id).filter(eq.status.in_(_UNAVAILABLE)),
                func.count(eq.id).filter(eq.status.in_(_MONITORED), eq.last_seen_at < threshold),
                func.count(eq.id).filter(eq.maintenance_need == MaintenanceNeed.IMEDIATA),
                func.count(eq.id).filter(eq.next_maintenance_date < today),
            )
            .outerjoin(eq, and_(eq.region_id == RegionModel.id, eq.archived_at.is_(None)))
            .group_by(RegionModel.id)
            .order_by(RegionModel.name)
        )
        alert_rows = (
            await self._session.execute(
                select(AlertModel.region_id, AlertModel.status, AlertModel.severity, func.count())
                .where(
                    _OPEN_ALERT,
                    AlertModel.region_id.is_not(None),
                    # O alerta de região degradada é consequência da nota, não causa:
                    # contá-lo derrubaria a nota de novo (realimentação).
                    AlertModel.kind != AlertKind.REGIAO_DEGRADADA,
                )
                .group_by(AlertModel.region_id, AlertModel.status, AlertModel.severity)
            )
        ).all()
        alerts: dict[UUID, dict[AlertSeverity, int]] = {}
        acknowledged: dict[UUID, dict[AlertSeverity, int]] = {}
        for region_id, status, severity, count in alert_rows:
            target = alerts if status is AlertStatus.ABERTO else acknowledged
            target.setdefault(region_id, {})[severity] = count

        on_duty_rows = (
            await self._session.execute(
                select(RegionModel.id, func.count(AgentModel.id))
                .join(
                    AgentModel,
                    func.ST_Covers(RegionModel.geom, cast(_AGENT_POSITION, Geometry)),
                )
                .where(
                    AgentModel.archived_at.is_(None),
                    AgentModel.duty_status.in_(ON_DUTY_STATUSES),
                )
                .group_by(RegionModel.id)
            )
        ).all()
        on_duty = {row[0]: row[1] for row in on_duty_rows}

        return [
            RegionMetrics(
                region_id=row[0],
                code=row[1],
                name=row[2],
                operational=row[3],
                unavailable=row[4],
                offline=row[5],
                immediate_maintenance=row[6],
                overdue_maintenance=row[7],
                agents_on_duty=on_duty.get(row[0], 0),
                open_alerts=alerts.get(row[0], {}),
                acknowledged_alerts=acknowledged.get(row[0], {}),
            )
            for row in (await self._session.execute(counts)).all()
        ]

    # ---- análises ---------------------------------------------------------------------

    async def heatmap(
        self, statuses: Sequence[EquipmentStatus], since: datetime
    ) -> list[HeatPoint]:
        history = EquipmentStatusHistoryModel
        stmt = (
            select(
                latitude_of(EquipmentModel.location),
                longitude_of(EquipmentModel.location),
                func.count(history.id),
            )
            .join(EquipmentModel, EquipmentModel.id == history.equipment_id)
            .where(history.to_status.in_(statuses), history.changed_at >= since)
            .group_by(EquipmentModel.id)
        )
        return [HeatPoint(r[0], r[1], r[2]) for r in (await self._session.execute(stmt)).all()]

    async def trends(self, start: date, end: date, timezone: str) -> list[TrendPoint]:
        params = {"start": start, "end": end, "tz": timezone}
        sql = text(
            """
            WITH days AS (
                SELECT generate_series(:start, :end, interval '1 day')::date AS day
            ),
            failures AS (
                SELECT (changed_at AT TIME ZONE :tz)::date AS day, count(*) AS n
                FROM equipment_status_history
                WHERE to_status = 'mau_funcionamento'
                  AND changed_at >= (:start)::timestamp AT TIME ZONE :tz
                GROUP BY 1
            ),
            repairs AS (
                SELECT (completed_at AT TIME ZONE :tz)::date AS day,
                       count(*) AS n,
                       avg(extract(epoch FROM completed_at - opened_at)) / 3600 AS mttr
                FROM maintenance_orders
                WHERE kind = :corrective AND status = :done
                  AND completed_at >= (:start)::timestamp AT TIME ZONE :tz
                GROUP BY 1
            )
            SELECT d.day, coalesce(f.n, 0), coalesce(r.n, 0), r.mttr
            FROM days d
            LEFT JOIN failures f ON f.day = d.day
            LEFT JOIN repairs r ON r.day = d.day
            ORDER BY d.day
            """
        )
        rows = await self._session.execute(
            sql,
            {
                **params,
                "corrective": MaintenanceKind.CORRETIVA.value,
                "done": MaintenanceOrderStatus.CONCLUIDA.value,
            },
        )
        return [
            TrendPoint(r[0], r[1], r[2], round(float(r[3]), 1) if r[3] is not None else None)
            for r in rows.all()
        ]

    # ---- despacho (KNN) -------------------------------------------------------------

    async def dispatch_candidates(
        self,
        target: GeoPoint,
        roles: Sequence[AgentRole],
        duty_statuses: Sequence[DutyStatus],
        limit: int,
    ) -> list[DispatchCandidate]:
        """Agentes livres mais próximos (operador KNN ``<->`` do PostGIS)."""
        point = cast(geography_point_literal(target), Geography)
        vehicle = EquipmentModel.__table__.alias("vehicle")
        busy = (
            select(DispatchModel.id)
            .where(
                DispatchModel.agent_id == AgentModel.id,
                DispatchModel.status.in_(ACTIVE_DISPATCH_STATUSES),
            )
            .exists()
        )
        stmt = (
            select(
                AgentModel.id,
                AgentModel.full_name,
                AgentModel.role,
                OrganizationModel.acronym,
                AgentModel.duty_status,
                latitude_of(_AGENT_POSITION).label("lat"),
                longitude_of(_AGENT_POSITION).label("lng"),
                func.ST_Distance(_AGENT_POSITION, point).label("distance"),
                vehicle.c.type_code.label("vehicle_type"),
            )
            .join(OrganizationModel, OrganizationModel.id == AgentModel.organization_id)
            .outerjoin(vehicle, vehicle.c.id == AgentModel.assigned_vehicle_id)
            .where(
                AgentModel.archived_at.is_(None),
                AgentModel.is_active.is_(True),
                AgentModel.role.in_(roles),
                AgentModel.duty_status.in_(duty_statuses),
                ~busy,
            )
            .order_by(_AGENT_POSITION.op("<->")(point))
            .limit(limit)
        )
        return [
            DispatchCandidate(
                agent_id=row.id,
                full_name=row.full_name,
                role=row.role,
                organization_acronym=row.acronym,
                duty_status=row.duty_status,
                location=GeoPoint(row.lat, row.lng),
                distance_m=float(row.distance),
                vehicle_type=row.vehicle_type,
            )
            for row in (await self._session.execute(stmt)).all()
        ]

    # ---- insumos do job de varredura de alertas ---------------------------------------

    async def offline_devices(self, now: datetime) -> list[MonitoredDevice]:
        stmt = self._monitored_select().where(
            EquipmentModel.status.in_(_MONITORED),
            EquipmentModel.last_seen_at < now - OFFLINE_AFTER,
        )
        return await self._monitored(stmt)

    async def overdue_devices(self, today: date) -> list[MonitoredDevice]:
        stmt = self._monitored_select().where(EquipmentModel.next_maintenance_date < today)
        return await self._monitored(stmt)

    @staticmethod
    def _monitored_select() -> Any:
        return (
            select(
                EquipmentModel.id,
                EquipmentModel.type_code,
                EquipmentModel.serial_number,
                EquipmentModel.region_id,
                RegionModel.code,
                EquipmentModel.last_seen_at,
                EquipmentModel.next_maintenance_date,
            )
            .outerjoin(RegionModel, RegionModel.id == EquipmentModel.region_id)
            .where(_ACTIVE_EQUIPMENT)
        )

    async def _monitored(self, stmt: Any) -> list[MonitoredDevice]:
        return [
            MonitoredDevice(
                equipment_id=row[0],
                type_code=row[1],
                serial_number=row[2],
                region_id=row[3],
                region_code=row[4],
                reference_at=row[5],
                next_maintenance_date=row[6],
            )
            for row in (await self._session.execute(stmt)).all()
        ]
