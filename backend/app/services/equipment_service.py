"""Casos de uso do inventário de equipamentos."""

import logging
import uuid
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from app.core.clock import Clock
from app.core.exceptions import (
    BusinessRuleError,
    ConflictError,
    NotFoundError,
    VersionConflictError,
)
from app.domain.equipment.entities import (
    Equipment,
    EquipmentRecord,
    EquipmentStatusChange,
    EquipmentType,
    EquipmentView,
    ensure_installation_consistency,
)
from app.domain.equipment.filters import EquipmentFilters
from app.domain.equipment.status import (
    MAINTENANCE_CANCELLING_STATUSES,
    EquipmentStatus,
    ensure_initial_status,
)
from app.domain.maintenance.entities import (
    MaintenanceNeed,
    MaintenanceOrder,
    MaintenanceOrderStatus,
    MaintenancePlan,
)
from app.domain.maintenance.policy import build_snapshot, compute_next_due_date
from app.domain.shared import Address, GeoPoint, Page, PageRequest
from app.schemas.equipment_attributes import validate_attributes
from app.services.equipment_lifecycle import EquipmentLifecycle, new_corrective_order
from app.services.ports import UnitOfWork

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PlanSpec:
    interval_days: int
    next_due_date: date | None


@dataclass(frozen=True, slots=True)
class NewEquipment:
    type_code: str
    serial_number: str
    brand: str
    model: str
    organization_id: UUID
    status: EquipmentStatus
    installed_on: date | None
    address: Address
    location: GeoPoint
    attributes: dict[str, Any]
    maintenance_plan: PlanSpec | None


@dataclass(frozen=True, slots=True)
class EquipmentChanges:
    version: int
    serial_number: str | None = None
    brand: str | None = None
    model: str | None = None
    organization_id: UUID | None = None
    installed_on: date | None = None
    address: Address | None = None
    location: GeoPoint | None = None
    attributes: dict[str, Any] | None = None


