"""Ferramentas do PROMETHEUS: as únicas ações que ele pode executar na cidade.

O LLM nunca chama nada direto: escolhe um ``ActionType`` da lista permitida pelo
procedimento e o código monta, valida e executa os parâmetros com os serviços existentes,
sempre com o usuário de sistema PROMETHEUS como autor (rastreável no histórico).
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.core.clock import Clock
from app.core.exceptions import AppError
from app.domain.maintenance.entities import MaintenanceKind, MaintenancePriority
from app.domain.operations.alerts import AlertKind, AlertSeverity
from app.domain.prometheus.entities import ActionType, Situation, SituationKind
from app.services.alert_engine import AlertEngine
from app.services.dispatch_service import DispatchService
from app.services.equipment_lifecycle import EquipmentLifecycle
from app.services.maintenance_service import MaintenanceService, NewMaintenanceOrder
from app.services.ports import UnitOfWork

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Validation:
    ok: bool
    params: dict[str, Any]
    message: str


def build_params(action: ActionType, situation: Situation) -> dict[str, Any]:
    """Parâmetros vêm da situação (dados reais), nunca de texto livre do LLM."""
    facts = situation.facts
    if action is ActionType.ABRIR_OS_PREVENTIVA:
        immediate = situation.kind is SituationKind.PRECURSOR_FALHA
        return {
            "equipment_id": str(situation.equipment_id) if situation.equipment_id else None,
            "priority": "imediata" if immediate else "agendada",
            "description": (f"PROMETHEUS: {situation.title}. {situation.summary}"[:480]),
        }
    if action is ActionType.DESPACHAR_INSPECAO:
        return {
            "equipment_id": str(situation.equipment_id or facts.get("hotspot_equipment_id") or "")
            or None,
            "notes": f"Inspeção preventiva (PROMETHEUS): {situation.title}"[:480],
        }
    if action is ActionType.ALERTA_PREVENTIVO:
        return {
            "equipment_id": str(situation.equipment_id) if situation.equipment_id else None,
            "region_id": str(situation.region_id) if situation.region_id else None,
            "title": situation.title[:200],
            "description": situation.summary[:1000],
        }
    return {  # REFORCAR_REGIAO
        "from_region": facts.get("from_region"),
        "to_region": facts.get("to_region") or situation.region_code,
        "agents": int(facts.get("agents", 1)),
        "hotspot_equipment_id": facts.get("hotspot_equipment_id"),
        "window": facts.get("window"),
    }


class ActionExecutor:
    def __init__(self, uow_factory: Callable[[], UnitOfWork], clock: Clock, actor_id: UUID) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._actor = actor_id

    async def validate(self, action: ActionType, params: dict[str, Any]) -> Validation:
        """Confere existência, estado e elegibilidade antes de executar (ou pedir aprovação)."""
        if action in (ActionType.ABRIR_OS_PREVENTIVA, ActionType.DESPACHAR_INSPECAO):
            equipment_id = params.get("equipment_id")
            if not equipment_id:
                return Validation(False, params, "A situação não aponta um equipamento.")
            async with self._uow_factory() as uow:
                equipment = await uow.equipment.get(UUID(equipment_id))
            if equipment is None:
                return Validation(False, params, "Equipamento não encontrado.")
            if action is ActionType.ABRIR_OS_PREVENTIVA and equipment.status.value not in (
                "operacional",
                "mau_funcionamento",
            ):
                return Validation(
                    False, params, f"Equipamento está '{equipment.status.value}': OS não se aplica."
                )
            if action is ActionType.DESPACHAR_INSPECAO:
                suggestions = await self._dispatch().suggestions(UUID(equipment_id))
                if not suggestions:
                    return Validation(False, params, "Nenhum agente apto e livre por perto.")
                best = suggestions[0]
                params = {
                    **params,
                    "agent_id": str(best.candidate.agent_id),
                    "agent_name": best.candidate.full_name,
                    "eta_minutes": round(best.eta_minutes, 1),
                }
            return Validation(True, params, "ok")
        if action is ActionType.ALERTA_PREVENTIVO:
            if not params.get("equipment_id") and not params.get("region_id"):
                return Validation(False, params, "Alerta sem equipamento nem região.")
            return Validation(True, params, "ok")
        if not params.get("from_region") or not params.get("to_region"):
            return Validation(False, params, "Remanejamento sem regiões de origem e destino.")
        if not params.get("hotspot_equipment_id"):
            async with self._uow_factory() as uow:
                devices = await uow.predictions.devices_now(self._clock.today())
            target = next((d for d in devices if d["region"] == params["to_region"]), None)
            if target is None:
                return Validation(False, params, "Sem ponto de referência na região de destino.")
            params = {**params, "hotspot_equipment_id": str(target["id"])}
        return Validation(True, params, "ok")

    async def execute(self, action: ActionType, params: dict[str, Any]) -> dict[str, Any]:
        try:
            if action is ActionType.ABRIR_OS_PREVENTIVA:
                return await self._open_order(params)
            if action is ActionType.DESPACHAR_INSPECAO:
                return await self._dispatch_inspection(params)
            if action is ActionType.ALERTA_PREVENTIVO:
                return await self._preventive_alert(params)
            return await self._reinforce(params)
        except AppError as exc:
            # Ex.: já existe OS aberta (conflito) — vira resultado legível, não exceção.
            return {"ok": False, "message": exc.detail}
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("Parâmetros inválidos na execução", extra={"action": action.value})
            return {"ok": False, "message": f"Parâmetros inválidos ({type(exc).__name__})."}

    def _dispatch(self) -> DispatchService:
        return DispatchService(self._uow_factory(), self._clock)

    async def _open_order(self, params: dict[str, Any]) -> dict[str, Any]:
        service = MaintenanceService(self._uow_factory(), self._clock, EquipmentLifecycle())
        priority = MaintenancePriority(params.get("priority", "imediata"))
        order = await service.open_order(
            UUID(params["equipment_id"]),
            NewMaintenanceOrder(
                kind=MaintenanceKind.PREVENTIVA,
                priority=priority,
                description=params["description"],
                scheduled_for=None,
            ),
            self._actor,
        )
        return {
            "ok": True,
            "message": f"OS preventiva ({priority.value}) aberta.",
            "order_id": str(order.id),
        }

    async def _dispatch_inspection(self, params: dict[str, Any]) -> dict[str, Any]:
        record = await self._dispatch().create(
            UUID(params["equipment_id"]), UUID(params["agent_id"]), params["notes"], self._actor
        )
        return {
            "ok": True,
            "message": f"{params.get('agent_name', 'Agente')} despachado(a) para inspeção.",
            "dispatch_id": str(record.dispatch.id),
        }

    async def _preventive_alert(self, params: dict[str, Any]) -> dict[str, Any]:
        engine = AlertEngine()
        subject = UUID(params.get("equipment_id") or params["region_id"])
        async with self._uow_factory() as uow:
            alert = await engine.raise_alert(
                uow,
                kind=AlertKind.PREVISAO_RISCO,
                subject_id=subject,
                severity=AlertSeverity.MEDIA,
                title=params["title"],
                description=params["description"],
                now=self._clock.now(),
                equipment_id=UUID(params["equipment_id"]) if params.get("equipment_id") else None,
                region_id=UUID(params["region_id"]) if params.get("region_id") else None,
                metadata={"source": "prometheus"},
                count_occurrence=False,
            )
            await uow.commit()
        return {"ok": True, "message": "Alerta preventivo emitido.", "alert_id": str(alert.id)}

    async def _reinforce(self, params: dict[str, Any]) -> dict[str, Any]:
        """Desloca agentes livres da região com sobra para o ponto crítico da região alvo."""
        hotspot = UUID(params["hotspot_equipment_id"])
        suggestions = await self._dispatch().suggestions(hotspot)
        sent: list[str] = []
        for suggestion in suggestions:
            if len(sent) >= int(params.get("agents", 1)):
                break
            try:
                await self._dispatch().create(
                    hotspot,
                    suggestion.candidate.agent_id,
                    f"Reforço preventivo para {params['to_region']} (PROMETHEUS)",
                    self._actor,
                )
                sent.append(suggestion.candidate.full_name)
            except AppError:
                continue
        if not sent:
            return {"ok": False, "message": "Nenhum agente disponível para o reforço."}
        return {
            "ok": True,
            "message": f"{len(sent)} agente(s) deslocado(s) para {params['to_region']}.",
            "agents": sent,
        }
