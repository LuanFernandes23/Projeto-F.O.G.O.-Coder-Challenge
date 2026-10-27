"""Base de conhecimento do PROMETHEUS: ingestão e busca híbrida (BM25 + vetores, fusão RRF).

- Ingestão idempotente (hash do conteúdo): arquivos ``knowledge/*.md`` no bootstrap e
  documentos criados/editados na tela de administração.
- Busca: BM25 sobre lexemas em português, vetor local (sempre) e vetor do provedor (se a
  chave de IA tiver embeddings), fundidos por RRF. Cada resultado traz a posição em cada busca
  e a similaridade, para a tela de teste e para a auditoria das decisões.
"""

import asyncio
import hashlib
import logging
import pathlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.ai.gateway import AiGateway
from app.core.clock import Clock
from app.core.exceptions import BusinessRuleError, NotFoundError
from app.domain.guardrails import (
    DOCUMENT_MAX_CHARS,
    SCREEN_MAX_AUTONOMY,
    FindingKind,
    scan,
)
from app.domain.knowledge.retrieval import (
    CHUNKER_VERSION,
    Bm25Index,
    evidence_from_similarity,
    parse_markdown,
    rrf,
    split_markdown,
)
from app.domain.prometheus.entities import RISK_ORDER, RiskClass
from app.knowledge.embeddings import TextEmbedder
from app.services.ports import UnitOfWork

logger = logging.getLogger(__name__)

_SLUG = re.compile(r"[^a-z0-9]+")
_CANDIDATES = 20

# Cache do índice BM25 por processo, invalidado pela "versão" da base (data + contagem).
_BM25_CACHE: dict[str, Bm25Index] = {}


@dataclass(frozen=True, slots=True)
class SearchHit:
    chunk: dict[str, Any]
    rrf: float
    ranks: dict[str, int]
    similarity: float  # cosseno do vetor local (0-1)

    @property
    def evidence(self) -> float:
        return evidence_from_similarity(self.similarity)

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.chunk,
            "rrf": round(self.rrf, 5),
            "ranks": self.ranks,
            "similarity": round(self.similarity, 3),
            "evidence": round(self.evidence, 3),
        }


def slugify(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.lower())
    plain = "".join(char for char in decomposed if not unicodedata.combining(char)).strip()
    return _SLUG.sub("-", plain).strip("-")[:120] or "documento"


