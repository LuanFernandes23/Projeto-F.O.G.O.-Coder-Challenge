"""Health checks (liveness e readiness)."""

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.dependencies.services import Container

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Saúde"])


class HealthOutput(BaseModel):
    status: str
    database: str | None = None


@router.get("/health", response_model=HealthOutput, summary="Aplicação está no ar (liveness)")
async def health() -> HealthOutput:
    return HealthOutput(status="ok")


@router.get(
    "/health/ready",
    response_model=HealthOutput,
    summary="Aplicação pronta para atender (verifica o banco)",
    responses={503: {"model": HealthOutput}},
)
async def readiness(container: Container) -> HealthOutput | JSONResponse:
    try:
        async with container.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError) as exc:
        logger.error("Banco indisponível no readiness", extra={"error": type(exc).__name__})
        return JSONResponse({"status": "degraded", "database": "unavailable"}, status_code=503)
    return HealthOutput(status="ok", database="ok")
