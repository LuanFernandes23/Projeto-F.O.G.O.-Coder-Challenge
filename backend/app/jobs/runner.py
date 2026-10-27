"""Execução padronizada dos jobs: nome, logs de início/fim, timeout e isolamento de falhas."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

PREVENTIVE_JOB = "preventive_maintenance_orders"
ALERT_SWEEP_JOB = "alert_sweep"
TELEMETRY_RETENTION_JOB = "telemetry_retention"
MODEL_FIT_JOB = "prediction_model_fit"
PREDICTION_REFRESH_JOB = "prediction_refresh"
ANOMALY_SCAN_JOB = "anomaly_scan"
PROMETHEUS_CYCLE_JOB = "prometheus_cycle"
APPROVAL_EXPIRY_JOB = "prometheus_approval_expiry"


class ScheduledJob:
    def __init__(
        self,
        name: str,
        action: Callable[[], Awaitable[dict[str, Any]]],
        timeout_seconds: float,
    ) -> None:
        self.name = name
        self._action = action
        self._timeout_seconds = timeout_seconds

    async def run(self) -> None:
        started = time.perf_counter()
        logger.info("Job iniciado", extra={"job": self.name})
        try:
            async with asyncio.timeout(self._timeout_seconds):
                result = await self._action()
        except TimeoutError:
            logger.error("Job excedeu o tempo máximo", extra={"job": self.name})
            return
        except Exception:
            # Um job nunca deve derrubar o scheduler: registra com contexto e segue.
            logger.exception("Job falhou", extra={"job": self.name})
            return
        logger.info(
            "Job finalizado",
            extra={
                "job": self.name,
                **result,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )
