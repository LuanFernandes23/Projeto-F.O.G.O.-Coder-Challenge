"""API da Parte 3: chave de IA só de escrita, RBAC, previsões e governança do PROMETHEUS."""

import httpx
import pytest

from app.core.permissions import Role
from tests.api.test_api import _headers, app, client  # noqa: F401  (fixtures compartilhadas)

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_database")]


async def test_ai_settings_are_admin_only_and_key_is_write_only(
    client: httpx.AsyncClient,  # noqa: F811
) -> None:
    manager = await _headers(client, Role.GESTOR)
    assert (await client.get("/api/v1/ai/settings", headers=manager)).status_code == 403

    admin = await _headers(client, Role.ADMIN)
    initial = (await client.get("/api/v1/ai/settings", headers=admin)).json()
    assert initial["enabled"] is False
    assert initial["has_key"] is False
    assert {p["code"] for p in initial["providers"]} == {
        "openai",
        "anthropic",
        "gemini",
        "openai_compatible",
    }

    payload = {
        "enabled": True,
        "provider": "openai",
        "model": "gpt-4.1-mini",
        "api_key": "sk-test-1234567890abcd",
        "embeddings_provider": "local",
    }
    saved = await client.put("/api/v1/ai/settings", json=payload, headers=admin)
    assert saved.status_code == 200, saved.text
    body = saved.json()["settings"]
    assert body["has_key"] is True
    assert body["key_hint"] == "…abcd"
    assert "sk-test" not in saved.text  # a chave nunca volta ao cliente

    # Salvar sem a chave mantém a atual; trocar de provedor descarta a chave do anterior.
    kept = await client.put("/api/v1/ai/settings", json={**payload, "api_key": None}, headers=admin)
    assert kept.json()["settings"]["has_key"] is True
    switched = await client.put(
        "/api/v1/ai/settings",
        json={**payload, "provider": "anthropic", "model": "claude-haiku-4-5", "api_key": None},
        headers=admin,
    )
    assert switched.json()["settings"]["has_key"] is False


async def test_provider_embeddings_require_the_same_provider(
    client: httpx.AsyncClient,  # noqa: F811
) -> None:
    admin = await _headers(client, Role.ADMIN)
    response = await client.put(
        "/api/v1/ai/settings",
        json={
            "enabled": True,
            "provider": "anthropic",
            "model": "claude-haiku-4-5",
            "api_key": "sk-ant-1234567890",
            "embeddings_provider": "openai",
        },
        headers=admin,
    )
    assert response.status_code == 422


async def test_predictions_report_not_ready_before_first_fit(
    client: httpx.AsyncClient,  # noqa: F811
) -> None:
    viewer = await _headers(client, Role.CONSULTA)
    response = await client.get("/api/v1/predictions/city", headers=viewer)
    assert response.status_code == 200
    assert response.json() == {"ready": False, "data": {}}
    refresh = await client.post("/api/v1/predictions/refresh", headers=viewer)
    assert refresh.status_code == 403


async def test_prometheus_governance_requires_manager(
    client: httpx.AsyncClient,  # noqa: F811
) -> None:
    operator = await _headers(client, Role.OPERADOR)
    settings = (await client.get("/api/v1/prometheus/settings", headers=operator)).json()
    assert settings["mode"] == "autonomo"
    assert {p["action_type"] for p in settings["policies"]} >= {
        "abrir_os_preventiva",
        "reforcar_regiao",
    }
    change = {
        "mode": "sugestao",
        "approval_ttl_minutes": 15,
        "policies": [
            {
                "action_type": "abrir_os_preventiva",
                "threshold": 0.7,
                "enabled": True,
                "max_per_hour": 4,
            }
        ],
    }
    assert (
        await client.put("/api/v1/prometheus/settings", json=change, headers=operator)
    ).status_code == 403
    manager = await _headers(client, Role.GESTOR)
    updated = await client.put("/api/v1/prometheus/settings", json=change, headers=manager)
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["mode"] == "sugestao"
    assert body["approval_ttl_minutes"] == 15
    policy = next(p for p in body["policies"] if p["action_type"] == "abrir_os_preventiva")
    assert policy["threshold"] == 0.7
    stats = await client.get("/api/v1/prometheus/stats", headers=operator)
    assert stats.status_code == 200
    assert stats.json()["mode"] == "sugestao"
