"""Hash de senhas (Argon2id) e emissão/validação de tokens JWT."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from app.core.exceptions import AuthenticationError
from app.core.permissions import Role

_TOKEN_ISSUER = "fogo-api"  # noqa: S105  (identificador do emissor, não é segredo)


class PasswordHasher:
    def __init__(self) -> None:
        self._hash = PasswordHash((Argon2Hasher(),))
        # Hash descartável usado quando o usuário não existe: mantém o tempo de resposta
        # do login constante e evita enumeração de e-mails por timing.
        self._dummy_hash = self._hash.hash("senha-inexistente-para-timing")

    def hash(self, password: str) -> str:
        return self._hash.hash(password)

    def verify(self, password: str, password_hash: str | None) -> bool:
        if password_hash is None:
            self._hash.verify(password, self._dummy_hash)
            return False
        return self._hash.verify(password, password_hash)


@dataclass(frozen=True, slots=True)
class TokenClaims:
    user_id: UUID
    role: Role
    expires_at: datetime


class TokenService:
    def __init__(self, secret_key: str, algorithm: str, expire_minutes: int) -> None:
        self._secret_key = secret_key
        self._algorithm = algorithm
        self._expires_in = timedelta(minutes=expire_minutes)

    @property
    def expires_in_seconds(self) -> int:
        return int(self._expires_in.total_seconds())

    def issue(self, user_id: UUID, role: Role, now: datetime) -> str:
        payload = {
            "sub": str(user_id),
            "role": role.value,
            "iat": now,
            "exp": now + self._expires_in,
            "iss": _TOKEN_ISSUER,
        }
        return jwt.encode(payload, self._secret_key, algorithm=self._algorithm)

    def decode(self, token: str) -> TokenClaims:
        try:
            payload = jwt.decode(
                token,
                self._secret_key,
                algorithms=[self._algorithm],
                issuer=_TOKEN_ISSUER,
                options={"require": ["sub", "exp", "iat", "iss", "role"]},
            )
            return TokenClaims(
                user_id=UUID(payload["sub"]),
                role=Role(payload["role"]),
                expires_at=datetime.fromtimestamp(payload["exp"]),
            )
        except jwt.ExpiredSignatureError as exc:
            raise AuthenticationError("Token expirado. Faça login novamente.") from exc
        except (jwt.InvalidTokenError, ValueError) as exc:
            raise AuthenticationError("Token inválido.") from exc
