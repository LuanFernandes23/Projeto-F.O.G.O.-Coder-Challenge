"""Inventário de equipamentos: cadastro, consulta com filtros, situação e histórico."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from app.api.dependencies.auth import CurrentUser, Requires
from app.api.dependencies.services import EquipmentServiceDep
from app.api.routes.common import AUTH_PROBLEMS, Pagination, problems
from app.core.exceptions import BusinessRuleError
from app.core.permissions import Permission
from app.domain.equipment.filters import EquipmentFilters, EquipmentSort, RadiusFilter
from app.domain.equipment.status import EquipmentStatus
from app.domain.maintenance.entities import MaintenanceNeed
from app.domain.shared import GeoPoint
from app.schemas.common import PageOutput
from app.schemas.equipment import (
    EquipmentCreate,
    EquipmentOutput,
    EquipmentUpdate,
    StatusChangeInput,
    StatusChangeOutput,
)
from app.services.equipment_service import EquipmentChanges, NewEquipment, PlanSpec

router = APIRouter(prefix="/equipment", tags=["Equipamentos"], responses=AUTH_PROBLEMS)

_MAX_RADIUS_M = 50_000


@router.get(
    "",
    response_model=PageOutput[EquipmentOutput],
    summary="Listar equipamentos com filtros (inclusive por raio geográfico)",
    dependencies=[Requires(Permission.EQUIPMENT_READ)],
    responses=problems(422),
)
async def list_equipment(
    service: EquipmentServiceDep,
    page: Pagination,
    type_code: Annotated[list[str] | None, Query(description="Um ou mais tipos.")] = None,
    status_: Annotated[list[EquipmentStatus] | None, Query(alias="status")] = None,
    organization_id: Annotated[list[UUID] | None, Query()] = None,
    region_id: Annotated[list[UUID] | None, Query()] = None,
    neighborhood: Annotated[str | None, Query(max_length=100)] = None,
    city: Annotated[str | None, Query(max_length=100)] = None,
    maintenance_need: Annotated[list[MaintenanceNeed] | None, Query()] = None,
    maintenance_due_within_days: Annotated[
        int | None, Query(ge=0, le=365, description="Próxima manutenção em até N dias.")
    ] = None,
    maintenance_overdue: Annotated[
        bool, Query(description="Somente com manutenção vencida.")
    ] = False,
    q: Annotated[
        str | None, Query(min_length=2, max_length=80, description="Série, marca, modelo ou rua.")
    ] = None,
    lat: Annotated[float | None, Query(ge=-90, le=90)] = None,
    lng: Annotated[float | None, Query(ge=-180, le=180)] = None,
    radius_m: Annotated[float | None, Query(gt=0, le=_MAX_RADIUS_M)] = None,
    sort: EquipmentSort = EquipmentSort.CREATED_AT_DESC,
) -> PageOutput[EquipmentOutput]:
    radius = _radius_filter(lat, lng, radius_m)
    if sort is EquipmentSort.DISTANCE and radius is None:
        raise BusinessRuleError("Ordenar por distância exige lat, lng e radius_m.")
    filters = EquipmentFilters(
        type_codes=tuple(type_code or ()),
        statuses=tuple(status_ or ()),
        organization_ids=tuple(organization_id or ()),
        region_ids=tuple(region_id or ()),
        neighborhood=neighborhood,
        city=city,
        maintenance_needs=tuple(maintenance_need or ()),
        search=q,
        radius=radius,
        sort=sort,
    )
    result = await service.search(
        filters,
        page,
        maintenance_due_within_days=maintenance_due_within_days,
        maintenance_overdue=maintenance_overdue,
    )
    return PageOutput(
        items=[EquipmentOutput.from_view(v) for v in result.items],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )


@router.post(
    "",
    response_model=EquipmentOutput,
    status_code=status.HTTP_201_CREATED,
    summary="Cadastrar equipamento",
    dependencies=[Requires(Permission.EQUIPMENT_WRITE)],
    responses=problems(409, 422),
)
async def create_equipment(
    payload: EquipmentCreate, service: EquipmentServiceDep, user: CurrentUser
) -> EquipmentOutput:
    plan = payload.maintenance_plan
    view = await service.create(
        NewEquipment(
            type_code=payload.type_code,
            serial_number=payload.serial_number,
            brand=payload.brand,
            model=payload.model,
            organization_id=payload.organization_id,
            status=payload.status,
            installed_on=payload.installed_on,
            address=payload.address.to_domain(),
            location=payload.location.to_domain(),
            attributes=payload.attributes,
            maintenance_plan=PlanSpec(plan.interval_days, plan.next_due_date) if plan else None,
        ),
        actor_id=user.id,
    )
    return EquipmentOutput.from_view(view)


@router.get(
    "/{equipment_id}",
    response_model=EquipmentOutput,
    summary="Detalhar equipamento",
    dependencies=[Requires(Permission.EQUIPMENT_READ)],
    responses=problems(404),
)
async def get_equipment(equipment_id: UUID, service: EquipmentServiceDep) -> EquipmentOutput:
    return EquipmentOutput.from_view(await service.get(equipment_id))


@router.patch(
    "/{equipment_id}",
    response_model=EquipmentOutput,
    summary="Atualizar dados do equipamento (exige a versão lida)",
    dependencies=[Requires(Permission.EQUIPMENT_WRITE)],
    responses=problems(404, 409, 422),
)
async def update_equipment(
    equipment_id: UUID, payload: EquipmentUpdate, service: EquipmentServiceDep, user: CurrentUser
) -> EquipmentOutput:
    view = await service.update(
        equipment_id,
        EquipmentChanges(
            version=payload.version,
            serial_number=payload.serial_number,
            brand=payload.brand,
            model=payload.model,
            organization_id=payload.organization_id,
            installed_on=payload.installed_on,
            address=payload.address.to_domain() if payload.address else None,
            location=payload.location.to_domain() if payload.location else None,
            attributes=payload.attributes,
        ),
        actor_id=user.id,
    )
    return EquipmentOutput.from_view(view)


@router.delete(
    "/{equipment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remover do inventário (arquivamento lógico, preserva histórico)",
    dependencies=[Requires(Permission.EQUIPMENT_DELETE)],
    responses=problems(404, 409),
)
async def archive_equipment(
    equipment_id: UUID, service: EquipmentServiceDep, user: CurrentUser
) -> Response:
    await service.archive(equipment_id, actor_id=user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{equipment_id}/status-changes",
    response_model=EquipmentOutput,
    summary="Mudar a situação (validada pela máquina de estados)",
    dependencies=[Requires(Permission.EQUIPMENT_STATUS_CHANGE)],
    responses=problems(404, 409, 422),
)
async def change_equipment_status(
    equipment_id: UUID,
    payload: StatusChangeInput,
    service: EquipmentServiceDep,
    user: CurrentUser,
) -> EquipmentOutput:
    view = await service.change_status(
        equipment_id, payload.to_status, payload.reason, user.id, payload.installed_on
    )
    return EquipmentOutput.from_view(view)


@router.get(
    "/{equipment_id}/status-history",
    response_model=PageOutput[StatusChangeOutput],
    summary="Histórico de situações (auditoria)",
    dependencies=[Requires(Permission.EQUIPMENT_READ)],
    responses=problems(404),
)
async def equipment_status_history(
    equipment_id: UUID, service: EquipmentServiceDep, page: Pagination
) -> PageOutput[StatusChangeOutput]:
    result = await service.status_history(equipment_id, page)
    return PageOutput(
        items=[StatusChangeOutput.from_domain(c) for c in result.items],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )


def _radius_filter(
    lat: float | None, lng: float | None, radius_m: float | None
) -> RadiusFilter | None:
    provided = [value is not None for value in (lat, lng, radius_m)]
    if not any(provided):
        return None
    if lat is None or lng is None or radius_m is None:
        raise BusinessRuleError("A busca por raio exige lat, lng e radius_m juntos.")
    return RadiusFilter(center=GeoPoint(latitude=lat, longitude=lng), radius_m=radius_m)
