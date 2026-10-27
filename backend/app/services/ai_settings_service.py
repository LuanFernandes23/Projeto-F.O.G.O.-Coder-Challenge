"""Casos de uso da configuração de IA (BYOK): ver, salvar, testar e listar modelos.

A chave é só de escrita: entra cifrada no banco e só sai mascarada (4 últimos caracteres).
"""

import logging
import time
from dataclasses import dataclass, replace
from typing import Any
from uuid import UUID

import httpx
from langchain_core.messages import HumanMessage

from app.ai.crypto import SecretBox
from app.ai.gateway import AiGateway, usage_of
from app.ai.providers import BREAKER, ProviderConfig, build_chat_model, translate_error
from app.core.clock import Clock
from app.core.exceptions import AppError, BusinessRuleError, IntegrationError
from app.domain.ai_settings import (
    AiProvider,
    AiSettings,
    EmbeddingsProvider,
    mask_key,
)
from app.services.ports import UnitOfWork

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AiSettingsChanges:
    enabled: bool
    provider: AiProvider
    model: str
    base_url: str | None
    api_key: str | None  # None = manter a chave atual
    clear_key: bool
    embeddings_provider: EmbeddingsProvider
    daily_call_limit: int
    daily_token_limit: int


@dataclass(frozen=True, slots=True)
class ConnectionTest:
    ok: bool
    latency_ms: int
    reply: str
    input_tokens: int
    output_tokens: int
    error: str | None = None


