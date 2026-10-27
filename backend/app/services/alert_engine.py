"""Motor de alertas: abre, escala, atualiza e resolve alertas de forma idempotente.

Assim como ``EquipmentLifecycle``, não controla transação: roda dentro da unidade de
trabalho do caso de uso que detectou o evento (mudança de situação, telemetria, job).
"""

import uuid
from datetime import datetime
from typing import Any
from uuid import UUID

from app.domain.equipment.entities import Equipment
from app.domain.equipment.status import EquipmentStatus
from app.domain.operations.alerts import (
    Alert,
    AlertKind,
    AlertSeverity,
    AlertStatus,
    dedup_key,
    failure_severity,
    sla_due_at,
    theft_severity,
)
from app.domain.operations.events import DomainEvent, EventType
from app.services.ports import UnitOfWork

_EQUIPMENT_ALERT_KINDS = (
    AlertKind.FALHA_EQUIPAMENTO,
    AlertKind.FURTO,
    AlertKind.EQUIPAMENTO_OFFLINE,
    AlertKind.MANUTENCAO_VENCIDA,
    AlertKind.BATERIA_BAIXA,
)


def alert_event_data(alert: Alert) -> dict[str, Any]:
    return {
        "id": str(alert.id),
        "kind": alert.kind.value,
        "severity": alert.severity.value,
        "status": alert.status.value,
        "title": alert.title,
        "equipment_id": str(alert.equipment_id) if alert.equipment_id else None,
        "region_id": str(alert.region_id) if alert.region_id else None,
        "opened_at": alert.opened_at.isoformat(),
        "sla_due_at": alert.sla_due_at.isoformat(),
    }


