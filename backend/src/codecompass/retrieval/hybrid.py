"""Hybrid retrieval: fuse, pin, pack, pre-check (FR-013, FR-015, research R6/R7, task T141).

Fusion is Reciprocal Rank Fusion written here (~20 lines) rather than LangChain's
EnsembleRetriever (moved to the legacy langchain-classic package in LangChain 1.x), so each
chunk's per-retriever rank and fused score go straight into the trace.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.runnables import RunnableConfig
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from codecompass.config import Settings
from codecompass.retrieval.retrievers import LexicalRetriever, SymbolRetriever, VectorRetriever

RRF_K = 60


@dataclass
class RetrievalResult:
    packed: list[Document]  # what the LLM sees
    ranked: list[Document] = field(default_factory=list)  # everything, fused order (for traces)
    found: bool = True  # False → the not-found pre-check fired (FR-013)


def fuse(vector: list[Document], lexical: list[Document], symbol: list[Document]) -> list[Document]:
    """RRF over vector + lexical; exact symbol hits are pinned first (FR-015)."""
    merged: dict[Any, dict[str, Any]] = {}
    docs: dict[Any, Document] = {}
    scores: dict[Any, float] = {}
    for ranked, rank_key in ((vector, "vector_rank"), (lexical, "lexical_rank")):
        for doc in ranked:
            cid = doc.metadata["chunk_id"]
            docs.setdefault(cid, doc)
            merged.setdefault(cid, {}).update(doc.metadata)
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (RRF_K + doc.metadata[rank_key])
    for doc in symbol:
        cid = doc.metadata["chunk_id"]
        docs.setdefault(cid, doc)
        merged.setdefault(cid, {}).update(doc.metadata)
        scores.setdefault(cid, 0.0)

    pinned = [d.metadata["chunk_id"] for d in symbol]
    rest = sorted((c for c in scores if c not in set(pinned)), key=lambda c: -scores[c])
    out: list[Document] = []
    for cid in [*pinned, *rest]:
        meta = {**merged[cid], "fused_score": round(scores[cid], 6), "symbol_hit": cid in pinned}
        out.append(Document(page_content=docs[cid].page_content, metadata=meta))
    return out


def pack(ranked: list[Document], max_chunks: int, max_tokens: int) -> list[Document]:
    """Keep the best chunks within the context budget, dropping spans already covered."""
    packed: list[Document] = []
    tokens = 0
    for doc in ranked:
        m = doc.metadata
        covered = any(
            p.metadata["path"] == m["path"]
            and p.metadata["start_line"] <= m["start_line"]
            and m["end_line"] <= p.metadata["end_line"]
            for p in packed
        )
        if covered:
            continue
        cost = int(m.get("token_count") or 0)
        if packed and (len(packed) >= max_chunks or tokens + cost > max_tokens):
            break
        packed.append(doc)
        tokens += cost
    for doc in ranked:
        doc.metadata["packed"] = doc in packed
    return packed


def has_support(
    vector: list[Document], lexical: list[Document], symbol: list[Document], min_score: float
) -> bool:
    """FR-013 pre-check: answer only when retrieval supports it."""
    if lexical or symbol:
        return True
    best = max((float(d.metadata.get("vector_score", 0.0)) for d in vector), default=0.0)
    return best >= min_score


class HybridRetriever:
    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], embeddings: Embeddings, settings: Settings
    ) -> None:
        self._sessions = sessions
        self._embeddings = embeddings
        self._settings = settings

    async def retrieve(
        self,
        question: str,
        identifiers: list[str],
        ingestion_id: uuid.UUID,
        config: RunnableConfig | None = None,
    ) -> RetrievalResult:
        s = self._settings
        common: dict[str, Any] = {
            "sessions": self._sessions,
            "ingestion_id": ingestion_id,
            "k": s.retrieval_top_k,
        }
        vector_r = VectorRetriever(embeddings=self._embeddings, **common)
        lexical_r = LexicalRetriever(**common)
        symbol_r = SymbolRetriever(**common)
        vector, lexical, symbol = await asyncio.gather(
            vector_r.ainvoke(question, config=config),
            lexical_r.ainvoke(" ".join([question, *identifiers]), config=config),
            symbol_r.ainvoke(" ".join(identifiers), config=config),
        )
        ranked = fuse(vector, lexical, symbol)
        if not has_support(vector, lexical, symbol, s.retrieval_min_score):
            return RetrievalResult(packed=[], ranked=ranked, found=False)
        return RetrievalResult(
            packed=pack(ranked, s.context_max_chunks, s.context_max_tokens), ranked=ranked
        )
