"""Autopreenchimento de endereço por CEP, com cadeia de provedores e cache."""

import logging
import re
from collections.abc import Sequence

from app.core.cache import TtlCache
from app.core.exceptions import (
    BusinessRuleError,
    IntegrationError,
    IntegrationUnavailableError,
    NotFoundError,
)
from app.integrations.cep.base import CepAddress, CepProvider

logger = logging.getLogger(__name__)


class AddressLookupService:
    """Consulta os provedores em ordem; o próximo só é chamado se o anterior falhar
    ou não conhecer o CEP. Se todos falharem, responde 503 e o cadastro manual segue
    funcionando normalmente.
    """

    def __init__(self, providers: Sequence[CepProvider], cache: TtlCache[str, CepAddress]) -> None:
        self._providers = providers
        self._cache = cache

    async def lookup(self, raw_cep: str) -> CepAddress:
        cep = re.sub(r"\D", "", raw_cep)
        if len(cep) != 8:
            raise BusinessRuleError("CEP deve conter 8 dígitos.", extra={"field": "cep"})
        cached = self._cache.get(cep)
        if cached is not None:
            return cached

        failures: list[str] = []
        for provider in self._providers:
            try:
                address = await provider.lookup(cep)
            except IntegrationError as exc:
                failures.append(provider.name)
                logger.info(
                    "Provedor de CEP falhou, tentando o próximo",
                    extra={"provider": provider.name, "detail": exc.detail},
                )
                continue
            if address is not None:
                self._cache.set(cep, address)
                return address

        if failures and len(failures) == len(self._providers):
            raise IntegrationUnavailableError(
                "Serviços de CEP indisponíveis no momento. Preencha o endereço manualmente.",
                extra={"providers": failures},
            )
        raise NotFoundError(f"CEP {cep} não encontrado.")
