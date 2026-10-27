"""Cidade Preditiva: previsões explicáveis, anomalias ao vivo e qualidade medida."""

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.dependencies.auth import Requires
from app.api.dependencies.services import PredictionServiceDep
from app.api.routes.common import AUTH_PROBLEMS
from app.core.permissions import Permission
from app.services.prediction_service import SNAPSHOT_ANOMALIES, SNAPSHOT_CITY

router = APIRouter(
    prefix="/predictions",
    tags=["Cidade Preditiva"],
    dependencies=[Requires(Permission.OPERATIONS_READ)],
    responses=AUTH_PROBLEMS,
)


class SnapshotOutput(BaseModel):
    ready: bool = Field(description="False enquanto o primeiro ajuste do modelo não terminou.")
    data: dict[str, Any] = Field(default_factory=dict)


class RefreshOutput(BaseModel):
    model_id: int | None
    skill_vs_mean: float | None
    top20_capture: float | None


@router.get(
    "/city",
    response_model=SnapshotOutput,
    summary="Previsão da cidade: risco por região × hora, reforço, equipamentos e tendências",
    description=(
        "Retrato calculado pelo scheduler a cada 5 min a partir do último modelo ajustado. "
        "Inclui o backtest (o modelo prevendo 8 semanas que não viu) e os fatores que "
        "explicam cada previsão."
    ),
)
async def city(service: PredictionServiceDep) -> SnapshotOutput:
    data = await service.snapshot(SNAPSHOT_CITY)
    return SnapshotOutput(ready=data is not None, data=data or {})


@router.get(
    "/anomalies",
    response_model=SnapshotOutput,
    summary="Comportamentos fora do padrão agora (precursores de falha e picos regionais)",
)
async def anomalies(service: PredictionServiceDep) -> SnapshotOutput:
    data = await service.snapshot(SNAPSHOT_ANOMALIES)
    return SnapshotOutput(ready=data is not None, data=data or {})


@router.post(
    "/refresh",
    response_model=RefreshOutput,
    summary="Reajustar os modelos e recalcular as previsões agora",
    dependencies=[Requires(Permission.PROMETHEUS_MANAGE)],
)
async def refresh(service: PredictionServiceDep) -> RefreshOutput:
    result = await service.fit_models()
    if result.get("skipped"):
        return RefreshOutput(model_id=None, skill_vs_mean=None, top20_capture=None)
    await service.refresh()
    return RefreshOutput(
        model_id=result["model_id"],
        skill_vs_mean=result["backtest"]["skill_vs_mean"],
        top20_capture=result["backtest"]["top20_capture"],
    )
