"""Cifra da chave de API do modelo de IA (Fernet: AES-128-CBC + HMAC-SHA256)."""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.exceptions import BusinessRuleError


class SecretBox:
    """A chave fica cifrada no banco; só o servidor (com ``AI_ENCRYPTION_KEY``) a decifra."""

    def __init__(self, key: str, fallback_secret: str) -> None:
        if not key:
            # Sem chave dedicada, deriva uma da chave JWT (aceitável em dev; produção deve
            # definir AI_ENCRYPTION_KEY para poder girar uma sem invalidar a outra).
            key = base64.urlsafe_b64encode(
                hashlib.sha256(fallback_secret.encode()).digest()
            ).decode()
        self._fernet = Fernet(key.encode())

    def encrypt(self, plaintext: str) -> bytes:
        return self._fernet.encrypt(plaintext.encode())

    def decrypt(self, token: bytes) -> str:
        try:
            return self._fernet.decrypt(token).decode()
        except InvalidToken as exc:
            raise BusinessRuleError(
                "Não foi possível decifrar a chave de IA salva (AI_ENCRYPTION_KEY mudou?). "
                "Cadastre a chave novamente."
            ) from exc
