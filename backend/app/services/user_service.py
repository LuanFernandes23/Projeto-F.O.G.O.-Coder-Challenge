"""Autenticação e gestão de usuários."""

import logging
import uuid
from dataclasses import dataclass
from uuid import UUID

from app.core.clock import Clock
from app.core.exceptions import AuthenticationError, BusinessRuleError, ConflictError, NotFoundError
from app.core.permissions import Role
from app.core.security import PasswordHasher, TokenService
from app.domain.shared import Page, PageRequest
from app.domain.users import User, ensure_admin_remains
from app.services.ports import UnitOfWork

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class IssuedToken:
    access_token: str
    expires_in: int


@dataclass(frozen=True, slots=True)
class NewUser:
    email: str
    full_name: str
    password: str
    role: Role


@dataclass(frozen=True, slots=True)
class UserChanges:
    full_name: str | None = None
    password: str | None = None
    role: Role | None = None
    is_active: bool | None = None


class AuthService:
    def __init__(
        self, uow: UnitOfWork, clock: Clock, hasher: PasswordHasher, tokens: TokenService
    ) -> None:
        self._uow = uow
        self._clock = clock
        self._hasher = hasher
        self._tokens = tokens

    async def login(self, email: str, password: str) -> IssuedToken:
        async with self._uow as uow:
            user = await uow.users.get_by_email(email)
        valid = self._hasher.verify(password, user.password_hash if user else None)
        if user is None or not valid or not user.is_active:
            logger.info("Falha de login", extra={"reason": "credenciais_invalidas"})
            raise AuthenticationError("E-mail ou senha inválidos.")
        token = self._tokens.issue(user.id, user.role, self._clock.now())
        logger.info("Login realizado", extra={"user_id": str(user.id)})
        return IssuedToken(token, self._tokens.expires_in_seconds)

    async def authenticate(self, token: str) -> User:
        claims = self._tokens.decode(token)
        async with self._uow as uow:
            user = await uow.users.get(claims.user_id)
        # O perfil vem do banco (não do token): desativação e troca de perfil valem na hora.
        if user is None or not user.is_active:
            raise AuthenticationError("Usuário inativo ou inexistente.")
        return user


class UserService:
    def __init__(self, uow: UnitOfWork, clock: Clock, hasher: PasswordHasher) -> None:
        self._uow = uow
        self._clock = clock
        self._hasher = hasher

    async def create(self, data: NewUser) -> User:
        now = self._clock.now()
        async with self._uow as uow:
            if await uow.users.get_by_email(data.email) is not None:
                raise ConflictError(
                    "Já existe um usuário com este e-mail.", extra={"field": "email"}
                )
            user = User(
                id=uuid.uuid4(),
                email=data.email.lower(),
                full_name=data.full_name,
                password_hash=self._hasher.hash(data.password),
                role=data.role,
                is_active=True,
                created_at=now,
                updated_at=now,
            )
            await uow.users.add(user)
            await uow.commit()
            logger.info("Usuário criado", extra={"user_id": str(user.id), "role": user.role.value})
            return user

    async def update(self, user_id: UUID, changes: UserChanges, actor_id: UUID) -> User:
        async with self._uow as uow:
            user = await uow.users.get(user_id)
            if user is None:
                raise NotFoundError("Usuário não encontrado.")
            new_role = changes.role or user.role
            new_active = user.is_active if changes.is_active is None else changes.is_active
            if user_id == actor_id and (new_role is not user.role or not new_active):
                raise BusinessRuleError("Você não pode alterar o próprio perfil ou se desativar.")
            ensure_admin_remains(user, new_role, new_active, await uow.users.list_active_admins())
            user.role = new_role
            user.is_active = new_active
            if changes.full_name is not None:
                user.full_name = changes.full_name
            if changes.password is not None:
                user.password_hash = self._hasher.hash(changes.password)
            user.updated_at = self._clock.now()
            await uow.users.update(user)
            await uow.commit()
            return user

    async def get(self, user_id: UUID) -> User:
        async with self._uow as uow:
            user = await uow.users.get(user_id)
        if user is None:
            raise NotFoundError("Usuário não encontrado.")
        return user

    async def list_page(self, page: PageRequest) -> Page[User]:
        async with self._uow as uow:
            return await uow.users.list_page(page)

    async def ensure_first_admin(self, email: str, full_name: str, password: str) -> bool:
        """Cria o primeiro administrador se o sistema ainda não tiver usuários."""
        async with self._uow as uow:
            if await uow.users.count() > 0:
                return False
        await self.create(
            NewUser(email=email, full_name=full_name, password=password, role=Role.ADMIN)
        )
        return True
