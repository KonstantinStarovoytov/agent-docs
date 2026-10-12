"""The shared handler forwards what both transports need, nothing more."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from src.service import core


def test_search_forwards_vendor_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_hybrid(*, query: str, k: int, vendor: str | None = None) -> list[Any]:
        seen.update(query=query, k=k, vendor=vendor)
        return []

    monkeypatch.setattr(core, "search_hybrid", fake_hybrid)
    reranker = Mock(side_effect=AssertionError("Cohere must not be initialized"))
    monkeypatch.setattr(core, "CohereReranker", reranker)

    monkeypatch.setattr(core.settings, "per_query_top_k", 20)

    core.search("rules", limit=3, vendor="openai")

    # The retrieval pool is wider than the caller's limit so that Cohere picks
    # the best 3 of 20, not merely reorders the 3 RRF chose (PR #12 regression).
    assert seen == {"query": "rules", "k": 20, "vendor": "openai"}
    reranker.assert_not_called()


def test_index_snapshot_comes_from_qdrant_meta(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(core, "_read_index_meta", lambda: {"indexed_at": "2026-09-20"})
    monkeypatch.setattr(core.settings, "index_snapshot", "2026-01-01")
    core.forget_index_snapshot()

    assert core.index_snapshot() == "2026-09-20"


def test_index_snapshot_falls_back_to_env_when_meta_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom() -> dict[str, Any]:
        raise ConnectionError("qdrant down")

    monkeypatch.setattr(core, "_read_index_meta", boom)
    monkeypatch.setattr(core.settings, "index_snapshot", "2026-01-01")
    core.forget_index_snapshot()

    assert core.index_snapshot() == "2026-01-01"


def test_index_snapshot_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def read() -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {"indexed_at": "2026-09-20"}

    monkeypatch.setattr(core, "_read_index_meta", read)
    core.forget_index_snapshot()

    core.index_snapshot()
    core.index_snapshot()

    assert calls == 1


def test_search_passage_content_is_raw_not_the_embedding_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MCP search_docs promises passages are "quoted documentation text";
    page_content may carry the Vendor/Product/.../embedding prefix, which
    must not leak into what the calling agent sees."""
    from langchain_core.documents import Document

    from src.rag.retriever import SearchResult

    def fake_search_hybrid(*, query, k, vendor=None):
        return [
            SearchResult(
                document=Document(
                    page_content="Vendor: a\nProduct: b\nDocument: c\nSection: d\n\nreal text",
                    metadata={"raw_content": "real text", "source": "https://x"},
                ),
                score=0.9,
            )
        ]

    monkeypatch.setattr(core, "search_hybrid", fake_search_hybrid)
    _stub_passthrough_reranker(monkeypatch)

    passages = core.search("q")

    assert passages[0].content == "real text"


def _stub_passthrough_reranker(monkeypatch: pytest.MonkeyPatch) -> None:
    """A fake CohereReranker whose rerank() wraps each SearchResult as a
    RerankResult with the same relative order and a fixed high score."""

    def rerank(query: str, results, top_n: int):
        from src.rag.reranker import RerankResult

        return [
            RerankResult(
                document=result.document,
                retrieval_score=result.score,
                rerank_score=0.9,
                original_rank=i,
                rerank_rank=i,
            )
            for i, result in enumerate(results[:top_n], start=1)
        ]

    monkeypatch.setattr(core, "CohereReranker", lambda: SimpleNamespace(rerank=rerank))


def test_search_reranks_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    """search_docs must be reranked like ask_docs, not left on raw RRF order
    (the tail of a raw hybrid result is unordered ties - see the MCP audit)."""
    from langchain_core.documents import Document

    from src.rag.retriever import SearchResult

    def fake_search_hybrid(*, query, k, vendor=None):
        return [
            SearchResult(
                document=Document(page_content="weak", metadata={}), score=0.1
            ),
            SearchResult(
                document=Document(page_content="strong", metadata={}), score=0.2
            ),
        ]

    monkeypatch.setattr(core, "search_hybrid", fake_search_hybrid)
    rerank_calls = []

    def rerank(query: str, results, top_n: int):
        from src.rag.reranker import RerankResult

        rerank_calls.append((query, list(results), top_n))
        # Reverse order and score, as a real Cohere rerank plausibly would.
        return [
            RerankResult(
                document=results[1].document,
                retrieval_score=results[1].score,
                rerank_score=0.95,
                original_rank=2,
                rerank_rank=1,
            ),
            RerankResult(
                document=results[0].document,
                retrieval_score=results[0].score,
                rerank_score=0.4,
                original_rank=1,
                rerank_rank=2,
            ),
        ]

    monkeypatch.setattr(core, "CohereReranker", lambda: SimpleNamespace(rerank=rerank))

    passages = core.search("q", limit=2)

    assert len(rerank_calls) == 1
    assert rerank_calls[0][0] == "q"
    assert rerank_calls[0][2] == 2  # the whole pool: both candidates
    assert [p.content for p in passages] == ["strong", "weak"]
    assert [p.score for p in passages] == [0.95, 0.4]


