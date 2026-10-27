"""API da Central de Operações ponta a ponta: gateway IoT → alertas → despacho."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.config import Settings
from app.core.permissions import Role
from app.main import build_container, create_app
from app.repositories.unit_of_work import SqlAlchemyUnitOfWork
from app.seed.marilia_data import REGIONS, region_geojson
from app.services.user_service import NewUser, UserService

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_database")]

PASSWORD = "Senha@Forte1"
ADDRESS = {
    "cep": "17500-000",
    "street": "Avenida Sampaio Vidal",
    "reference": "181",
    "neighborhood": "Centro",
    "city": "Marília",
    "uf": "SP",
}
CENTER = {"latitude": -22.2139, "longitude": -49.9458}


@pytest.fixture
async def client(
    test_settings: Settings, migrated_database: str
) -> AsyncIterator[httpx.AsyncClient]:
    app: FastAPI = create_app(test_settings)
    container = build_container(test_settings)
    app.state.container = container
    users = UserService(
        SqlAlchemyUnitOfWork(container.session_factory), container.clock, container.password_hasher
    )
    for role in Role:
        await users.create(NewUser(f"{role.value}@teste.dev", role.value, PASSWORD, role))
    async with SqlAlchemyUnitOfWork(container.session_factory) as uow:
        for region in REGIONS:
            await uow.regions.add(region.code, region.name, region_geojson(region))
        await uow.commit()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as http:
        yield http
    await container.http_client.aclose()
    await container.engine.dispose()


async def _auth(client: httpx.AsyncClient, role: Role) -> dict[str, str]:
    r = await client.post(
        "/api/v1/auth/token", data={"username": f"{role.value}@teste.dev", "password": PASSWORD}
    )
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _gateway(settings: Settings) -> dict[str, str]:
    return {"X-Gateway-Key": settings.iot_gateway_key.get_secret_value()}


async def _scenario(client: httpx.AsyncClient) -> dict[str, Any]:
    manager = await _auth(client, Role.GESTOR)
    org = (
        await client.post(
            "/api/v1/organizations",
            json={"name": "Guarda Civil", "acronym": "GCM", "kind": "guarda_municipal"},
            headers=manager,
        )
    ).json()
    camera = (
        await client.post(
            "/api/v1/equipment",
            json={
                "type_code": "camera",
                "serial_number": "CAM-API",
                "brand": "Axis",
                "model": "Q6075",
                "organization_id": org["id"],
                "status": "operacional",
                "installed_on": "2026-09-01",
                "address": ADDRESS,
                "location": CENTER,
                "attributes": {"resolution": "4k", "night_vision": True},
            },
            headers=manager,
        )
    ).json()
    agent = (
        await client.post(
            "/api/v1/agents",
            json={
                "full_name": "Ana Ribeiro",
                "registration_number": "GCM-1",
                "role": "guarda_municipal",
                "organization_id": org["id"],
                "duty_status": "em_patrulha",
                "base_address": ADDRESS,
                "base_location": {"latitude": -22.2239, "longitude": -49.9458},
            },
            headers=manager,
        )
    ).json()
    return {"camera": camera, "agent": agent}


async def test_gateway_endpoints_require_the_gateway_key(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/telemetry/registry")).status_code == 401
    wrong = await client.get("/api/v1/telemetry/registry", headers={"X-Gateway-Key": "errada"})
    assert wrong.status_code == 401
    user_token = await _auth(client, Role.ADMIN)
    assert (await client.get("/api/v1/telemetry/registry", headers=user_token)).status_code == 401


async def test_device_fault_to_dispatch_arrival(
    client: httpx.AsyncClient, test_settings: Settings
) -> None:
    data = await _scenario(client)
    camera, agent = data["camera"], data["agent"]
    now = datetime.now(UTC).isoformat()

    ingest = await client.post(
        "/api/v1/telemetry/equipment",
        json={
            "heartbeats": [
                {
                    "equipment_id": camera["id"],
                    "recorded_at": now,
                    "metrics": {"signal_dbm": -71},
                    "fault": "Sem imagem",
                }
            ]
        },
        headers=_gateway(test_settings),
    )
    assert ingest.json() == {"accepted": 1, "unknown": 0, "faults_registered": 1, "arrivals": 0}

    operator = await _auth(client, Role.OPERADOR)
    alerts = (
        await client.get("/api/v1/alerts", params={"status": "aberto"}, headers=operator)
    ).json()
    assert alerts["total"] == 1
    alert = alerts["items"][0]
    assert (alert["kind"], alert["severity"]) == ("falha_equipamento", "critica")
    assert alert["equipment"]["serial_number"] == "CAM-API"
    assert alert["sla_breached"] is False

    suggestions = (
        await client.get(
            "/api/v1/operations/dispatch-suggestions",
            params={"equipment_id": camera["id"]},
            headers=operator,
        )
    ).json()
    assert suggestions[0]["agent_id"] == agent["id"]
    assert suggestions[0]["recommended"] is True

    dispatch = await client.post(
        "/api/v1/dispatches",
        json={"equipment_id": camera["id"], "agent_id": agent["id"]},
        headers=operator,
    )
    assert dispatch.status_code == 201, dispatch.text
    acknowledged = (await client.get(f"/api/v1/alerts/{alert['id']}", headers=operator)).json()
    assert acknowledged["status"] == "reconhecido"

    arrival = await client.post(
        "/api/v1/telemetry/agents",
        json={"positions": [{"agent_id": agent["id"], "recorded_at": now, **CENTER}]},
        headers=_gateway(test_settings),
    )
    assert arrival.json()["arrivals"] == 1
    active = (await client.get("/api/v1/dispatches", headers=operator)).json()
    assert active[0]["status"] == "no_local"

    features = (await client.get("/api/v1/operations/map-features", headers=operator)).json()
    live = next(a for a in features["agents"] if a["id"] == agent["id"])
    assert live["live"] is True
    assert live["dispatch_status"] == "no_local"
    assert live["lat"] == pytest.approx(CENTER["latitude"])


async def test_overview_and_regions_for_read_only_users(client: httpx.AsyncClient) -> None:
    await _scenario(client)
    viewer = await _auth(client, Role.CONSULTA)
    overview = (await client.get("/api/v1/operations/overview", headers=viewer)).json()
    assert overview["total_equipment"] == 1
    assert overview["availability_pct"] == 100.0
    assert overview["agents_on_duty"] == 1
    regions = (await client.get("/api/v1/operations/regions", headers=viewer)).json()
    assert {r["code"] for r in regions} == {r.code for r in REGIONS}
    assert all(0 <= r["score"] <= 100 for r in regions)
    trends = await client.get("/api/v1/operations/trends", params={"days": 7}, headers=viewer)
    assert len(trends.json()) == 7


async def test_read_only_users_cannot_act(
    client: httpx.AsyncClient, test_settings: Settings
) -> None:
    data = await _scenario(client)
    await client.post(
        "/api/v1/telemetry/equipment",
        json={
            "heartbeats": [
                {
                    "equipment_id": data["camera"]["id"],
                    "recorded_at": datetime.now(UTC).isoformat(),
                    "fault": "x",
                }
            ]
        },
        headers=_gateway(test_settings),
    )
    viewer = await _auth(client, Role.CONSULTA)
    alert_id = (await client.get("/api/v1/alerts", headers=viewer)).json()["items"][0]["id"]
    assert (
        await client.post(f"/api/v1/alerts/{alert_id}/acknowledge", headers=viewer)
    ).status_code == 403
    denied = await client.post(
        "/api/v1/dispatches",
        json={"equipment_id": data["camera"]["id"], "agent_id": data["agent"]["id"]},
        headers=viewer,
    )
    assert denied.status_code == 403


async def test_manual_resolution_requires_a_note(
    client: httpx.AsyncClient, test_settings: Settings
) -> None:
    data = await _scenario(client)
    await client.post(
        "/api/v1/telemetry/equipment",
        json={
            "heartbeats": [
                {
                    "equipment_id": data["camera"]["id"],
                    "recorded_at": datetime.now(UTC).isoformat(),
                    "fault": "x",
                }
            ]
        },
        headers=_gateway(test_settings),
    )
    operator = await _auth(client, Role.OPERADOR)
    alert_id = (await client.get("/api/v1/alerts", headers=operator)).json()["items"][0]["id"]
    assert (
        await client.post(f"/api/v1/alerts/{alert_id}/resolve", json={}, headers=operator)
    ).status_code == 422
    resolved = await client.post(
        f"/api/v1/alerts/{alert_id}/resolve", json={"note": "Falso positivo"}, headers=operator
    )
    assert resolved.json()["status"] == "resolvido"
