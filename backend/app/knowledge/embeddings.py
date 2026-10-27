"""Embeddings locais (fastembed/ONNX, multilíngue, 384 dimensões): funcionam sem chave.

O modelo é baixado no build da imagem (``/opt/models``) e carregado uma vez por processo.
A inferência roda numa thread para não travar o loop assíncrono.
"""

import asyncio
import logging
import threading
from collections.abc import Sequence
from typing import ClassVar, Protocol

logger = logging.getLogger(__name__)


class TextEmbedder(Protocol):
    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class LocalEmbedder:
    _lock: ClassVar[threading.Lock] = threading.Lock()
    _models: ClassVar[dict[str, object]] = {}

    def __init__(self, model_name: str, cache_dir: str | None) -> None:
        self._model_name = model_name
        self._cache_dir = cache_dir

    def _model(self) -> object:
        with self._lock:
            model = self._models.get(self._model_name)
            if model is None:
                from fastembed import TextEmbedding

                logger.info("Carregando modelo de embeddings", extra={"model": self._model_name})
                model = TextEmbedding(self._model_name, cache_dir=self._cache_dir)
                self._models[self._model_name] = model
            return model

    def _embed_sync(self, texts: Sequence[str]) -> list[list[float]]:
        model = self._model()
        vectors = model.embed(list(texts))  # type: ignore[attr-defined]
        return [[float(x) for x in vector] for vector in vectors]

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        return await asyncio.to_thread(self._embed_sync, texts)
