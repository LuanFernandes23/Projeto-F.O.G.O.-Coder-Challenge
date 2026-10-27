"""Seed de demonstração (Marília-SP) gerado por SIMULAÇÃO através dos próprios serviços.

Em vez de inserir linhas prontas, o seed "vive" um ano da cidade com relógio controlado:
cadastra, instala, quebra, conserta, faz preventivas, registra furtos e turnos de agentes
chamando os mesmos casos de uso da API. Resultado: histórico coerente com todas as regras
de negócio (máquina de estados, ordens automáticas, planos) e com padrões temporais e
regionais que alimentarão a Parte 3 (cidade preditiva).
"""

import asyncio
import json
import logging
import random
import time
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import ManualClock
from app.core.config import Settings
from app.core.permissions import Role
from app.core.security import PasswordHasher
from app.domain.operations.alerts import AlertStatus
from app.domain.organizations import OrganizationKind
from app.repositories.unit_of_work import SqlAlchemyUnitOfWork
from app.seed.agent_simulation import AgentPlan, AgentSimulation, build_agent_plans
from app.seed.city_patterns import (
    CityEvent,
    build_calendar,
    device_baseline,
    expected_temperature,
)
from app.seed.equipment_simulation import SEED, EquipmentSimulation, SimulatedEquipment
from app.seed.generators import EquipmentSpec, generate_equipment_specs
from app.seed.marilia_data import DEMO_USERS, ORGANIZATIONS, REGIONS, region_geojson
from app.services.alert_service import AlertService
from app.services.reference_service import OrganizationService
from app.services.user_service import NewUser, UserService
from app.simulator.city import precursor_drift

logger = logging.getLogger("app.seed")

SIMULATION_DAYS = 365
CALENDAR_DAYS_AHEAD = 30  # o calendário público já conhece os próximos eventos
DISPATCH_HISTORY_DAYS = 90
DETECTION_HISTORY = 180
DETECTION_HISTORY_DAYS = 30
CONCURRENCY = 8


