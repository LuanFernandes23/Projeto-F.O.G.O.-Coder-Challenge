"""Ingestão de telemetria IoT e GPS: o ponto em que a cidade "fala" com o PROMETHEUS."""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.core.clock import Clock
from app.domain.equipment.status import EquipmentStatus
from app.domain.operations.alerts import AlertKind, AlertSeverity
from app.domain.operations.dispatch import (
    ARRIVAL_RADIUS_M,
    DEPARTURE_THRESHOLD_M,
    DispatchStatus,
)
from app.domain.operations.events import DomainEvent, EventType
from app.domain.operations.telemetry import (
    POSITION_SAMPLE_INTERVAL,
    READING_SAMPLE_INTERVAL,
    AgentPositionReport,
    Connectivity,
    DeviceState,
    EquipmentHeartbeat,
    RegistryAgent,
    RegistryDevice,
    battery_alert_change,
    battery_of,
    connectivity,
    distance_m,
    should_sample,
)
from app.services.alert_engine import AlertEngine
from app.services.equipment_lifecycle import EquipmentLifecycle
from app.services.ports import UnitOfWork
from app.services.prediction_service import on_averted, on_fault

logger = logging.getLogger(__name__)

_POSITIONS_PER_EVENT = 50  # mantém cada NOTIFY bem abaixo de 8 KB


@dataclass(frozen=True, slots=True)
class IngestResult:
    accepted: int
    unknown: int
    faults_registered: int = 0
    arrivals: int = 0


@dataclass(frozen=True, slots=True)
class Registry:
    devices: list[RegistryDevice]
    agents: list[RegistryAgent]