class AiSettingsService:
    def __init__(
        self,
        uow: UnitOfWork,
        clock: Clock,
        box: SecretBox,
        gateway: AiGateway,
        http: httpx.AsyncClient,
        timeout_seconds: float,
    ) -> None:
        self._uow = uow
        self._clock = clock
        self._box = box
        self._gateway = gateway
        self._http = http
        self._timeout = timeout_seconds

    async def get(self) -> AiSettings:
        async with self._uow as uow:
            return await uow.ai.get_settings()

    async def update(self, changes: AiSettingsChanges, actor_id: UUID) -> tuple[AiSettings, bool]:
        """Salva atomicamente. Devolve (configuração, embeddings mudaram → reindexar)."""
        async with self._uow as uow:
            current = await uow.ai.get_settings()
            encrypted, last4 = current.api_key_encrypted, current.key_last4
            if changes.clear_key:
                encrypted, last4 = None, None
            elif changes.api_key:
                encrypted, last4 = self._box.encrypt(changes.api_key), mask_key(changes.api_key)
            elif changes.provider is not current.provider and current.has_key:
                # A chave salva é de outro provedor: não pode ser reaproveitada.
                encrypted, last4 = None, None
            if changes.embeddings_provider is not EmbeddingsProvider.LOCAL and (
                changes.embeddings_provider.value != changes.provider.value
            ):
                raise BusinessRuleError(
                    "Embeddings do provedor exigem o mesmo provedor do chat (OpenAI ou Gemini). "
                    "Use os embeddings locais com os demais.",
                    extra={"field": "embeddings_provider"},
                )
            if changes.provider is AiProvider.OPENAI_COMPATIBLE and not changes.base_url:
                raise BusinessRuleError(
                    "Informe a URL base do servidor compatível com OpenAI.",
                    extra={"field": "base_url"},
                )
            updated = replace(
                current,
                enabled=changes.enabled,
                provider=changes.provider,
                model=changes.model.strip(),
                base_url=(changes.base_url or "").strip() or None,
                api_key_encrypted=encrypted,
                key_last4=last4,
                embeddings_provider=changes.embeddings_provider,
                daily_call_limit=changes.daily_call_limit,
                daily_token_limit=changes.daily_token_limit,
                updated_at=self._clock.now(),
                updated_by=actor_id,
            )
            await uow.ai.save_settings(updated)
            await uow.commit()
        logger.info(
            "Configuração de IA alterada",
            extra={
                "actor_id": str(actor_id),
                "provider": updated.provider.value,
                "model": updated.model,
                "enabled": updated.enabled,
                "key_changed": changes.api_key is not None or changes.clear_key,
            },
        )
        embeddings_changed = current.embeddings_provider is not updated.embeddings_provider or (
            updated.provider_embeddings_active and changes.api_key is not None
        )
        return updated, embeddings_changed

    async def _candidate(
        self, provider: AiProvider, model: str, base_url: str | None, api_key: str | None
    ) -> ProviderConfig:
        """Configuração a testar: a chave informada ou, se omitida, a salva do mesmo provedor."""
        if not api_key:
            current = await self.get()
            if current.provider is provider and current.api_key_encrypted:
                api_key = self._box.decrypt(current.api_key_encrypted)
        return ProviderConfig(provider, model, api_key, base_url, self._timeout)

    async def test(
        self, provider: AiProvider, model: str, base_url: str | None, api_key: str | None
    ) -> ConnectionTest:
        """Chamada mínima (≈ 20 tokens) antes de salvar: valida chave, modelo e rede."""
        config = await self._candidate(provider, model, base_url, api_key)
        started = time.perf_counter()
        try:
            chat = build_chat_model(config, max_tokens=8)
            message = await chat.ainvoke([HumanMessage("Responda apenas a palavra OK.")])
        except Exception as exc:
            error = translate_error(exc)
            await self._gateway.record("teste_conexao", config, 0, 0, ok=False, error=error.detail)
            return ConnectionTest(False, _ms(started), "", 0, 0, error.detail)
        input_tokens, output_tokens = usage_of(message)
        await self._gateway.record("teste_conexao", config, input_tokens, output_tokens, ok=True)
        BREAKER.success()
        reply = message.content if isinstance(message.content, str) else str(message.content)
        return ConnectionTest(True, _ms(started), reply[:60], input_tokens, output_tokens)

    async def models(
        self, provider: AiProvider, base_url: str | None, api_key: str | None
    ) -> list[str]:
        """Modelos de chat disponíveis para a chave (sem custo: só lista)."""
        config = await self._candidate(provider, "", base_url, api_key)
        if not config.api_key and provider is not AiProvider.OPENAI_COMPATIBLE:
            raise BusinessRuleError("Informe a chave para listar os modelos.")
        try:
            return await self._list_models(config)
        except AppError:
            raise
        except Exception as exc:
            raise translate_error(exc) from exc

    async def _list_models(self, config: ProviderConfig) -> list[str]:
        key = config.api_key or ""
        timeout = httpx.Timeout(self._timeout)
        if config.provider is AiProvider.ANTHROPIC:
            response = await self._http.get(
                "https://api.anthropic.com/v1/models",
                headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                params={"limit": 100},
                timeout=timeout,
            )
            ids = [m["id"] for m in _json(response).get("data", [])]
        elif config.provider is AiProvider.GEMINI:
            response = await self._http.get(
                "https://generativelanguage.googleapis.com/v1beta/models",
                headers={"x-goog-api-key": key},
                params={"pageSize": 200},
                timeout=timeout,
            )
            ids = [
                m["name"].removeprefix("models/")
                for m in _json(response).get("models", [])
                if "generateContent" in m.get("supportedGenerationMethods", [])
            ]
        else:
            base = (
                (config.base_url or "").rstrip("/")
                if config.provider is AiProvider.OPENAI_COMPATIBLE
                else "https://api.openai.com/v1"
            )
            headers = {"Authorization": f"Bearer {key}"} if key else {}
            response = await self._http.get(f"{base}/models", headers=headers, timeout=timeout)
            ids = [m["id"] for m in _json(response).get("data", [])]
            if config.provider is AiProvider.OPENAI:
                ids = [i for i in ids if i.startswith(("gpt-", "o1", "o3", "o4", "chatgpt"))]
        return sorted(set(ids))

    async def usage(self, days: int) -> list[dict[str, Any]]:
        return await self._gateway.usage(days)


def _json(response: httpx.Response) -> dict[str, Any]:
    if response.status_code in (401, 403):
        raise IntegrationError("Chave de API inválida ou sem permissão.")
    if response.status_code >= 400:
        raise IntegrationError(f"O provedor respondeu {response.status_code} ao listar modelos.")
    data: dict[str, Any] = response.json()
    return data


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