class DemoSeeder:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], settings: Settings
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings

    async def run_if_empty(self) -> None:
        async with SqlAlchemyUnitOfWork(self._session_factory) as uow:
            if await uow.organizations.list_all():
                logger.info("Seed ignorado: o banco já possui dados")
                return
            admin = await uow.users.get_by_email(self._settings.first_admin_email)
        if admin is None:
            raise RuntimeError("Crie o primeiro administrador antes do seed.")

        started = time.perf_counter()
        # Os serviços registram cada operação em INFO; na simulação isso viraria milhares de
        # linhas. Mantém só avisos/erros durante o seed e restaura o nível ao final.
        services_logger = logging.getLogger("app.services")
        previous_level = services_logger.level
        services_logger.setLevel(logging.WARNING)
        try:
            await self._seed(admin.id, started)
        finally:
            services_logger.setLevel(previous_level)

    async def _seed(self, admin_id: UUID, started: float) -> None:
        end = datetime.now(UTC)
        start = end - timedelta(days=SIMULATION_DAYS)
        await self._seed_regions()
        organizations = await self._seed_organizations(start)
        await self._seed_users()
        tz = self._settings.tz
        events = build_calendar(
            start.astimezone(tz).date(),
            (end + timedelta(days=CALENDAR_DAYS_AHEAD)).astimezone(tz).date(),
        )
        await self._seed_calendar(events)
        equipment = await self._simulate_equipment(organizations, admin_id, start, end, events)
        await self._acknowledge_old_alerts(end)
        agents = await self._simulate_agents(organizations, admin_id, equipment, end)
        await self._seed_dispatch_history(admin_id, end)
        await self._seed_recent_telemetry(end)
        await self._seed_detection_history(end)
        logger.info(
            "Seed de demonstração concluído",
            extra={
                "equipment": len(equipment),
                "agents": agents,
                "duration_s": round(time.perf_counter() - started, 1),
            },
        )

    async def _acknowledge_old_alerts(self, end: datetime) -> None:
        """Alertas antigos já teriam sido assumidos por um operador (realismo do histórico)."""
        async with SqlAlchemyUnitOfWork(self._session_factory) as uow:
            operator = await uow.users.get_by_email(DEMO_USERS[1][0])
            alerts = await uow.alerts.list_open_by_prefix("")
        if operator is None:
            return
        rng = random.Random(SEED + 11)
        clock = ManualClock(end, self._settings.tz)
        service = AlertService(SqlAlchemyUnitOfWork(self._session_factory), clock)
        for alert in alerts:
            if alert.status is not AlertStatus.ABERTO or alert.opened_at > end - timedelta(days=2):
                continue
            clock.set(alert.opened_at + timedelta(minutes=rng.uniform(5, 90)))
            await service.acknowledge(alert.id, operator.id)

    async def _seed_calendar(self, events: list[CityEvent]) -> None:
        """Calendário público de eventos (feriados, jogos, shows, feiras) em ``city_events``."""
        statement = text(
            "INSERT INTO city_events (name, kind, region_id, starts_at, ends_at, expected_public) "
            "VALUES (:name, :kind, (SELECT id FROM regions WHERE code = :region), "
            "(CAST(:starts AS timestamp) AT TIME ZONE :tz), "
            "(CAST(:ends AS timestamp) AT TIME ZONE :tz), :public)"
        )
        async with self._session_factory() as session:
            await session.execute(
                statement,
                [
                    {
                        "name": e.name,
                        "kind": e.kind,
                        "region": e.region_code,
                        "starts": e.starts_at,
                        "ends": e.ends_at,
                        "tz": self._settings.timezone,
                        "public": e.expected_public,
                    }
                    for e in events
                ],
            )
            await session.commit()

    async def _seed_dispatch_history(self, admin_id: UUID, end: datetime) -> None:
        """Histórico de atendimentos dos últimos 90 dias (base do tempo médio por ocorrência).

        Cada falha/furto com alerta vira um despacho concluído de um agente apto da mesma
        região: furto para GCM/PM; falha de trânsito para agente de trânsito; demais, GCM.
        Inserido direto (dado histórico importado), com aleatoriedade determinística.
        """
        statement = text(
            """
            INSERT INTO dispatches (agent_id, equipment_id, alert_id, status, target, origin,
                                    distance_m, eta_minutes, created_at, created_by,
                                    departed_at, arrived_at, closed_at, notes)
            SELECT ag.id, e.id, a.id, 'concluido', e.location, ag.location, d.meters,
                   d.meters * 1.3 / 400.0,
                   a.opened_at + t.wait, :actor,
                   a.opened_at + t.wait + interval '2 minutes',
                   a.opened_at + t.wait + interval '2 minutes'
                       + make_interval(secs => d.meters * 1.3 / 400.0 * 60 * t.traffic),
                   a.opened_at + t.wait + interval '2 minutes'
                       + make_interval(secs => d.meters * 1.3 / 400.0 * 60 * t.traffic)
                       + t.handling,
                   'Atendimento histórico'
            FROM alerts a
            JOIN equipment e ON e.id = a.equipment_id
            CROSS JOIN LATERAL (
                SELECT g.id, g.location FROM agents g
                WHERE g.region_id = e.region_id
                  AND g.role::text = ANY (
                      CASE
                          WHEN a.kind = 'furto' THEN ARRAY['guarda_municipal', 'policial_militar']
                          WHEN e.type_code IN ('semaforo', 'radar', 'cancela')
                              THEN ARRAY['agente_transito']
                          ELSE ARRAY['guarda_municipal']
                      END)
                ORDER BY md5(g.id::text || a.id::text)
                LIMIT 1
            ) ag
            CROSS JOIN LATERAL (SELECT ST_Distance(e.location, ag.location) AS meters) d
            CROSS JOIN LATERAL (
                SELECT make_interval(mins => 2 + (abs(hashtext(a.id::text)) % 13)) AS wait,
                       0.8 + (abs(hashtext(a.id::text || 't')) % 50) / 100.0 AS traffic,
                       make_interval(mins => CASE WHEN a.kind = 'furto'
                           THEN 60 + abs(hashtext(a.id::text || 'h')) % 60
                           ELSE 25 + abs(hashtext(a.id::text || 'h')) % 45 END) AS handling
            ) t
            WHERE a.kind IN ('falha_equipamento', 'furto')
              AND a.opened_at >= :since AND a.opened_at < :until - interval '3 hours'
            """
        )
        async with self._session_factory() as session:
            await session.execute(
                statement,
                {
                    "actor": admin_id,
                    "since": end - timedelta(days=DISPATCH_HISTORY_DAYS),
                    "until": end,
                },
            )
            await session.commit()

    async def _seed_recent_telemetry(self, end: datetime) -> None:
        """Última 1,5 h de leituras (a cada 5 min): a detecção de anomalias já nasce com linha
        de base, em vez de esperar o simulador acumular histórico."""
        rng = random.Random(SEED + 29)
        tz = self._settings.tz
        async with self._session_factory() as session:
            ids = (
                await session.execute(text("SELECT id FROM equipment WHERE status = 'operacional'"))
            ).scalars()
            rows = []
            for equipment_id in ids:
                signal, uptime = device_baseline(str(equipment_id))
                for minutes in range(90, 0, -5):
                    moment = end - timedelta(minutes=minutes)
                    local = moment.astimezone(tz)
                    rows.append(
                        {
                            "equipment_id": equipment_id,
                            "recorded_at": moment,
                            "metrics": json.dumps(
                                {
                                    "signal_dbm": round(signal + rng.uniform(-2, 2), 1),
                                    "temperature_c": round(
                                        expected_temperature(local.hour + local.minute / 60)
                                        + rng.uniform(-1.2, 1.2),
                                        1,
                                    ),
                                    "uptime_pct": round(
                                        min(100.0, uptime + rng.uniform(-0.15, 0.15)), 2
                                    ),
                                }
                            ),
                        }
                    )
            await session.execute(
                text(
                    "INSERT INTO telemetry_readings (equipment_id, recorded_at, metrics) "
                    "VALUES (:equipment_id, :recorded_at, CAST(:metrics AS jsonb))"
                ),
                rows,
            )
            await session.commit()

    async def _seed_detection_history(self, end: datetime) -> None:
        """30 dias de detecções de precursores com desfecho (rótulos do classificador).

        Mesmos padrões do simulador (``precursor_drift``): o classificador já nasce treinado
        e continua aprendendo com os desfechos ao vivo.
        """
        rng = random.Random(SEED + 31)
        spread = {"temperature_c": 1.2, "signal_dbm": 2.0, "uptime_pct": 0.25}
        async with self._session_factory() as session:
            ids = list(
                (
                    await session.execute(
                        text("SELECT id FROM equipment WHERE status = 'operacional'")
                    )
                ).scalars()
            )
            rows = []
            for _ in range(DETECTION_HISTORY):
                real = rng.random() < 0.62
                progress = rng.uniform(0.0, 0.45)
                temp, signal, uptime = precursor_drift(real, rng.random(), progress)
                z = {
                    "temperature_c": round(temp / spread["temperature_c"] + rng.gauss(0, 1.6), 2),
                    "signal_dbm": round(signal / spread["signal_dbm"] + rng.gauss(0, 1.6), 2),
                    "uptime_pct": round(uptime / spread["uptime_pct"] + rng.gauss(0, 1.6), 2),
                }
                detected = end - timedelta(minutes=rng.uniform(60, DETECTION_HISTORY_DAYS * 1440))
                if real:
                    outcome = "falhou" if rng.random() < 0.55 else "evitada"
                    lead = rng.uniform(2, 12)
                else:
                    outcome, lead = "falso_alarme", 30.0
                signals = [
                    {"metric": metric, "label": metric, "value": 0, "baseline": 0, "z": value}
                    for metric, value in z.items()
                    if value >= 3
                ]
                rows.append(
                    {
                        "equipment_id": rng.choice(ids),
                        "detected_at": detected,
                        "score": round(min(1.0, sum(sorted(z.values())[-2:]) / 24), 3),
                        "signals": json.dumps({"signals": signals, "z": z}),
                        "outcome": outcome,
                        "outcome_at": detected + timedelta(minutes=lead),
                        "lead": None if outcome == "falso_alarme" else round(lead, 1),
                    }
                )
            await session.execute(
                text(
                    "INSERT INTO anomaly_detections (equipment_id, detected_at, score, signals, "
                    "outcome, outcome_at, lead_minutes) VALUES (:equipment_id, :detected_at, "
                    ":score, CAST(:signals AS jsonb), :outcome, :outcome_at, :lead)"
                ),
                rows,
            )
            # Cada detecção "evitada" também é uma falha evitada (a mesma verdade de campo do
            # simulador), para os dois contadores da tela contarem a mesma coisa.
            averted = [
                {"equipment_id": r["equipment_id"], "averted_at": r["outcome_at"]}
                for r in rows
                if r["outcome"] == "evitada"
            ]
            await session.execute(
                text(
                    "INSERT INTO averted_faults (equipment_id, averted_at, intervention) "
                    "VALUES (:equipment_id, :averted_at, 'intervencao_preventiva')"
                ),
                averted,
            )
            await session.commit()

    async def _seed_regions(self) -> None:
        async with SqlAlchemyUnitOfWork(self._session_factory) as uow:
            for region in REGIONS:
                await uow.regions.add(region.code, region.name, region_geojson(region))
            await uow.commit()

    async def _seed_organizations(self, start: datetime) -> dict[str, UUID]:
        service = OrganizationService(
            SqlAlchemyUnitOfWork(self._session_factory), ManualClock(start, self._settings.tz)
        )
        ids: dict[str, UUID] = {}
        for acronym, name, kind in ORGANIZATIONS:
            organization = await service.create(name, acronym, OrganizationKind(kind))
            ids[acronym] = organization.id
        return ids

    async def _seed_users(self) -> None:
        service = UserService(
            SqlAlchemyUnitOfWork(self._session_factory),
            ManualClock(datetime.now(UTC), self._settings.tz),
            PasswordHasher(),
        )
        password = self._settings.demo_users_password.get_secret_value()
        for email, name, role in DEMO_USERS:
            await service.create(
                NewUser(email=email, full_name=name, password=password, role=Role(role))
            )

    async def _simulate_equipment(
        self,
        organizations: dict[str, UUID],
        actor_id: UUID,
        start: datetime,
        end: datetime,
        events: list[CityEvent],
    ) -> list[SimulatedEquipment]:
        specs = generate_equipment_specs(SEED)
        semaphore = asyncio.Semaphore(CONCURRENCY)
        progress = {"done": 0}

        async def simulate(spec: EquipmentSpec) -> SimulatedEquipment:
            async with semaphore:
                simulation = EquipmentSimulation(
                    spec,
                    organizations[spec.organization],
                    actor_id,
                    self._session_factory,
                    self._settings,
                    start,
                    end,
                    events,
                )
                result = await simulation.run()
            progress["done"] += 1
            if progress["done"] % 50 == 0:
                logger.info("Simulando equipamentos", extra={**progress, "total": len(specs)})
            return result

        return list(await asyncio.gather(*(simulate(spec) for spec in specs)))

    async def _simulate_agents(
        self,
        organizations: dict[str, UUID],
        actor_id: UUID,
        equipment: list[SimulatedEquipment],
        end: datetime,
    ) -> int:
        plans = build_agent_plans(equipment)
        semaphore = asyncio.Semaphore(CONCURRENCY)

        async def simulate(plan: AgentPlan) -> None:
            async with semaphore:
                simulation = AgentSimulation(
                    plan,
                    organizations[plan.organization],
                    actor_id,
                    self._session_factory,
                    self._settings,
                    end,
                )
                await simulation.run()

        await asyncio.gather(*(simulate(plan) for plan in plans))
        return len(plans)
