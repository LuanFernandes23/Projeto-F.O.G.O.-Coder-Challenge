"""Persistência de alertas operacionais."""

from typing import Any
from uuid import UUID

from sqlalchemy import case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.tables import (
    AlertModel,
    EquipmentModel,
    EquipmentTypeModel,
    RegionModel,
)
from app.domain.operations.alerts import (
    Alert,
    AlertFilters,
    AlertRecord,
    AlertSeverity,
    AlertStatus,
    AlertSubject,
)
from app.domain.shared import Page, PageRequest
from app.repositories.sql_helpers import latitude_of, longitude_of

_SEVERITY_ORDER = case(
    {
        AlertSeverity.CRITICA: 4,
        AlertSeverity.ALTA: 3,
        AlertSeverity.MEDIA: 2,
        AlertSeverity.BAIXA: 1,
    },
    value=AlertModel.severity,
)
_STATUS_ORDER = case(
    {AlertStatus.ABERTO: 0, AlertStatus.RECONHECIDO: 1, AlertStatus.RESOLVIDO: 2},
    value=AlertModel.status,
)


def _to_domain(model: AlertModel) -> Alert:
    return Alert(
        id=model.id,
        kind=model.kind,
        severity=model.severity,
        status=model.status,
        title=model.title,
        description=model.description,
        dedup_key=model.dedup_key,
        opened_at=model.opened_at,
        sla_due_at=model.sla_due_at,
        last_occurrence_at=model.last_occurrence_at,
        occurrences=model.occurrences,
        equipment_id=model.equipment_id,
        agent_id=model.agent_id,
        region_id=model.region_id,
        acknowledged_at=model.acknowledged_at,
        acknowledged_by=model.acknowledged_by,
        resolved_at=model.resolved_at,
        resolved_by=model.resolved_by,
        resolution_note=model.resolution_note,
        metadata=dict(model.metadata_),
    )


class SqlAlertRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, alert_id: UUID, *, for_update: bool = False) -> Alert | None:
        stmt = select(AlertModel).where(AlertModel.id == alert_id)
        if for_update:
            stmt = stmt.with_for_update()
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_domain(model) if model else None

    async def get_open_by_dedup(self, dedup_key: str) -> Alert | None:
        stmt = (
            select(AlertModel)
            .where(AlertModel.dedup_key == dedup_key, AlertModel.status != AlertStatus.RESOLVIDO)
            .with_for_update()
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_domain(model) if model else None

    async def list_open_by_prefix(self, prefix: str) -> list[Alert]:
        stmt = select(AlertModel).where(
            AlertModel.dedup_key.startswith(prefix), AlertModel.status != AlertStatus.RESOLVIDO
        )
        return [_to_domain(m) for m in (await self._session.execute(stmt)).scalars()]

    async def add(self, alert: Alert) -> None:
        self._session.add(
            AlertModel(
                id=alert.id,
                kind=alert.kind,
                severity=alert.severity,
                status=alert.status,
                title=alert.title,
                description=alert.description,
                dedup_key=alert.dedup_key,
                equipment_id=alert.equipment_id,
                agent_id=alert.agent_id,
                region_id=alert.region_id,
                opened_at=alert.opened_at,
                sla_due_at=alert.sla_due_at,
                last_occurrence_at=alert.last_occurrence_at,
                occurrences=alert.occurrences,
                metadata_=alert.metadata,
            )
        )
        await self._session.flush()

    async def update(self, alert: Alert) -> None:
        await self._session.execute(
            update(AlertModel)
            .where(AlertModel.id == alert.id)
            .values(
                severity=alert.severity,
                status=alert.status,
                title=alert.title,
                description=alert.description,
                sla_due_at=alert.sla_due_at,
                last_occurrence_at=alert.last_occurrence_at,
                occurrences=alert.occurrences,
                acknowledged_at=alert.acknowledged_at,
                acknowledged_by=alert.acknowledged_by,
                resolved_at=alert.resolved_at,
                resolved_by=alert.resolved_by,
                resolution_note=alert.resolution_note,
                metadata_=alert.metadata,
            )
        )

    async def get_record(self, alert_id: UUID) -> AlertRecord | None:
        row = (
            await self._session.execute(self._record_select().where(AlertModel.id == alert_id))
        ).one_or_none()
        return self._record_from_row(row) if row else None

    async def list_records(self, filters: AlertFilters, page: PageRequest) -> Page[AlertRecord]:
        conditions: list[Any] = []
        if filters.statuses:
            conditions.append(AlertModel.status.in_(filters.statuses))
        if filters.severities:
            conditions.append(AlertModel.severity.in_(filters.severities))
        if filters.kinds:
            conditions.append(AlertModel.kind.in_(filters.kinds))
        if filters.region_ids:
            conditions.append(AlertModel.region_id.in_(filters.region_ids))
        if filters.equipment_id:
            conditions.append(AlertModel.equipment_id == filters.equipment_id)
        total = (
            await self._session.execute(select(func.count(AlertModel.id)).where(*conditions))
        ).scalar_one()
        stmt = (
            self._record_select()
            .where(*conditions)
            .order_by(_STATUS_ORDER, _SEVERITY_ORDER.desc(), AlertModel.opened_at.desc())
            .limit(page.limit)
            .offset(page.offset)
        )
        rows = (await self._session.execute(stmt)).all()
        return Page([self._record_from_row(r) for r in rows], total, page.limit, page.offset)

    @staticmethod
    def _record_select() -> Any:
        return (
            select(
                AlertModel,
                RegionModel.name.label("region_name"),
                EquipmentModel.id.label("eq_id"),
                EquipmentModel.type_code.label("eq_type"),
                EquipmentTypeModel.name.label("eq_type_name"),
                EquipmentModel.serial_number.label("eq_serial"),
                EquipmentModel.street.label("eq_street"),
                EquipmentModel.neighborhood.label("eq_neighborhood"),
                latitude_of(EquipmentModel.location).label("eq_lat"),
                longitude_of(EquipmentModel.location).label("eq_lng"),
            )
            .outerjoin(RegionModel, RegionModel.id == AlertModel.region_id)
            .outerjoin(EquipmentModel, EquipmentModel.id == AlertModel.equipment_id)
            .outerjoin(EquipmentTypeModel, EquipmentTypeModel.code == EquipmentModel.type_code)
        )

    @staticmethod
    def _record_from_row(row: Any) -> AlertRecord:
        subject = (
            AlertSubject(
                equipment_id=row.eq_id,
                type_code=row.eq_type,
                type_name=row.eq_type_name,
                serial_number=row.eq_serial,
                latitude=row.eq_lat,
                longitude=row.eq_lng,
                street=row.eq_street,
                neighborhood=row.eq_neighborhood,
            )
            if row.eq_id
            else None
        )
        return AlertRecord(_to_domain(row.AlertModel), row.region_name, subject)
