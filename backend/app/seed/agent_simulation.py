"""Simulação de agentes: cadastro, atribuição de viatura e turnos dos últimos dias."""

import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import ManualClock
from app.core.config import Settings
from app.domain.agents.entities import AgentRole, DutyStatus
from app.domain.equipment.status import EquipmentStatus
from app.repositories.unit_of_work import SqlAlchemyUnitOfWork
from app.seed.equipment_simulation import SEED, SimulatedEquipment
from app.seed.generators import REGIONS_BY_CODE, Placement, person_name, random_placement
from app.services.agent_service import AgentChanges, AgentService, NewAgent

AGENT_SIMULATION_DAYS = 7

_ASSIGNABLE = frozenset({EquipmentStatus.OPERACIONAL, EquipmentStatus.NAO_INSTALADO})


@dataclass(frozen=True, slots=True)
class ShiftPattern:
    start_hour: int
    hours: int


@dataclass(frozen=True, slots=True)
class AgentGroup:
    organization: str
    role: AgentRole
    count: int
    base_region: str
    vehicle_type: str
    shifts: tuple[ShiftPattern, ...]
    twelve_by_thirty_six: bool  # escala 12x36 (senão, 6x1)


AGENT_GROUPS = (
    AgentGroup(
        "SEMOB",
        AgentRole.AGENTE_TRANSITO,
        50,
        "centro",
        "moto_agente",
        (ShiftPattern(6, 8), ShiftPattern(14, 8)),
        twelve_by_thirty_six=False,
    ),
    AgentGroup(
        "GCM",
        AgentRole.GUARDA_MUNICIPAL,
        40,
        "leste",
        "viatura",
        (ShiftPattern(7, 12), ShiftPattern(19, 12)),
        twelve_by_thirty_six=True,
    ),
    AgentGroup(
        "PMESP",
        AgentRole.POLICIAL_MILITAR,
        30,
        "norte",
        "viatura",
        (ShiftPattern(7, 12), ShiftPattern(19, 12)),
        twelve_by_thirty_six=True,
    ),
)


@dataclass(frozen=True, slots=True)
class AgentPlan:
    index: int
    organization: str
    role: AgentRole
    base: Placement
    vehicle_id: UUID | None
    shift: ShiftPattern
    working_days: frozenset[int]  # deslocamento em dias a partir do início da janela


def build_agent_plans(equipment: list[SimulatedEquipment]) -> list[AgentPlan]:
    rng = random.Random(SEED + 7)
    seats: dict[tuple[str, str], list[UUID]] = {}
    for item in equipment:
        if item.spec.type_code in {"moto_agente", "viatura"} and item.final_status in _ASSIGNABLE:
            crew = 1 if item.spec.type_code == "moto_agente" else 2
            key = (item.spec.organization, item.spec.type_code)
            seats.setdefault(key, []).extend([item.equipment_id] * crew)

    plans: list[AgentPlan] = []
    window = range(AGENT_SIMULATION_DAYS + 1)
    for group in AGENT_GROUPS:
        base = random_placement(rng, REGIONS_BY_CODE[group.base_region])
        available = seats.get((group.organization, group.vehicle_type), [])
        for i in range(group.count):
            if group.twelve_by_thirty_six:
                days = frozenset(d for d in window if (d + i) % 2 == 0)
            else:
                days = frozenset(d for d in window if d % 7 != i % 7)
            plans.append(
                AgentPlan(
                    index=len(plans) + 1,
                    organization=group.organization,
                    role=group.role,
                    base=base,
                    vehicle_id=available[i] if i < len(available) else None,
                    # turno por par de agentes e escala pela paridade: cobre dia e noite todo dia
                    shift=group.shifts[(i // 2) % len(group.shifts)],
                    working_days=days,
                )
            )
    return plans


class AgentSimulation:
    def __init__(
        self,
        plan: AgentPlan,
        organization_id: UUID,
        actor_id: UUID,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        end: datetime,
    ) -> None:
        self._plan = plan
        self._organization_id = organization_id
        self._actor = actor_id
        self._end = end
        self._tz: ZoneInfo = settings.tz
        self._rng = random.Random(SEED * 20_000 + plan.index)
        self._clock = ManualClock(end - timedelta(days=AGENT_SIMULATION_DAYS + 30), self._tz)
        self._service = AgentService(SqlAlchemyUnitOfWork(session_factory), self._clock)
        self._status = DutyStatus.FORA_DE_SERVICO

    async def run(self) -> None:
        agent_id = await self._register()
        if self._rng.random() < 0.03:
            self._clock.set(self._end - timedelta(days=AGENT_SIMULATION_DAYS))
            await self._change(agent_id, DutyStatus.AFASTADO, "Licença médica")
            return
        window_start = (self._end - timedelta(days=AGENT_SIMULATION_DAYS)).astimezone(self._tz)
        for offset in sorted(self._plan.working_days):
            day = window_start.date() + timedelta(days=offset)
            start = datetime(
                day.year, day.month, day.day, self._plan.shift.start_hour, tzinfo=self._tz
            )
            finish = start + timedelta(hours=self._plan.shift.hours)
            if not await self._shift(agent_id, start, finish):
                return

    async def _register(self) -> UUID:
        plan = self._plan
        record = await self._service.create(
            NewAgent(
                full_name=person_name(self._rng),
                registration_number=f"{plan.organization}-{plan.index:04d}",
                role=plan.role,
                organization_id=self._organization_id,
                duty_status=DutyStatus.FORA_DE_SERVICO,
                base_address=plan.base.address,
                base_location=plan.base.location,
                assigned_vehicle_id=None,
            ),
            self._actor,
        )
        if plan.vehicle_id is not None:
            await self._service.update(
                record.agent.id,
                AgentChanges(version=record.agent.version, assigned_vehicle_id=plan.vehicle_id),
                self._actor,
            )
        return record.agent.id

    async def _shift(self, agent_id: UUID, start: datetime, finish: datetime) -> bool:
        """Simula um turno; retorna False quando alcança "agora" (estado atual fica gravado)."""
        if start >= self._end:
            return False
        self._clock.set(start)
        await self._change(agent_id, DutyStatus.DISPONIVEL, "Início do turno")
        moment, paused = start, False
        while True:
            moment += timedelta(minutes=self._rng.randint(40, 150))
            if moment >= min(finish, self._end):
                break
            options = [DutyStatus.EM_PATRULHA, DutyStatus.EM_OCORRENCIA, DutyStatus.DISPONIVEL]
            weights = [5, 2, 2]
            if not paused:
                options.append(DutyStatus.EM_PAUSA)
                weights.append(1)
            target = self._rng.choices(options, weights=weights)[0]
            if target is self._status:
                continue
            paused = paused or target is DutyStatus.EM_PAUSA
            self._clock.set(moment)
            reason = "Atendimento de ocorrência" if target is DutyStatus.EM_OCORRENCIA else None
            await self._change(agent_id, target, reason)
        if finish >= self._end:
            return False
        self._clock.set(finish)
        await self._change(agent_id, DutyStatus.FORA_DE_SERVICO, "Fim do turno")
        return True

    async def _change(self, agent_id: UUID, target: DutyStatus, reason: str | None) -> None:
        await self._service.change_duty_status(agent_id, target, reason, self._actor)
        self._status = target
