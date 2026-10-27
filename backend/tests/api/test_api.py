"""Testes de API ponta a ponta (HTTP → rotas → serviços → PostGIS)."""

from collections.abc import AsyncIterator
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
CAMERA_PAYLOAD: dict[str, Any] = {
    "type_code": "camera",
    "serial_number": "HKV-2026-000123",
    "brand": "Hikvision",
    "model": "DS-2CD2T47G2",
    "status": "operacional",
    "installed_on": "2026-09-01",
    "address": {
        "cep": "17500-000",
        "street": "Avenida Sampaio Vidal",
        "reference": "em frente ao Mercado do Tio",
        "neighborhood": "Centro",
        "city": "Marília",
        "uf": "SP",
    },
    "location": {"latitude": -22.2139, "longitude": -49.9458},
    "attributes": {"resolution": "4k", "night_vision": True, "ptz": True},
    "maintenance_plan": {"interval_days": 90},
}


@pytest.fixture
async def app(test_settings: Settings, migrated_database: str) -> AsyncIterator[FastAPI]:
    application = create_app(test_settings)
    container = build_container(test_settings)
    application.state.container = container  # o ASGITransport não executa o lifespan
    users = UserService(
        SqlAlchemyUnitOfWork(container.session_factory), container.clock, container.password_hasher
    )
    for role in Role:
        await users.create(
            NewUser(f"{role.value}@teste.dev", f"Usuário {role.value}", PASSWORD, role)
        )
    async with SqlAlchemyUnitOfWork(container.session_factory) as uow:
        for region in REGIONS:
            await uow.regions.add(region.code, region.name, region_geojson(region))
        await uow.commit()
    yield application
    if container.prometheus is not None:
        await container.prometheus.close()
    await container.http_client.aclose()
    await container.engine.dispose()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


async def _headers(client: httpx.AsyncClient, role: Role) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/token", data={"username": f"{role.value}@teste.dev", "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _organization(client: httpx.AsyncClient, kind: str = "guarda_municipal") -> str:
    response = await client.post(
        "/api/v1/organizations",
        json={"name": f"Órgão {kind}", "acronym": kind[:6].upper(), "kind": kind},
        headers=await _headers(client, Role.GESTOR),
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def _camera(client: httpx.AsyncClient, **overrides: Any) -> dict[str, Any]:
    payload = {**CAMERA_PAYLOAD, "organization_id": await _organization(client), **overrides}
    response = await client.post(
        "/api/v1/equipment", json=payload, headers=await _headers(client, Role.GESTOR)
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


async def test_health_and_request_id(client: httpx.AsyncClient) -> None:
    response = await client.get("/health", headers={"X-Request-ID": "teste-123"})
    assert response.json() == {"status": "ok", "database": None}
    assert response.headers["x-request-id"] == "teste-123"
    ready = await client.get("/health/ready")
    assert ready.json()["database"] == "ok"


async def test_protected_routes_require_token(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/equipment")
    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "nao_autenticado"


async def test_login_with_wrong_password(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/token", data={"username": "admin@teste.dev", "password": "errada"}
    )
    assert response.status_code == 401


async def test_me_lists_permissions_of_the_role(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/auth/me", headers=await _headers(client, Role.CONSULTA))
    assert response.json()["role"] == "consulta"
    assert "equipment:write" not in response.json()["permissions"]


@pytest.mark.parametrize(
    ("role", "expected"),
    [(Role.CONSULTA, 403), (Role.OPERADOR, 403), (Role.GESTOR, 201), (Role.ADMIN, 201)],
)
async def test_only_managers_register_equipment(
    client: httpx.AsyncClient, role: Role, expected: int
) -> None:
    payload = {**CAMERA_PAYLOAD, "organization_id": await _organization(client)}
    response = await client.post(
        "/api/v1/equipment", json=payload, headers=await _headers(client, role)
    )
    assert response.status_code == expected, response.text


async def test_create_returns_region_maintenance_and_normalized_data(
    client: httpx.AsyncClient,
) -> None:
    equipment = await _camera(client)
    assert equipment["region"]["code"] == "centro"
    assert equipment["address"]["cep"] == "17500000"
    assert equipment["attributes"]["color_mode"] == "colorida"
    assert equipment["maintenance"]["need"] == "agendada"
    assert equipment["maintenance"]["plan"]["interval_days"] == 90
    assert equipment["status_label"] == "Operacional"


async def test_validation_errors_are_problem_details(client: httpx.AsyncClient) -> None:
    payload = {
        **CAMERA_PAYLOAD,
        "organization_id": await _organization(client),
        "address": {**CAMERA_PAYLOAD["address"], "cep": "123"},
        "location": {"latitude": -49.9, "longitude": -22.2},  # invertidas
    }
    response = await client.post(
        "/api/v1/equipment", json=payload, headers=await _headers(client, Role.GESTOR)
    )
    assert response.status_code == 422
    fields = {error["field"] for error in response.json()["errors"]}
    assert {"address.cep", "location"} <= fields


async def test_invalid_type_attributes_return_field_errors(client: httpx.AsyncClient) -> None:
    payload = {
        **CAMERA_PAYLOAD,
        "type_code": "radar",
        "organization_id": await _organization(client),
        "attributes": {"enforcement_types": ["velocidade"]},
    }
    response = await client.post(
        "/api/v1/equipment", json=payload, headers=await _headers(client, Role.GESTOR)
    )
    assert response.status_code == 422
    assert response.json()["code"] == "regra_de_negocio_violada"
    assert response.json()["errors"]


async def test_full_failure_and_repair_flow(client: httpx.AsyncClient) -> None:
    equipment = await _camera(client)
    url = f"/api/v1/equipment/{equipment['id']}"
    operator = await _headers(client, Role.OPERADOR)

    failed = await client.post(
        f"{url}/status-changes",
        json={"to_status": "mau_funcionamento", "reason": "Lente quebrada"},
        headers=operator,
    )
    assert failed.status_code == 200, failed.text
    assert failed.json()["maintenance"]["need"] == "imediata"

    orders = (await client.get(f"{url}/maintenance-orders", headers=operator)).json()
    assert orders["total"] == 1
    order_url = f"/api/v1/maintenance-orders/{orders['items'][0]['id']}"

    started = await client.patch(order_url, json={"status": "em_andamento"}, headers=operator)
    assert started.status_code == 200
    assert (await client.get(url, headers=operator)).json()["status"] == "em_manutencao"

    done = await client.patch(
        order_url,
        json={"status": "concluida", "resolution_notes": "Lente trocada"},
        headers=operator,
    )
    assert done.json()["completed_at"] is not None
    final = (await client.get(url, headers=operator)).json()
    assert final["status"] == "operacional"
    assert final["maintenance"]["need"] == "agendada"

    history = (await client.get(f"{url}/status-history", headers=operator)).json()
    assert [h["to_status"] for h in history["items"]] == [
        "operacional",
        "em_manutencao",
        "mau_funcionamento",
        "operacional",
    ]


async def test_invalid_transition_is_conflict_with_allowed_options(
    client: httpx.AsyncClient,
) -> None:
    equipment = await _camera(client, status="nao_instalado", installed_on=None)
    response = await client.post(
        f"/api/v1/equipment/{equipment['id']}/status-changes",
        json={"to_status": "furtado", "reason": "teste"},
        headers=await _headers(client, Role.OPERADOR),
    )
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "transicao_de_situacao_invalida"
    assert body["allowed_transitions"] == ["desativado", "operacional"]


async def test_patch_with_stale_version_is_conflict(client: httpx.AsyncClient) -> None:
    equipment = await _camera(client)
    url = f"/api/v1/equipment/{equipment['id']}"
    manager = await _headers(client, Role.GESTOR)
    first = await client.patch(url, json={"version": 1, "model": "Novo"}, headers=manager)
    assert first.json()["version"] == 2
    stale = await client.patch(url, json={"version": 1, "model": "Outro"}, headers=manager)
    assert stale.status_code == 409
    assert stale.json()["code"] == "versao_desatualizada"


async def test_list_with_filters_and_radius(client: httpx.AsyncClient) -> None:
    await _camera(client)
    headers = await _headers(client, Role.CONSULTA)
    near = await client.get(
        "/api/v1/equipment",
        params={"lat": -22.2140, "lng": -49.9459, "radius_m": 100, "sort": "distance"},
        headers=headers,
    )
    far = await client.get(
        "/api/v1/equipment",
        params={"lat": -22.30, "lng": -49.90, "radius_m": 100},
        headers=headers,
    )
    partial = await client.get("/api/v1/equipment", params={"lat": -22.2}, headers=headers)
    assert near.json()["total"] == 1
    assert near.json()["items"][0]["distance_m"] < 100
    assert far.json()["total"] == 0
    assert partial.status_code == 422


async def test_delete_archives_and_hides_equipment(client: httpx.AsyncClient) -> None:
    equipment = await _camera(client)
    url = f"/api/v1/equipment/{equipment['id']}"
    admin = await _headers(client, Role.ADMIN)
    assert (await client.delete(url, headers=admin)).status_code == 204
    assert (await client.get(url, headers=admin)).status_code == 404


async def test_agent_registration_and_duty_change(client: httpx.AsyncClient) -> None:
    organization_id = await _organization(client)
    manager = await _headers(client, Role.GESTOR)
    created = await client.post(
        "/api/v1/agents",
        json={
            "full_name": "Ana Paula Ribeiro",
            "registration_number": "GCM-0457",
            "role": "guarda_municipal",
            "organization_id": organization_id,
            "base_address": CAMERA_PAYLOAD["address"],
            "base_location": CAMERA_PAYLOAD["location"],
        },
        headers=manager,
    )
    assert created.status_code == 201, created.text
    agent = created.json()
    assert agent["on_duty"] is False
    changed = await client.post(
        f"/api/v1/agents/{agent['id']}/status-changes",
        json={"to_status": "em_patrulha"},
        headers=await _headers(client, Role.OPERADOR),
    )
    assert changed.json()["on_duty"] is True
    on_duty = await client.get("/api/v1/agents", params={"on_duty": True}, headers=manager)
    assert on_duty.json()["total"] == 1


async def test_agent_role_must_match_organization_kind(client: httpx.AsyncClient) -> None:
    organization_id = await _organization(client, kind="policia_militar")
    response = await client.post(
        "/api/v1/agents",
        json={
            "full_name": "João Souza",
            "registration_number": "X-1",
            "role": "agente_transito",
            "organization_id": organization_id,
            "base_address": CAMERA_PAYLOAD["address"],
            "base_location": CAMERA_PAYLOAD["location"],
        },
        headers=await _headers(client, Role.GESTOR),
    )
    assert response.status_code == 422


async def test_catalogs_expose_types_schemas_and_state_machine(client: httpx.AsyncClient) -> None:
    headers = await _headers(client, Role.CONSULTA)
    types = (await client.get("/api/v1/equipment-types", headers=headers)).json()
    camera = next(t for t in types if t["code"] == "camera")
    assert "night_vision" in camera["attributes_schema"]["properties"]
    statuses = (await client.get("/api/v1/equipment-statuses", headers=headers)).json()
    stolen = next(s for s in statuses if s["code"] == "furtado")
    assert stolen["allowed_transitions"] == ["desativado", "nao_instalado"]
    regions = (
        await client.get("/api/v1/regions", params={"include_geometry": True}, headers=headers)
    ).json()
    assert regions[0]["geometry"]["type"] == "MultiPolygon"


async def test_admin_cannot_demote_or_deactivate_themselves(client: httpx.AsyncClient) -> None:
    admin = await _headers(client, Role.ADMIN)
    me = (await client.get("/api/v1/auth/me", headers=admin)).json()
    response = await client.patch(
        f"/api/v1/users/{me['id']}", json={"is_active": False}, headers=admin
    )
    assert response.status_code == 422


async def test_deactivated_user_loses_access_immediately(client: httpx.AsyncClient) -> None:
    operator = await _headers(client, Role.OPERADOR)
    admin = await _headers(client, Role.ADMIN)
    users = (await client.get("/api/v1/users", headers=admin)).json()["items"]
    operator_id = next(u["id"] for u in users if u["role"] == "operador")
    await client.patch(f"/api/v1/users/{operator_id}", json={"is_active": False}, headers=admin)
    response = await client.get("/api/v1/equipment", headers=operator)
    assert response.status_code == 401


async def test_organization_list_counts_links_and_blocks_delete_in_use(
    client: httpx.AsyncClient,
) -> None:
    camera = await _camera(client)
    manager = await _headers(client, Role.GESTOR)
    organizations = (await client.get("/api/v1/organizations", headers=manager)).json()
    used = next(o for o in organizations if o["id"] == camera["organization"]["id"])
    assert (used["equipment_count"], used["agent_count"], used["in_use"]) == (1, 0, True)

    response = await client.delete(f"/api/v1/organizations/{used['id']}", headers=manager)
    assert response.status_code == 409


async def test_only_admins_manage_users_and_emails_are_unique(client: httpx.AsyncClient) -> None:
    payload = {
        "email": "nova.operadora@teste.dev",
        "full_name": "Nova Operadora",
        "password": "Senha-forte-123",
        "role": "operador",
    }
    manager = await _headers(client, Role.GESTOR)
    assert (await client.post("/api/v1/users", json=payload, headers=manager)).status_code == 403

    admin = await _headers(client, Role.ADMIN)
    created = await client.post("/api/v1/users", json=payload, headers=admin)
    assert created.status_code == 201, created.text
    assert created.json()["is_active"] is True
    duplicate = await client.post(
        "/api/v1/users", json={**payload, "email": payload["email"].upper()}, headers=admin
    )
    assert duplicate.status_code == 409