class TelemetryService:
    def __init__(self, uow: UnitOfWork, clock: Clock, lifecycle: EquipmentLifecycle) -> None:
        self._uow = uow
        self._clock = clock
        self._lifecycle = lifecycle
        self._engine = AlertEngine()

    async def registry(self) -> Registry:
        async with self._uow as uow:
            return Registry(
                await uow.telemetry.registry_devices(), await uow.telemetry.registry_agents()
            )

    async def ingest_equipment(self, heartbeats: list[EquipmentHeartbeat]) -> IngestResult:
        now, today = self._clock.now(), self._clock.today()
        async with self._uow as uow:
            states = {
                s.equipment_id: s
                for s in await uow.telemetry.device_states([h.equipment_id for h in heartbeats])
            }
            accepted = [h for h in heartbeats if h.equipment_id in states]
            rows: list[dict[str, Any]] = []
            readings: list[tuple[Any, datetime, dict[str, Any]]] = []
            for beat in accepted:
                state = states[beat.equipment_id]
                seen_at = min(beat.recorded_at, now)  # relógio do dispositivo adiantado
                rows.append(
                    {
                        "id": beat.equipment_id,
                        "last_seen_at": seen_at,
                        "last_telemetry": beat.metrics,
                    }
                )
                if should_sample(state.last_reading_at, seen_at, READING_SAMPLE_INTERVAL):
                    readings.append((beat.equipment_id, seen_at, beat.metrics))
            await uow.telemetry.record_heartbeats(rows)
            await uow.telemetry.add_readings(readings)

            for beat in accepted:
                state = states[beat.equipment_id]
                await self._handle_reconnection(uow, state, now)
                await self._handle_battery(uow, state, beat, now)

            faults = 0
            for beat in accepted:
                if beat.fault and states[beat.equipment_id].status is EquipmentStatus.OPERACIONAL:
                    await self._register_fault(uow, beat, now, today)
                    await on_fault(uow, self._engine, beat.equipment_id, now)
                    faults += 1
                elif beat.fault_averted:
                    await on_averted(uow, self._engine, beat.equipment_id, beat.fault_averted, now)
            await uow.commit()
        if faults:
            logger.info("Falhas reportadas por dispositivos", extra={"faults": faults})
        return IngestResult(
            len(accepted), len(heartbeats) - len(accepted), faults_registered=faults
        )

    async def ingest_agent_positions(self, reports: list[AgentPositionReport]) -> IngestResult:
        now = self._clock.now()
        async with self._uow as uow:
            known = await uow.telemetry.known_agent_ids([r.agent_id for r in reports])
            valid = [r for r in reports if r.agent_id in known]
            rows = [(r.agent_id, min(r.recorded_at, now), r.location) for r in valid]
            await uow.telemetry.update_agent_positions(rows)

            sampled = await uow.telemetry.last_sampled_positions(
                [r.agent_id for r in valid], since=now - 2 * POSITION_SAMPLE_INTERVAL
            )
            await uow.telemetry.add_agent_positions(
                [
                    row
                    for row in rows
                    if should_sample(sampled.get(row[0]), row[1], POSITION_SAMPLE_INTERVAL)
                ]
            )
            arrivals = await self._track_dispatches(uow, valid, now)
            for start in range(0, len(valid), _POSITIONS_PER_EVENT):
                chunk = valid[start : start + _POSITIONS_PER_EVENT]
                await uow.events.publish(
                    DomainEvent(
                        EventType.AGENTS_POSITIONS,
                        {
                            "positions": [
                                {
                                    "id": str(r.agent_id),
                                    "lat": round(r.location.latitude, 6),
                                    "lng": round(r.location.longitude, 6),
                                }
                                for r in chunk
                            ]
                        },
                    )
                )
            await uow.commit()
        return IngestResult(len(valid), len(reports) - len(valid), arrivals=arrivals)

    async def _handle_reconnection(
        self, uow: UnitOfWork, state: DeviceState, now: datetime
    ) -> None:
        if connectivity(state.last_seen_at, now) is Connectivity.ONLINE:
            return
        resolved = await self._lifecycle.alerts.resolve(
            uow,
            AlertKind.EQUIPAMENTO_OFFLINE,
            state.equipment_id,
            now=now,
            note="Comunicação restabelecida.",
        )
        await uow.events.publish(
            DomainEvent(
                EventType.EQUIPMENT_CONNECTIVITY,
                {
                    "id": str(state.equipment_id),
                    "connectivity": Connectivity.ONLINE.value,
                    "alert_resolved": resolved,
                },
            )
        )

    async def _handle_battery(
        self, uow: UnitOfWork, state: DeviceState, beat: EquipmentHeartbeat, now: datetime
    ) -> None:
        current = battery_of(beat.metrics)
        change = battery_alert_change(state.battery_pct, current)
        if change is None:
            return
        if change is False:
            await self._lifecycle.alerts.resolve(
                uow,
                AlertKind.BATERIA_BAIXA,
                state.equipment_id,
                now=now,
                note="Bateria recarregada.",
            )
            return
        name = await self._lifecycle.alerts.type_name(uow, state.type_code)
        await self._lifecycle.alerts.raise_alert(
            uow,
            kind=AlertKind.BATERIA_BAIXA,
            subject_id=state.equipment_id,
            severity=AlertSeverity.BAIXA,
            title=f"{name} com bateria baixa",
            description=f"Bateria em {current:.0f}%.",
            now=now,
            equipment_id=state.equipment_id,
            region_id=state.region_id,
            count_occurrence=False,
        )

    async def _register_fault(
        self, uow: UnitOfWork, beat: EquipmentHeartbeat, now: datetime, today: Any
    ) -> None:
        equipment = await uow.equipment.get(beat.equipment_id, for_update=True)
        if equipment is None or equipment.status is not EquipmentStatus.OPERACIONAL:
            return
        await self._lifecycle.change_status(
            uow,
            equipment,
            EquipmentStatus.MAU_FUNCIONAMENTO,
            reason=f"Falha reportada pelo dispositivo: {beat.fault}",
            actor_id=None,
            now=now,
            today=today,
        )
        await self._lifecycle.refresh_and_save(uow, equipment)

    @staticmethod
    async def _track_dispatches(
        uow: UnitOfWork, reports: list[AgentPositionReport], now: datetime
    ) -> int:
        """Geofence: detecta saída e chegada das equipes despachadas."""
        by_agent = {r.agent_id: r for r in reports}
        arrivals = 0
        for dispatch in await uow.dispatches.list_active():
            report = by_agent.get(dispatch.agent_id)
            if report is None or dispatch.status is DispatchStatus.NO_LOCAL:
                continue
            changed = False
            if (
                dispatch.status is DispatchStatus.DESIGNADO
                and distance_m(report.location, dispatch.origin) > DEPARTURE_THRESHOLD_M
            ):
                dispatch.status = DispatchStatus.A_CAMINHO
                dispatch.departed_at = now
                changed = True
            if distance_m(report.location, dispatch.target) <= ARRIVAL_RADIUS_M:
                dispatch.status = DispatchStatus.NO_LOCAL
                dispatch.arrived_at = now
                arrivals += 1
                changed = True
            if changed:
                await uow.dispatches.update(dispatch)
                await uow.events.publish(
                    DomainEvent(
                        EventType.DISPATCH_UPDATED,
                        {
                            "id": str(dispatch.id),
                            "status": dispatch.status.value,
                            "agent_id": str(dispatch.agent_id),
                        },
                    )
                )
        return arrivals
