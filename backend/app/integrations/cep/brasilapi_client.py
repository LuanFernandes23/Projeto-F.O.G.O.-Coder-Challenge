"""Cliente da BrasilAPI CEP v2 (https://brasilapi.com.br) — fallback com coordenadas."""

from typing import Any

import httpx

from app.domain.shared import GeoPoint
from app.integrations.cep.base import CepAddress, blank_to_none, get_json, parse_uf


def _parse_location(payload: dict[str, Any]) -> GeoPoint | None:
    coordinates = (payload.get("location") or {}).get("coordinates") or {}
    try:
        latitude = float(coordinates["latitude"])
        longitude = float(coordinates["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    return GeoPoint(latitude=latitude, longitude=longitude)


class BrasilApiCepClient:
    name = "brasilapi"

    def __init__(self, client: httpx.AsyncClient, base_url: str) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")

    async def lookup(self, cep: str) -> CepAddress | None:
        payload = await get_json(
            self._client, self.name, f"{self._base_url}/api/cep/v2/{cep}", frozenset({404})
        )
        if payload is None:
            return None
        return CepAddress(
            cep=cep,
            street=blank_to_none(payload.get("street")),
            neighborhood=blank_to_none(payload.get("neighborhood")),
            city=str(payload.get("city", "")).strip(),
            uf=parse_uf(self.name, payload.get("state")),
            location=_parse_location(payload),
            source=self.name,
        )