class AlertEngine:
    def __init__(self) -> None:
        # Pequenos caches de referência (imutáveis durante a vida do serviço).
        self._type_names: dict[str, str] = {}
        self._region_codes: dict[UUID, str | None] = {}

    async def raise_alert(
        self,
        uow: UnitOfWork,
        *,
        kind: AlertKind,
        subject_id: UUID,
        severity: AlertSeverity,
        title: str,
        description: str,
        now: datetime,
        equipment_id: UUID | None = None,
        agent_id: UUID | None = None,
        region_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
        count_occurrence: bool = True,
        follow_severity: bool = False,
    ) -> Alert:
        """Abre o alerta ou atualiza o aberto equivalente (mesmo tipo e sujeito).

        ``follow_severity``: a criticidade acompanha o estado atual (pode cair); senão
        apenas escala, nunca rebaixa um alerta já aberto.
        """
        existing = await uow.alerts.get_open_by_dedup(dedup_key(kind, subject_id))
        if existing is None:
            alert = Alert(
                id=uuid.uuid4(),
                kind=kind,
                severity=severity,
                status=AlertStatus.ABERTO,
                title=title,
                description=description,
                dedup_key=dedup_key(kind, subject_id),
                opened_at=now,
                sla_due_at=sla_due_at(severity, now),
                last_occurrence_at=now,
                equipment_id=equipment_id,
                agent_id=agent_id,
                region_id=region_id,
                metadata=metadata or {},
            )
            await uow.alerts.add(alert)
            await uow.events.publish(DomainEvent(EventType.ALERT_OPENED, alert_event_data(alert)))
            return alert

        changed = self._apply_severity(existing, severity, follow_severity)
        if count_occurrence:
            existing.occurrences += 1
            existing.last_occurrence_at = now
            changed = True
        if existing.description != description or existing.title != title:
            existing.description = description
            existing.title = title
            changed = True
        if changed:
            await uow.alerts.update(existing)
            await uow.events.publish(
                DomainEvent(EventType.ALERT_UPDATED, alert_event_data(existing))
            )
        return existing

    async def resolve(
        self,
        uow: UnitOfWork,
        kind: AlertKind,
        subject_id: UUID,
        *,
        now: datetime,
        note: str,
        actor_id: UUID | None = None,
    ) -> bool:
        alert = await uow.alerts.get_open_by_dedup(dedup_key(kind, subject_id))
        if alert is None:
            return False
        await self.close(uow, alert, now=now, note=note, actor_id=actor_id)
        return True

    async def close(
        self,
        uow: UnitOfWork,
        alert: Alert,
        *,
        now: datetime,
        note: str,
        actor_id: UUID | None = None,
    ) -> None:
        alert.status = AlertStatus.RESOLVIDO
        alert.resolved_at = now
        alert.resolved_by = actor_id
        alert.resolution_note = note
        await uow.alerts.update(alert)
        await uow.events.publish(DomainEvent(EventType.ALERT_RESOLVED, alert_event_data(alert)))

    async def on_equipment_status_changed(
        self,
        uow: UnitOfWork,
        equipment: Equipment,
        previous: EquipmentStatus,
        *,
        reason: str,
        now: datetime,
    ) -> None:
        """Regras de alerta disparadas por mudança de situação do equipamento."""
        target = equipment.status
        resolve = self._resolver(uow, equipment.id, now)
        if target is EquipmentStatus.MAU_FUNCIONAMENTO:
            region_code = await self.region_code(uow, equipment.region_id)
            await self.raise_alert(
                uow,
                kind=AlertKind.FALHA_EQUIPAMENTO,
                subject_id=equipment.id,
                severity=failure_severity(equipment.type_code, region_code),
                title=await self._title(uow, equipment, "com falha"),
                description=reason,
                now=now,
                equipment_id=equipment.id,
                region_id=equipment.region_id,
            )
        elif target is EquipmentStatus.FURTADO:
            await resolve(AlertKind.FALHA_EQUIPAMENTO, "Substituído pelo alerta de furto.")
            await resolve(AlertKind.EQUIPAMENTO_OFFLINE, "Equipamento furtado.")
            await self.raise_alert(
                uow,
                kind=AlertKind.FURTO,
                subject_id=equipment.id,
                severity=theft_severity(equipment.type_code),
                title=await self._title(uow, equipment, "furtado"),
                description=reason,
                now=now,
                equipment_id=equipment.id,
                region_id=equipment.region_id,
            )
        elif target is EquipmentStatus.OPERACIONAL:
            await resolve(AlertKind.FALHA_EQUIPAMENTO, "Equipamento voltou a operar.")
        elif target is EquipmentStatus.EM_MANUTENCAO:
            # Em manutenção é esperado ficar sem comunicação; a falha segue aberta até o fim.
            await resolve(AlertKind.EQUIPAMENTO_OFFLINE, "Equipamento em manutenção.")
        elif target is EquipmentStatus.NAO_INSTALADO and previous is EquipmentStatus.FURTADO:
            await resolve(AlertKind.FURTO, "Equipamento recuperado.")
        elif target is EquipmentStatus.DESATIVADO:
            for kind in _EQUIPMENT_ALERT_KINDS:
                await resolve(kind, "Equipamento desativado.")

    async def region_code(self, uow: UnitOfWork, region_id: UUID | None) -> str | None:
        if region_id is None:
            return None
        if region_id not in self._region_codes:
            self._region_codes[region_id] = await uow.regions.code_of(region_id)
        return self._region_codes[region_id]

    async def type_name(self, uow: UnitOfWork, type_code: str) -> str:
        if type_code not in self._type_names:
            equipment_type = await uow.equipment_types.get(type_code)
            self._type_names[type_code] = equipment_type.name if equipment_type else type_code
        return self._type_names[type_code]

    async def _title(self, uow: UnitOfWork, equipment: Equipment, suffix: str) -> str:
        name = await self.type_name(uow, equipment.type_code)
        return f"{name} {equipment.serial_number} {suffix}"

    def _resolver(self, uow: UnitOfWork, equipment_id: UUID, now: datetime) -> Any:
        async def resolve(kind: AlertKind, note: str) -> None:
            await self.resolve(uow, kind, equipment_id, now=now, note=note)

        return resolve

    @staticmethod
    def _apply_severity(alert: Alert, severity: AlertSeverity, follow: bool) -> bool:
        if severity is alert.severity:
            return False
        if severity.rank < alert.severity.rank and not follow:
            return False
        alert.severity = severity
        alert.sla_due_at = sla_due_at(severity, alert.opened_at)
        return True
