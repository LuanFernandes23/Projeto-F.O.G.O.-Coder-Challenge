"""Autenticação (Bearer JWT) e autorização por permissão (RBAC)."""

from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer

from app.api.dependencies.services import AuthServiceDep
from app.core.exceptions import AuthenticationError, PermissionDeniedError
from app.core.permissions import Permission, has_permission
from app.domain.users import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)


async def get_current_user(
    auth_service: AuthServiceDep,
    token: Annotated[str | None, Depends(oauth2_scheme)],
) -> User:
    if not token:
        raise AuthenticationError("Envie o token no cabeçalho Authorization: Bearer <token>.")
    return await auth_service.authenticate(token)


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_permission(permission: Permission) -> Callable[[User], Awaitable[None]]:
    """Uso: ``dependencies=[Requires(Permission.X)]``; o usuário vem de ``CurrentUser``
    (o FastAPI reaproveita a mesma resolução por requisição, sem consulta duplicada)."""

    async def dependency(user: CurrentUser) -> None:
        if not has_permission(user.role, permission):
            raise PermissionDeniedError(
                f"Seu perfil ({user.role.value}) não tem a permissão '{permission.value}'.",
                extra={"required_permission": permission.value},
            )

    return dependency


def Requires(permission: Permission) -> Any:  # noqa: N802  (lê como um marcador declarativo)
    return Depends(require_permission(permission))
