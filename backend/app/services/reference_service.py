"""Casos de uso de dados de referência: órgãos, regiões e tipos de equipamento."""

import uuid
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.core.clock import Clock
from app.core.exceptions import ConflictError, NotFoundError
from app.domain.equipment.entities import EquipmentCategory, EquipmentType
from app.domain.organizations import Organization, OrganizationKind, OrganizationUsage
from app.domain.regions import Region
from app.schemas.equipment_attributes import attributes_json_schema
from app.services.ports import UnitOfWork

_FREE_ATTRIBUTES_SCHEMA = "outro"


@dataclass(frozen=True, slots=True)
class EquipmentTypeWithSchema:
    type: EquipmentType
    attributes_schema: dict[str, Any]


class OrganizationService:
    def __init__(self, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def list_all(self) -> list[Organization]:
        async with self._uow as uow:
            return await uow.organizations.list_all()

    async def list_with_usage(self) -> list[tuple[Organization, OrganizationUsage]]:
        async with self._uow as uow:
            organizations = await uow.organizations.list_all()
            usage = await uow.organizations.usage()
        return [(o, usage.get(o.id, OrganizationUsage())) for o in organizations]

    async def get(self, organization_id: UUID) -> Organization:
        async with self._uow as uow:
            return await self._require(uow, organization_id)

    async def create(self, name: str, acronym: str, kind: OrganizationKind) -> Organization:
        now = self._clock.now()
        async with self._uow as uow:
            await self._ensure_unique(uow, name, acronym, None)
            organization = Organization(uuid.uuid4(), name, acronym.upper(), kind, now, now)
            await uow.organizations.add(organization)
            await uow.commit()
            return organization

    async def update(
        self,
        organization_id: UUID,
        name: str | None,
        acronym: str | None,
        kind: OrganizationKind | None,
    ) -> Organization:
        async with self._uow as uow:
            organization = await self._require(uow, organization_id)
            if kind is not None and kind is not organization.kind:
                if await uow.organizations.is_referenced(organization_id):
                    raise ConflictError(
                        "Não é possível mudar o tipo de um órgão que já possui equipamentos "
                        "ou agentes (os cargos dos agentes dependem dele)."
                    )
                organization.kind = kind
            organization.name = name or organization.name
            organization.acronym = (acronym or organization.acronym).upper()
            await self._ensure_unique(uow, organization.name, organization.acronym, organization_id)
            organization.updated_at = self._clock.now()
            await uow.organizations.update(organization)
            await uow.commit()
            return organization

    async def delete(self, organization_id: UUID) -> None:
        async with self._uow as uow:
            await self._require(uow, organization_id)
            if await uow.organizations.is_referenced(organization_id):
                raise ConflictError("O órgão possui equipamentos ou agentes vinculados.")
            await uow.organizations.delete(organization_id)
            await uow.commit()

    @staticmethod
    async def _require(uow: UnitOfWork, organization_id: UUID) -> Organization:
        organization = await uow.organizations.get(organization_id)
        if organization is None:
            raise NotFoundError("Órgão não encontrado.")
        return organization

    @staticmethod
    async def _ensure_unique(
        uow: UnitOfWork, name: str, acronym: str, exclude_id: UUID | None
    ) -> None:
        if await uow.organizations.find_conflicting(name, acronym, exclude_id) is not None:
            raise ConflictError("Já existe um órgão com este nome ou sigla.")


class RegionService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def list_all(self, include_geometry: bool) -> list[Region]:
        async with self._uow as uow:
            return await uow.regions.list_all(include_geometry)


class EquipmentTypeService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def list_all(self) -> list[EquipmentTypeWithSchema]:
        async with self._uow as uow:
            types = await uow.equipment_types.list_all()
        return [
            EquipmentTypeWithSchema(t, attributes_json_schema(t.attributes_schema_key))
            for t in types
        ]

    async def create(
        self,
        code: str,
        name: str,
        category: EquipmentCategory,
        icon: str,
        is_mobile: bool,
        description: str | None,
    ) -> EquipmentTypeWithSchema:
        """Novos tipos ("entre outros") usam características livres até ganharem schema próprio."""
        equipment_type = EquipmentType(
            code=code,
            name=name,
            category=category,
            icon=icon,
            is_mobile=is_mobile,
            is_vehicle=False,
            attributes_schema_key=_FREE_ATTRIBUTES_SCHEMA,
            description=description,
        )
        async with self._uow as uow:
            if await uow.equipment_types.get(code) is not None:
                raise ConflictError("Já existe um tipo de equipamento com este código.")
            await uow.equipment_types.add(equipment_type)
            await uow.commit()
        return EquipmentTypeWithSchema(
            equipment_type, attributes_json_schema(_FREE_ATTRIBUTES_SCHEMA)
        )
