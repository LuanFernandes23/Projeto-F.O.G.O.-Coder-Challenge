from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest

from app.core.cache import TtlCache
from app.core.exceptions import AuthenticationError, IntegrationUnavailableError, NotFoundError
from app.core.permissions import Role
from app.core.security import PasswordHasher, TokenService
from app.integrations.cep.base import CepAddress
from app.integrations.cep.brasilapi_client import BrasilApiCepClient
from app.integrations.cep.viacep_client import ViaCepClient
from app.services.address_service import AddressLookupService


class TestSecurity:
    def test_password_hash_roundtrip(self) -> None:
        hasher = PasswordHasher()
        hashed = hasher.hash("Segredo@123")
        assert hashed != "Segredo@123"
        assert hasher.verify("Segredo@123", hashed)
        assert not hasher.verify("errada", hashed)

    def test_verify_without_user_is_false(self) -> None:
        assert PasswordHasher().verify("qualquer", None) is False

    def test_token_roundtrip(self) -> None:
        tokens = TokenService("k" * 40, "HS256", 60)
        user_id = uuid4()
        claims = tokens.decode(tokens.issue(user_id, Role.OPERADOR, datetime.now(UTC)))
        assert (claims.user_id, claims.role) == (user_id, Role.OPERADOR)

    def test_expired_token_is_rejected(self) -> None:
        tokens = TokenService("k" * 40, "HS256", 1)
        token = tokens.issue(uuid4(), Role.ADMIN, datetime.now(UTC) - timedelta(minutes=5))
        with pytest.raises(AuthenticationError, match="expirado"):
            tokens.decode(token)

    def test_tampered_token_is_rejected(self) -> None:
        token = TokenService("k" * 40, "HS256", 60).issue(uuid4(), Role.ADMIN, datetime.now(UTC))
        with pytest.raises(AuthenticationError):
            TokenService("outra-chave" * 4, "HS256", 60).decode(token)


class TestTtlCache:
    def test_entries_expire(self) -> None:
        now = [0.0]
        cache: TtlCache[str, int] = TtlCache(10, 5, time_source=lambda: now[0])
        cache.set("a", 1)
        assert cache.get("a") == 1
        now[0] = 11
        assert cache.get("a") is None

    def test_least_recently_used_is_evicted(self) -> None:
        cache: TtlCache[str, int] = TtlCache(100, 2)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.get("a")
        cache.set("c", 3)
        assert cache.get("b") is None
        assert cache.get("a") == 1


VIACEP_OK = {
    "cep": "17500-000",
    "logradouro": "Rua X",
    "bairro": "Centro",
    "localidade": "Marília",
    "uf": "SP",
}
BRASILAPI_OK = {
    "cep": "17500000",
    "state": "SP",
    "city": "Marília",
    "neighborhood": "Centro",
    "street": "Rua X",
    "location": {"coordinates": {"latitude": "-22.21", "longitude": "-49.94"}},
}


def _service(handler: httpx.MockTransport) -> tuple[AddressLookupService, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=handler, timeout=1)
    providers = [
        ViaCepClient(client, "https://viacep"),
        BrasilApiCepClient(client, "https://brasil"),
    ]
    return AddressLookupService(providers, TtlCache(60, 10)), client


class TestAddressLookup:
    async def test_primary_provider_answers(self) -> None:
        service, client = _service(
            httpx.MockTransport(lambda r: httpx.Response(200, json=VIACEP_OK))
        )
        async with client:
            address = await service.lookup("17500-000")
        assert (address.city, address.source) == ("Marília", "viacep")

    async def test_falls_back_when_primary_fails(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if "viacep" in str(request.url):
                raise httpx.ConnectTimeout("timeout")
            return httpx.Response(200, json=BRASILAPI_OK)

        service, client = _service(httpx.MockTransport(handler))
        async with client:
            address = await service.lookup("17500000")
        assert address.source == "brasilapi"
        assert address.location is not None

    async def test_unavailable_when_all_providers_fail(self) -> None:
        service, client = _service(httpx.MockTransport(lambda r: httpx.Response(500)))
        async with client:
            with pytest.raises(IntegrationUnavailableError):
                await service.lookup("17500000")

    async def test_not_found_when_providers_do_not_know_the_cep(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if "viacep" in str(request.url):
                return httpx.Response(200, json={"erro": "true"})
            return httpx.Response(404)

        service, client = _service(httpx.MockTransport(handler))
        async with client:
            with pytest.raises(NotFoundError):
                await service.lookup("99999999")

    async def test_results_are_cached(self) -> None:
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url)
            return httpx.Response(200, json=VIACEP_OK)

        service, client = _service(httpx.MockTransport(handler))
        async with client:
            first: CepAddress = await service.lookup("17500000")
            second = await service.lookup("17500-000")
        assert first == second
        assert len(calls) == 1
