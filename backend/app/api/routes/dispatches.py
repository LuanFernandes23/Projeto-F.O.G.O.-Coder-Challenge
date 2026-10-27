"""Despachos de agentes para ocorrências."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.dependencies.auth import CurrentUser, Requires
from app.api.dependencies.services import DispatchServiceDep
from app.api.routes.common import AUTH_PROBLEMS, problems
from app.core.permissions import Permission
from app.schemas.operations import DispatchCreate, DispatchOutput, DispatchTransition

router = APIRouter(prefix="/dispatches", tags=["Despachos"], responses=AUTH_PROBLEMS)


@router.get(
    "",
    response_model=list[DispatchOutput],
    summary="Despachos recentes (ou só os ativos)",
    dependencies=[Requires(Permission.OPERATIONS_READ)],
)
async def list_dispatches(
    service: DispatchServiceDep,
    active: bool = True,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[DispatchOutput]:
    return [DispatchOutput.from_record(r) for r in await service.search(active, limit)]


@router.post(
    "",
    response_model=DispatchOutput,
    status_code=status.HTTP_201_CREATED,
    summary="Despachar agente para o equipamento (agente entra em ocorrência)",
    dependencies=[Requires(Permission.DISPATCH_MANAGE)],
    responses=problems(404, 409, 422),
)
async def create_dispatch(
    payload: DispatchCreate, service: DispatchServiceDep, user: CurrentUser
) -> DispatchOutput:
    record = await service.create(payload.equipment_id, payload.agent_id, payload.notes, user.id)
    return DispatchOutput.from_record(record)


@router.patch(
    "/{dispatch_id}",
    response_model=DispatchOutput,
    summary="Atualizar despacho (no local, concluído, cancelado)",
    dependencies=[Requires(Permission.DISPATCH_MANAGE)],
    responses=problems(404, 409),
)
async def transition_dispatch(
    dispatch_id: UUID, payload: DispatchTransition, service: DispatchServiceDep, user: CurrentUser
) -> DispatchOutput:
    record = await service.transition(dispatch_id, payload.status, payload.notes, user.id)
    return DispatchOutput.from_record(record)