def test_search_returns_nothing_when_no_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(core, "search_hybrid", lambda *, query, k, vendor=None: [])
    reranker = Mock(side_effect=AssertionError("Cohere must not be initialized"))
    monkeypatch.setattr(core, "CohereReranker", reranker)

    assert core.search("q") == []
    reranker.assert_not_called()


def test_search_reranks_a_wide_pool_and_returns_only_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from langchain_core.documents import Document

    from src.rag.retriever import SearchResult

    monkeypatch.setattr(core.settings, "per_query_top_k", 20)
    monkeypatch.setattr(
        core,
        "search_hybrid",
        lambda *, query, k, vendor=None: [
            SearchResult(
                document=Document(page_content=f"c{i}", metadata={}), score=1.0
            )
            for i in range(k)
        ],
    )
    seen: dict[str, Any] = {}

    def rerank(query: str, results, top_n: int):
        from src.rag.reranker import RerankResult

        seen.update(pool=len(results), top_n=top_n)
        return [
            RerankResult(r.document, r.score, 0.9, i, i)
            for i, r in enumerate(results[:top_n], start=1)
        ]

    monkeypatch.setattr(core, "CohereReranker", lambda: SimpleNamespace(rerank=rerank))

    passages = core.search("q", limit=3)

    # Cohere returns the whole pool so that distinct pages can fill the limit.
    assert seen == {"pool": 20, "top_n": 20}
    assert len(passages) == 3


def test_search_pool_never_shrinks_below_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """A caller asking for more than per_query_top_k still gets that many."""
    seen: dict[str, Any] = {}
    monkeypatch.setattr(core.settings, "per_query_top_k", 20)
    monkeypatch.setattr(
        core, "search_hybrid", lambda *, query, k, vendor=None: seen.update(k=k) or []
    )
    monkeypatch.setattr(core, "CohereReranker", Mock())

    core.search("q", limit=30)

    assert seen == {"k": 30}


def test_answer_passes_vendor_to_pipeline(monkeypatch) -> None:
    seen: dict[str, Any] = {}

    def answer_question(question, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(answer="a", sources=[])

    monkeypatch.setattr(core, "answer_question", answer_question)

    core.answer("q", vendor="cursor")

    assert seen["vendor"] == "cursor"


def _page_chunks(monkeypatch: pytest.MonkeyPatch, scored: list[tuple[str, float]]):
    """search_hybrid returns one chunk per (url, score); the fake reranker
    orders them by that score. Returns the list of rerank calls."""
    from langchain_core.documents import Document

    from src.rag.reranker import RerankResult
    from src.rag.retriever import SearchResult

    monkeypatch.setattr(core.settings, "per_query_top_k", 20)
    monkeypatch.setattr(core.settings, "rerank_pool", None)
    monkeypatch.setattr(
        core,
        "search_hybrid",
        lambda *, query, k, vendor=None: [
            SearchResult(
                document=Document(
                    page_content=f"{url}#{i}",
                    metadata={"source": url, "rerank": score},
                ),
                score=1.0,
            )
            for i, (url, score) in enumerate(scored)
        ],
    )
    calls: list[dict[str, Any]] = []

    def rerank(query: str, results, top_n: int):
        calls.append({"pool": len(results), "top_n": top_n})
        ordered = sorted(results, key=lambda r: -r.document.metadata["rerank"])
        return [
            RerankResult(r.document, r.score, r.document.metadata["rerank"], i, i)
            for i, r in enumerate(ordered[:top_n], start=1)
        ]

    monkeypatch.setattr(core, "CohereReranker", lambda: SimpleNamespace(rerank=rerank))
    return calls


def test_search_keeps_only_the_best_passage_per_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _page_chunks(
        monkeypatch,
        [("a", 0.5), ("a", 0.9), ("b", 0.8), ("a", 0.7), ("c", 0.6), ("b", 0.3)],
    )

    passages = core.search("q", limit=5)

    assert [(p.url, p.score) for p in passages] == [("a", 0.9), ("b", 0.8), ("c", 0.6)]
    assert [p.content for p in passages] == ["a#1", "b#2", "c#4"]
    assert [p.rank for p in passages] == [1, 2, 3]


def test_search_fills_limit_with_distinct_pages_in_one_rerank_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Page "a" holds the five best chunks; the limit must still be filled
    # with other pages, so Cohere has to return the whole pool.
    scored = [("a", 0.99 - i / 100) for i in range(5)]
    scored += [(f"p{i}", 0.5 - i / 100) for i in range(15)]
    calls = _page_chunks(monkeypatch, scored)

    passages = core.search("q", limit=4)

    assert calls == [{"pool": 20, "top_n": 20}]
    assert [p.url for p in passages] == ["a", "p0", "p1", "p2"]
    assert [p.rank for p in passages] == [1, 2, 3, 4]
    assert [p.score for p in passages] == sorted(
        (p.score for p in passages), reverse=True
    )
