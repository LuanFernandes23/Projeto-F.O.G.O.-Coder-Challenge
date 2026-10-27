"""Base de conhecimento: divisão em trechos, BM25 e fusão de rankings (RRF). Puro.

- Trechos: o markdown é dividido pelos títulos (cada trecho carrega o caminho de títulos como
  contexto) e, se passar do tamanho-alvo, em janelas com sobreposição.
- BM25 (Okapi, k1 = 1,2; b = 0,75) sobre os lexemas em português (radicais do PostgreSQL).
- RRF (Reciprocal Rank Fusion, k = 60): soma 1 / (k + posição) de cada busca. Não exige
  normalizar escalas diferentes (BM25 × cosseno), por isso é o padrão em busca híbrida.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import yaml

CHUNK_TARGET_CHARS = 800
CHUNK_OVERLAP_CHARS = 120
# Entra no hash da ingestão: mudar o fatiamento reindexa a base na próxima subida.
CHUNKER_VERSION = 2
BM25_K1 = 1.2
BM25_B = 0.75
RRF_K = 60

_HEADING = re.compile(r"^(#{1,4})\s+(.+?)\s*$")
_FRONT_MATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    slug: str
    title: str
    doc_type: str
    metadata: dict[str, Any]
    body: str


def parse_markdown(slug: str, text: str) -> ParsedDocument:
    """Lê o front matter YAML (titulo, tipo, situacoes, acoes_permitidas, autonomia_max…)."""
    metadata: dict[str, Any] = {}
    body = text
    match = _FRONT_MATTER.match(text)
    if match:
        loaded = yaml.safe_load(match.group(1)) or {}
        metadata = dict(loaded) if isinstance(loaded, dict) else {}
        body = text[match.end() :]
    title = str(metadata.pop("titulo", "") or _first_heading(body) or slug)
    doc_type = str(metadata.pop("tipo", "documento"))
    return ParsedDocument(slug, title, doc_type, metadata, body.strip())


def _first_heading(body: str) -> str | None:
    for line in body.splitlines():
        match = _HEADING.match(line)
        if match:
            return match.group(2)
    return None


@dataclass(frozen=True, slots=True)
class Chunk:
    ordinal: int
    heading: str
    content: str


def split_markdown(title: str, body: str) -> list[Chunk]:
    sections: list[tuple[str, list[str]]] = []
    path: list[str] = []
    current: list[str] = []
    for line in body.splitlines():
        match = _HEADING.match(line)
        if match:
            level = len(match.group(1))
            carry: list[str] = []
            if any(text.strip() for text in current):
                if not path and level > 1:
                    # Preâmbulo (título + aviso) sozinho vira um trecho quase vazio que bate com o
                    # título e toma a vaga das seções na busca: ele segue junto da primeira seção.
                    carry = [*current, ""]
                else:
                    sections.append((" › ".join([title, *path]), current))
            path = [*path[: max(level - 2, 0)], match.group(2)] if level > 1 else []
            current = carry
        else:
            current.append(line)
    if any(text.strip() for text in current):
        sections.append((" › ".join([title, *path]), current))

    chunks: list[Chunk] = []
    for heading, lines in sections:
        text = "\n".join(lines).strip()
        for piece in _windows(text):
            chunks.append(Chunk(len(chunks), heading[:300], piece))
    return chunks


def _windows(text: str) -> list[str]:
    if len(text) <= CHUNK_TARGET_CHARS:
        return [text]
    pieces: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + CHUNK_TARGET_CHARS)
        if end < len(text):  # corta no fim de frase/linha mais próximo
            cut = max(text.rfind(". ", start, end), text.rfind("\n", start, end))
            if cut > start + CHUNK_TARGET_CHARS // 2:
                end = cut + 1
        pieces.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - CHUNK_OVERLAP_CHARS, start + 1)
    return [p for p in pieces if p]


@dataclass(slots=True)
class Bm25Index:
    """Índice BM25 em memória (a base é pequena: centenas de trechos)."""

    doc_ids: list[int]
    term_freqs: list[Counter[str]]
    lengths: list[int]
    document_freq: Counter[str] = field(default_factory=Counter)
    avg_length: float = 0.0

    @classmethod
    def build(cls, items: Sequence[tuple[int, Sequence[str]]]) -> Bm25Index:
        index = cls(
            [i for i, _ in items], [Counter(t) for _, t in items], [len(t) for _, t in items]
        )
        for freqs in index.term_freqs:
            index.document_freq.update(freqs.keys())
        index.avg_length = sum(index.lengths) / max(len(index.lengths), 1)
        return index

    def search(self, query_terms: Sequence[str], limit: int) -> list[tuple[int, float]]:
        n = len(self.doc_ids)
        scores: list[tuple[int, float]] = []
        unique = set(query_terms)
        for pos, freqs in enumerate(self.term_freqs):
            score = 0.0
            for term in unique:
                tf = freqs.get(term, 0)
                if not tf:
                    continue
                df = self.document_freq[term]
                idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
                norm = tf + BM25_K1 * (1 - BM25_B + BM25_B * self.lengths[pos] / self.avg_length)
                score += idf * tf * (BM25_K1 + 1) / norm
            if score > 0:
                scores.append((self.doc_ids[pos], score))
        scores.sort(key=lambda item: item[1], reverse=True)
        return scores[:limit]


def rrf(
    rankings: Mapping[str, Sequence[int]], k: int = RRF_K
) -> list[tuple[int, float, dict[str, int]]]:
    """Funde rankings: [(id, score RRF, {busca: posição})], do mais relevante ao menos."""
    scores: dict[int, float] = {}
    positions: dict[int, dict[str, int]] = {}
    for name, ranking in rankings.items():
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
            positions.setdefault(item, {})[name] = rank
    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    return [(item, score, positions[item]) for item, score in ordered]


def evidence_from_similarity(similarity: float) -> float:
    """Converte a similaridade de cosseno do trecho autorizador em evidência 0-1.

    Calibrado para o modelo multilíngue local (medido na base: trechos certos ficam entre
    0,45 e 0,65; ruído abaixo de 0,15): ≤ 0,15 → 0, ≥ 0,50 → 1, linear no meio. Mostrado na
    tela junto com o trecho, para auditoria.
    """
    return max(0.0, min(1.0, (similarity - 0.15) / 0.35))
