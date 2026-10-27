"""Cliente do ViaCEP (https://viacep.com.br) — provedor primário."""

import httpx

from app.integrations.cep.base import CepAddress, blank_to_none, get_json, parse_uf


class ViaCepClient:
    name = "viacep"

    def __init__(self, client: httpx.AsyncClient, base_url: str) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")

    async def lookup(self, cep: str) -> CepAddress | None:
        payload = await get_json(
            self._client, self.name, f"{self._base_url}/ws/{cep}/json/", frozenset({400, 404})
        )
        # O ViaCEP responde 200 com {"erro": true} para CEP inexistente.
        if payload is None or payload.get("erro") in (True, "true"):
            return None
        return CepAddress(
            cep=cep,
            street=blank_to_none(payload.get("logradouro")),
            neighborhood=blank_to_none(payload.get("bairro")),
            city=str(payload.get("localidade", "")).strip(),
            uf=parse_uf(self.name, payload.get("uf")),
            location=None,  # o ViaCEP não fornece coordenadas
            source=self.name,
        )
