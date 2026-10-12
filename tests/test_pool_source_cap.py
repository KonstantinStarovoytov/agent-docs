from langchain_core.documents import Document

from src.rag.retriever import SearchResult, cap_per_source


def _r(source: str, n: int, score: float) -> SearchResult:
    return SearchResult(
        document=Document(page_content=f"{source}-{n}", metadata={"source": source}),
        score=score,
    )


RANKED = [
    _r("a", 1, 0.9),
    _r("a", 2, 0.8),
    _r("a", 3, 0.7),
    _r("b", 1, 0.6),
    _r("a", 4, 0.5),
    _r("c", 1, 0.4),
    _r("b", 2, 0.3),
]


def _ids(results: list[SearchResult]) -> list[str]:
    return [r.document.page_content for r in results]


def test_none_keeps_first_k_unchanged():
    assert _ids(cap_per_source(RANKED, k=4, max_per_source=None)) == [
        "a-1",
        "a-2",
        "a-3",
        "b-1",
    ]


def test_cap_respected_and_order_preserved():
    out = cap_per_source(RANKED, k=10, max_per_source=2)
    assert _ids(out) == ["a-1", "a-2", "b-1", "c-1", "b-2"]


def test_refills_from_overfetch_to_keep_pool_size():
    out = cap_per_source(RANKED, k=4, max_per_source=1)
    assert _ids(out) == ["a-1", "b-1", "c-1"]
    out = cap_per_source(RANKED, k=4, max_per_source=2)
    assert _ids(out) == ["a-1", "a-2", "b-1", "c-1"]
    assert len(out) == 4
