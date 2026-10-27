"""Autenticação."""

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm

from app.api.dependencies.auth import CurrentUser
from app.api.dependencies.services import AuthServiceDep
from app.api.routes.common import problems
from app.core.permissions import ROLE_PERMISSIONS
from app.schemas.users import CurrentUserOutput, TokenOutput

router = APIRouter(prefix="/auth", tags=["Autenticação"])


@router.post(
    "/token",
    response_model=TokenOutput,
    summary="Login (OAuth2 password): use o e-mail no campo username",
    responses=problems(401, 422),
)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()], auth_service: AuthServiceDep
) -> TokenOutput:
    issued = await auth_service.login(form.username, form.password)
    return TokenOutput(access_token=issued.access_token, expires_in=issued.expires_in)


@router.get(
    "/me",
    response_model=CurrentUserOutput,
    summary="Usuário autenticado e suas permissões",
    responses=problems(401),
)
async def me(user: CurrentUser) -> CurrentUserOutput:
    return CurrentUserOutput(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at,
        updated_at=user.updated_at,
        permissions=sorted(ROLE_PERMISSIONS[user.role]),
    )
