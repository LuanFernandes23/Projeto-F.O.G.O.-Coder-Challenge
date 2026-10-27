"""Casos de uso de alertas: consulta, reconhecimento, resolução e varredura periódica."""

import logging
from dataclasses import dataclass
from uuid import UUID

from app.core.clock import Clock
from app.core.exceptions import NotFoundError
from app.domain.operations.alerts import (
    AlertFilters,
    AlertKind,
    AlertSeverity,
    AlertStatus,
    AlertView,
    ensure_can_acknowledge,
    ensure_can_resolve,
    offline_severity,
    overdue_severity,
    sla_state,
)
from app.domain.operations.events import DomainEvent, EventType
from app.domain.operations.read_models import MonitoredDevice
from app.domain.operations.region_health import HealthLevel, compute_region_health
from app.domain.shared import Page, PageRequest
from app.services.alert_engine import AlertEngine, alert_event_data
from app.services.ports import UnitOfWork

logger = logging.getLogger(__name__)

ALERT_SWEEP_LOCK_KEY = 7_412_027


@dataclass(frozen=True, slots=True)
class SweepResult:
    opened_or_updated: int
    resolved: int


class AlertService:
    def __init__(self, uow: UnitOfWork, clock: Clock, engine: AlertEngine | None = None) -> None:
        self._uow = uow
        self._clock = clock
        self._engine = engine or AlertEngine()

    async def search(self, filters: AlertFilters, page: PageRequest) -> Page[AlertView]:
        now = self._clock.now()
        async with self._uow as uow:
            records = await uow.alerts.list_records(filters, page)
        return Page(
            [AlertView(r, sla_state(r.alert, now)) for r in records.items],
            records.total,
            page.limit,
            page.offset,
        )

    async def get(self, alert_id: UUID) -> AlertView:
        async with self._uow as uow:
            record = await uow.alerts.get_record(alert_id)
        if record is None:
            raise NotFoundError("Alerta não encontrado.")
        return AlertView(record, sla_state(record.alert, self._clock.now()))

    async def acknowledge(self, alert_id: UUID, actor_id: UUID) -> AlertView:
        now = self._clock.now()
        async with self._uow as uow:
            alert = await uow.alerts.get(alert_id, for_update=True)
            if alert is None:
                raise NotFoundError("Alerta não encontrado.")
            ensure_can_acknowledge(alert)
            alert.status = AlertStatus.RECONHECIDO
            alert.acknowledged_at = now
            alert.acknowledged_by = actor_id
            await uow.alerts.update(alert)
            await uow.events.publish(DomainEvent(EventType.ALERT_UPDATED, alert_event_data(alert)))
            await uow.commit()
        return await self.get(alert_id)

    async def resolve(self, alert_id: UUID, note: str, actor_id: UUID) -> AlertView:
        now = self._clock.now()
        async with self._uow as uow:
            alert = await uow.alerts.get(alert_id, for_update=True)
            if alert is None:
                raise NotFoundError("Alerta não encontrado.")
            ensure_can_resolve(alert)
            await self._engine.close(uow, alert, now=now, note=note, actor_id=actor_id)
            await uow.commit()
        return await self.get(alert_id)

    async def sweep(self, due_soon_days: int) -> SweepResult:
        """Varre a cidade: equipamentos sem comunicação, preventivas vencidas e regiões.

        Idempotente: reabrir um alerta já aberto não conta nova ocorrência.
        """
        now, today = self._clock.now(), self._clock.today()
        raised = resolved = 0
        async with self._uow as uow:
            if not await uow.job_locks.try_acquire(ALERT_SWEEP_LOCK_KEY):
                logger.warning("Varredura de alertas já em execução em outra instância")
                return SweepResult(0, 0)
            r1, s1 = await self._reconcile_devices(
                uow,
                AlertKind.EQUIPAMENTO_OFFLINE,
                await uow.operations.offline_devices(now),
                "Comunicação restabelecida ou fora de monitoramento.",
            )
            r2, s2 = await self._reconcile_devices(
                uow,
                AlertKind.MANUTENCAO_VENCIDA,
                await uow.operations.overdue_devices(today),
                "Manutenção em dia.",
            )
            r3, s3 = await self._reconcile_regions(uow)
            raised, resolved = r1 + r2 + r3, s1 + s2 + s3
            await uow.commit()
        return SweepResult(raised, resolved)

    async def _reconcile_devices(
        self,
        uow: UnitOfWork,
        kind: AlertKind,
        devices: list[MonitoredDevice],
        resolution_note: str,
    ) -> tuple[int, int]:
        now = self._clock.now()
        current = {d.equipment_id: d for d in devices}
        resolved = 0
        for alert in await uow.alerts.list_open_by_prefix(f"{kind.value}:"):
            if alert.equipment_id not in current:
                await self._engine.close(uow, alert, now=now, note=resolution_note)
                resolved += 1
        for device in devices:
            await self._engine.raise_alert(
                uow,
                kind=kind,
                subject_id=device.equipment_id,
                severity=self._device_severity(kind, device),
                title=await self._device_title(uow, kind, device),
                description=self._device_description(kind, device),
                now=now,
                equipment_id=device.equipment_id,
                region_id=device.region_id,
                count_occurrence=False,
            )
        return len(devices), resolved

    async def _reconcile_regions(self, uow: UnitOfWork) -> tuple[int, int]:
        now, today = self._clock.now(), self._clock.today()
        raised = resolved = 0
        for metrics in await uow.operations.region_metrics(now, today):
            health = compute_region_health(metrics)
            if health.level is HealthLevel.NORMAL:
                if await self._engine.resolve(
                    uow,
                    AlertKind.REGIAO_DEGRADADA,
                    metrics.region_id,
                    now=now,
                    note="Região voltou a operar normalmente.",
                ):
                    resolved += 1
                continue
            severity = (
                AlertSeverity.ALTA if health.level is HealthLevel.CRITICO else AlertSeverity.MEDIA
            )
            await self._engine.raise_alert(
                uow,
                kind=AlertKind.REGIAO_DEGRADADA,
                subject_id=metrics.region_id,
                severity=severity,
                title=f"{metrics.name}: índice de saúde {health.score:.0f}",
                description="; ".join(health.reasons),
                now=now,
                region_id=metrics.region_id,
                metadata={"score": health.score, "level": health.level.value},
                count_occurrence=False,
                follow_severity=True,
            )
            raised += 1
        return raised, resolved

    @staticmethod
    def _device_severity(kind: AlertKind, device: MonitoredDevice) -> AlertSeverity:
        if kind is AlertKind.EQUIPAMENTO_OFFLINE:
            return offline_severity(device.type_code, device.region_code)
        return overdue_severity(device.type_code)

    async def _device_title(self, uow: UnitOfWork, kind: AlertKind, device: MonitoredDevice) -> str:
        name = await self._engine.type_name(uow, device.type_code)
        suffix = (
            "sem comunicação" if kind is AlertKind.EQUIPAMENTO_OFFLINE else "com manutenção vencida"
        )
        return f"{name} {device.serial_number} {suffix}"

    @staticmethod
    def _device_description(kind: AlertKind, device: MonitoredDevice) -> str:
        if kind is AlertKind.EQUIPAMENTO_OFFLINE and device.reference_at:
            return f"Último contato em {device.reference_at.isoformat(timespec='minutes')}."
        if device.next_maintenance_date:
            return f"Manutenção prevista para {device.next_maintenance_date.isoformat()}."
        return "Sem informações adicionais."
