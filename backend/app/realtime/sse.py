"""Formatação e geração do fluxo Server-Sent Events."""

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from app.realtime.broker import EventBroker


def format_sse(event: str, data: str, event_id: int | None = None) -> str:
    """Mensagem SSE (cada linha de dados prefixada por ``data:``)."""
    lines = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.extend(f"data: {line}" for line in data.splitlines() or [""])
    return "\n".join(lines) + "\n\n"


async def event_stream(
    broker: EventBroker,
    is_disconnected: Callable[[], Awaitable[bool]],
    heartbeat_seconds: float,
    ready_payload: dict[str, Any],
) -> AsyncIterator[str]:
    async with broker.subscribe() as subscription:
        yield format_sse("ready", json.dumps(ready_payload))
        counter = 0
        while not await is_disconnected():
            try:
                payload = await asyncio.wait_for(subscription.queue.get(), heartbeat_seconds)
            except TimeoutError:
                yield ": ping\n\n"  # comentário SSE: mantém proxies e a conexão vivos
                continue
            if subscription.dropped:
                yield format_sse("resync", "{}")
                return
            counter += 1
            event_type = json.loads(payload).get("type", "message")
            yield format_sse(event_type, payload, counter)
