"""Processo agendador (serviço ``scheduler`` do compose), separado da API.

Uso: ``python -m app.jobs.scheduler``.
"""

import asyncio
import logging
import signal
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.base import BaseTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.runtime import PrometheusRuntime, build_runtime
from app.core.clock import SystemClock
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.database.engine import create_engine, create_session_factory
from app.jobs.runner import (
    ALERT_SWEEP_JOB,
    ANOMALY_SCAN_JOB,
    APPROVAL_EXPIRY_JOB,
    MODEL_FIT_JOB,
    PREDICTION_REFRESH_JOB,
    PREVENTIVE_JOB,
    PROMETHEUS_CYCLE_JOB,
    TELEMETRY_RETENTION_JOB,
    ScheduledJob,
)
from app.repositories.unit_of_work import SqlAlchemyUnitOfWork
from app.services.alert_service import AlertService
from app.services.equipment_lifecycle import EquipmentLifecycle
from app.services.maintenance_service import MaintenanceService
from app.services.prediction_service import PredictionService

logger = logging.getLogger("app.scheduler")


@dataclass(frozen=True, slots=True)
class Schedule:
    job: ScheduledJob
    trigger: BaseTrigger
    first_run: datetime | None = None


def build_jobs(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    runtime: PrometheusRuntime,
) -> list[ScheduledJob]:
    clock = SystemClock(settings.tz)

    def uow() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory)

    async def preventive() -> dict[str, Any]:
        service = MaintenanceService(uow(), clock, EquipmentLifecycle())
        return {"orders_opened": await service.open_due_preventive_orders()}

    async def sweep() -> dict[str, Any]:
        result = await AlertService(uow(), clock).sweep(settings.maintenance_due_soon_days)
        return {"alerts_raised": result.opened_or_updated, "alerts_resolved": result.resolved}

    async def retention() -> dict[str, Any]:
        cutoff = clock.now() - timedelta(days=settings.telemetry_retention_days)
        async with uow() as work:
            removed = await work.telemetry.purge_older_than(cutoff)
            await work.commit()
        return {"rows_removed": removed}

    def predictions() -> PredictionService:
        return PredictionService(uow(), clock, settings.tz)

    async def model_fit() -> dict[str, Any]:
        result = await predictions().fit_models()
        if result.get("skipped"):
            return result
        await predictions().refresh()
        backtest = result["backtest"]
        return {
            "model_id": result["model_id"],
            "skill_vs_mean": backtest["skill_vs_mean"],
            "top20_capture": backtest["top20_capture"],
        }

    async def refresh() -> dict[str, Any]:
        payload = await predictions().refresh()
        return {"cells": len(payload.get("cells", []))}

    async def anomalies() -> dict[str, Any]:
        return await predictions().scan_anomalies()

    async def prometheus() -> dict[str, Any]:
        return await runtime.service.cycle()

    async def expiry() -> dict[str, Any]:
        return {"expired": await runtime.service.expire_pending()}

    timeout = settings.job_timeout_seconds
    return [
        ScheduledJob(PREVENTIVE_JOB, preventive, timeout),
        ScheduledJob(ALERT_SWEEP_JOB, sweep, timeout),
        ScheduledJob(TELEMETRY_RETENTION_JOB, retention, timeout),
        ScheduledJob(MODEL_FIT_JOB, model_fit, timeout),
        ScheduledJob(PREDICTION_REFRESH_JOB, refresh, timeout),
        ScheduledJob(ANOMALY_SCAN_JOB, anomalies, timeout),
        ScheduledJob(PROMETHEUS_CYCLE_JOB, prometheus, timeout),
        ScheduledJob(APPROVAL_EXPIRY_JOB, expiry, timeout),
    ]


def build_schedule(settings: Settings, jobs: list[ScheduledJob]) -> list[Schedule]:
    now = datetime.now(settings.tz)
    tz = settings.tz
    by_name = {job.name: job for job in jobs}
    return [
        Schedule(
            by_name[PREVENTIVE_JOB],
            CronTrigger(hour=settings.preventive_job_hour, minute=0, timezone=tz),
            now,  # roda também ao subir
        ),
        Schedule(
            by_name[ALERT_SWEEP_JOB],
            IntervalTrigger(seconds=settings.alert_sweep_interval_seconds),
            now + timedelta(seconds=20),
        ),
        Schedule(by_name[TELEMETRY_RETENTION_JOB], CronTrigger(hour=4, minute=30, timezone=tz)),
        # Ajuste diário dos modelos (madrugada) e também ao subir: previsões prontas logo.
        Schedule(
            by_name[MODEL_FIT_JOB],
            CronTrigger(hour=2, minute=30, timezone=tz),
            now + timedelta(seconds=5),
        ),
        Schedule(
            by_name[PREDICTION_REFRESH_JOB],
            IntervalTrigger(minutes=settings.prediction_refresh_minutes),
            now + timedelta(minutes=settings.prediction_refresh_minutes),
        ),
        Schedule(
            by_name[ANOMALY_SCAN_JOB],
            IntervalTrigger(seconds=settings.anomaly_scan_seconds),
            now + timedelta(seconds=45),
        ),
        Schedule(
            by_name[PROMETHEUS_CYCLE_JOB],
            IntervalTrigger(seconds=settings.prometheus_cycle_seconds),
            now + timedelta(seconds=75),
        ),
        Schedule(by_name[APPROVAL_EXPIRY_JOB], IntervalTrigger(seconds=60)),
    ]


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    runtime = await build_runtime(session_factory, SystemClock(settings.tz), settings)
    schedule = build_schedule(settings, build_jobs(settings, session_factory, runtime))
    common: dict[str, Any] = {"max_instances": 1, "coalesce": True, "misfire_grace_time": 3600}

    scheduler = AsyncIOScheduler(timezone=settings.tz)
    for item in schedule:
        # Sem ``next_run_time`` o job segue o gatilho (passar None deixaria o job pausado).
        first = {"next_run_time": item.first_run} if item.first_run else {}
        scheduler.add_job(item.job.run, item.trigger, id=item.job.name, **common, **first)
    scheduler.start()
    logger.info("Scheduler iniciado", extra={"jobs": [item.job.name for item in schedule]})

    stop = asyncio.Event()
    if sys.platform != "win32":
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)
    try:
        await stop.wait()
    finally:
        scheduler.shutdown(wait=False)
        await runtime.close()
        await engine.dispose()
        logger.info("Scheduler finalizado")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
