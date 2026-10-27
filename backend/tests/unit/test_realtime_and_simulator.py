"""Tempo real (SSE/broker) e simulador IoT, sem rede e sem banco."""

import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.realtime.broker import EventBroker
from app.realtime.sse import event_stream, format_sse
from app.simulator.city import CitySimulation, distance_and_bearing

NOW = datetime(2026, 10, 26, 17, 0, tzinfo=UTC)


def test_format_sse_prefixes_every_data_line() -> None:
    assert (
        format_sse("alert.opened", '{"a":1}', 7) == 'id: 7\nevent: alert.opened\ndata: {"a":1}\n\n'
    )
    assert format_sse("x", "l1\nl2") == "event: x\ndata: l1\ndata: l2\n\n"


async def _never_disconnected() -> bool:
    return False


async def test_stream_delivers_broker_events_and_pings() -> None:
    broker = EventBroker("postgresql://unused", queue_size=10)
    stream = event_stream(broker, _never_disconnected, 0.05, {"user": "teste"})
    assert (await anext(stream)).startswith("event: ready")
    assert await anext(stream) == ": ping\n\n"  # nenhum evento dentro do heartbeat

    broker.dispatch(json.dumps({"type": "alert.opened", "data": {"id": "1"}}))
    message = await anext(stream)
    assert "event: alert.opened" in message
    await stream.aclose()
    assert broker.subscribers == 0


async def test_slow_client_is_told_to_resync() -> None:
    broker = EventBroker("postgresql://unused", queue_size=1)
    stream = event_stream(broker, _never_disconnected, 1, {})
    await anext(stream)
    for i in range(3):  # a fila de 1 estoura
        broker.dispatch(json.dumps({"type": "agents.positions", "data": {"i": i}}))
    assert "event: resync" in await anext(stream)
    with pytest.raises(StopAsyncIteration):
        await anext(stream)


def _registry() -> dict[str, object]:
    base = {"latitude": -22.2139, "longitude": -49.9458}
    return {
        "devices": [
            {
                "equipment_id": "cam",
                "type_code": "camera",
                "status": "operacional",
                "region_code": "centro",
            },
            {
                "equipment_id": "pat",
                "type_code": "patinete",
                "status": "operacional",
                "region_code": "norte",
            },
            {
                "equipment_id": "off",
                "type_code": "radar",
                "status": "furtado",
                "region_code": "sul",
            },
        ],
        "agents": [
            {
                "agent_id": "patrol",
                "duty_status": "em_patrulha",
                "is_active": True,
                "region_code": "centro",
                "base": base,
                "current": None,
                "vehicle_type": "viatura",
                "dispatch_target": None,
            },
            {
                "agent_id": "sent",
                "duty_status": "em_ocorrencia",
                "is_active": True,
                "region_code": "centro",
                "base": base,
                "current": None,
                "vehicle_type": "viatura",
                "dispatch_target": {"latitude": -22.2039, "longitude": -49.9458},
            },
            {
                "agent_id": "home",
                "duty_status": "fora_de_servico",
                "is_active": True,
                "region_code": "centro",
                "base": base,
                "current": None,
                "vehicle_type": None,
                "dispatch_target": None,
            },
        ],
    }


def _city(seconds_between_faults: float = 1e9) -> CitySimulation:
    return CitySimulation(
        seed=7,
        tz=ZoneInfo("America/Sao_Paulo"),
        tick_seconds=5,
        heartbeat_seconds=30,
        mean_seconds_between_faults=seconds_between_faults,
    )


def test_only_installed_devices_transmit_and_scooters_report_battery() -> None:
    city = _city()
    city.sync(_registry(), NOW)
    sent: dict[str, dict[str, object]] = {}
    for i in range(8):  # 40 s > intervalo de heartbeat
        for beat in city.step(NOW + timedelta(seconds=5 * i)).heartbeats:
            sent[str(beat["equipment_id"])] = beat
    assert "off" not in sent  # furtado não transmite
    assert {"cam", "pat"} <= set(sent)
    assert "battery_pct" in sent["pat"]["metrics"]  # type: ignore[operator]


def test_dispatched_agent_moves_toward_target_and_off_duty_stays_silent() -> None:
    city = _city()
    city.sync(_registry(), NOW)
    target = (-22.2039, -49.9458)
    start, _ = distance_and_bearing((-22.2139, -49.9458), target)
    positions: dict[str, dict[str, object]] = {}
    for i in range(10):
        for p in city.step(NOW + timedelta(seconds=5 * i)).positions:
            positions[str(p["agent_id"])] = p
    sent = positions["sent"]
    remaining, _ = distance_and_bearing((float(sent["latitude"]), float(sent["longitude"])), target)  # type: ignore[arg-type]
    assert remaining < start - 400  # ~55 m por tick a 40 km/h
    assert "patrol" in positions
    assert "home" not in positions


def _run_for(city: CitySimulation, minutes: int) -> tuple[list[str], int, int]:
    faults: list[str] = []
    precursors = averted = 0
    for i in range(minutes * 12):  # tick de 5 s
        output = city.step(NOW + timedelta(seconds=5 * i))
        faults += [str(b["fault"]) for b in output.heartbeats if b["fault"]]
        precursors += output.precursors_started
        averted += output.averted
    return faults, precursors, averted


def test_faults_come_with_precursors_and_are_deterministic() -> None:
    def run() -> tuple[list[str], int, int]:
        city = _city(seconds_between_faults=5)
        city.sync(_registry(), NOW)
        return _run_for(city, 30)

    faults, precursors, _ = run()
    assert faults
    assert precursors
    assert run() == (faults, precursors, 0)


def test_precursor_degrades_telemetry_before_the_fault() -> None:
    city = _city()
    city.sync(_registry(), NOW)
    device = city.devices["cam"]
    device.degrading_since = NOW
    device.fault_at = NOW + timedelta(minutes=10)
    hot = city._metrics(device, NOW + timedelta(minutes=9))
    device.degrading_since = device.fault_at = None
    normal = city._metrics(device, NOW + timedelta(minutes=9))
    assert hot["temperature_c"] > normal["temperature_c"] + 10
    assert hot["signal_dbm"] < normal["signal_dbm"] - 15


def test_intervention_in_time_averts_the_fault() -> None:
    city = _city()
    registry = _registry()
    city.sync(registry, NOW)
    device = city.devices["cam"]
    device.degrading_since = NOW
    device.fault_at = NOW + timedelta(minutes=12)
    device.response_minutes = 3
    devices = registry["devices"]
    assert isinstance(devices, list)
    devices[0]["intervention_since"] = (NOW + timedelta(minutes=1)).isoformat()
    city.sync(registry, NOW)
    faults, _, averted = _run_for(city, 15)
    assert averted == 1
    assert not faults  # a falha agendada não aconteceu
