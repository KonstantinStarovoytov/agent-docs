"""Prefetch depth and rerank pool are separate knobs; defaults keep old behaviour."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from langchain_core.documents import Document

from src.rag import multi_query_retriever, pipeline, retriever
from src.rag.retriever import SearchResult, document_key, search_hybrid
from src.service import core


def _doc(name: str) -> Document:
    return Document(
        page_content=f"chunk-{name}",
        metadata={"source": f"https://docs.test/{name}.md", "h1": name},
    )


def _store(rows: list[tuple[Document, float]]) -> Mock:
    store = Mock()
    store.similarity_search_with_score.return_value = rows
    return store


@pytest.fixture
def unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(retriever.settings, "hybrid_prefetch_depth", None)
    monkeypatch.setattr(retriever.settings, "rerank_pool", None)
    monkeypatch.setattr(retriever.settings, "max_chunks_per_source_in_pool", None)
    monkeypatch.setattr(retriever.settings, "retrieval_top_k", 10)
    monkeypatch.setattr(retriever.settings, "per_query_top_k", 20)


def test_defaults_are_todays_behaviour(unset: None) -> None:
    assert retriever.settings.hybrid_prefetch_depth is None
    assert retriever.settings.rerank_pool is None
    assert retriever.prefetch_limit(10) == 30
    assert retriever.prefetch_limit(20) == 60
    assert pipeline.rerank_pool_size() == 10


def test_default_prefetch_is_three_times_k(
    monkeypatch: pytest.MonkeyPatch, unset: None
) -> None:
    store = _store([(_doc("a"), 0.5)])
    monkeypatch.setattr(retriever, "get_hybrid_vector_store", lambda: store)
    search_hybrid("q", k=10)
    assert store.similarity_search_with_score.call_args.kwargs["k"] == 30


def test_prefetch_depth_is_passed_to_qdrant(
    monkeypatch: pytest.MonkeyPatch, unset: None
) -> None:
    monkeypatch.setattr(retriever.settings, "hybrid_prefetch_depth", 150)
    rows = [(_doc(str(i)), 1.0 / (i + 1)) for i in range(150)]
    store = _store(rows)
    monkeypatch.setattr(retriever, "get_hybrid_vector_store", lambda: store)
    results = search_hybrid("q", k=10)
    assert store.similarity_search_with_score.call_args.kwargs["k"] == 150
    assert len(results) == 10


def test_prefetch_never_below_k(monkeypatch: pytest.MonkeyPatch, unset: None) -> None:
    monkeypatch.setattr(retriever.settings, "hybrid_prefetch_depth", 5)
    assert retriever.prefetch_limit(10) == 10


def test_multi_query_path_uses_the_same_prefetch(
    monkeypatch: pytest.MonkeyPatch, unset: None
) -> None:
    monkeypatch.setattr(retriever.settings, "hybrid_prefetch_depth", 100)
    store = _store([(_doc("a"), 0.5), (_doc("b"), 0.4)])
    monkeypatch.setattr(retriever, "get_hybrid_vector_store", lambda: store)
    multi_query_retriever.search_queries_hybrid(
        ["first", "second"], per_query_k=20, final_k=10
    )
    depths = [c.kwargs["k"] for c in store.similarity_search_with_score.call_args_list]
    assert depths == [100, 100]


def test_pool_is_cut_after_the_stable_sort(
    monkeypatch: pytest.MonkeyPatch, unset: None
) -> None:
    """The rerank pool is the first `pool` candidates of the tie-broken order,
    whatever order Qdrant returned the tied rows in."""
    docs = [_doc(name) for name in "abcdef"]
    tied = 0.25
    shuffled = [
        (docs[4], tied),
        (docs[0], 0.5),
        (docs[2], tied),
        (docs[5], 0.1),
        (docs[1], tied),
        (docs[3], tied),
    ]
    store = _store(shuffled)
    monkeypatch.setattr(retriever, "get_hybrid_vector_store", lambda: store)
    monkeypatch.setattr(pipeline, "search_hybrid", retriever.search_hybrid)
    monkeypatch.setattr(pipeline.settings, "rerank_pool", 3)
    monkeypatch.setattr(pipeline.settings, "retrieval_top_k", 2)
    rerank = Mock(return_value=[])
    monkeypatch.setattr(
        pipeline, "CohereReranker", lambda: SimpleNamespace(rerank=rerank)
    )
    monkeypatch.setattr(pipeline, "generate_answer", Mock(return_value="answer"))

    pipeline.answer_question("question", strategy="hybrid")

    sent = rerank.call_args.kwargs["results"]
    ties = sorted([docs[1], docs[2], docs[3], docs[4]], key=document_key)
    assert [document_key(r.document) for r in sent] == [
        document_key(docs[0]),
        document_key(ties[0]),
        document_key(ties[1]),
    ]
    # The pool feeds the reranker; retrieval_top_k stays the rerank output size.
    assert rerank.call_args.kwargs["top_n"] == 2


def test_single_query_pipeline_sends_the_pool_to_rerank(
    monkeypatch: pytest.MonkeyPatch, unset: None
) -> None:
    monkeypatch.setattr(pipeline.settings, "rerank_pool", 40)
    candidates = [SearchResult(_doc("a"), 0.5)]
    hybrid = Mock(return_value=candidates)
    rerank = Mock(return_value=[])
    monkeypatch.setattr(pipeline, "search_hybrid", hybrid)
    monkeypatch.setattr(
        pipeline, "CohereReranker", lambda: SimpleNamespace(rerank=rerank)
    )
    monkeypatch.setattr(pipeline, "generate_answer", Mock(return_value="answer"))
    pipeline.answer_question("question", strategy="hybrid")
    assert hybrid.call_args.kwargs["k"] == 40
    assert rerank.call_args.kwargs["top_n"] == 10


def test_default_pipeline_pool_is_retrieval_top_k(
    monkeypatch: pytest.MonkeyPatch, unset: None
) -> None:
    hybrid = Mock(return_value=[SearchResult(_doc("a"), 0.5)])
    rerank = Mock(return_value=[])
    monkeypatch.setattr(pipeline, "search_hybrid", hybrid)
    monkeypatch.setattr(
        pipeline, "CohereReranker", lambda: SimpleNamespace(rerank=rerank)
    )
    monkeypatch.setattr(pipeline, "generate_answer", Mock(return_value="answer"))
    pipeline.answer_question("question", strategy="hybrid")
    assert hybrid.call_args.kwargs["k"] == 10
    assert rerank.call_args.kwargs["top_n"] == 10


def test_translated_query_pool_widens_per_query_k(
    monkeypatch: pytest.MonkeyPatch, unset: None
) -> None:
    monkeypatch.setattr(pipeline.settings, "rerank_pool", 40)
    multi = Mock(return_value=[SearchResult(_doc("a"), 0.5)])
    monkeypatch.setattr(pipeline, "search_queries_hybrid", multi)
    monkeypatch.setattr(pipeline, "translate_query", lambda q: "English question")
    monkeypatch.setattr(
        pipeline, "CohereReranker", lambda: SimpleNamespace(rerank=Mock())
    )
    monkeypatch.setattr(pipeline, "generate_answer", Mock(return_value="answer"))
    pipeline.answer_question("как настроить", strategy="hybrid")
    assert multi.call_args.kwargs["final_k"] == 40
    assert multi.call_args.kwargs["per_query_k"] == 40


def test_translated_query_defaults_unchanged(
    monkeypatch: pytest.MonkeyPatch, unset: None
) -> None:
    multi = Mock(return_value=[SearchResult(_doc("a"), 0.5)])
    monkeypatch.setattr(pipeline, "search_queries_hybrid", multi)
    monkeypatch.setattr(pipeline, "translate_query", lambda q: "English question")
    monkeypatch.setattr(
        pipeline, "CohereReranker", lambda: SimpleNamespace(rerank=Mock())
    )
    monkeypatch.setattr(pipeline, "generate_answer", Mock(return_value="answer"))
    pipeline.answer_question("как настроить", strategy="hybrid")
    assert multi.call_args.kwargs["final_k"] == 10
    assert multi.call_args.kwargs["per_query_k"] == 20


def test_search_docs_pool_not_smaller_than_answer_pool(
    monkeypatch: pytest.MonkeyPatch, unset: None
) -> None:
    monkeypatch.setattr(core.settings, "rerank_pool", 40)
    calls: list[int] = []

    def fake_hybrid(*, query: str, k: int, vendor: str | None = None) -> list:
        calls.append(k)
        return []

    monkeypatch.setattr(core, "search_hybrid", fake_hybrid)
    core.search("question", limit=8)
    assert calls == [40]


def test_search_docs_default_pool_unchanged(
    monkeypatch: pytest.MonkeyPatch, unset: None
) -> None:
    calls: list[int] = []

    def fake_hybrid(*, query: str, k: int, vendor: str | None = None) -> list:
        calls.append(k)
        return []

    monkeypatch.setattr(core, "search_hybrid", fake_hybrid)
    core.search("question", limit=8)
    assert calls == [20]
