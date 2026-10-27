"""Alertas operacionais: consulta, reconhecimento e resolução."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.dependencies.auth import CurrentUser, Requires
from app.api.dependencies.services import AlertServiceDep
from app.api.routes.common import AUTH_PROBLEMS, Pagination, problems
from app.core.permissions import Permission
from app.domain.operations.alerts import AlertFilters, AlertKind, AlertSeverity, AlertStatus
from app.schemas.common import PageOutput
from app.schemas.operations import AlertOutput, AlertResolveInput

router = APIRouter(prefix="/alerts", tags=["Alertas"], responses=AUTH_PROBLEMS)


@router.get(
    "",
    response_model=PageOutput[AlertOutput],
    summary="Listar alertas (abertos primeiro, por criticidade)",
    dependencies=[Requires(Permission.OPERATIONS_READ)],
)
async def list_alerts(
    service: AlertServiceDep,
    page: Pagination,
    status_: Annotated[list[AlertStatus] | None, Query(alias="status")] = None,
    severity: Annotated[list[AlertSeverity] | None, Query()] = None,
    kind: Annotated[list[AlertKind] | None, Query()] = None,
    region_id: Annotated[list[UUID] | None, Query()] = None,
    equipment_id: UUID | None = None,
) -> PageOutput[AlertOutput]:
    filters = AlertFilters(
        statuses=tuple(status_ or ()),
        severities=tuple(severity or ()),
        kinds=tuple(kind or ()),
        region_ids=tuple(region_id or ()),
        equipment_id=equipment_id,
    )
    result = await service.search(filters, page)
    return PageOutput(
        items=[AlertOutput.from_view(v) for v in result.items],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )


@router.get(
    "/{alert_id}",
    response_model=AlertOutput,
    summary="Detalhar alerta",
    dependencies=[Requires(Permission.OPERATIONS_READ)],
    responses=problems(404),
)
async def get_alert(alert_id: UUID, service: AlertServiceDep) -> AlertOutput:
    return AlertOutput.from_view(await service.get(alert_id))


@router.post(
    "/{alert_id}/acknowledge",
    response_model=AlertOutput,
    summary="Reconhecer alerta (o operador assumiu o tratamento)",
    dependencies=[Requires(Permission.ALERT_ACKNOWLEDGE)],
    responses=problems(404, 409),
)
async def acknowledge_alert(
    alert_id: UUID, service: AlertServiceDep, user: CurrentUser
) -> AlertOutput:
    return AlertOutput.from_view(await service.acknowledge(alert_id, user.id))


@router.post(
    "/{alert_id}/resolve",
    response_model=AlertOutput,
    summary="Resolver alerta manualmente (com justificativa)",
    dependencies=[Requires(Permission.ALERT_ACKNOWLEDGE)],
    responses=problems(404, 409, 422),
)
async def resolve_alert(
    alert_id: UUID, payload: AlertResolveInput, service: AlertServiceDep, user: CurrentUser
) -> AlertOutput:
    return AlertOutput.from_view(await service.resolve(alert_id, payload.note, user.id))
