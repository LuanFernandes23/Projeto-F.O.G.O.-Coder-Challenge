"""Telemetria IoT e posição de agentes: regras de conectividade, amostragem e bateria."""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID

from app.domain.agents.entities import DutyStatus
from app.domain.equipment.status import EquipmentStatus
from app.domain.shared import GeoPoint

OFFLINE_AFTER = timedelta(minutes=5)
READING_SAMPLE_INTERVAL = timedelta(minutes=5)
POSITION_SAMPLE_INTERVAL = timedelta(minutes=2)
LOW_BATTERY_PCT = 15.0
BATTERY_RECOVERED_PCT = 25.0  # histerese: evita alerta "pisca-pisca" perto do limite

# Só faz sentido cobrar comunicação de quem deveria estar transmitindo.
CONNECTIVITY_MONITORED_STATUSES = frozenset(
    {EquipmentStatus.OPERACIONAL, EquipmentStatus.MAU_FUNCIONAMENTO}
)


class Connectivity(StrEnum):
    ONLINE = "online"
    OFFLINE = "offline"
    SEM_TELEMETRIA = "sem_telemetria"  # nunca reportou (ex.: recém-cadastrado)


@dataclass(frozen=True, slots=True)
class EquipmentHeartbeat:
    equipment_id: UUID
    recorded_at: datetime
    metrics: dict[str, Any] = field(default_factory=dict)
    fault: str | None = None  # descrição da falha autodetectada pelo dispositivo
    fault_averted: str | None = None  # falha iminente evitada por intervenção a tempo


@dataclass(frozen=True, slots=True)
class AgentPositionReport:
    agent_id: UUID
    recorded_at: datetime
    location: GeoPoint


@dataclass(frozen=True, slots=True)
class DeviceState:
    """Estado atual de um dispositivo, necessário para processar o heartbeat."""

    equipment_id: UUID
    type_code: str
    status: EquipmentStatus
    region_id: UUID | None
    region_code: str | None
    last_seen_at: datetime | None
    last_reading_at: datetime | None
    battery_pct: float | None


def connectivity(last_seen_at: datetime | None, now: datetime) -> Connectivity:
    if last_seen_at is None:
        return Connectivity.SEM_TELEMETRIA
    return Connectivity.ONLINE if now - last_seen_at <= OFFLINE_AFTER else Connectivity.OFFLINE


def should_sample(last_sample_at: datetime | None, now: datetime, interval: timedelta) -> bool:
    return last_sample_at is None or now - last_sample_at >= interval


def battery_of(metrics: Mapping[str, Any]) -> float | None:
    value = metrics.get("battery_pct")
    return float(value) if isinstance(value, int | float) else None


def battery_alert_change(previous: float | None, current: float | None) -> bool | None:
    """True = abrir alerta, False = resolver, None = nada muda (histerese)."""
    if current is None:
        return None
    if current < LOW_BATTERY_PCT:
        return True
    if current >= BATTERY_RECOVERED_PCT and (previous is None or previous < BATTERY_RECOVERED_PCT):
        return False
    return None


def distance_m(a: GeoPoint, b: GeoPoint) -> float:
    """Distância haversine em metros (suficiente para geofence de dezenas de metros)."""
    radius = 6_371_000.0
    lat1, lat2 = math.radians(a.latitude), math.radians(b.latitude)
    dlat = lat2 - lat1
    dlng = math.radians(b.longitude - a.longitude)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(h))


@dataclass(frozen=True, slots=True)
class RegistryDevice:
    equipment_id: UUID
    type_code: str
    status: EquipmentStatus
    location: GeoPoint
    region_code: str | None
    # Desde quando há intervenção em curso (OS preventiva aberta ou equipe no local).
    intervention_since: datetime | None = None


@dataclass(frozen=True, slots=True)
class RegistryAgent:
    agent_id: UUID
    duty_status: DutyStatus
    is_active: bool
    region_code: str | None
    base: GeoPoint
    current: GeoPoint | None
    vehicle_type: str | None
    dispatch_target: GeoPoint | None
