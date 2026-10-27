"""Dados de referência e catálogos para o front-end."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from app.api.dependencies.auth import CurrentUser, Requires
from app.api.dependencies.services import (
    EquipmentTypeServiceDep,
    OrganizationServiceDep,
    RegionServiceDep,
)
from app.api.routes.common import AUTH_PROBLEMS, problems
from app.core.permissions import Permission
from app.domain.agents.entities import DUTY_STATUS_LABELS, ON_DUTY_STATUSES, DutyStatus
from app.domain.equipment.status import (
    INITIAL_STATUSES,
    STATUS_LABELS,
    EquipmentStatus,
    allowed_transitions,
)
from app.schemas.common import StatusOption
from app.schemas.reference import (
    EquipmentTypeCreate,
    EquipmentTypeOutput,
    OrganizationCreate,
    OrganizationListItemOutput,
    OrganizationOutput,
    OrganizationUpdate,
    RegionOutput,
)
from app.services.reference_service import EquipmentTypeWithSchema

router = APIRouter(responses=AUTH_PROBLEMS)


def _type_output(item: EquipmentTypeWithSchema) -> EquipmentTypeOutput:
    t = item.type
    return EquipmentTypeOutput(
        code=t.code,
        name=t.name,
        category=t.category,
        icon=t.icon,
        is_mobile=t.is_mobile,
        is_vehicle=t.is_vehicle,
        description=t.description,
        attributes_schema=item.attributes_schema,
    )


@router.get(
    "/organizations",
    response_model=list[OrganizationListItemOutput],
    tags=["Órgãos"],
    summary="Listar órgãos responsáveis (com equipamentos e agentes vinculados)",
    dependencies=[Requires(Permission.ORGANIZATION_READ)],
)
async def list_organizations(service: OrganizationServiceDep) -> list[OrganizationListItemOutput]:
    return [
        OrganizationListItemOutput(
            **OrganizationOutput.model_validate(o).model_dump(),
            equipment_count=usage.equipment,
            agent_count=usage.agents,
            in_use=usage.in_use,
        )
        for o, usage in await service.list_with_usage()
    ]


@router.post(
    "/organizations",
    response_model=OrganizationOutput,
    status_code=status.HTTP_201_CREATED,
    tags=["Órgãos"],
    summary="Cadastrar órgão",
    dependencies=[Requires(Permission.ORGANIZATION_WRITE)],
    responses=problems(409, 422),
)
async def create_organization(
    payload: OrganizationCreate, service: OrganizationServiceDep
) -> OrganizationOutput:
    organization = await service.create(payload.name, payload.acronym, payload.kind)
    return OrganizationOutput.model_validate(organization)


@router.patch(
    "/organizations/{organization_id}",
    response_model=OrganizationOutput,
    tags=["Órgãos"],
    summary="Atualizar órgão",
    dependencies=[Requires(Permission.ORGANIZATION_WRITE)],
    responses=problems(404, 409, 422),
)
async def update_organization(
    organization_id: UUID, payload: OrganizationUpdate, service: OrganizationServiceDep
) -> OrganizationOutput:
    organization = await service.update(
        organization_id, payload.name, payload.acronym, payload.kind
    )
    return OrganizationOutput.model_validate(organization)


@router.delete(
    "/organizations/{organization_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Órgãos"],
    summary="Excluir órgão sem vínculos",
    dependencies=[Requires(Permission.ORGANIZATION_WRITE)],
    responses=problems(404, 409),
)
async def delete_organization(organization_id: UUID, service: OrganizationServiceDep) -> Response:
    await service.delete(organization_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/regions",
    response_model=list[RegionOutput],
    tags=["Regiões"],
    summary="Listar regiões da cidade",
)
async def list_regions(
    service: RegionServiceDep,
    _user: CurrentUser,
    include_geometry: Annotated[
        bool, Query(description="Incluir o polígono (GeoJSON) de cada região.")
    ] = False,
) -> list[RegionOutput]:
    return [RegionOutput.model_validate(r) for r in await service.list_all(include_geometry)]


@router.get(
    "/equipment-types",
    response_model=list[EquipmentTypeOutput],
    tags=["Tipos de equipamento"],
    summary="Tipos de equipamento com o JSON Schema das características",
)
async def list_equipment_types(
    service: EquipmentTypeServiceDep, _user: CurrentUser
) -> list[EquipmentTypeOutput]:
    return [_type_output(item) for item in await service.list_all()]


@router.post(
    "/equipment-types",
    response_model=EquipmentTypeOutput,
    status_code=status.HTTP_201_CREATED,
    tags=["Tipos de equipamento"],
    summary="Cadastrar novo tipo (características livres)",
    dependencies=[Requires(Permission.REFERENCE_WRITE)],
    responses=problems(409, 422),
)
async def create_equipment_type(
    payload: EquipmentTypeCreate, service: EquipmentTypeServiceDep
) -> EquipmentTypeOutput:
    created = await service.create(
        payload.code,
        payload.name,
        payload.category,
        payload.icon,
        payload.is_mobile,
        payload.description,
    )
    return _type_output(created)


@router.get(
    "/equipment-statuses",
    response_model=list[StatusOption],
    tags=["Catálogos"],
    summary="Situações de equipamento e transições permitidas (máquina de estados)",
)
async def list_equipment_statuses(_user: CurrentUser) -> list[StatusOption]:
    return [
        StatusOption(
            code=s.value,
            label=STATUS_LABELS[s],
            allowed_transitions=sorted(t.value for t in allowed_transitions(s)),
            metadata={
                "allowed_on_create": s in INITIAL_STATUSES,
                "counts_as_available": s is EquipmentStatus.OPERACIONAL,
            },
        )
        for s in EquipmentStatus
    ]


@router.get(
    "/agent-duty-statuses",
    response_model=list[StatusOption],
    tags=["Catálogos"],
    summary="Situações de serviço dos agentes",
)
async def list_agent_duty_statuses(_user: CurrentUser) -> list[StatusOption]:
    return [
        StatusOption(
            code=s.value,
            label=DUTY_STATUS_LABELS[s],
            allowed_transitions=sorted(t.value for t in DutyStatus if t is not s),
            metadata={"on_duty": s in ON_DUTY_STATUSES},
        )
        for s in DutyStatus
    ]
