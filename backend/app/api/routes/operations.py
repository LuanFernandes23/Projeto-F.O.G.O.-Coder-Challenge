"""Central de Operações: indicadores, mapa, saúde das regiões, análises e sugestões."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.dependencies.auth import Requires
from app.api.dependencies.services import (
    Container,
    DispatchServiceDep,
    OperationsServiceDep,
)
from app.api.routes.common import AUTH_PROBLEMS, problems
from app.core.permissions import Permission
from app.schemas.location import GeoPointSchema
from app.schemas.operations import (
    DispatchSuggestionOutput,
    HeatPointOutput,
    MapAgentOutput,
    MapEquipmentOutput,
    MapFeaturesOutput,
    OverviewOutput,
    RegionHealthOutput,
    TrendPointOutput,
)
from app.services.operations_service import HeatmapKind

router = APIRouter(
    prefix="/operations",
    tags=["Central de Operações"],
    dependencies=[Requires(Permission.OPERATIONS_READ)],
    responses=AUTH_PROBLEMS,
)


@router.get("/overview", response_model=OverviewOutput, summary="Indicadores gerais da cidade")
async def overview(service: OperationsServiceDep) -> OverviewOutput:
    return OverviewOutput.from_domain(await service.overview())


@router.get(
    "/map-features",
    response_model=MapFeaturesOutput,
    summary="Todos os equipamentos e agentes (payload leve para o mapa)",
)
async def map_features(service: OperationsServiceDep, container: Container) -> MapFeaturesOutput:
    snapshot = await service.map_snapshot()
    now = container.clock.now()
    return MapFeaturesOutput(
        generated_at=snapshot.generated_at,
        equipment=[MapEquipmentOutput.from_domain(f, now) for f in snapshot.equipment],
        agents=[MapAgentOutput.from_domain(f, now) for f in snapshot.agents],
    )


@router.get(
    "/regions",
    response_model=list[RegionHealthOutput],
    summary="Saúde por região (índice 0–100, nível e motivos), da pior para a melhor",
)
async def regions(service: OperationsServiceDep) -> list[RegionHealthOutput]:
    return [RegionHealthOutput.from_domain(h) for h in await service.regions()]


@router.get(
    "/heatmap",
    response_model=list[HeatPointOutput],
    summary="Pontos ponderados para o mapa de calor de falhas ou furtos",
)
async def heatmap(
    service: OperationsServiceDep,
    kind: HeatmapKind = HeatmapKind.FALHAS,
    days: Annotated[int, Query(ge=1, le=365)] = 90,
) -> list[HeatPointOutput]:
    return [HeatPointOutput.model_validate(p) for p in await service.heatmap(kind, days)]


@router.get(
    "/trends",
    response_model=list[TrendPointOutput],
    summary="Falhas, reparos e tempo médio de reparo (MTTR) por dia",
)
async def trends(
    service: OperationsServiceDep, days: Annotated[int, Query(ge=2, le=90)] = 14
) -> list[TrendPointOutput]:
    return [TrendPointOutput.model_validate(p) for p in await service.trends(days)]


@router.get(
    "/dispatch-suggestions",
    response_model=list[DispatchSuggestionOutput],
    summary="Agentes livres mais próximos e aptos à ocorrência (KNN PostGIS)",
    responses=problems(404),
)
async def dispatch_suggestions(
    equipment_id: UUID, service: DispatchServiceDep
) -> list[DispatchSuggestionOutput]:
    suggestions = await service.suggestions(equipment_id)
    return [
        DispatchSuggestionOutput(
            agent_id=s.candidate.agent_id,
            full_name=s.candidate.full_name,
            role=s.candidate.role,
            organization_acronym=s.candidate.organization_acronym,
            duty_status=s.candidate.duty_status,
            location=GeoPointSchema.from_domain(s.candidate.location),
            distance_m=round(s.candidate.distance_m, 1),
            eta_minutes=s.eta_minutes,
            vehicle_type=s.candidate.vehicle_type,
            recommended=index == 0,
        )
        for index, s in enumerate(suggestions)
    ]
