"""Fluxo de eventos em tempo real (Server-Sent Events)."""

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.api.dependencies.auth import CurrentUser, Requires
from app.api.dependencies.services import Container
from app.api.routes.common import AUTH_PROBLEMS
from app.core.permissions import Permission
from app.realtime.sse import event_stream

router = APIRouter(tags=["Tempo real"], responses=AUTH_PROBLEMS)


@router.get(
    "/stream",
    summary="Eventos da cidade em tempo real (text/event-stream)",
    description=(
        "Eventos: equipment.status_changed, equipment.connectivity, agents.positions, "
        "agent.status_changed, alert.opened/updated/resolved, dispatch.updated, "
        "maintenance.order_changed. Ao receber `resync`, recarregue o snapshot."
    ),
    response_class=StreamingResponse,
    dependencies=[Requires(Permission.OPERATIONS_READ)],
)
async def stream(request: Request, user: CurrentUser, container: Container) -> StreamingResponse:
    generator = event_stream(
        container.event_broker,
        request.is_disconnected,
        container.settings.sse_heartbeat_seconds,
        {"user": user.full_name, "broker_connected": container.event_broker.connected},
    )
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
