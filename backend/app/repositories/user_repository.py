"""Persistência de usuários."""

from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Role
from app.database.models.tables import UserModel
from app.domain.shared import Page, PageRequest
from app.domain.users import User


def _to_domain(model: UserModel) -> User:
    return User(
        id=model.id,
        email=model.email,
        full_name=model.full_name,
        password_hash=model.password_hash,
        role=model.role,
        is_active=model.is_active,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


class SqlUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: UUID) -> User | None:
        model = await self._session.get(UserModel, user_id)
        return _to_domain(model) if model else None

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(UserModel).where(func.lower(UserModel.email) == email.lower())
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_domain(model) if model else None

    async def list_page(self, page: PageRequest) -> Page[User]:
        total = (await self._session.execute(select(func.count(UserModel.id)))).scalar_one()
        stmt = select(UserModel).order_by(UserModel.full_name).limit(page.limit).offset(page.offset)
        models = (await self._session.execute(stmt)).scalars().all()
        return Page([_to_domain(m) for m in models], total, page.limit, page.offset)

    async def list_active_admins(self) -> list[User]:
        stmt = select(UserModel).where(UserModel.role == Role.ADMIN, UserModel.is_active.is_(True))
        return [_to_domain(m) for m in (await self._session.execute(stmt)).scalars().all()]

    async def count(self) -> int:
        return (await self._session.execute(select(func.count(UserModel.id)))).scalar_one()

    async def add(self, user: User) -> None:
        self._session.add(
            UserModel(
                id=user.id,
                email=user.email,
                full_name=user.full_name,
                password_hash=user.password_hash,
                role=user.role,
                is_active=user.is_active,
                created_at=user.created_at,
                updated_at=user.updated_at,
            )
        )
        await self._session.flush()

    async def update(self, user: User) -> None:
        await self._session.execute(
            update(UserModel)
            .where(UserModel.id == user.id)
            .values(
                full_name=user.full_name,
                password_hash=user.password_hash,
                role=user.role,
                is_active=user.is_active,
                updated_at=user.updated_at,
            )
        )
