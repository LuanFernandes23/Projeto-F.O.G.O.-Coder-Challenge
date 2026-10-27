"""Agentes de campo: cadastro, consulta, situação de serviço e histórico."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from app.api.dependencies.auth import CurrentUser, Requires
from app.api.dependencies.services import AgentServiceDep
from app.api.routes.common import AUTH_PROBLEMS, Pagination, problems
from app.core.permissions import Permission
from app.domain.agents.entities import AgentFilters, AgentRole, DutyStatus
from app.schemas.agents import (
    AgentCreate,
    AgentOutput,
    AgentStatusChangeInput,
    AgentStatusChangeOutput,
    AgentUpdate,
)
from app.schemas.common import PageOutput
from app.services.agent_service import AgentChanges, NewAgent

router = APIRouter(prefix="/agents", tags=["Agentes"], responses=AUTH_PROBLEMS)


@router.get(
    "",
    response_model=PageOutput[AgentOutput],
    summary="Listar agentes",
    dependencies=[Requires(Permission.AGENT_READ)],
)
async def list_agents(
    service: AgentServiceDep,
    page: Pagination,
    role: Annotated[list[AgentRole] | None, Query()] = None,
    duty_status: Annotated[list[DutyStatus] | None, Query()] = None,
    organization_id: Annotated[list[UUID] | None, Query()] = None,
    region_id: Annotated[list[UUID] | None, Query()] = None,
    on_duty: Annotated[bool | None, Query(description="Somente em serviço (ou fora).")] = None,
    is_active: Annotated[bool | None, Query()] = None,
    q: Annotated[str | None, Query(min_length=2, max_length=80)] = None,
) -> PageOutput[AgentOutput]:
    filters = AgentFilters(
        roles=tuple(role or ()),
        duty_statuses=tuple(duty_status or ()),
        organization_ids=tuple(organization_id or ()),
        region_ids=tuple(region_id or ()),
        on_duty=on_duty,
        is_active=is_active,
        search=q,
    )
    result = await service.search(filters, page)
    return PageOutput(
        items=[AgentOutput.from_record(r) for r in result.items],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )


@router.post(
    "",
    response_model=AgentOutput,
    status_code=status.HTTP_201_CREATED,
    summary="Cadastrar agente",
    dependencies=[Requires(Permission.AGENT_WRITE)],
    responses=problems(409, 422),
)
async def create_agent(
    payload: AgentCreate, service: AgentServiceDep, user: CurrentUser
) -> AgentOutput:
    record = await service.create(
        NewAgent(
            full_name=payload.full_name,
            registration_number=payload.registration_number,
            role=payload.role,
            organization_id=payload.organization_id,
            duty_status=payload.duty_status,
            base_address=payload.base_address.to_domain(),
            base_location=payload.base_location.to_domain(),
            assigned_vehicle_id=payload.assigned_vehicle_id,
        ),
        actor_id=user.id,
    )
    return AgentOutput.from_record(record)


@router.get(
    "/{agent_id}",
    response_model=AgentOutput,
    summary="Detalhar agente",
    dependencies=[Requires(Permission.AGENT_READ)],
    responses=problems(404),
)
async def get_agent(agent_id: UUID, service: AgentServiceDep) -> AgentOutput:
    return AgentOutput.from_record(await service.get(agent_id))


@router.patch(
    "/{agent_id}",
    response_model=AgentOutput,
    summary="Atualizar agente (exige a versão lida)",
    dependencies=[Requires(Permission.AGENT_WRITE)],
    responses=problems(404, 409, 422),
)
async def update_agent(
    agent_id: UUID, payload: AgentUpdate, service: AgentServiceDep, user: CurrentUser
) -> AgentOutput:
    record = await service.update(
        agent_id,
        AgentChanges(
            version=payload.version,
            full_name=payload.full_name,
            registration_number=payload.registration_number,
            role=payload.role,
            organization_id=payload.organization_id,
            is_active=payload.is_active,
            base_address=payload.base_address.to_domain() if payload.base_address else None,
            base_location=payload.base_location.to_domain() if payload.base_location else None,
            assigned_vehicle_id=payload.assigned_vehicle_id,
            unassign_vehicle=payload.unassign_vehicle,
        ),
        actor_id=user.id,
    )
    return AgentOutput.from_record(record)


@router.delete(
    "/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remover agente (arquivamento lógico)",
    dependencies=[Requires(Permission.AGENT_DELETE)],
    responses=problems(404),
)
async def archive_agent(agent_id: UUID, service: AgentServiceDep) -> Response:
    await service.archive(agent_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{agent_id}/status-changes",
    response_model=AgentOutput,
    summary="Mudar a situação de serviço do agente",
    dependencies=[Requires(Permission.AGENT_STATUS_CHANGE)],
    responses=problems(404, 409, 422),
)
async def change_agent_status(
    agent_id: UUID, payload: AgentStatusChangeInput, service: AgentServiceDep, user: CurrentUser
) -> AgentOutput:
    record = await service.change_duty_status(
        agent_id, payload.to_status, payload.reason, actor_id=user.id
    )
    return AgentOutput.from_record(record)


@router.get(
    "/{agent_id}/status-history",
    response_model=PageOutput[AgentStatusChangeOutput],
    summary="Histórico de situações de serviço",
    dependencies=[Requires(Permission.AGENT_READ)],
    responses=problems(404),
)
async def agent_status_history(
    agent_id: UUID, service: AgentServiceDep, page: Pagination
) -> PageOutput[AgentStatusChangeOutput]:
    result = await service.status_history(agent_id, page)
    return PageOutput(
        items=[AgentStatusChangeOutput.from_domain(c) for c in result.items],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )
