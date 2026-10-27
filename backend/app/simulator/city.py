"""Modelo da cidade simulada: dispositivos IoT e GPS dos agentes (sem decisões humanas).

Puro e determinístico (``random.Random(seed)``): recebe o instante atual e devolve o
que os dispositivos e as viaturas "transmitiriam". Quem envia é o ``GatewayClient``.
"""

import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.seed.city_patterns import device_baseline, expected_temperature, intensity
from app.seed.marilia_data import CENTER_LAT, CENTER_LNG

_METERS_PER_DEG_LAT = 111_320.0
_CITY_RADIUS_M = 6_200.0
_ARRIVAL_STOP_M = 8.0

TRANSMITTING_STATUSES = frozenset({"operacional", "mau_funcionamento"})
MOVING_DUTY_STATUSES = frozenset({"em_patrulha", "em_ocorrencia"})
ON_DUTY_STATUSES = frozenset({"disponivel", "em_patrulha", "em_ocorrencia", "em_pausa"})
BATTERY_TYPES = frozenset({"patinete", "veiculo_fiscalizacao_autonomo"})

# Peso relativo de falha por tipo (quem quebra mais) e por região (risco/vandalismo).
_FAULT_WEIGHT = {"patinete": 3.0, "camera": 2.0, "semaforo": 1.6, "totem_estacionamento": 1.5}
_REGION_RISK = {"centro": 1.0, "norte": 1.45, "leste": 1.1, "sul": 1.25, "oeste": 0.9}
_FAULTS = {
    "camera": ("Sem imagem: falha na fonte", "Perda de conexão com o NVR", "Lente obstruída"),
    "radar": ("Falha no laço indutivo", "Câmera OCR sem leitura de placas"),
    "semaforo": ("Lâmpada queimada no grupo focal", "Controlador em amarelo intermitente"),
    "totem_estacionamento": ("Impressora travada", "Leitor de cartão inoperante"),
    "patinete": ("Falha no controlador do motor", "Rastreador GPS sem sinal"),
}
_GENERIC_FAULTS = ("Autodiagnóstico detectou falha de hardware", "Reinicializações sucessivas")
_SPEED_KMH = {"viatura": 40.0, "moto_agente": 45.0, None: 5.0}
# Falhas com aviso: o equipamento degrada (temperatura sobe, sinal e uptime caem) por
# alguns minutos antes de parar. Parte das falhas é súbita e parte dos desvios é alarme falso,
# para que nenhuma previsão acerte 100% (precisão e cobertura medidas ao vivo).
_PRECURSOR_MINUTES = (8.0, 15.0)
_SUDDEN_FAULT_SHARE = 0.25
_FALSE_ALARM_SHARE = 0.25
# Tempo de resposta da equipe acionada por uma OS preventiva (técnico da concessionária
# reinicia, troca a fonte ou isola o defeito): se agir antes da falha, ela é evitada.
_INTERVENTION_RESPONSE_MINUTES = (2.0, 5.0)
_PATROL_SPEED_KMH = {"viatura": 25.0, "moto_agente": 28.0, None: 4.0}


@dataclass(slots=True)
class DeviceSim:
    equipment_id: str
    type_code: str
    status: str
    region_code: str | None
    next_heartbeat_at: datetime
    battery_pct: float | None = None
    outage_until: datetime | None = None
    pending_fault: str | None = None
    base_signal: float = -70.0
    base_uptime: float = 99.6
    degrading_since: datetime | None = None
    fault_at: datetime | None = None  # falha agendada ao fim do precursor (None = alarme falso)
    fault_reason: str | None = None
    degrade_until: datetime | None = None
    intervention_since: datetime | None = None
    response_minutes: float = 3.0
    averted: str | None = None
    drift_profile: float = 0.5  # sorteado por precursor: varia a intensidade de cada sinal


@dataclass(slots=True)
class AgentSim:
    agent_id: str
    duty_status: str
    lat: float
    lng: float
    vehicle_type: str | None
    heading_deg: float
    target: tuple[float, float] | None = None
    last_report_at: datetime | None = None


