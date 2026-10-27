"""Simulação da vida de um equipamento (cadastro, instalação, falhas, reparos, preventivas,
furtos), sempre através dos serviços da aplicação com relógio controlado."""

import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import ManualClock
from app.core.config import Settings
from app.domain.equipment.status import EquipmentStatus
from app.domain.maintenance.entities import (
    MaintenanceKind,
    MaintenanceOrderStatus,
    MaintenancePriority,
)
from app.domain.shared import PageRequest
from app.repositories.unit_of_work import SqlAlchemyUnitOfWork
from app.seed.city_patterns import MAX_INTENSITY, CityEvent, intensity
from app.seed.generators import EquipmentSpec
from app.services.equipment_lifecycle import EquipmentLifecycle
from app.services.equipment_service import EquipmentService, NewEquipment
from app.services.maintenance_service import MaintenanceService, NewMaintenanceOrder

SEED = 2026
# Densidade do histórico: ~3x a taxa nominal de falhas do tipo, para o motor preditivo ter
# eventos suficientes para separar hora, dia da semana, estação e eventos (≈1.500/ano).
HISTORY_RATE_BOOST = 3.0
# Preventiva vencida aumenta a chance de falha; a frota de patinetes envelhece ao longo do ano.
OVERDUE_FAILURE_FACTOR = 1.8
AGING_TYPES = frozenset({"patinete"})

_FAILURE_REASONS = {
    "camera": (
        "Sem imagem: falha na fonte",
        "Lente danificada por vandalismo",
        "Perda de conexão com a central",
        "Infiltração de água no invólucro",
    ),
    "radar": (
        "Falha no laço indutivo",
        "Câmera OCR sem leitura de placas",
        "Sem comunicação com a central",
    ),
    "semaforo": (
        "Lâmpada queimada no grupo focal",
        "Controlador em amarelo intermitente",
        "Queda de energia sem nobreak",
    ),
    "totem_estacionamento": (
        "Impressora travada",
        "Leitor de cartão inoperante",
        "Tela danificada",
    ),
    "patinete": ("Bateria não carrega", "Pneu furado", "Rastreador GPS sem sinal"),
}
_GENERIC_FAILURES = ("Falha reportada pela telemetria", "Equipamento sem resposta (offline)")


@dataclass(frozen=True, slots=True)
class SimulatedEquipment:
    spec: EquipmentSpec
    equipment_id: UUID
    final_status: EquipmentStatus


