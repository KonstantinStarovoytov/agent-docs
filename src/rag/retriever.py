from dataclasses import dataclass
from hashlib import sha1

from langchain_core.documents import Document
from qdrant_client import models

from src.ingestion.ingest import (
    get_hybrid_vector_store,
    get_vector_store,
)
from src.config import settings
from src.observability import traced

TIE_BREAK_OVERFETCH = 3


@dataclass(frozen=True, slots=True)
class SearchResult:
    document: Document
    score: float


def document_key(document: Document) -> str:
    """Stable identity of a chunk: its source, heading path and content."""
    metadata = document.metadata
    raw = "|".join(
        [
            metadata.get("source", ""),
            metadata.get("h1", ""),
            metadata.get("h2", ""),
            metadata.get("h3", ""),
            document.page_content,
        ]
    )
    return sha1(raw.encode("utf-8")).hexdigest()


def _search_trace_input(query: str, k: int = 10) -> dict[str, object]:
    return {"query": query, "k": k}


def _hybrid_search_trace_input(
    query: str, k: int = 10, vendor: str | None = None
) -> dict[str, object]:
    return {"query": query, "k": k, "vendor_scope": vendor}


def _vendor_filter(vendor: str | None) -> models.Filter | None:
    if vendor is None:
        return None
    return models.Filter(
        must=[
            models.FieldCondition(
                key="metadata.vendor",
                match=models.MatchValue(value=vendor),
            )
        ]
    )


def _search_trace_output(results: list[SearchResult]) -> list[dict[str, object]]:
    return [
        {
            "rank": rank,
            "content": result.document.page_content,
            "metadata": result.document.metadata,
            "source": result.document.metadata.get("source"),
            "title": result.document.metadata.get("title"),
            "heading": " > ".join(
                value
                for value in (
                    result.document.metadata.get("h1"),
                    result.document.metadata.get("h2"),
                    result.document.metadata.get("h3"),
                )
                if value
            ),
            "retrieval_score": result.score,
        }
        for rank, result in enumerate(results, start=1)
    ]


@traced(
    "dense-search",
    "retriever",
    input_factory=_search_trace_input,
    output_factory=_search_trace_output,
)
def search(
    query: str,
    k: int = 10,
) -> list[SearchResult]:
    vector_store = get_vector_store()

    results = vector_store.similarity_search_with_score(
        query=query,
        k=k,
    )

    return [
        SearchResult(
            document=document,
            score=score,
        )
        for document, score in results
    ]


def cap_per_source(
    ranked: list[SearchResult], k: int, max_per_source: int | None
) -> list[SearchResult]:
    """First `k` results in order, keeping at most `max_per_source` per page.

    Skipped chunks free their slot for later (over-fetched) candidates, so the
    pool keeps size `k` when enough distinct pages exist. None = plain cut.
    """
    if max_per_source is None:
        return ranked[:k]
    counts: dict[str, int] = {}
    kept: list[SearchResult] = []
    for result in ranked:
        source = str(result.document.metadata.get("source", ""))
        if counts.get(source, 0) >= max_per_source:
            continue
        counts[source] = counts.get(source, 0) + 1
        kept.append(result)
        if len(kept) == k:
            break
    return kept


@traced(
    "hybrid-search",
    "retriever",
    input_factory=_hybrid_search_trace_input,
    output_factory=_search_trace_output,
)
def search_hybrid(
    query: str,
    k: int = 10,
    vendor: str | None = None,
) -> list[SearchResult]:
    vector_store = get_hybrid_vector_store()

    # RRF scores take few distinct values, so many candidates tie. Qdrant returns
    # tied documents in an arbitrary order, which makes the cut at k drop a
    # different document on each call. Over-fetch, then break ties by content id.
    results = vector_store.similarity_search_with_score(
        query=query,
        k=k * TIE_BREAK_OVERFETCH,
        filter=_vendor_filter(vendor),
        hybrid_fusion=models.FusionQuery(fusion=models.Fusion.RRF),
    )

    ordered = sorted(results, key=lambda row: (-row[1], document_key(row[0])))

    return cap_per_source(
        [SearchResult(document=document, score=score) for document, score in ordered],
        k,
        settings.max_chunks_per_source_in_pool,
    )
