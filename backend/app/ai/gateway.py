"""Porta única para o modelo de IA do usuário: configuração, limites, disjuntor e consumo.

Toda chamada passa por aqui: confere se a IA está ligada e dentro dos limites diários, monta o
modelo do provedor, traduz erros e registra tokens e custo em ``ai_usage``. Quando a IA não
está configurada, devolve ``None`` e quem chamou usa o caminho determinístico.
"""

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, TypeVar
from zoneinfo import ZoneInfo

from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from pydantic import BaseModel

from app.ai.crypto import SecretBox
from app.ai.pricing import estimate_cost
from app.ai.providers import (
    BREAKER,
    AiLimitReachedError,
    ProviderConfig,
    build_chat_model,
    build_embeddings,
    translate_error,
)
from app.core.clock import Clock
from app.core.exceptions import AppError
from app.domain.ai_settings import AiSettings
from app.services.ports import UnitOfWork

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def usage_of(messages: list[BaseMessage] | AIMessage) -> tuple[int, int]:
    items = messages if isinstance(messages, list) else [messages]
    input_tokens = output_tokens = 0
    for message in items:
        usage = getattr(message, "usage_metadata", None) or {}
        input_tokens += int(usage.get("input_tokens", 0) or 0)
        output_tokens += int(usage.get("output_tokens", 0) or 0)
    return input_tokens, output_tokens


class AiGateway:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        clock: Clock,
        box: SecretBox,
        tz: ZoneInfo,
        timeout_seconds: float,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._box = box
        self._tz = tz
        self._timeout = timeout_seconds

    async def settings(self) -> AiSettings:
        async with self._uow_factory() as uow:
            return await uow.ai.get_settings()

    def config_from(self, settings: AiSettings) -> ProviderConfig:
        key = self._box.decrypt(settings.api_key_encrypted) if settings.api_key_encrypted else None
        return ProviderConfig(
            settings.provider, settings.model, key, settings.base_url, self._timeout
        )

    async def active_config(self) -> ProviderConfig | None:
        """Configuração utilizável agora, ou None (IA desligada → modo determinístico)."""
        settings = await self.settings()
        if not settings.usable:
            return None
        return self.config_from(settings)

    async def _check_limits(self, settings: AiSettings) -> None:
        start = datetime.now(self._tz).replace(hour=0, minute=0, second=0, microsecond=0)
        async with self._uow_factory() as uow:
            calls, tokens = await uow.ai.usage_since(start)
        if calls >= settings.daily_call_limit:
            raise AiLimitReachedError(
                f"Limite diário de {settings.daily_call_limit} chamadas à IA atingido."
            )
        if tokens >= settings.daily_token_limit:
            raise AiLimitReachedError(
                f"Limite diário de {settings.daily_token_limit} tokens de IA atingido."
            )

    async def chat_model(self, feature: str, *, max_tokens: int = 800) -> BaseChatModel | None:
        settings = await self.settings()
        if not settings.usable:
            return None
        BREAKER.check()
        await self._check_limits(settings)
        return build_chat_model(self.config_from(settings), max_tokens=max_tokens)

    async def structured(
        self,
        feature: str,
        schema: type[T],
        messages: list[BaseMessage],
        *,
        max_tokens: int = 700,
    ) -> tuple[T, int] | None:
        """Saída estruturada (Pydantic). None se a IA estiver desligada."""
        settings = await self.settings()
        if not settings.usable:
            return None
        BREAKER.check()
        await self._check_limits(settings)
        config = self.config_from(settings)
        model = build_chat_model(config, max_tokens=max_tokens)
        try:
            result: dict[str, Any] = await model.with_structured_output(
                schema, include_raw=True
            ).ainvoke(messages)  # type: ignore[assignment]
        except Exception as exc:
            error = translate_error(exc)
            BREAKER.failure(error)
            await self.record(feature, config, 0, 0, ok=False, error=error.detail)
            raise error from exc
        BREAKER.success()
        raw = result.get("raw")
        input_tokens, output_tokens = usage_of(raw) if isinstance(raw, AIMessage) else (0, 0)
        parsed = result.get("parsed")
        if not isinstance(parsed, schema):
            await self.record(
                feature, config, input_tokens, output_tokens, ok=False, error="resposta inválida"
            )
            raise translate_error(ValueError("O modelo não devolveu a estrutura esperada."))
        await self.record(feature, config, input_tokens, output_tokens, ok=True)
        return parsed, input_tokens + output_tokens

    async def record(
        self,
        feature: str,
        config: ProviderConfig,
        input_tokens: int,
        output_tokens: int,
        *,
        ok: bool,
        error: str | None = None,
    ) -> None:
        await self._add_usage(
            feature, config.provider.value, config.model, input_tokens, output_tokens, ok, error
        )

    async def _add_usage(
        self,
        feature: str,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        ok: bool,
        error: str | None,
    ) -> None:
        async with self._uow_factory() as uow:
            await uow.ai.add_usage(
                at=self._clock.now(),
                provider=provider,
                model=model,
                feature=feature,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=estimate_cost(model, input_tokens, output_tokens),
                ok=ok,
                error=error,
            )
            await uow.commit()

    async def _embeddings(self) -> tuple[Embeddings, str, str] | None:
        """Cliente de embeddings do provedor (OpenAI/Gemini com a mesma chave), se configurado."""
        settings = await self.settings()
        if not settings.provider_embeddings_active or settings.api_key_encrypted is None:
            return None
        client, model = build_embeddings(
            settings.embeddings_provider, self._box.decrypt(settings.api_key_encrypted)
        )
        return client, model, settings.embeddings_provider.value

    async def _embed(
        self, feature: str, texts: list[str], *, query: bool
    ) -> tuple[Any, str] | None:
        found = await self._embeddings()
        if found is None:
            return None
        client, model, provider = found
        # O SDK não devolve o uso de embeddings: estimativa de ~4 caracteres por token.
        tokens = sum(len(t) for t in texts) // 4 + 1
        try:
            BREAKER.check()
            vectors: Any = (
                await client.aembed_query(texts[0])
                if query
                else await client.aembed_documents(texts)
            )
        except Exception as exc:
            error = translate_error(exc)
            BREAKER.failure(error)
            await self._add_usage(feature, provider, model, 0, 0, False, error.detail)
            raise error from exc
        BREAKER.success()
        await self._add_usage(feature, provider, model, tokens, 0, True, None)
        return vectors, model

    async def embed_documents(self, texts: list[str]) -> tuple[list[list[float]], str] | None:
        """Vetores do provedor para indexar a base. None se não configurado; erros sobem."""
        return await self._embed("embeddings_base", texts, query=False)

    async def embed_query(self, text: str) -> tuple[list[float], str] | None:
        """Vetor da consulta. Se o provedor falhar, None: a busca segue com BM25 e o local."""
        try:
            return await self._embed("embeddings_busca", [text], query=True)
        except AppError as exc:
            logger.warning("Embedding da consulta indisponível", extra={"error": exc.detail})
            return None

    async def usage(self, days: int) -> list[dict[str, Any]]:
        since = self._clock.now() - timedelta(days=days)
        async with self._uow_factory() as uow:
            return await uow.ai.usage_by_day(since, self._tz.key)


def safe_detail(exc: Exception) -> str:
    return exc.detail if isinstance(exc, AppError) else type(exc).__name__
