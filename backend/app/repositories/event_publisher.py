"""Publicação de eventos via PostgreSQL NOTIFY, dentro da transação do caso de uso.

O PostgreSQL só entrega o NOTIFY quando a transação confirma: se o caso de uso falhar
e fizer rollback, nenhum evento "fantasma" chega ao painel.
"""

import json
import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.operations.events import DomainEvent

logger = logging.getLogger(__name__)

EVENTS_CHANNEL = "fogo_events"
_MAX_PAYLOAD_BYTES = 7900  # limite do NOTIFY é 8000 bytes


def serialize_event(event: DomainEvent) -> str:
    return json.dumps(
        {"type": event.type.value, "data": event.data},
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )


class PgEventPublisher:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def publish(self, event: DomainEvent) -> None:
        payload = serialize_event(event)
        if len(payload.encode()) > _MAX_PAYLOAD_BYTES:
            logger.warning(
                "Evento grande demais para NOTIFY; enviando só o tipo",
                extra={"event_type": event.type.value},
            )
            payload = serialize_event(DomainEvent(event.type, {"truncated": True}))
        await self._session.execute(select(func.pg_notify(EVENTS_CHANNEL, payload)))