class EquipmentSimulation:
    """Vive a história de um equipamento do cadastro até ``end``."""

    def __init__(
        self,
        spec: EquipmentSpec,
        organization_id: UUID,
        actor_id: UUID,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        start: datetime,
        end: datetime,
        events: list[CityEvent],
    ) -> None:
        self._spec = spec
        self._events = events
        self._organization_id = organization_id
        self._actor = actor_id
        self._end = end
        self._rng = random.Random(SEED * 10_000 + spec.index)
        self._tz: ZoneInfo = settings.tz
        self._clock = ManualClock(start + timedelta(days=self._rng.uniform(0, 150)), self._tz)
        lifecycle = EquipmentLifecycle()
        self._equipment = EquipmentService(
            SqlAlchemyUnitOfWork(session_factory),
            self._clock,
            lifecycle,
            settings.maintenance_due_soon_days,
        )
        self._maintenance = MaintenanceService(
            SqlAlchemyUnitOfWork(session_factory), self._clock, lifecycle
        )
        self._status = EquipmentStatus.NAO_INSTALADO
        self._id: UUID | None = None
        self._start = start
        self._overdue_until: datetime | None = None

    async def run(self) -> SimulatedEquipment:
        never_installed = self._rng.random() < 0.04
        if never_installed:
            self._clock.set(self._end - timedelta(days=self._rng.uniform(1, 25)))
        await self._create()
        if not never_installed:
            await self._lifecycle_loop()
        return SimulatedEquipment(self._spec, self._require_id(), self._status)

    async def _create(self) -> None:
        spec = self._spec
        view = await self._equipment.create(
            NewEquipment(
                type_code=spec.type_code,
                serial_number=spec.serial_number,
                brand=spec.brand,
                model=spec.model,
                organization_id=self._organization_id,
                status=EquipmentStatus.NAO_INSTALADO,
                installed_on=None,
                address=spec.placement.address,
                location=spec.placement.location,
                attributes=spec.attributes,
                maintenance_plan=None,
            ),
            actor_id=self._actor,
        )
        self._id = view.record.equipment.id

    async def _lifecycle_loop(self) -> None:
        spec = self._spec
        self._clock.advance(timedelta(days=self._rng.uniform(2, 20)))
        if self._clock.now() >= self._end:
            return
        await self._set_status(EquipmentStatus.OPERACIONAL, "Instalação concluída e testada")

        next_preventive: datetime | None = None
        if spec.plan_interval_days:
            plan = await self._maintenance.set_plan(
                self._require_id(), spec.plan_interval_days, None
            )
            next_preventive = self._at_local(plan.next_due_date, hour=9)
        theft_at = self._maybe(spec.theft_probability, self._clock.now(), pattern="patinete")
        retire_at = self._maybe(0.02, self._clock.now())

        while True:
            failure_at = self._next_failure_time()
            candidates = [
                (failure_at, "failure"),
                (next_preventive, "preventive"),
                (theft_at, "theft"),
                (retire_at, "retire"),
            ]
            moment, event = min(
                ((m, e) for m, e in candidates if m is not None), key=lambda item: item[0]
            )
            if moment >= self._end:
                return
            self._clock.set(moment)
            if event == "failure":
                if not await self._failure_and_repair():
                    return
            elif event == "preventive":
                next_preventive = await self._preventive()
            elif event == "theft":
                if not await self._theft():
                    return
                theft_at = None
            else:
                await self._set_status(
                    EquipmentStatus.DESATIVADO, "Desativado para substituição por modelo novo"
                )
                return

    async def _failure_and_repair(self) -> bool:
        reasons = _FAILURE_REASONS.get(self._spec.type_code, _GENERIC_FAILURES)
        await self._set_status(EquipmentStatus.MAU_FUNCIONAMENTO, self._rng.choice(reasons))
        risk = self._spec.placement.region.risk_factor
        if not await self._advance(timedelta(days=self._rng.uniform(0.2, 6) * risk)):
            return False
        order_id = await self._open_order_id(MaintenanceKind.CORRETIVA)
        await self._maintenance.transition_order(
            order_id, MaintenanceOrderStatus.EM_ANDAMENTO, None, self._actor
        )
        self._status = EquipmentStatus.EM_MANUTENCAO
        waits_for_parts = self._rng.random() < 0.45
        repair = (
            timedelta(days=self._rng.uniform(1, 14))
            if waits_for_parts
            else timedelta(hours=self._rng.uniform(2, 12))
        )
        if not await self._advance(repair):
            return False
        notes = (
            "Peça substituída após aguardar fornecedor" if waits_for_parts else "Reparo em campo"
        )
        await self._maintenance.transition_order(
            order_id, MaintenanceOrderStatus.CONCLUIDA, notes, self._actor
        )
        self._status = EquipmentStatus.OPERACIONAL
        return True

    async def _preventive(self) -> datetime | None:
        if self._rng.random() < 0.15:  # equipe atrasou a preventiva: fica vencida por um tempo
            self._overdue_until = self._clock.now() + timedelta(days=self._rng.uniform(3, 45))
            return self._overdue_until
        today = self._clock.today()
        order = await self._maintenance.open_order(
            self._require_id(),
            NewMaintenanceOrder(
                kind=MaintenanceKind.PREVENTIVA,
                priority=MaintenancePriority.AGENDADA,
                description="Manutenção preventiva periódica",
                scheduled_for=today,
            ),
            self._actor,
        )
        if not await self._advance(timedelta(hours=self._rng.uniform(1, 6))):
            return None
        await self._maintenance.transition_order(
            order.id, MaintenanceOrderStatus.EM_ANDAMENTO, None, self._actor
        )
        self._status = EquipmentStatus.EM_MANUTENCAO
        if not await self._advance(timedelta(hours=self._rng.uniform(1, 4))):
            return None
        await self._maintenance.transition_order(
            order.id, MaintenanceOrderStatus.CONCLUIDA, "Limpeza, aferição e testes", self._actor
        )
        self._status = EquipmentStatus.OPERACIONAL
        interval = self._spec.plan_interval_days or 0
        return self._at_local(self._clock.today() + timedelta(days=interval), hour=9)

    async def _theft(self) -> bool:
        await self._set_status(
            EquipmentStatus.FURTADO, f"Furto registrado (B.O. nº {self._rng.randint(1000, 9999)})"
        )
        if self._rng.random() >= 0.4:
            return False
        if not await self._advance(timedelta(days=self._rng.uniform(3, 30))):
            return False
        await self._set_status(EquipmentStatus.NAO_INSTALADO, "Recuperado pela Guarda Municipal")
        if not await self._advance(timedelta(days=self._rng.uniform(2, 10))):
            return False
        await self._set_status(EquipmentStatus.OPERACIONAL, "Reinstalado após recuperação")
        return True

    async def _set_status(self, target: EquipmentStatus, reason: str) -> None:
        await self._equipment.change_status(self._require_id(), target, reason, self._actor)
        self._status = target

    async def _open_order_id(self, kind: MaintenanceKind) -> UUID:
        orders = await self._maintenance.list_orders(
            self._require_id(), [MaintenanceOrderStatus.ABERTA], PageRequest(10, 0)
        )
        return next(o.id for o in orders.items if o.kind is kind)

    async def _advance(self, delta: timedelta) -> bool:
        target = self._clock.now() + delta
        if target >= self._end:
            return False
        self._clock.set(target)
        return True

    def _next_failure_time(self) -> datetime:
        """Processo de Poisson não homogêneo por "thinning" (Lewis-Shedler).

        Taxa base = 1 / (MTBF do tipo ÷ risco da região), modulada pela hora, dia da semana,
        estação e eventos do calendário (``city_patterns.intensity``).
        """
        mean_days = (
            self._spec.failure_mean_days
            / self._spec.placement.region.risk_factor
            / HISTORY_RATE_BOOST
        )
        ceiling = MAX_INTENSITY * OVERDUE_FAILURE_FACTOR * 2.0
        rate_max = ceiling / mean_days
        moment = self._clock.now()
        while moment < self._end:
            moment += timedelta(days=self._rng.expovariate(rate_max))
            if self._rng.random() < self._failure_intensity(moment) / ceiling:
                break
        return max(moment, self._clock.now() + timedelta(minutes=5))

    def _failure_intensity(self, moment: datetime) -> float:
        value = self._intensity(self._spec.type_code, moment)
        if self._overdue_until is not None and moment < self._overdue_until:
            value *= OVERDUE_FAILURE_FACTOR
        if self._spec.type_code in AGING_TYPES:
            value *= 1.0 + (moment - self._start).days / 365  # dobra ao longo do ano
        return value

    def _intensity(self, type_code: str, moment: datetime) -> float:
        local = moment.astimezone(self._tz).replace(tzinfo=None)
        return intensity(type_code, self._spec.placement.region.code, local, self._events)

    def _maybe(
        self, probability: float, after: datetime, pattern: str | None = None
    ) -> datetime | None:
        """Sorteia se o evento ocorre e quando; ``pattern`` aplica o perfil temporal de um tipo."""
        if probability <= 0 or self._rng.random() >= probability:
            return None
        span = max((self._end - after).total_seconds(), 0)
        for _ in range(200):
            moment = after + timedelta(seconds=self._rng.uniform(0, span))
            if pattern is None or (
                self._rng.random() < self._intensity(pattern, moment) / MAX_INTENSITY
            ):
                return moment
        return after + timedelta(seconds=self._rng.uniform(0, span))

    def _at_local(self, day: date, hour: int) -> datetime:
        return datetime(day.year, day.month, day.day, hour, tzinfo=self._tz)

    def _require_id(self) -> UUID:
        if self._id is None:
            raise RuntimeError("Equipamento ainda não cadastrado na simulação.")
        return self._id
