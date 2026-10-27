"""Cliente HTTP do gateway IoT simulado (timeout explícito e retentativas)."""

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_RETRIES = 3


class GatewayClient:
    def __init__(self, base_url: str, gateway_key: str, timeout_seconds: float) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/api/v1/telemetry",
            headers={"X-Gateway-Key": gateway_key, "User-Agent": "fogo-iot-gateway/0.1"},
            timeout=httpx.Timeout(timeout_seconds),
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def registry(self) -> dict[str, Any]:
        response = await self._request("GET", "/registry")
        data: dict[str, Any] = response.json()
        return data

    async def send_heartbeats(self, heartbeats: list[dict[str, Any]]) -> dict[str, Any]:
        response = await self._request("POST", "/equipment", json={"heartbeats": heartbeats})
        data: dict[str, Any] = response.json()
        return data

    async def send_positions(self, positions: list[dict[str, Any]]) -> dict[str, Any]:
        response = await self._request("POST", "/agents", json={"positions": positions})
        data: dict[str, Any] = response.json()
        return data

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        delay = 1.0
        for attempt in range(1, _RETRIES + 1):
            try:
                response = await self._client.request(method, path, **kwargs)
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code < 500:
                    raise  # erro do cliente (ex.: chave inválida): retentar não resolve
                logger.warning(
                    "API respondeu erro; nova tentativa",
                    extra={"path": path, "status_code": exc.response.status_code},
                )
            except httpx.TransportError as exc:
                logger.warning(
                    "Falha de rede com a API; nova tentativa",
                    extra={"path": path, "error": type(exc).__name__, "attempt": attempt},
                )
            if attempt < _RETRIES:
                await asyncio.sleep(delay)
                delay *= 2
        raise ConnectionError(f"API indisponível após {_RETRIES} tentativas ({path}).")