@dataclass(slots=True)
class TickOutput:
    heartbeats: list[dict[str, Any]] = field(default_factory=list)
    positions: list[dict[str, Any]] = field(default_factory=list)
    faults: int = 0
    outages_started: int = 0
    precursors_started: int = 0
    averted: int = 0


def precursor_drift(real: bool, profile: float, progress: float) -> tuple[float, float, float]:
    """Desvio (temperatura +°C, sinal −dB, uptime −p.p.) de um precursor.

    Falha real: aquecimento E perda de link (sinal e uptime caem juntos); em ~30% dos casos a
    queda de sinal é discreta e em ~20% o link quase não sofre (defeito silencioso).
    Alarme falso (ex.: sol forte no invólucro): sobretudo aquecimento, com queda de link
    pequena; ~30% têm um soluço de uptime. Os padrões se sobrepõem, então nenhuma regra fixa
    separa os dois: é o que o classificador aprende.
    """
    if real:
        weak_link = profile < 0.2  # defeito "silencioso": o link quase não sofre
        weak_signal = 0.2 <= profile < 0.5
        return (
            4 + 9 * progress,
            (2 + 3 * progress) if weak_link or weak_signal else (8 + 14 * progress),
            (0.3 + 0.8 * progress) if weak_link else (1.5 + 5 * progress),
        )
    uptime_blip = profile > 0.7
    return (
        5 + 10 * progress,
        (2 + 4 * progress) if profile > 0.5 else (1 + 2 * progress),
        (1.0 + 2 * progress) if uptime_blip else 0.2,
    )


def move(lat: float, lng: float, meters: float, heading_deg: float) -> tuple[float, float]:
    heading = math.radians(heading_deg)
    dlat = meters * math.cos(heading) / _METERS_PER_DEG_LAT
    dlng = meters * math.sin(heading) / (_METERS_PER_DEG_LAT * math.cos(math.radians(lat)))
    return lat + dlat, lng + dlng


