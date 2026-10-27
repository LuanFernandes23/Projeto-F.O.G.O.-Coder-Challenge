"""Critérios de busca de equipamentos (independentes de SQL)."""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from uuid import UUID

from app.domain.equipment.status import EquipmentStatus
from app.domain.maintenance.entities import MaintenanceNeed
from app.domain.shared import GeoPoint


class EquipmentSort(StrEnum):
    CREATED_AT_DESC = "-created_at"
    CREATED_AT = "created_at"
    NEXT_MAINTENANCE = "next_maintenance_date"
    SERIAL_NUMBER = "serial_number"
    DISTANCE = "distance"


@dataclass(frozen=True, slots=True)
class RadiusFilter:
    center: GeoPoint
    radius_m: float


@dataclass(frozen=True, slots=True)
class EquipmentFilters:
    type_codes: tuple[str, ...] = ()
    statuses: tuple[EquipmentStatus, ...] = ()
    organization_ids: tuple[UUID, ...] = ()
    region_ids: tuple[UUID, ...] = ()
    neighborhood: str | None = None
    city: str | None = None
    maintenance_needs: tuple[MaintenanceNeed, ...] = ()
    next_maintenance_until: date | None = None
    search: str | None = None
    radius: RadiusFilter | None = None
    sort: EquipmentSort = EquipmentSort.CREATED_AT_DESC
