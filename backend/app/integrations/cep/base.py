"""Contrato comum dos provedores de consulta de CEP."""

import logging
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.core.exceptions import IntegrationError
from app.domain.shared import UF, GeoPoint

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CepAddress:
    cep: str
    street: str | None
    neighborhood: str | None
    city: str
    uf: UF
    location: GeoPoint | None
    source: str


class CepProvider(Protocol):
    name: str

    async def lookup(self, cep: str) -> CepAddress | None:
        """Endereço do CEP, ``None`` se o provedor afirma que ele não existe.

        Falhas de rede, timeout ou respostas inesperadas levantam ``IntegrationError``.
        """
        ...


async def get_json(
    client: httpx.AsyncClient, provider: str, url: str, not_found_statuses: frozenset[int]
) -> dict[str, Any] | None:
    """GET com tratamento padronizado de erros de rede e de HTTP."""
    try:
        response = await client.get(url)
    except httpx.TimeoutException as exc:
        logger.warning("Timeout no provedor de CEP", extra={"provider": provider})
        raise IntegrationError(f"Tempo esgotado ao consultar {provider}.") from exc
    except httpx.HTTPError as exc:
        logger.warning(
            "Falha de rede no provedor de CEP",
            extra={"provider": provider, "error": type(exc).__name__},
        )
        raise IntegrationError(f"Falha de comunicação com {provider}.") from exc
    if response.status_code in not_found_statuses:
        return None
    if response.status_code != httpx.codes.OK:
        logger.warning(
            "Resposta inesperada do provedor de CEP",
            extra={"provider": provider, "status_code": response.status_code},
        )
        raise IntegrationError(f"{provider} respondeu com status {response.status_code}.")
    try:
        payload = response.json()
    except ValueError as exc:
        raise IntegrationError(f"{provider} retornou um corpo inválido.") from exc
    if not isinstance(payload, dict):
        raise IntegrationError(f"{provider} retornou um formato inesperado.")
    return payload


def parse_uf(provider: str, value: Any) -> UF:
    try:
        return UF(str(value).upper())
    except ValueError as exc:
        raise IntegrationError(f"{provider} retornou UF inválida.") from exc


def blank_to_none(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None
