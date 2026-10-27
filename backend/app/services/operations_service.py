"""Consultas da Central de Operações: indicadores, mapa, regiões e análises."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from app.core.clock import Clock
from app.domain.equipment.status import EquipmentStatus
from app.domain.operations.read_models import (
    HeatPoint,
    MapAgentFeature,
    MapEquipmentFeature,
    OperationsOverview,
    TrendPoint,
)
from app.domain.operations.region_health import RegionHealth, compute_region_health
from app.services.ports import UnitOfWork


class HeatmapKind(StrEnum):
    FALHAS = "falhas"
    FURTOS = "furtos"


_HEATMAP_STATUSES = {
    HeatmapKind.FALHAS: (EquipmentStatus.MAU_FUNCIONAMENTO,),
    HeatmapKind.FURTOS: (EquipmentStatus.FURTADO,),
}


@dataclass(frozen=True, slots=True)
class MapSnapshot:
    generated_at: datetime
    equipment: list[MapEquipmentFeature]
    agents: list[MapAgentFeature]


class OperationsQueryService:
    def __init__(self, uow: UnitOfWork, clock: Clock, due_soon_days: int, timezone: str) -> None:
        self._uow = uow
        self._clock = clock
        self._due_soon_days = due_soon_days
        self._timezone = timezone

    async def overview(self) -> OperationsOverview:
        now, today = self._clock.now(), self._clock.today()
        async with self._uow as uow:
            ops = uow.operations
            return OperationsOverview(
                generated_at=now,
                by_status=await ops.status_counts(),
                connectivity=await ops.connectivity_counts(now),
                maintenance=await ops.maintenance_counts(today, self._due_soon_days),
                agents=await ops.agent_counts(),
                alerts=await ops.alert_counts(now),
                by_type=await ops.type_breakdown(),
            )

    async def map_snapshot(self) -> MapSnapshot:
        async with self._uow as uow:
            return MapSnapshot(
                generated_at=self._clock.now(),
                equipment=await uow.operations.map_equipment(),
                agents=await uow.operations.map_agents(),
            )

    async def regions(self) -> list[RegionHealth]:
        now, today = self._clock.now(), self._clock.today()
        async with self._uow as uow:
            metrics = await uow.operations.region_metrics(now, today)
        return sorted((compute_region_health(m) for m in metrics), key=lambda health: health.score)

    async def heatmap(self, kind: HeatmapKind, days: int) -> list[HeatPoint]:
        since = self._clock.now() - timedelta(days=days)
        async with self._uow as uow:
            return await uow.operations.heatmap(_HEATMAP_STATUSES[kind], since)

    async def trends(self, days: int) -> list[TrendPoint]:
        end = self._clock.today()
        start = end - timedelta(days=days - 1)
        async with self._uow as uow:
            return await uow.operations.trends(start, end, self._timezone)
