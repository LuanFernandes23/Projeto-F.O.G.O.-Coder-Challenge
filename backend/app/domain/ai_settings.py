"""Configuração do modelo de IA trazido pelo usuário (BYOK): provedores e regras puras."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class AiProvider(StrEnum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    OPENAI_COMPATIBLE = "openai_compatible"  # Ollama, OpenRouter, Azure, Groq...


class EmbeddingsProvider(StrEnum):
    LOCAL = "local"  # modelo multilíngue embutido na imagem: funciona sem chave
    OPENAI = "openai"
    GEMINI = "gemini"


PROVIDER_LABELS: dict[AiProvider, str] = {
    AiProvider.OPENAI: "OpenAI",
    AiProvider.ANTHROPIC: "Anthropic",
    AiProvider.GEMINI: "Google Gemini",
    AiProvider.OPENAI_COMPATIBLE: "Compatível com OpenAI",
}

DEFAULT_MODELS: dict[AiProvider, str] = {
    AiProvider.OPENAI: "gpt-4.1-mini",
    AiProvider.ANTHROPIC: "claude-haiku-4-5",
    AiProvider.GEMINI: "gemini-2.5-flash",
    AiProvider.OPENAI_COMPATIBLE: "llama3.1",
}

# Embeddings do provedor (dimensão fixa 768 para caber num único índice HNSW).
PROVIDER_EMBEDDING_MODELS: dict[EmbeddingsProvider, str] = {
    EmbeddingsProvider.OPENAI: "text-embedding-3-small",
    EmbeddingsProvider.GEMINI: "gemini-embedding-001",
}
PROVIDER_EMBEDDING_DIM = 768
LOCAL_EMBEDDING_DIM = 384


@dataclass(slots=True)
class AiSettings:
    enabled: bool
    provider: AiProvider
    model: str
    base_url: str | None
    api_key_encrypted: bytes | None
    key_last4: str | None
    embeddings_provider: EmbeddingsProvider
    daily_call_limit: int
    daily_token_limit: int
    updated_at: datetime | None
    updated_by: UUID | None

    @property
    def has_key(self) -> bool:
        return self.api_key_encrypted is not None

    @property
    def usable(self) -> bool:
        """IA ligada e com o necessário para chamar o modelo (compatível pode dispensar chave)."""
        if not self.enabled or not self.model:
            return False
        return self.has_key or self.provider is AiProvider.OPENAI_COMPATIBLE

    @property
    def provider_embeddings_active(self) -> bool:
        """Embeddings do provedor usam a mesma chave do chat (OpenAI ou Gemini)."""
        return (
            self.usable
            and self.embeddings_provider is not EmbeddingsProvider.LOCAL
            and self.embeddings_provider.value == self.provider.value
        )


def mask_key(key: str) -> str:
    """Só os 4 últimos caracteres saem do servidor."""
    return key[-4:] if len(key) >= 8 else ""


def default_settings() -> AiSettings:
    return AiSettings(
        enabled=False,
        provider=AiProvider.OPENAI,
        model=DEFAULT_MODELS[AiProvider.OPENAI],
        base_url=None,
        api_key_encrypted=None,
        key_last4=None,
        embeddings_provider=EmbeddingsProvider.LOCAL,
        daily_call_limit=200,
        daily_token_limit=200_000,
        updated_at=None,
        updated_by=None,
    )
