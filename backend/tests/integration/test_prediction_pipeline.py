"""Pipeline preditivo no PostgreSQL real: ajuste, previsão e varredura sem quebrar."""

from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import SystemClock
from app.repositories.unit_of_work import SqlAlchemyUnitOfWork
from app.seed.marilia_data import REGIONS, region_geojson
from app.services.prediction_service import SNAPSHOT_CITY, PredictionService

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_database")]

TZ = ZoneInfo("America/Sao_Paulo")


async def test_fit_refresh_and_scan_produce_snapshots(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        for region in REGIONS:
            await uow.regions.add(region.code, region.name, region_geojson(region))
        await uow.commit()

    def service() -> PredictionService:
        return PredictionService(SqlAlchemyUnitOfWork(session_factory), SystemClock(TZ), TZ)

    fitted = await service().fit_models()
    assert fitted["model_id"] > 0
    assert "calibration" in fitted["backtest"]

    payload = await service().refresh()
    assert len(payload["cells"]) == len(REGIONS) * 24 * 7
    assert len(payload["reinforcement"]) == 3
    assert payload["backtest"]["test_days"] == 56

    scan = await service().scan_anomalies()
    assert scan["devices"] == 0

    stored = await service().snapshot(SNAPSHOT_CITY)
    assert stored is not None
    assert stored["model"]["id"] == fitted["model_id"]
