from collections import defaultdict

from langchain_core.documents import Document

from src.config import settings
from src.observability import traced
from src.rag.query_transformer import (
    QueryTransformer,
)
from src.rag.retriever import (
    SearchResult,
    cap_per_source,
    document_key,
    search_hybrid,
)

RRF_K = 60

_document_key = document_key


@traced("multi-query-fusion", "retriever")
def search_queries_hybrid(
    queries: list[str],
    per_query_k: int = 20,
    final_k: int = 20,
    vendor: str | None = None,
) -> list[SearchResult]:
    """
    Run hybrid retrieval for several query variants
    and merge their rankings using RRF.
    """

    # Remove empty / duplicate queries.
    unique_queries: list[str] = []
    seen: set[str] = set()

    for query in queries:
        value = query.strip()

        if not value:
            continue

        key = value.casefold()

        if key in seen:
            continue

        seen.add(key)
        unique_queries.append(value)

    documents: dict[str, Document] = {}
    rrf_scores: dict[str, float] = defaultdict(float)

    for query in unique_queries:
        results = search_hybrid(
            query=query,
            k=per_query_k,
            vendor=vendor,
        )

        for rank, result in enumerate(
            results,
            start=1,
        ):
            key = _document_key(result.document)

            documents[key] = result.document

            rrf_scores[key] += 1.0 / (RRF_K + rank)

    # Explicit tie-break: fused scores collide often, and insertion order would
    # otherwise decide which tied chunk survives the cut at final_k.
    ranked = sorted(
        rrf_scores.items(),
        key=lambda item: (-item[1], item[0]),
    )

    return cap_per_source(
        [SearchResult(document=documents[key], score=score) for key, score in ranked],
        final_k,
        settings.max_chunks_per_source_in_pool,
    )


def search_multi_query_hybrid(
    query: str,
    per_query_k: int = 20,
    final_k: int = 20,
) -> list[SearchResult]:
    """
    Existing full query-transform strategy:

    original
    + English translation
    + semantic variant
    """

    transformer = QueryTransformer()

    transformed = transformer.build_queries(query)

    queries = transformed.unique_queries()

    return search_queries_hybrid(
        queries=queries,
        per_query_k=per_query_k,
        final_k=final_k,
    )
