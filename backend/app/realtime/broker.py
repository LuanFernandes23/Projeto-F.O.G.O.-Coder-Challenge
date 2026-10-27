"""Broker de eventos em tempo real: PostgreSQL LISTEN → filas por cliente SSE.

Uma única conexão dedicada (fora do pool) escuta o canal; cada cliente conectado tem
uma fila limitada. Cliente lento que estoura a fila é marcado para ressincronizar,
em vez de travar os demais ou consumir memória sem limite.
"""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import psycopg

from app.repositories.event_publisher import EVENTS_CHANNEL

logger = logging.getLogger(__name__)

_MAX_BACKOFF_SECONDS = 30.0


@dataclass(eq=False, slots=True)
class Subscription:
    queue: asyncio.Queue[str]
    dropped: bool = field(default=False)


class EventBroker:
    def __init__(self, dsn: str, queue_size: int) -> None:
        self._dsn = dsn
        self._queue_size = queue_size
        self._subscriptions: set[Subscription] = set()
        self._task: asyncio.Task[None] | None = None
        self.connected = False

    @property
    def subscribers(self) -> int:
        return len(self._subscriptions)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._listen_forever(), name="event-broker")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self.connected = False

    @contextlib.asynccontextmanager
    async def subscribe(self) -> AsyncIterator[Subscription]:
        subscription = Subscription(asyncio.Queue(maxsize=self._queue_size))
        self._subscriptions.add(subscription)
        try:
            yield subscription
        finally:
            self._subscriptions.discard(subscription)

    def dispatch(self, payload: str) -> None:
        """Entrega o payload a todos os inscritos (público para testes e uso local)."""
        for subscription in list(self._subscriptions):
            if subscription.dropped:
                continue
            try:
                subscription.queue.put_nowait(payload)
            except asyncio.QueueFull:
                subscription.dropped = True
                logger.warning("Cliente de tempo real lento: ressincronização forçada")

    async def _listen_forever(self) -> None:
        backoff = 1.0
        while True:
            try:
                async with await psycopg.AsyncConnection.connect(
                    self._dsn, autocommit=True, connect_timeout=5
                ) as connection:
                    await connection.execute(f"LISTEN {EVENTS_CHANNEL}")
                    self.connected = True
                    backoff = 1.0
                    logger.info("Broker de eventos conectado", extra={"channel": EVENTS_CHANNEL})
                    async for notify in connection.notifies():
                        self.dispatch(notify.payload)
            except asyncio.CancelledError:
                raise
            except (psycopg.Error, OSError) as exc:
                self.connected = False
                logger.warning(
                    "Broker de eventos desconectado; tentando novamente",
                    extra={"error": type(exc).__name__, "retry_in_s": backoff},
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _MAX_BACKOFF_SECONDS)
