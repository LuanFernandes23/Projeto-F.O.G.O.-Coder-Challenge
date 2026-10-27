"""Usuários do sistema (operadores da Central, gestores, administradores)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.core.exceptions import BusinessRuleError
from app.core.permissions import Role


@dataclass(slots=True)
class User:
    id: UUID
    email: str
    full_name: str
    password_hash: str
    role: Role
    is_active: bool
    created_at: datetime
    updated_at: datetime


def ensure_admin_remains(
    target: User, new_role: Role, new_is_active: bool, active_admins: Sequence[User]
) -> None:
    """Impede que o sistema fique sem nenhum administrador ativo."""
    loses_admin = (
        target.role is Role.ADMIN
        and target.is_active
        and (new_role is not Role.ADMIN or not new_is_active)
    )
    if loses_admin and all(admin.id == target.id for admin in active_admins):
        raise BusinessRuleError("Não é possível remover o último administrador ativo do sistema.")
