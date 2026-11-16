"""FR-013 / FR-015 / research R6: fusion, symbol pinning, packing, pre-check (task T141)."""

from __future__ import annotations

from langchain_core.documents import Document

from codecompass.retrieval.hybrid import RRF_K, fuse, has_support, pack
from codecompass.retrieval.retrievers import lexical_terms


def d(
    cid: int, path: str = "a.py", start: int = 1, end: int = 10, tokens: int = 100, **meta: object
) -> Document:
    return Document(
        page_content=f"chunk {cid}",
        metadata={
            "chunk_id": cid,
            "path": path,
            "start_line": start,
            "end_line": end,
            "token_count": tokens,
            **meta,
        },
    )


def test_fr015_symbol_hit_is_pinned_first_despite_unrelated_vector_scores() -> None:
    vector = [d(1, vector_rank=1, vector_score=0.9), d(2, vector_rank=2, vector_score=0.8)]
    lexical = [d(2, lexical_rank=1, lexical_score=0.5)]
    symbol = [d(7, path="app/core/config.py", symbol_rank=1, symbol_hit=True)]
    fused = fuse(vector, lexical, symbol)
    assert fused[0].metadata["chunk_id"] == 7
    assert fused[0].metadata["symbol_hit"] is True


def test_rrf_orders_by_summed_reciprocal_rank() -> None:
    vector = [d(1, vector_rank=1), d(2, vector_rank=2), d(3, vector_rank=3)]
    lexical = [d(3, lexical_rank=1), d(2, lexical_rank=2)]
    fused = fuse(vector, lexical, [])
    # 2: 1/62 + 1/62; 3: 1/63 + 1/61; 1: 1/61
    assert [x.metadata["chunk_id"] for x in fused] == [3, 2, 1]
    score_2 = 1 / (RRF_K + 2) + 1 / (RRF_K + 2)
    assert (
        abs(
            next(x for x in fused if x.metadata["chunk_id"] == 2).metadata["fused_score"]
            - round(score_2, 6)
        )
        < 1e-9
    )


def test_fused_docs_keep_every_retrievers_metadata() -> None:
    fused = fuse(
        [d(1, vector_rank=1, vector_score=0.7)], [d(1, lexical_rank=3, lexical_score=0.2)], []
    )
    meta = fused[0].metadata
    assert meta["vector_rank"] == 1 and meta["lexical_rank"] == 3 and meta["symbol_hit"] is False


def test_pack_respects_chunk_and_token_budget_and_skips_covered_spans() -> None:
    ranked = [
        d(1, start=1, end=50, tokens=100),
        d(2, start=10, end=20, tokens=50),  # inside chunk 1 → skipped
        d(3, path="b.py", tokens=100),
        d(4, path="c.py", tokens=100),
    ]
    packed = pack(ranked, max_chunks=2, max_tokens=10_000)
    assert [p.metadata["chunk_id"] for p in packed] == [1, 3]
    assert ranked[1].metadata["packed"] is False
    assert [p.metadata["chunk_id"] for p in pack(ranked, max_chunks=8, max_tokens=150)] == [1]


def test_pack_always_keeps_the_best_chunk_even_if_large() -> None:
    assert len(pack([d(1, tokens=99_999)], max_chunks=8, max_tokens=10)) == 1


def test_fr013_precheck() -> None:
    weak = [d(1, vector_rank=1, vector_score=0.1)]
    assert has_support(weak, [], [], min_score=0.35) is False
    assert has_support(weak, [d(2, lexical_rank=1)], [], min_score=0.35) is True
    assert has_support(weak, [], [d(3, symbol_hit=True)], min_score=0.35) is True
    assert has_support([d(1, vector_rank=1, vector_score=0.6)], [], [], min_score=0.35) is True
    assert has_support([], [], [], min_score=0.35) is False


def test_lexical_terms_drop_stopwords_and_split_identifiers() -> None:
    assert lexical_terms("Where is the parseConfig function defined?") == [
        "parseconfig",
        "parse",
        "config",
        "function",
        "defined",
    ]