class KnowledgeService:
    def __init__(
        self,
        uow: UnitOfWork,
        clock: Clock,
        embedder: TextEmbedder,
        gateway: AiGateway | None = None,
    ) -> None:
        self._uow = uow
        self._clock = clock
        self._embedder = embedder
        self._gateway = gateway

    # ---- ingestão -----------------------------------------------------------------------------

    async def ingest_directory(self, directory: str) -> dict[str, int]:
        created = unchanged = 0
        for slug, content in await asyncio.to_thread(_read_markdown, directory):
            blocking = [f for f in scan(content) if f.kind is not FindingKind.DADO_PESSOAL]
            if blocking:
                logger.error(
                    "Documento recusado pelos guardrails",
                    extra={"slug": slug, "findings": [f.label for f in blocking]},
                )
                continue
            changed = await self._ingest(slug, content, "arquivo")
            created += int(changed)
            unchanged += int(not changed)
        logger.info(
            "Base de conhecimento sincronizada",
            extra={"indexed": created, "unchanged": unchanged},
        )
        return {"indexed": created, "unchanged": unchanged}

    async def save_document(
        self,
        *,
        slug: str | None,
        title: str,
        doc_type: str,
        metadata: dict[str, Any],
        body: str,
        actor_id: UUID,
    ) -> UUID:
        target = slug or slugify(title)
        check_document(title, metadata, body)
        text = _render(title, doc_type, metadata, body)
        await self._ingest(target, text, "tela", actor_id=actor_id, force=True)
        async with self._uow as uow:
            found = await uow.knowledge.find_by_slug(target)
        if found is None:
            raise NotFoundError("Documento não encontrado após salvar.")
        return found[0]

    async def _ingest(
        self,
        slug: str,
        text: str,
        source: str,
        *,
        actor_id: UUID | None = None,
        force: bool = False,
    ) -> bool:
        digest = hashlib.sha256(f"v{CHUNKER_VERSION}\n{text}".encode()).hexdigest()
        async with self._uow as uow:
            existing = await uow.knowledge.find_by_slug(slug)
        if existing and existing[1] == digest and not force:
            return False
        parsed = parse_markdown(slug, text)
        chunks = split_markdown(parsed.title, parsed.body)
        texts = [f"{c.heading}\n{c.content}" for c in chunks]
        local = await self._embedder.embed(texts)
        provider_vectors: list[list[float]] | None = None
        provider_model: str | None = None
        if self._gateway is not None:
            embedded = await self._gateway.embed_documents(texts)
            if embedded is not None:
                provider_vectors, provider_model = embedded
        async with self._uow as uow:
            lexemes = await uow.knowledge.lexemes(texts)
            document_id = await uow.knowledge.upsert_document(
                slug=slug,
                title=parsed.title,
                doc_type=parsed.doc_type,
                metadata=parsed.metadata,
                content=text,
                content_hash=digest,
                source=source,
                updated_by=actor_id,
                at=self._clock.now(),
            )
            await uow.knowledge.replace_chunks(
                document_id,
                [
                    {
                        "ordinal": c.ordinal,
                        "heading": c.heading,
                        "content": c.content,
                        "lexemes": lexemes[i],
                        "embedding_local": local[i],
                        "embedding_provider": provider_vectors[i] if provider_vectors else None,
                        "provider_model": provider_model if provider_vectors else None,
                    }
                    for i, c in enumerate(chunks)
                ],
            )
            await uow.commit()
        return True

    async def reindex_provider(self) -> int:
        """Recalcula (ou remove) os vetores do provedor após trocar a configuração de IA."""
        async with self._uow as uow:
            items = await uow.knowledge.chunks_for_provider()
        embedded = (
            await self._gateway.embed_documents([content for _, content in items])
            if self._gateway is not None and items
            else None
        )
        async with self._uow as uow:
            if embedded is None:
                await uow.knowledge.clear_provider_embeddings()
                await uow.commit()
                return 0
            vectors, model = embedded
            await uow.knowledge.set_provider_embeddings(
                [(chunk_id, vectors[i]) for i, (chunk_id, _) in enumerate(items)], model
            )
            await uow.commit()
        return len(items)

    # ---- consulta -----------------------------------------------------------------------------

    async def list_documents(self) -> list[dict[str, Any]]:
        async with self._uow as uow:
            return await uow.knowledge.list_documents()

    async def get_document(self, document_id: UUID) -> dict[str, Any]:
        async with self._uow as uow:
            document = await uow.knowledge.get_document(document_id)
        if document is None:
            raise NotFoundError("Documento não encontrado.")
        return document

    async def delete_document(self, document_id: UUID) -> None:
        async with self._uow as uow:
            if not await uow.knowledge.delete_document(document_id):
                raise NotFoundError("Documento não encontrado.")
            await uow.commit()

    async def search(
        self,
        query: str,
        *,
        limit: int = 5,
        situation: str | None = None,
        doc_types: list[str] | None = None,
    ) -> list[SearchHit]:
        [query_vector] = await self._embedder.embed([query])
        provider_vector: list[float] | None = None
        provider_model: str | None = None
        if self._gateway is not None:
            embedded = await self._gateway.embed_query(query)
            if embedded is not None:
                provider_vector, provider_model = embedded
        async with self._uow as uow:
            version = await uow.knowledge.version()
            index = _BM25_CACHE.get(version)
            if index is None:
                index = Bm25Index.build(await uow.knowledge.all_lexemes())
                _BM25_CACHE.clear()
                _BM25_CACHE[version] = index
            [query_terms] = await uow.knowledge.lexemes([query])
            bm25 = index.search(query_terms, _CANDIDATES)
            local = await uow.knowledge.vector_search("embedding_local", query_vector, _CANDIDATES)
            rankings: dict[str, list[int]] = {
                "bm25": [chunk_id for chunk_id, _ in bm25],
                "vetor_local": [chunk_id for chunk_id, _ in local],
            }
            if provider_vector is not None:
                remote = await uow.knowledge.vector_search(
                    "embedding_provider", provider_vector, _CANDIDATES, provider_model
                )
                rankings["vetor_provedor"] = [chunk_id for chunk_id, _ in remote]
            fused = rrf(rankings)
            chunks = await uow.knowledge.chunks([chunk_id for chunk_id, _, _ in fused])
            similarity = dict(local)
            missing = [chunk_id for chunk_id, _, _ in fused if chunk_id not in similarity]
            if missing:
                # similaridade local também para os que só o BM25 achou (evidência comparável)
                for chunk_id, sim in await uow.knowledge.vector_search(
                    "embedding_local", query_vector, 200
                ):
                    similarity.setdefault(chunk_id, sim)
        hits: list[SearchHit] = []
        for chunk_id, score, ranks in fused:
            chunk = chunks.get(chunk_id)
            if chunk is None:
                continue
            meta = chunk["metadata"] or {}
            if situation and situation not in (meta.get("situacoes") or []):
                continue
            if doc_types and chunk["doc_type"] not in doc_types:
                continue
            hits.append(SearchHit(chunk, score, ranks, similarity.get(chunk_id, 0.0)))
            if len(hits) >= limit:
                break
        return hits


def check_document(title: str, metadata: dict[str, Any], body: str) -> None:
    """Guardrails dos documentos criados na tela; recusa com a lista do que foi encontrado."""
    problems: list[dict[str, str]] = [
        {"kind": f.kind.value, "label": f.label, "excerpt": f.excerpt}
        for f in scan(f"{title}\n{body}")
    ]
    if len(body) > DOCUMENT_MAX_CHARS:
        problems.append(
            {"kind": "tamanho", "label": f"Mais de {DOCUMENT_MAX_CHARS} caracteres", "excerpt": ""}
        )
    if not re.search(r"^#{2,4}\s+\S", body, re.MULTILINE):
        problems.append(
            {"kind": "estrutura", "label": "Sem seções (## Título): nada a indexar", "excerpt": ""}
        )
    if (
        RISK_ORDER[RiskClass(metadata.get("autonomia_max") or "baixo")]
        > RISK_ORDER[RiskClass(SCREEN_MAX_AUTONOMY)]
    ):
        problems.append(
            {
                "kind": "autonomia",
                "label": "Documentos da tela autorizam no máximo risco médio",
                "excerpt": "",
            }
        )
    if problems:
        raise BusinessRuleError(
            "O documento não passou nas verificações de segurança.",
            extra={"guardrails": problems, "field": "body"},
        )


def _read_markdown(directory: str) -> list[tuple[str, str]]:
    return [
        (path.stem, path.read_text(encoding="utf-8"))
        for path in sorted(pathlib.Path(directory).glob("*.md"))
    ]


def _render(title: str, doc_type: str, metadata: dict[str, Any], body: str) -> str:
    import yaml

    front = yaml.safe_dump(
        {"titulo": title, "tipo": doc_type, **metadata}, allow_unicode=True, sort_keys=False
    )
    return f"---\n{front}---\n\n{body.strip()}\n"
