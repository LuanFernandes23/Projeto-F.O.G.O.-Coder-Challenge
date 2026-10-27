"""Persistência de planos e ordens de manutenção."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.tables import MaintenanceOrderModel, MaintenancePlanModel
from app.domain.maintenance.entities import (
    OPEN_ORDER_STATUSES,
    MaintenanceOrder,
    MaintenanceOrderStatus,
    MaintenancePlan,
)
from app.domain.shared import Page, PageRequest


def _order_to_domain(model: MaintenanceOrderModel) -> MaintenanceOrder:
    return MaintenanceOrder(
        id=model.id,
        equipment_id=model.equipment_id,
        kind=model.kind,
        priority=model.priority,
        status=model.status,
        description=model.description,
        scheduled_for=model.scheduled_for,
        opened_at=model.opened_at,
        opened_by=model.opened_by,
        started_at=model.started_at,
        completed_at=model.completed_at,
        cancelled_at=model.cancelled_at,
        closed_by=model.closed_by,
        resolution_notes=model.resolution_notes,
    )


class SqlMaintenancePlanRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, equipment_id: UUID) -> MaintenancePlan | None:
        model = await self._session.get(MaintenancePlanModel, equipment_id)
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

    async def upsert(self, plan: MaintenancePlan) -> None:
        values = {
            "equipment_id": plan.equipment_id,
            "interval_days": plan.interval_days,
            "next_due_date": plan.next_due_date,
            "last_done_on": plan.last_done_on,
            "created_at": plan.created_at,
            "updated_at": plan.updated_at,
        }
        stmt = insert(MaintenancePlanModel).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[MaintenancePlanModel.equipment_id],
            set_={
                "interval_days": stmt.excluded.interval_days,
                "next_due_date": stmt.excluded.next_due_date,
                "last_done_on": stmt.excluded.last_done_on,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        await self._session.execute(stmt)

    async def delete(self, equipment_id: UUID) -> None:
        await self._session.execute(
            delete(MaintenancePlanModel).where(MaintenancePlanModel.equipment_id == equipment_id)
        )


class SqlMaintenanceOrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, order_id: UUID, *, for_update: bool = False) -> MaintenanceOrder | None:
        stmt = select(MaintenanceOrderModel).where(MaintenanceOrderModel.id == order_id)
        if for_update:
            stmt = stmt.with_for_update()
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return _order_to_domain(model) if model else None

    async def list_open(self, equipment_id: UUID) -> list[MaintenanceOrder]:
        stmt = (
            select(MaintenanceOrderModel)
            .where(
                MaintenanceOrderModel.equipment_id == equipment_id,
                MaintenanceOrderModel.status.in_(OPEN_ORDER_STATUSES),
            )
            .order_by(MaintenanceOrderModel.opened_at)
        )
        return [_order_to_domain(m) for m in (await self._session.execute(stmt)).scalars()]

    async def list_by_equipment(
        self,
        equipment_id: UUID,
        statuses: Sequence[MaintenanceOrderStatus],
        page: PageRequest,
    ) -> Page[MaintenanceOrder]:
        conditions = [MaintenanceOrderModel.equipment_id == equipment_id]
        if statuses:
            conditions.append(MaintenanceOrderModel.status.in_(statuses))
        total = (
            await self._session.execute(
                select(func.count(MaintenanceOrderModel.id)).where(*conditions)
            )
        ).scalar_one()
        stmt = (
            select(MaintenanceOrderModel)
            .where(*conditions)
            .order_by(MaintenanceOrderModel.opened_at.desc())
            .limit(page.limit)
            .offset(page.offset)
        )
        items = [_order_to_domain(m) for m in (await self._session.execute(stmt)).scalars()]
        return Page(items, total, page.limit, page.offset)

    async def add(self, order: MaintenanceOrder) -> None:
        self._session.add(
            MaintenanceOrderModel(
                id=order.id,
                equipment_id=order.equipment_id,
                kind=order.kind,
                priority=order.priority,
                status=order.status,
                description=order.description,
                scheduled_for=order.scheduled_for,
                opened_at=order.opened_at,
                opened_by=order.opened_by,
            )
        )
        await self._session.flush()

    async def update(self, order: MaintenanceOrder) -> None:
        await self._session.execute(
            update(MaintenanceOrderModel)
            .where(MaintenanceOrderModel.id == order.id)
            .values(
                status=order.status,
                started_at=order.started_at,
                completed_at=order.completed_at,
                cancelled_at=order.cancelled_at,
                closed_by=order.closed_by,
                resolution_notes=order.resolution_notes,
            )
        )
