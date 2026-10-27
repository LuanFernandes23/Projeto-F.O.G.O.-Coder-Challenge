"""Gestão de usuários (somente administradores)."""

from uuid import UUID

from fastapi import APIRouter, status

from app.api.dependencies.auth import CurrentUser, Requires
from app.api.dependencies.services import UserServiceDep
from app.api.routes.common import AUTH_PROBLEMS, Pagination, problems
from app.core.permissions import Permission
from app.schemas.common import PageOutput
from app.schemas.users import UserCreate, UserOutput, UserUpdate
from app.services.user_service import NewUser, UserChanges

router = APIRouter(
    prefix="/users",
    tags=["Usuários"],
    dependencies=[Requires(Permission.USER_MANAGE)],
    responses=AUTH_PROBLEMS,
)


@router.get("", response_model=PageOutput[UserOutput], summary="Listar usuários")
async def list_users(service: UserServiceDep, page: Pagination) -> PageOutput[UserOutput]:
    result = await service.list_page(page)
    return PageOutput(
        items=[UserOutput.model_validate(u) for u in result.items],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )


@router.post(
    "",
    response_model=UserOutput,
    status_code=status.HTTP_201_CREATED,
    summary="Criar usuário",
    responses=problems(409, 422),
)
async def create_user(payload: UserCreate, service: UserServiceDep) -> UserOutput:
    user = await service.create(
        NewUser(
            email=str(payload.email),
            full_name=payload.full_name,
            password=payload.password.get_secret_value(),
            role=payload.role,
        )
    )
    return UserOutput.model_validate(user)


@router.get(
    "/{user_id}", response_model=UserOutput, summary="Detalhar usuário", responses=problems(404)
)
async def get_user(user_id: UUID, service: UserServiceDep) -> UserOutput:
    return UserOutput.model_validate(await service.get(user_id))


@router.patch(
    "/{user_id}",
    response_model=UserOutput,
    summary="Atualizar usuário (perfil, senha, ativação)",
    responses=problems(404, 422),
)
async def update_user(
    user_id: UUID, payload: UserUpdate, service: UserServiceDep, actor: CurrentUser
) -> UserOutput:
    user = await service.update(
        user_id,
        UserChanges(
            full_name=payload.full_name,
            password=payload.password.get_secret_value() if payload.password else None,
            role=payload.role,
            is_active=payload.is_active,
        ),
        actor_id=actor.id,
    )
    return UserOutput.model_validate(user)
