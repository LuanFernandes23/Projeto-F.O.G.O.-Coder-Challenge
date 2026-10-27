"""Persistência da base de conhecimento: documentos, trechos, lexemas e vetores (pgvector)."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.intelligence import KnowledgeChunkModel, KnowledgeDocumentModel


class SqlKnowledgeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lexemes(self, texts: Sequence[str]) -> list[list[str]]:
        """Radicais em português (dicionário do PostgreSQL), repetidos pela frequência."""
        result: list[list[str]] = []
        for content in texts:
            rows = await self._session.execute(
                text(
                    "SELECT lexeme, coalesce(array_length(positions, 1), 1) AS tf "
                    "FROM unnest(to_tsvector('portuguese', :content))"
                ),
                {"content": content},
            )
            result.append([r.lexeme for r in rows for _ in range(int(r.tf))])
        return result

    async def list_documents(self) -> list[dict[str, Any]]:
        chunks = (
            select(KnowledgeChunkModel.document_id, func.count().label("n"))
            .group_by(KnowledgeChunkModel.document_id)
            .subquery()
        )
        rows = await self._session.execute(
            select(KnowledgeDocumentModel, func.coalesce(chunks.c.n, 0))
            .outerjoin(chunks, chunks.c.document_id == KnowledgeDocumentModel.id)
            .order_by(KnowledgeDocumentModel.doc_type, KnowledgeDocumentModel.title)
        )
        return [_document(doc) | {"chunks": int(n)} for doc, n in rows.all()]

    async def get_document(self, document_id: UUID) -> dict[str, Any] | None:
        doc = await self._session.get(KnowledgeDocumentModel, document_id)
        if doc is None:
            return None
        rows = await self._session.execute(
            select(KnowledgeChunkModel)
            .where(KnowledgeChunkModel.document_id == document_id)
            .order_by(KnowledgeChunkModel.ordinal)
        )
        return _document(doc) | {
            "content": doc.content,
            "chunk_list": [
                {
                    "id": c.id,
                    "ordinal": c.ordinal,
                    "heading": c.heading,
                    "content": c.content,
                    "has_provider_embedding": c.embedding_provider is not None,
                }
                for c in rows.scalars()
            ],
        }

    async def find_by_slug(self, slug: str) -> tuple[UUID, str] | None:
        row = (
            await self._session.execute(
                select(KnowledgeDocumentModel.id, KnowledgeDocumentModel.content_hash).where(
                    KnowledgeDocumentModel.slug == slug
                )
            )
        ).first()
        return (row.id, row.content_hash) if row else None

    async def upsert_document(
        self,
        *,
        slug: str,
        title: str,
        doc_type: str,
        metadata: dict[str, Any],
        content: str,
        content_hash: str,
        source: str,
        updated_by: UUID | None,
        at: datetime,
    ) -> UUID:
        existing = await self.find_by_slug(slug)
        values = {
            "title": title,
            "doc_type": doc_type,
            "metadata_": metadata,
            "content": content,
            "content_hash": content_hash,
            "source": source,
            "updated_by": updated_by,
            "updated_at": at,
        }
        if existing:
            await self._session.execute(
                update(KnowledgeDocumentModel)
                .where(KnowledgeDocumentModel.id == existing[0])
                .values(**values)
            )
            return existing[0]
        result = await self._session.execute(
            insert(KnowledgeDocumentModel)
            .values(slug=slug, **values)
            .returning(KnowledgeDocumentModel.id)
        )
        return UUID(str(result.scalar_one()))

    async def replace_chunks(self, document_id: UUID, chunks: Sequence[dict[str, Any]]) -> None:
        await self._session.execute(
            delete(KnowledgeChunkModel).where(KnowledgeChunkModel.document_id == document_id)
        )
        if chunks:
            await self._session.execute(
                insert(KnowledgeChunkModel), [{"document_id": document_id, **c} for c in chunks]
            )

    async def delete_document(self, document_id: UUID) -> bool:
        result = await self._session.execute(
            delete(KnowledgeDocumentModel)
            .where(KnowledgeDocumentModel.id == document_id)
            .returning(KnowledgeDocumentModel.id)
        )
        return result.first() is not None

    async def version(self) -> str:
        row = (
            await self._session.execute(
                select(func.max(KnowledgeDocumentModel.updated_at), func.count())
            )
        ).one()
        return f"{row[0]}|{row[1]}"

    async def all_lexemes(self) -> list[tuple[int, list[str]]]:
        rows = await self._session.execute(
            select(KnowledgeChunkModel.id, KnowledgeChunkModel.lexemes)
        )
        return [(r.id, list(r.lexemes)) for r in rows]

    async def vector_search(
        self, column: str, vector: Sequence[float], limit: int, model: str | None = None
    ) -> list[tuple[int, float]]:
        target = getattr(KnowledgeChunkModel, column)
        distance = target.cosine_distance(list(vector))
        stmt = select(KnowledgeChunkModel.id, (1 - distance).label("similarity")).where(
            target.is_not(None)
        )
        if model is not None:
            stmt = stmt.where(KnowledgeChunkModel.provider_model == model)
        rows = await self._session.execute(stmt.order_by(distance).limit(limit))
        return [(r.id, float(r.similarity)) for r in rows]

    async def chunks(self, ids: Sequence[int]) -> dict[int, dict[str, Any]]:
        if not ids:
            return {}
        rows = await self._session.execute(
            select(KnowledgeChunkModel, KnowledgeDocumentModel)
            .join(
                KnowledgeDocumentModel,
                KnowledgeDocumentModel.id == KnowledgeChunkModel.document_id,
            )
            .where(KnowledgeChunkModel.id.in_(list(ids)))
        )
        return {
            chunk.id: {
                "chunk_id": chunk.id,
                "heading": chunk.heading,
                "content": chunk.content,
                "document_id": str(doc.id),
                "slug": doc.slug,
                "title": doc.title,
                "doc_type": doc.doc_type,
                "metadata": doc.metadata_,
            }
            for chunk, doc in rows.all()
        }

    async def chunks_for_provider(self) -> list[tuple[int, str]]:
        rows = await self._session.execute(
            select(KnowledgeChunkModel.id, KnowledgeChunkModel.heading, KnowledgeChunkModel.content)
        )
        return [(r.id, f"{r.heading}\n{r.content}") for r in rows]

    async def set_provider_embeddings(
        self, items: Sequence[tuple[int, list[float]]], model: str | None
    ) -> None:
        for chunk_id, vector in items:
            await self._session.execute(
                update(KnowledgeChunkModel)
                .where(KnowledgeChunkModel.id == chunk_id)
                .values(embedding_provider=vector, provider_model=model)
            )

    async def clear_provider_embeddings(self) -> None:
        await self._session.execute(
            update(KnowledgeChunkModel).values(embedding_provider=None, provider_model=None)
        )


def _document(doc: KnowledgeDocumentModel) -> dict[str, Any]:
    return {
        "id": doc.id,
        "slug": doc.slug,
        "title": doc.title,
        "doc_type": doc.doc_type,
        "metadata": doc.metadata_,
        "source": doc.source,
        "updated_at": doc.updated_at,
    }
