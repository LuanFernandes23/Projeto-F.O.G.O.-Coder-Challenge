"""Manutenção: plano periódico e ordens de manutenção."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from app.api.dependencies.auth import CurrentUser, Requires
from app.api.dependencies.services import MaintenanceServiceDep
from app.api.routes.common import AUTH_PROBLEMS, Pagination, problems
from app.core.permissions import Permission
from app.domain.maintenance.entities import MaintenanceOrderStatus
from app.schemas.common import PageOutput
from app.schemas.maintenance import (
    MaintenanceOrderCreate,
    MaintenanceOrderOutput,
    MaintenanceOrderTransition,
    MaintenancePlanInput,
    MaintenancePlanOutput,
)
from app.services.maintenance_service import NewMaintenanceOrder

router = APIRouter(tags=["Manutenção"], responses=AUTH_PROBLEMS)


@router.put(
    "/equipment/{equipment_id}/maintenance-plan",
    response_model=MaintenancePlanOutput,
    summary="Definir/alterar plano de manutenção periódica",
    dependencies=[Requires(Permission.MAINTENANCE_PLAN_WRITE)],
    responses=problems(404, 422),
)
async def set_maintenance_plan(
    equipment_id: UUID, payload: MaintenancePlanInput, service: MaintenanceServiceDep
) -> MaintenancePlanOutput:
    plan = await service.set_plan(equipment_id, payload.interval_days, payload.next_due_date)
    return MaintenancePlanOutput.model_validate(plan)


@router.delete(
    "/equipment/{equipment_id}/maintenance-plan",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remover plano de manutenção periódica",
    dependencies=[Requires(Permission.MAINTENANCE_PLAN_WRITE)],
    responses=problems(404),
)
async def remove_maintenance_plan(equipment_id: UUID, service: MaintenanceServiceDep) -> Response:
    await service.remove_plan(equipment_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/equipment/{equipment_id}/maintenance-orders",
    response_model=PageOutput[MaintenanceOrderOutput],
    summary="Ordens de manutenção do equipamento",
    dependencies=[Requires(Permission.EQUIPMENT_READ)],
    responses=problems(404),
)
async def list_maintenance_orders(
    equipment_id: UUID,
    service: MaintenanceServiceDep,
    page: Pagination,
    status_: Annotated[list[MaintenanceOrderStatus] | None, Query(alias="status")] = None,
) -> PageOutput[MaintenanceOrderOutput]:
    result = await service.list_orders(equipment_id, status_ or [], page)
    return PageOutput(
        items=[MaintenanceOrderOutput.model_validate(o) for o in result.items],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )


@router.post(
    "/equipment/{equipment_id}/maintenance-orders",
    response_model=MaintenanceOrderOutput,
    status_code=status.HTTP_201_CREATED,
    summary="Abrir ordem de manutenção",
    dependencies=[Requires(Permission.MAINTENANCE_ORDER_OPERATE)],
    responses=problems(404, 409, 422),
)
async def open_maintenance_order(
    equipment_id: UUID,
    payload: MaintenanceOrderCreate,
    service: MaintenanceServiceDep,
    user: CurrentUser,
) -> MaintenanceOrderOutput:
    order = await service.open_order(
        equipment_id,
        NewMaintenanceOrder(
            kind=payload.kind,
            priority=payload.priority,
            description=payload.description,
            scheduled_for=payload.scheduled_for,
        ),
        actor_id=user.id,
    )
    return MaintenanceOrderOutput.model_validate(order)


@router.patch(
    "/maintenance-orders/{order_id}",
    response_model=MaintenanceOrderOutput,
    summary="Iniciar, concluir ou cancelar ordem (atualiza a situação do equipamento)",
    dependencies=[Requires(Permission.MAINTENANCE_ORDER_OPERATE)],
    responses=problems(404, 409, 422),
)
async def transition_maintenance_order(
    order_id: UUID,
    payload: MaintenanceOrderTransition,
    service: MaintenanceServiceDep,
    user: CurrentUser,
) -> MaintenanceOrderOutput:
    order = await service.transition_order(
        order_id, payload.status, payload.resolution_notes, actor_id=user.id
    )
    return MaintenanceOrderOutput.model_validate(order)
