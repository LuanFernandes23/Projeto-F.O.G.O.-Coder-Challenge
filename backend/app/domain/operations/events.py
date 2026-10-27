"""Eventos de domínio publicados em tempo real para a Central de Operações."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class EventType(StrEnum):
    EQUIPMENT_STATUS_CHANGED = "equipment.status_changed"
    EQUIPMENT_CONNECTIVITY = "equipment.connectivity"
    AGENTS_POSITIONS = "agents.positions"
    AGENT_STATUS_CHANGED = "agent.status_changed"
    ALERT_OPENED = "alert.opened"
    ALERT_UPDATED = "alert.updated"
    ALERT_RESOLVED = "alert.resolved"
    DISPATCH_UPDATED = "dispatch.updated"
    MAINTENANCE_ORDER_CHANGED = "maintenance.order_changed"
    # Parte 3
    FAULT_AVERTED = "fault.averted"
    ANOMALY_DETECTED = "anomaly.detected"
    PREDICTION_UPDATED = "prediction.updated"
    PROMETHEUS_DECISION = "prometheus.decision"


@dataclass(frozen=True, slots=True)
class DomainEvent:
    type: EventType
    data: dict[str, Any] = field(default_factory=dict)
