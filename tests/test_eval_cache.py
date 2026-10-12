from types import SimpleNamespace

import pytest
from cohere.errors.too_many_requests_error import TooManyRequestsError
from langchain_core.documents import Document

from evals import eval_cache
from src.rag.retriever import SearchResult


class FakeClient:
    def __init__(self, scores: dict[str, float]) -> None:
        self.scores = scores
        self.calls: list[list[str]] = []

    def rerank(self, *, model, query, documents, top_n):
        self.calls.append(list(documents))
        ranked = sorted(range(len(documents)), key=lambda i: -self.scores[documents[i]])
        return SimpleNamespace(
            results=[
                SimpleNamespace(index=i, relevance_score=self.scores[documents[i]])
                for i in ranked[:top_n]
            ]
        )


def _result(text: str) -> SearchResult:
    return SearchResult(Document(page_content=text, metadata={"title": "t"}), 0.1)


@pytest.fixture
def reranker(monkeypatch, tmp_path):
    monkeypatch.setenv("EVAL_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(eval_cache, "CALL_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(eval_cache, "_exhausted", False)
    monkeypatch.setattr(eval_cache, "_cache", None)
    instance = eval_cache.EvalReranker()
    return instance


def test_scores_only_uncached_documents(reranker):
    texts = ["a", "b", "c"]
    docs = {
        reranker._document_text(_result(t).document): s
        for t, s in zip(texts, [0.2, 0.9, 0.5])
    }
    client = FakeClient(docs)
    reranker.client = client

    first = reranker.rerank("q", [_result("a"), _result("b")], top_n=2)
    second = reranker.rerank("q", [_result("a"), _result("b"), _result("c")], top_n=3)

    assert len(client.calls) == 2
    assert len(client.calls[1]) == 1  # only "c" was new
    assert [r.document.page_content for r in first] == ["b", "a"]
    assert [r.document.page_content for r in second] == ["b", "c", "a"]
    assert [r.original_rank for r in second] == [2, 3, 1]


def test_fully_cached_pool_makes_no_call(reranker):
    docs = {reranker._document_text(_result("a").document): 0.4}
    client = FakeClient(docs)
    reranker.client = client
    reranker.rerank("q", [_result("a")], top_n=1)
    reranker.rerank("q", [_result("a")], top_n=1)
    assert len(client.calls) == 1


def test_monthly_quota_stops_and_never_uses_fallback(reranker):
    class Exhausted:
        def rerank(self, **_kwargs):
            raise TooManyRequestsError(
                body={"message": "limited to 1000 API calls / month"}
            )

    fallback = FakeClient({})
    reranker.client = Exhausted()
    reranker._fallback_client = fallback
    with pytest.raises(eval_cache.QuotaExhausted):
        reranker.rerank("q", [_result("a")], top_n=1)
    with pytest.raises(eval_cache.QuotaExhausted):
        reranker.rerank("q", [_result("z")], top_n=1)
    assert fallback.calls == []
