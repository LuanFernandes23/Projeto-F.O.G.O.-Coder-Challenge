"""Simulador IoT da cidade (serviço ``simulator`` do compose).

Faz o papel de um gateway externo: transmite heartbeats, métricas, falhas autodetectadas
e o GPS das equipes em campo para a API, como fariam os dispositivos reais. Não toma
decisões humanas (reparos, despachos): essas ficam com o operador — e, na Parte 3,
com o PROMETHEUS.

Uso: ``python -m app.simulator.main``.
"""

import asyncio
import logging
import sys
import time
from datetime import UTC, datetime

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.simulator.city import CitySimulation
from app.simulator.gateway_client import GatewayClient

logger = logging.getLogger("app.simulator")

_REGISTRY_REFRESH_SECONDS = 15.0
_SUMMARY_EVERY_SECONDS = 60.0


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    if not settings.simulator_enabled:
        logger.info("Simulador desativado (SIMULATOR_ENABLED=false); aguardando.")
        await asyncio.Event().wait()

    client = GatewayClient(
        settings.simulator_api_url,
        settings.iot_gateway_key.get_secret_value(),
        settings.http_timeout_seconds,
    )
    city = CitySimulation(
        seed=settings.simulator_seed,
        tz=settings.tz,
        tick_seconds=settings.simulator_tick_seconds,
        heartbeat_seconds=settings.simulator_heartbeat_seconds,
        mean_seconds_between_faults=settings.simulator_mean_seconds_between_faults,
    )
    last_registry = last_summary = 0.0
    totals = {"heartbeats": 0, "positions": 0, "faults": 0, "outages": 0}
    totals.update(precursors=0, averted=0)
    logger.info("Simulador iniciado", extra={"api": settings.simulator_api_url})
    try:
        while True:
            started = time.monotonic()
            try:
                if started - last_registry >= _REGISTRY_REFRESH_SECONDS:
                    city.sync(await client.registry(), datetime.now(UTC))
                    last_registry = started
                tick = city.step(datetime.now(UTC))
                if tick.heartbeats:
                    await client.send_heartbeats(tick.heartbeats)
                if tick.positions:
                    await client.send_positions(tick.positions)
                totals["heartbeats"] += len(tick.heartbeats)
                totals["positions"] += len(tick.positions)
                totals["faults"] += tick.faults
                totals["outages"] += tick.outages_started
                totals["precursors"] += tick.precursors_started
                totals["averted"] += tick.averted
            except ConnectionError as exc:
                logger.warning("Ciclo do simulador sem sucesso", extra={"error": str(exc)})
            if started - last_summary >= _SUMMARY_EVERY_SECONDS:
                logger.info(
                    "Simulador ativo",
                    extra={**totals, "devices": len(city.devices), "agents": len(city.agents)},
                )
                last_summary = started
            elapsed = time.monotonic() - started
            await asyncio.sleep(max(0.0, settings.simulator_tick_seconds - elapsed))
    finally:
        await client.close()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run())
