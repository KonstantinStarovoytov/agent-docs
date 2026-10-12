from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.rag import pipeline


def test_root_trace_uses_question_as_input_and_strategy_as_metadata():
    assert (
        pipeline._answer_trace_input(
            "What is MCP?", strategy="hybrid-english", iterative=True
        )
        == "What is MCP?"
    )
    metadata = pipeline._answer_trace_metadata(
        "What is MCP?", strategy="hybrid-english", iterative=True
    )
    assert metadata["strategy"] == "hybrid-english"
    assert metadata["iterative"] is True
    assert metadata["needs_english_translation"] is False
    assert metadata["retrieval_top_k"] == pipeline.settings.retrieval_top_k


@pytest.mark.parametrize("strategy", ["dense", "hybrid", "hybrid-english"])
def test_routes_and_reranks_original_query(monkeypatch, strategy):
    candidates = [object()]
    ranked = [object()]
    dense = Mock(return_value=candidates)
    hybrid = Mock(return_value=candidates)
    multi = Mock(return_value=candidates)
    transform = Mock(return_value="English question")
    rerank = Mock(return_value=ranked)
    generate = Mock(return_value="answer")
    monkeypatch.setattr(pipeline, "search", dense)
    monkeypatch.setattr(pipeline, "search_hybrid", hybrid)
    monkeypatch.setattr(pipeline, "search_queries_hybrid", multi)
    monkeypatch.setattr(pipeline, "translate_query", transform)
    monkeypatch.setattr(
        pipeline, "CohereReranker", lambda: SimpleNamespace(rerank=rerank)
    )
    monkeypatch.setattr(pipeline, "generate_answer", generate)
    assert (
        pipeline.answer_question("  исходный вопрос  ", strategy=strategy) == "answer"
    )
    assert dense.call_count == (strategy == "dense")
    if strategy == "dense":
        assert hybrid.call_count == 0
        assert multi.call_count == 0
        transform.assert_not_called()
    else:
        assert hybrid.call_count == 0
        assert multi.call_count == 1
        transform.assert_called_once()
        assert multi.call_args.kwargs["queries"] == [
            "исходный вопрос",
            "English question",
        ]
    assert rerank.call_args.kwargs["query"] == "исходный вопрос"
    assert rerank.call_args.kwargs["results"] is candidates
    assert generate.call_args.kwargs["results"] is ranked


def test_empty_candidates_skip_reranker(monkeypatch):
    monkeypatch.setattr(pipeline, "search_hybrid", lambda **kwargs: [])
    reranker = Mock(side_effect=AssertionError("Cohere must not be initialized"))
    monkeypatch.setattr(pipeline, "CohereReranker", reranker)
    result = pipeline.answer_question("question", strategy="hybrid")
    assert result.sources == []
    reranker.assert_not_called()


@pytest.mark.parametrize("query,strategy", [("  ", "hybrid"), ("query", "unknown")])
def test_invalid_input(query, strategy):
    with pytest.raises(ValueError):
        pipeline.answer_question(query, strategy=strategy)


def test_vendor_reaches_single_query_hybrid_search(monkeypatch):
    hybrid = Mock(return_value=[])
    monkeypatch.setattr(pipeline, "search_hybrid", hybrid)

    pipeline.answer_question("question", strategy="hybrid", vendor="cursor")

    assert hybrid.call_args.kwargs["vendor"] == "cursor"


def test_vendor_reaches_multi_query_search(monkeypatch):
    multi = Mock(return_value=[])
    monkeypatch.setattr(pipeline, "search_queries_hybrid", multi)
    monkeypatch.setattr(pipeline, "translate_query", Mock(return_value="English"))

    pipeline.answer_question("вопрос", strategy="hybrid-english", vendor="openai")

    assert multi.call_args.kwargs["vendor"] == "openai"


def test_vendor_reaches_iterative_retrieval(monkeypatch):
    multi = Mock(return_value=[])
    monkeypatch.setattr(pipeline, "search_queries_hybrid", multi)
    monkeypatch.setattr(
        pipeline, "CohereReranker", lambda: SimpleNamespace(rerank=None, assess=None)
    )
    monkeypatch.setattr(
        pipeline, "EvidencePlanner", lambda: SimpleNamespace(rerank=None, assess=None)
    )
    monkeypatch.setattr(pipeline, "generate_answer", Mock(return_value="answer"))

    def two_hop(query, queries, *, retrieve, **_kwargs):
        retrieve(queries)
        return SimpleNamespace(results=[])

    monkeypatch.setattr(pipeline, "retrieve_two_hop", two_hop)

    pipeline.answer_question("q", strategy="hybrid", iterative=True, vendor="cursor")

    assert multi.call_args.kwargs["vendor"] == "cursor"


def test_dense_strategy_rejects_vendor_filter():
    with pytest.raises(ValueError):
        pipeline.answer_question("q", strategy="dense", vendor="cursor")


def test_multi_query_fusion_filters_every_query_by_vendor(monkeypatch):
    from src.rag import multi_query_retriever

    hybrid = Mock(return_value=[])
    monkeypatch.setattr(multi_query_retriever, "search_hybrid", hybrid)

    multi_query_retriever.search_queries_hybrid(["a", "b"], vendor="cursor")

    assert [c.kwargs["vendor"] for c in hybrid.call_args_list] == ["cursor", "cursor"]
