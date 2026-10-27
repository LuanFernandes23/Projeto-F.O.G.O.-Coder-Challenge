"""Recursos de processo criados no lifespan e expostos às dependências por request."""

import asyncio
from dataclasses import dataclass, field

import httpx
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.agent.runtime import PrometheusRuntime, build_runtime
from app.core.cache import TtlCache
from app.core.clock import Clock
from app.core.config import Settings
from app.core.security import PasswordHasher, TokenService
from app.integrations.cep.base import CepAddress
from app.realtime.broker import EventBroker


@dataclass(slots=True)
class AppContainer:
    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    http_client: httpx.AsyncClient
    clock: Clock
    password_hasher: PasswordHasher
    token_service: TokenService
    cep_cache: TtlCache[str, CepAddress]
    event_broker: EventBroker
    prometheus: PrometheusRuntime | None = None
    _prometheus_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def prometheus_runtime(self) -> PrometheusRuntime:
        """Montado sob demanda (pool do checkpointer + modelo de embeddings são pesados)."""
        async with self._prometheus_lock:
            if self.prometheus is None:
                self.prometheus = await build_runtime(
                    self.session_factory, self.clock, self.settings
                )
            return self.prometheus


def get_container(request: Request) -> AppContainer:
    container: AppContainer = request.app.state.container
    return container
