"""Fábrica de modelos por provedor (LangChain), tradução de erros e disjuntor.

Um único ponto conhece os SDKs: o resto do sistema recebe um ``BaseChatModel`` e erros já
traduzidos para mensagens que o operador entende ("chave inválida", "cota excedida"...).
"""

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import SecretStr

from app.core.exceptions import AppError, BusinessRuleError, IntegrationError
from app.domain.ai_settings import (
    PROVIDER_EMBEDDING_DIM,
    PROVIDER_EMBEDDING_MODELS,
    AiProvider,
    EmbeddingsProvider,
)

logger = logging.getLogger(__name__)

_FAILURES_TO_OPEN = 3
_OPEN_SECONDS = 300.0


class AiUnavailableError(AppError):
    status_code = 503
    code = "ia_indisponivel"
    title = "Modelo de IA indisponível"


class AiNotConfiguredError(BusinessRuleError):
    code = "ia_nao_configurada"
    title = "Modelo de IA não configurado"


class AiLimitReachedError(BusinessRuleError):
    code = "limite_de_ia_atingido"
    title = "Limite diário de uso de IA atingido"


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    provider: AiProvider
    model: str
    api_key: str | None
    base_url: str | None
    timeout_seconds: float


def build_chat_model(config: ProviderConfig, *, max_tokens: int = 800) -> BaseChatModel:
    key = SecretStr(config.api_key) if config.api_key else None
    common: dict[str, Any] = {"temperature": 0, "max_retries": 2}
    if config.provider is AiProvider.ANTHROPIC:
        from langchain_anthropic import ChatAnthropic

        if key is None:
            raise AiNotConfiguredError("Informe a chave de API da Anthropic.")
        return ChatAnthropic(
            model_name=config.model,
            api_key=key,
            max_tokens=max_tokens,
            timeout=config.timeout_seconds,
            **common,
        )
    if config.provider is AiProvider.GEMINI:
        from langchain_google_genai import ChatGoogleGenerativeAI

        if key is None:
            raise AiNotConfiguredError("Informe a chave de API do Google Gemini.")
        return ChatGoogleGenerativeAI(
            model=config.model,
            api_key=key,
            max_tokens=max_tokens,
            timeout=config.timeout_seconds,
            **common,
        )
    from langchain_openai import ChatOpenAI

    if config.provider is AiProvider.OPENAI and key is None:
        raise AiNotConfiguredError("Informe a chave de API da OpenAI.")
    if config.provider is AiProvider.OPENAI_COMPATIBLE and not config.base_url:
        raise AiNotConfiguredError("Informe a URL base do servidor compatível com OpenAI.")
    return ChatOpenAI(
        model=config.model,
        api_key=key or SecretStr("sem-chave"),  # servidores locais (Ollama) ignoram a chave
        base_url=config.base_url if config.provider is AiProvider.OPENAI_COMPATIBLE else None,
        max_completion_tokens=max_tokens,
        timeout=config.timeout_seconds,
        **common,
    )


def build_embeddings(provider: EmbeddingsProvider, api_key: str) -> tuple[Embeddings, str]:
    """Embeddings do provedor com dimensão fixa (768) para o índice ``embedding_provider``."""
    model = PROVIDER_EMBEDDING_MODELS[provider]
    if provider is EmbeddingsProvider.GEMINI:
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        return (
            GoogleGenerativeAIEmbeddings(
                model=f"models/{model}",
                api_key=SecretStr(api_key),
                output_dimensionality=PROVIDER_EMBEDDING_DIM,
            ),
            model,
        )
    from langchain_openai import OpenAIEmbeddings

    return (
        OpenAIEmbeddings(
            model=model, openai_api_key=SecretStr(api_key), dimensions=PROVIDER_EMBEDDING_DIM
        ),
        model,
    )


def translate_error(exc: Exception) -> AppError:
    """Erro do SDK → mensagem acionável (sem vazar a chave nem o corpo da resposta)."""
    if isinstance(exc, AppError):
        return exc
    status = getattr(exc, "status_code", None) or getattr(
        getattr(exc, "response", None), "status_code", None
    )
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    if status == 401 or "authentication" in name or "api key" in text or "api_key" in text:
        return IntegrationError("Chave de API inválida ou revogada.")
    if status == 403 or "permission" in name:
        return IntegrationError("A chave não tem permissão para este modelo.")
    if status == 404 or "notfound" in name or "not found" in text:
        return IntegrationError("Modelo não encontrado neste provedor.")
    if status == 429 or "ratelimit" in name or "quota" in text or "resource_exhausted" in text:
        return IntegrationError("Cota excedida ou limite de requisições do provedor atingido.")
    if "timeout" in name or "timed out" in text:
        return AiUnavailableError("O provedor não respondeu a tempo.")
    if "connect" in name or "connection" in text:
        return AiUnavailableError("Sem conexão com o provedor de IA.")
    return IntegrationError(f"Falha no provedor de IA ({type(exc).__name__}).")


class CircuitBreaker:
    """Após 3 falhas de rede seguidas, pausa as chamadas por 5 min (protege a operação)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._failures = 0
        self._open_until = 0.0

    def check(self) -> None:
        with self._lock:
            if time.monotonic() < self._open_until:
                raise AiUnavailableError(
                    "IA pausada por falhas seguidas de conexão; usando o modo determinístico."
                )

    def success(self) -> None:
        with self._lock:
            self._failures = 0

    def failure(self, error: AppError) -> None:
        if not isinstance(error, AiUnavailableError):
            return  # chave inválida ou cota não é instabilidade: não abre o disjuntor
        with self._lock:
            self._failures += 1
            if self._failures >= _FAILURES_TO_OPEN:
                self._open_until = time.monotonic() + _OPEN_SECONDS
                self._failures = 0
                logger.warning("Disjuntor da IA aberto", extra={"seconds": _OPEN_SECONDS})


BREAKER = CircuitBreaker()