class EquipmentService:
    def __init__(
        self,
        uow: UnitOfWork,
        clock: Clock,
        lifecycle: EquipmentLifecycle,
        due_soon_days: int,
    ) -> None:
        self._uow = uow
        self._clock = clock
        self._lifecycle = lifecycle
        self._due_soon_days = due_soon_days

    async def create(self, data: NewEquipment, actor_id: UUID | None) -> EquipmentView:
        now, today = self._clock.now(), self._clock.today()
        async with self._uow as uow:
            equipment_type = await self._require_type(uow, data.type_code)
            await self._require_organization(uow, data.organization_id)
            ensure_initial_status(data.status)
            ensure_installation_consistency(data.status, data.installed_on, today)
            attributes = validate_attributes(equipment_type.attributes_schema_key, data.attributes)
            await self._ensure_unique_serial(uow, data.brand, data.serial_number, None)

            equipment = Equipment(
                id=uuid.uuid4(),
                type_code=equipment_type.code,
                serial_number=data.serial_number,
                brand=data.brand,
                model=data.model,
                organization_id=data.organization_id,
                status=data.status,
                address=data.address,
                location=data.location,
                region_id=await uow.regions.find_covering(data.location),
                installed_on=data.installed_on,
                attributes=attributes,
                maintenance_need=MaintenanceNeed.NENHUMA,
                next_maintenance_date=None,
                version=1,
                created_at=now,
                updated_at=now,
                created_by=actor_id,
                updated_by=actor_id,
            )
            plan = self._build_plan(equipment.id, data.maintenance_plan, today, now)
            orders: list[MaintenanceOrder] = []
            if data.status is EquipmentStatus.MAU_FUNCIONAMENTO:
                orders.append(
                    new_corrective_order(equipment.id, "cadastrado com defeito", actor_id, now)
                )
            self._lifecycle.apply_snapshot(equipment, plan, orders)

            await uow.equipment.add(equipment)
            await uow.equipment_history.add(
                equipment_id=equipment.id,
                from_status=None,
                to_status=equipment.status,
                reason="Cadastro inicial",
                changed_by=actor_id,
                changed_at=now,
            )
            if plan is not None:
                await uow.maintenance_plans.upsert(plan)
            for order in orders:
                await uow.maintenance_orders.add(order)
            await uow.commit()
            logger.info(
                "Equipamento cadastrado",
                extra={"equipment_id": str(equipment.id), "type_code": equipment.type_code},
            )
            return await self._view(uow, equipment.id)

    async def update(
        self, equipment_id: UUID, changes: EquipmentChanges, actor_id: UUID | None
    ) -> EquipmentView:
        now, today = self._clock.now(), self._clock.today()
        async with self._uow as uow:
            equipment = await self._require_active(uow, equipment_id, for_update=True)
            if changes.version != equipment.version:
                raise VersionConflictError(
                    "Equipamento alterado desde a última leitura. Recarregue e tente de novo.",
                    extra={"current_version": equipment.version},
                )
            equipment_type = await self._require_type(uow, equipment.type_code)
            updated = await self._apply_changes(uow, equipment, equipment_type, changes)
            ensure_installation_consistency(updated.status, updated.installed_on, today)
            updated.updated_at = now
            updated.updated_by = actor_id
            updated.version = await uow.equipment.update(updated)
            await uow.commit()
            return await self._view(uow, equipment_id)

    async def archive(self, equipment_id: UUID, actor_id: UUID | None) -> None:
        now = self._clock.now()
        async with self._uow as uow:
            equipment = await self._require_active(uow, equipment_id, for_update=True)
            if await uow.agents.count_active_crew(equipment_id, None) > 0:
                raise ConflictError(
                    "Há agentes usando esta viatura. Remova a atribuição antes de excluir."
                )
            for order in await uow.maintenance_orders.list_open(equipment_id):
                order.status = MaintenanceOrderStatus.CANCELADA
                order.cancelled_at = now
                order.closed_by = actor_id
                order.resolution_notes = "Cancelada: equipamento removido do inventário."
                await uow.maintenance_orders.update(order)
            equipment.archived_at = now
            equipment.updated_at = now
            equipment.updated_by = actor_id
            await self._lifecycle.refresh_and_save(uow, equipment)
            await uow.commit()
            logger.info("Equipamento arquivado", extra={"equipment_id": str(equipment_id)})

    async def change_status(
        self,
        equipment_id: UUID,
        target: EquipmentStatus,
        reason: str,
        actor_id: UUID | None,
        installed_on: date | None = None,
    ) -> EquipmentView:
        now, today = self._clock.now(), self._clock.today()
        async with self._uow as uow:
            equipment = await self._require_active(uow, equipment_id, for_update=True)
            if target in MAINTENANCE_CANCELLING_STATUSES:
                await self._ensure_vehicle_has_no_crew(uow, equipment)
            await self._lifecycle.change_status(
                uow,
                equipment,
                target,
                reason=reason,
                actor_id=actor_id,
                now=now,
                today=today,
                installed_on=installed_on,
            )
            await self._lifecycle.refresh_and_save(uow, equipment)
            await uow.commit()
            logger.info(
                "Situação do equipamento alterada",
                extra={"equipment_id": str(equipment_id), "to_status": target.value},
            )
            return await self._view(uow, equipment_id)

    async def get(self, equipment_id: UUID) -> EquipmentView:
        async with self._uow as uow:
            return await self._view(uow, equipment_id)

    async def search(
        self,
        filters: EquipmentFilters,
        page: PageRequest,
        *,
        maintenance_due_within_days: int | None = None,
        maintenance_overdue: bool = False,
    ) -> Page[EquipmentView]:
        today = self._clock.today()
        if maintenance_due_within_days is not None:
            filters = replace(
                filters, next_maintenance_until=today + timedelta(days=maintenance_due_within_days)
            )
        if maintenance_overdue:  # vencida = próxima data já passou
            filters = replace(filters, next_maintenance_until=today - timedelta(days=1))
        async with self._uow as uow:
            records = await uow.equipment.list_records(filters, page)
        return Page(
            [self._to_view(r) for r in records.items], records.total, page.limit, page.offset
        )

    async def status_history(
        self, equipment_id: UUID, page: PageRequest
    ) -> Page[EquipmentStatusChange]:
        async with self._uow as uow:
            if await uow.equipment.get(equipment_id) is None:
                raise NotFoundError("Equipamento não encontrado.")
            return await uow.equipment_history.list_for_equipment(equipment_id, page)

    async def _apply_changes(
        self,
        uow: UnitOfWork,
        equipment: Equipment,
        equipment_type: EquipmentType,
        changes: EquipmentChanges,
    ) -> Equipment:
        updated = replace(equipment)
        if changes.serial_number is not None:
            updated.serial_number = changes.serial_number
        if changes.brand is not None:
            updated.brand = changes.brand
        if changes.model is not None:
            updated.model = changes.model
        if changes.installed_on is not None:
            updated.installed_on = changes.installed_on
        if changes.address is not None:
            updated.address = changes.address
        if changes.location is not None:
            updated.location = changes.location
            updated.region_id = await uow.regions.find_covering(changes.location)
        if changes.attributes is not None:
            updated.attributes = validate_attributes(
                equipment_type.attributes_schema_key, changes.attributes
            )
        if (
            changes.organization_id is not None
            and changes.organization_id != equipment.organization_id
        ):
            await self._require_organization(uow, changes.organization_id)
            if await uow.agents.count_active_crew(equipment.id, None) > 0:
                raise ConflictError(
                    "Não é possível trocar o órgão de uma viatura com agentes atribuídos."
                )
            updated.organization_id = changes.organization_id
        if changes.serial_number is not None or changes.brand is not None:
            await self._ensure_unique_serial(
                uow, updated.brand, updated.serial_number, equipment.id
            )
        return updated

    @staticmethod
    async def _ensure_vehicle_has_no_crew(uow: UnitOfWork, equipment: Equipment) -> None:
        # Viatura furtada/desativada não pode seguir atribuída a agentes (estado incoerente).
        if await uow.agents.count_active_crew(equipment.id, None) > 0:
            raise ConflictError(
                "Remova os agentes atribuídos a esta viatura antes de desativá-la ou "
                "registrá-la como furtada."
            )

    @staticmethod
    def _build_plan(
        equipment_id: UUID, spec: PlanSpec | None, today: date, now: datetime
    ) -> MaintenancePlan | None:
        if spec is None:
            return None
        next_due = spec.next_due_date or compute_next_due_date(today, spec.interval_days)
        return MaintenancePlan(
            equipment_id=equipment_id,
            interval_days=spec.interval_days,
            next_due_date=next_due,
            last_done_on=None,
            created_at=now,
            updated_at=now,
        )

    async def _view(self, uow: UnitOfWork, equipment_id: UUID) -> EquipmentView:
        record = await uow.equipment.get_record(equipment_id)
        if record is None or record.equipment.is_archived:
            raise NotFoundError("Equipamento não encontrado.")
        return self._to_view(record)

    def _to_view(self, record: EquipmentRecord) -> EquipmentView:
        equipment = record.equipment
        snapshot = build_snapshot(
            equipment.maintenance_need,
            equipment.next_maintenance_date,
            self._clock.today(),
            self._due_soon_days,
        )
        return EquipmentView(record=record, maintenance=snapshot)

    @staticmethod
    async def _require_type(uow: UnitOfWork, type_code: str) -> EquipmentType:
        equipment_type = await uow.equipment_types.get(type_code)
        if equipment_type is None:
            raise BusinessRuleError(
                f"Tipo de equipamento '{type_code}' não existe.", extra={"field": "type_code"}
            )
        return equipment_type

    @staticmethod
    async def _require_organization(uow: UnitOfWork, organization_id: UUID) -> None:
        if await uow.organizations.get(organization_id) is None:
            raise BusinessRuleError(
                "Órgão responsável não encontrado.", extra={"field": "organization_id"}
            )

    @staticmethod
    async def _require_active(
        uow: UnitOfWork, equipment_id: UUID, *, for_update: bool = False
    ) -> Equipment:
        equipment = await uow.equipment.get(equipment_id, for_update=for_update)
        if equipment is None or equipment.is_archived:
            raise NotFoundError("Equipamento não encontrado.")
        return equipment

    @staticmethod
    async def _ensure_unique_serial(
        uow: UnitOfWork, brand: str, serial_number: str, exclude_id: UUID | None
    ) -> None:
        if await uow.equipment.exists_brand_serial(brand, serial_number, exclude_id):
            raise ConflictError(
                "Já existe um equipamento ativo com esta marca e número de série.",
                extra={"field": "serial_number"},
            )
