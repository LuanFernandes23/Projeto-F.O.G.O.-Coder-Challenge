"""Contratos de autenticação e usuários."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr

from app.core.permissions import Permission, Role


class TokenOutput(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105  (tipo do token OAuth2, não é segredo)
    expires_in: int = Field(description="Validade do token em segundos.")


class UserCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr
    full_name: str = Field(min_length=3, max_length=120)
    password: SecretStr = Field(min_length=8, max_length=128)
    role: Role


class UserUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    full_name: str | None = Field(default=None, min_length=3, max_length=120)
    password: SecretStr | None = Field(default=None, min_length=8, max_length=128)
    role: Role | None = None
    is_active: bool | None = None


class UserOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    full_name: str
    role: Role
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CurrentUserOutput(UserOutput):
    permissions: list[Permission]