def distance_and_bearing(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    """Aproximação plana (equiretangular), precisa para poucos quilômetros."""
    dy = (b[0] - a[0]) * _METERS_PER_DEG_LAT
    dx = (b[1] - a[1]) * _METERS_PER_DEG_LAT * math.cos(math.radians(a[0]))
    return math.hypot(dx, dy), math.degrees(math.atan2(dx, dy)) % 360


class CitySimulation:
    def __init__(
        self,
        *,
        seed: int,
        tz: ZoneInfo,
        tick_seconds: float,
        heartbeat_seconds: float,
        mean_seconds_between_faults: float,
    ) -> None:
        self._rng = random.Random(seed)
        self._tz = tz
        self._tick = tick_seconds
        self._heartbeat = timedelta(seconds=heartbeat_seconds)
        self._fault_probability = min(1.0, tick_seconds / mean_seconds_between_faults)
        self.devices: dict[str, DeviceSim] = {}
        self.agents: dict[str, AgentSim] = {}

    # ---- sincronização com o cadastro (registry) -------------------------------------

    def sync(self, registry: dict[str, Any], now: datetime) -> None:
        seen: set[str] = set()
        for item in registry["devices"]:
            device_id = str(item["equipment_id"])
            seen.add(device_id)
            device = self.devices.get(device_id)
            if device is None:
                offset = timedelta(seconds=self._rng.uniform(0, self._heartbeat.total_seconds()))
                device = DeviceSim(
                    device_id,
                    item["type_code"],
                    item["status"],
                    item.get("region_code"),
                    next_heartbeat_at=now + offset,
                    battery_pct=(
                        self._rng.uniform(25, 100) if item["type_code"] in BATTERY_TYPES else None
                    ),
                    base_signal=device_baseline(device_id)[0],
                    base_uptime=device_baseline(device_id)[1],
                )
                self.devices[device_id] = device
            device.status = item["status"]
            since = item.get("intervention_since")
            device.intervention_since = datetime.fromisoformat(since) if since else None
        for stale in set(self.devices) - seen:
            del self.devices[stale]

        seen_agents: set[str] = set()
        for item in registry["agents"]:
            agent_id = str(item["agent_id"])
            seen_agents.add(agent_id)
            position = item.get("current") or item["base"]
            agent = self.agents.get(agent_id)
            if agent is None:
                agent = AgentSim(
                    agent_id,
                    item["duty_status"],
                    position["latitude"],
                    position["longitude"],
                    item.get("vehicle_type"),
                    heading_deg=self._rng.uniform(0, 360),
                )
                self.agents[agent_id] = agent
            agent.duty_status = item["duty_status"] if item["is_active"] else "fora_de_servico"
            target = item.get("dispatch_target")
            agent.target = (target["latitude"], target["longitude"]) if target else None
            if agent.duty_status not in ON_DUTY_STATUSES:
                agent.lat, agent.lng = item["base"]["latitude"], item["base"]["longitude"]
        for stale in set(self.agents) - seen_agents:
            del self.agents[stale]

    # ---- um passo da simulação --------------------------------------------------------

    def step(self, now: datetime) -> TickOutput:
        output = TickOutput()
        night = now.astimezone(self._tz).hour in {22, 23, 0, 1, 2, 3, 4, 5}
        self._maybe_fault(now, output)
        for device in self.devices.values():
            self._advance_precursor(device, now, output)
            self._step_device(device, now, night, output)
        for agent in self.agents.values():
            self._step_agent(agent, now, output)
        return output

    def _maybe_fault(self, now: datetime, output: TickOutput) -> None:
        """Sorteia uma nova falha, com a mesma modulação temporal do histórico (seed)."""
        candidates = [
            d
            for d in self.devices.values()
            if d.status == "operacional" and d.degrading_since is None and d.pending_fault is None
        ]
        if not candidates:
            return
        local = now.astimezone(self._tz).replace(tzinfo=None)
        base = [
            _FAULT_WEIGHT.get(d.type_code, 1.0) * _REGION_RISK.get(d.region_code or "", 1.0)
            for d in candidates
        ]
        weights = [
            w * intensity(d.type_code, d.region_code or "", local, [])
            for w, d in zip(base, candidates, strict=True)
        ]
        mean_intensity = sum(weights) / sum(base)
        if self._rng.random() >= self._fault_probability * mean_intensity:
            return
        device = self._rng.choices(candidates, weights=weights)[0]
        reason = self._rng.choice(_FAULTS.get(device.type_code, _GENERIC_FAULTS))
        roll = self._rng.random()
        if roll < _SUDDEN_FAULT_SHARE:
            self._fail_now(device, reason, output)
            return
        minutes = self._rng.uniform(*_PRECURSOR_MINUTES)
        device.degrading_since = now
        device.drift_profile = self._rng.random()
        device.response_minutes = self._rng.uniform(*_INTERVENTION_RESPONSE_MINUTES)
        if roll < _SUDDEN_FAULT_SHARE + _FALSE_ALARM_SHARE:
            device.fault_at = None  # alarme falso: degrada e se recupera sozinho
            device.degrade_until = now + timedelta(minutes=minutes)
        else:
            device.fault_at = now + timedelta(minutes=minutes)
            device.fault_reason = reason
        output.precursors_started += 1

    def _fail_now(self, device: DeviceSim, reason: str, output: TickOutput) -> None:
        device.pending_fault = reason
        device.next_heartbeat_at = datetime.min.replace(tzinfo=self._tz)  # transmite já
        output.faults += 1

    def _advance_precursor(self, device: DeviceSim, now: datetime, output: TickOutput) -> None:
        if device.degrading_since is None:
            return
        if device.status != "operacional":
            # Entrou em manutenção durante o precursor: a equipe chegou antes da falha.
            if device.fault_at is not None and device.status == "em_manutencao":
                device.averted = "manutencao_em_andamento"
                output.averted += 1
            self._clear_precursor(device)
            return
        if device.fault_at is None:
            if device.degrade_until is not None and now >= device.degrade_until:
                self._clear_precursor(device)
            return
        intervened = device.intervention_since is not None and (
            device.intervention_since + timedelta(minutes=device.response_minutes) <= now
        )
        if intervened and now < device.fault_at:
            device.averted = "intervencao_preventiva"
            device.next_heartbeat_at = datetime.min.replace(tzinfo=self._tz)
            output.averted += 1
            self._clear_precursor(device)
            return
        if now >= device.fault_at:
            reason = device.fault_reason or self._rng.choice(_GENERIC_FAULTS)
            self._clear_precursor(device)
            self._fail_now(device, reason, output)

    @staticmethod
    def _clear_precursor(device: DeviceSim) -> None:
        device.degrading_since = device.fault_at = device.degrade_until = None
        device.fault_reason = None

    def _step_device(
        self, device: DeviceSim, now: datetime, night: bool, output: TickOutput
    ) -> None:
        if device.status not in TRANSMITTING_STATUSES and device.averted is None:
            return
        if device.outage_until and now < device.outage_until:
            return
        device.outage_until = None
        risk = _REGION_RISK.get(device.region_code or "", 1.0) * (1.6 if night else 1.0)
        idle = device.pending_fault is None and device.degrading_since is None
        if idle and self._rng.random() < 0.00008 * risk:
            device.outage_until = now + timedelta(minutes=self._rng.uniform(6, 15))
            output.outages_started += 1
            return
        if now < device.next_heartbeat_at:
            return
        device.next_heartbeat_at = now + self._heartbeat
        output.heartbeats.append(
            {
                "equipment_id": device.equipment_id,
                "recorded_at": now.isoformat(),
                "metrics": self._metrics(device, now),
                "fault": device.pending_fault,
                "fault_averted": device.averted,
            }
        )
        device.pending_fault = None
        device.averted = None

    def _metrics(self, device: DeviceSim, now: datetime) -> dict[str, Any]:
        hour = now.astimezone(self._tz).hour + now.minute / 60
        temperature = expected_temperature(hour)
        signal = device.base_signal
        uptime = device.base_uptime
        if device.degrading_since is not None:
            end = device.fault_at or device.degrade_until or now
            span = max((end - device.degrading_since).total_seconds(), 1.0)
            progress = min(1.0, (now - device.degrading_since).total_seconds() / span)
            drift = precursor_drift(device.fault_at is not None, device.drift_profile, progress)
            temperature += drift[0]
            signal -= drift[1]
            uptime -= drift[2]
        metrics: dict[str, Any] = {
            "signal_dbm": round(signal + self._rng.uniform(-2, 2), 1),
            "temperature_c": round(temperature + self._rng.uniform(-1.2, 1.2), 1),
            "uptime_pct": round(min(100.0, uptime + self._rng.uniform(-0.15, 0.15)), 2),
        }
        if device.battery_pct is not None:
            device.battery_pct -= self._rng.uniform(0.2, 0.6)
            if device.battery_pct < 8:  # troca de bateria pela operadora
                device.battery_pct = self._rng.uniform(92, 100)
            metrics["battery_pct"] = round(device.battery_pct, 1)
        return metrics

    def _step_agent(self, agent: AgentSim, now: datetime, output: TickOutput) -> None:
        if agent.duty_status not in ON_DUTY_STATUSES:
            return
        moving = False
        if agent.target is not None:
            distance, bearing = distance_and_bearing((agent.lat, agent.lng), agent.target)
            if distance > _ARRIVAL_STOP_M:
                step = _SPEED_KMH.get(agent.vehicle_type, 5.0) / 3.6 * self._tick
                agent.lat, agent.lng = move(agent.lat, agent.lng, min(step, distance), bearing)
                moving = True
        elif agent.duty_status in MOVING_DUTY_STATUSES:
            agent.heading_deg = (agent.heading_deg + self._rng.uniform(-35, 35)) % 360
            from_center, bearing_out = distance_and_bearing(
                (CENTER_LAT, CENTER_LNG), (agent.lat, agent.lng)
            )
            if from_center > _CITY_RADIUS_M:
                agent.heading_deg = (bearing_out + 180) % 360  # volta para dentro da cidade
            step = _PATROL_SPEED_KMH.get(agent.vehicle_type, 4.0) / 3.6 * self._tick
            agent.lat, agent.lng = move(agent.lat, agent.lng, step, agent.heading_deg)
            moving = True
        stale = agent.last_report_at is None or now - agent.last_report_at >= timedelta(seconds=30)
        if moving or stale:
            agent.last_report_at = now
            output.positions.append(
                {
                    "agent_id": agent.agent_id,
                    "recorded_at": now.isoformat(),
                    "latitude": round(agent.lat, 6),
                    "longitude": round(agent.lng, 6),
                }
            )
