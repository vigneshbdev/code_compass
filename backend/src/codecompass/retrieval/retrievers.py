"""Three retrievers over the active ingestion's chunks (FR-006, FR-015, research R6, task T141).

They are LangChain `BaseRetriever`s, so every retrieval shows up as a span in Langfuse.
- VectorRetriever: cosine similarity on pgvector embeddings.
- LexicalRetriever: Postgres full-text search on chunk text + split identifiers + path.
- SymbolRetriever: exact (then case-insensitive) match on function/class names.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from langchain_core.callbacks import (
    AsyncCallbackManagerForRetrieverRun,
    CallbackManagerForRetrieverRun,
)
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from codecompass.chunking.identifiers import split_identifiers
from codecompass.storage.models import Chunk

# Words that carry no meaning for code search; the 'simple' text config keeps them.
_STOPWORD_TEXT = """
    a an and are as at be but by can do does for from how i if in into is it its me my
    of on or our so that the their them then there these this to us was we what when
    where which who why will with you your there's what's where's show tell explain find
"""
STOPWORDS = frozenset(_STOPWORD_TEXT.split())
WORD = re.compile(r"[a-z0-9_]+")


def chunk_document(chunk: Chunk, **metadata: Any) -> Document:
    return Document(
        page_content=chunk.text,
        metadata={
            "chunk_id": chunk.id,
            "path": chunk.path,
            "start_line": chunk.start_line,
            "end_line": chunk.end_line,
            "language": chunk.language,
            "kind": chunk.kind,
            "symbol": chunk.symbol,
            "token_count": chunk.token_count,
            "injection_flag": chunk.injection_flag,
            **metadata,
        },
    )


class ChunkRetriever(BaseRetriever):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    sessions: async_sessionmaker[AsyncSession]
    ingestion_id: uuid.UUID
    k: int = 20

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:
        raise NotImplementedError("CodeCompass retrievers are async only")


class VectorRetriever(ChunkRetriever):
    embeddings: Embeddings

    async def _aget_relevant_documents(
        self, query: str, *, run_manager: AsyncCallbackManagerForRetrieverRun
    ) -> list[Document]:
        vector = await self.embeddings.aembed_query(query)
        distance = Chunk.embedding.cosine_distance(vector)
        stmt = (
            select(Chunk, distance.label("distance"))
            .where(Chunk.ingestion_id == self.ingestion_id)
            .order_by(distance)
            .limit(self.k)
        )
        async with self.sessions() as session:
            rows = (await session.execute(stmt)).all()
        return [
            chunk_document(chunk, vector_rank=rank, vector_score=round(1 - float(d), 4))
            for rank, (chunk, d) in enumerate(rows, start=1)
        ]


def lexical_terms(query: str) -> list[str]:
    """Meaningful lowercase terms (identifiers split), stopwords removed, order kept."""
    seen: dict[str, None] = {}
    for word in WORD.findall(split_identifiers(query).lower()):
        if len(word) > 1 and word not in STOPWORDS:
            seen.setdefault(word, None)
    return list(seen)


class LexicalRetriever(ChunkRetriever):
    async def _aget_relevant_documents(
        self, query: str, *, run_manager: AsyncCallbackManagerForRetrieverRun
    ) -> list[Document]:
        terms = lexical_terms(query)
        if not terms:
            return []
        # OR of terms: natural-language questions rarely contain every word of the code.
        tsquery = func.to_tsquery("simple", " | ".join(terms))
        rank = func.ts_rank_cd(Chunk.search, tsquery)
        stmt = (
            select(Chunk, rank.label("rank"))
            .where(Chunk.ingestion_id == self.ingestion_id, Chunk.search.op("@@")(tsquery))
            .order_by(text("rank DESC"), Chunk.id)
            .limit(self.k)
        )
        async with self.sessions() as session:
            rows = (await session.execute(stmt)).all()
        return [
            chunk_document(chunk, lexical_rank=i, lexical_score=round(float(r), 4))
            for i, (chunk, r) in enumerate(rows, start=1)
        ]


class SymbolRetriever(ChunkRetriever):
    """`query` is a space-separated list of identifiers."""

    async def _aget_relevant_documents(
        self, query: str, *, run_manager: AsyncCallbackManagerForRetrieverRun
    ) -> list[Document]:
        names = [n for n in query.split() if n]
        if not names:
            return []
        lowered = [n.lower() for n in names]
        leaves = [n.rsplit(".", 1)[-1] for n in names]
        exact = or_(Chunk.symbol.in_(names), Chunk.symbol_leaf.in_(leaves))
        loose = or_(
            func.lower(Chunk.symbol).in_(lowered),
            func.lower(Chunk.symbol_leaf).in_([leaf.lower() for leaf in leaves]),
        )
        base = select(Chunk).where(Chunk.ingestion_id == self.ingestion_id)
        async with self.sessions() as session:
            found = list((await session.execute(base.where(exact).limit(self.k))).scalars())
            if not found:
                found = list((await session.execute(base.where(loose).limit(self.k))).scalars())
        return [chunk_document(c, symbol_hit=True, symbol_rank=i) for i, c in enumerate(found, 1)]
