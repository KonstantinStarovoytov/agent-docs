"""Transport-independent request handling.

The HTTP endpoint and the MCP server must answer identically, so both go through
`answer` here rather than calling the pipeline with their own arguments.
"""

import logging
from uuid import NAMESPACE_URL, uuid5
import time
from dataclasses import dataclass
from typing import Any

from src.config import settings
from src.ingestion.ingest import get_qdrant_client
from src.rag.pipeline import RetrievalStrategy, answer_question
from src.rag.reranker import CohereReranker, RerankResult
from src.rag.retriever import rerank_pool_size, search_hybrid

logger = logging.getLogger(__name__)

# The re-index job writes one point per hybrid collection here; see
# src/reindex.py. Point 1 is the single point written before that.
META_COLLECTION = "agent_docs_meta"
META_POINT_ID = 1


def meta_point_id(collection: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"agent-docs-meta/{collection}"))


SNAPSHOT_TTL_SECONDS = 600.0

_snapshot_cache: tuple[float, str | None] | None = None


class QuestionRejected(ValueError):
    """The request is malformed; the caller should not retry it unchanged."""


def _read_index_meta() -> dict[str, Any]:
    client = get_qdrant_client()
    try:
        if not client.collection_exists(META_COLLECTION):
            return {}
        own = meta_point_id(settings.qdrant_hybrid_collection)
        points = {
            str(point.id): point
            for point in client.retrieve(META_COLLECTION, ids=[own, META_POINT_ID])
        }
    finally:
        client.close()
    point = points.get(own) or points.get(str(META_POINT_ID))
    return dict(point.payload or {}) if point else {}


def index_snapshot() -> str | None:
    """When the index was built, as the re-index job recorded it in Qdrant.

    Cached for ten minutes so every tool call does not pay a round trip; the
    env value is the fallback for an index built before the job existed.
    """
    global _snapshot_cache
    now = time.monotonic()
    if _snapshot_cache is not None and now - _snapshot_cache[0] < SNAPSHOT_TTL_SECONDS:
        return _snapshot_cache[1]
    try:
        value = _read_index_meta().get("indexed_at") or settings.index_snapshot
    except Exception:
        logger.warning("index meta unavailable; using INDEX_SNAPSHOT", exc_info=True)
        value = settings.index_snapshot
    _snapshot_cache = (now, value)
    return value


def forget_index_snapshot() -> None:
    global _snapshot_cache
    _snapshot_cache = None


@dataclass(frozen=True, slots=True)
class Source:
    citation: int
    title: str
    heading: str
    url: str
    rerank_score: float


@dataclass(frozen=True, slots=True)
class Answer:
    answer: str
    sources: list[Source]
    strategy: str
    iterative: bool


@dataclass(frozen=True, slots=True)
class Passage:
    rank: int
    title: str
    heading: str
    url: str
    score: float
    content: str
    # The page's one-sentence description; filled in by `pages.search`.
    description: str = ""


def _validated_question(question: str) -> str:
    question = question.strip()
    if not question:
        raise QuestionRejected("Question must not be empty")
    limit = settings.api_max_question_chars
    if len(question) > limit:
        raise QuestionRejected(f"Question must be at most {limit} characters")
    return question


def answer(
    question: str,
    *,
    strategy: RetrievalStrategy | None = None,
    iterative: bool = False,
    vendor: str | None = None,
) -> Answer:
    question = _validated_question(question)
    result = answer_question(
        question, strategy=strategy, iterative=iterative, vendor=vendor
    )
    return Answer(
        answer=result.answer,
        sources=[
            Source(
                citation=source.citation,
                title=source.title,
                heading=source.heading,
                url=source.url,
                rerank_score=source.rerank_score,
            )
            for source in result.sources
        ],
        strategy=strategy or settings.retrieval_strategy,
        iterative=iterative,
    )


def one_per_page(reranked: list[RerankResult]) -> list[RerankResult]:
    """The best-scoring chunk of each page (`metadata.source`), best first.

    A chunk without a source is never merged with another one.
    """
    best: dict[object, RerankResult] = {}
    for index, result in enumerate(reranked):
        page: object = result.document.metadata.get("source") or index
        if page not in best or result.rerank_score > best[page].rerank_score:
            best[page] = result
    return sorted(best.values(), key=lambda result: -result.rerank_score)


def rerank_pages(
    question: str, *, limit: int | None = None, vendor: str | None = None
) -> list[RerankResult]:
    """The best-scoring chunk of each of the top `limit` pages, best first.

    Shared by search_docs and /pages: one hybrid search, one Cohere call.
    """
    question = _validated_question(question)
    k = limit if limit is not None else settings.retrieval_top_k
    if k < 1:
        raise QuestionRejected("limit must be positive")
    if k > 50:
        raise QuestionRejected("limit must be at most 50")

    # Retrieve a pool wider than the caller's limit, then let Cohere pick the
    # best `k` of it. Reranking only `k` candidates would merely reorder what
    # RRF already chose, and past the first few results RRF is mostly ties
    # (reports/mcp-audit-2026-09-15.md #4a). Same single Cohere call either way.
    # Never narrower than the answer pipeline's pool, so search_docs sees at
    # least the candidates /ask would.
    pool = max(k, settings.per_query_top_k, rerank_pool_size())
    candidates = search_hybrid(query=question, k=pool, vendor=vendor)
    if not candidates:
        return []
    # Cohere returns the whole pool (still one call) so that `k` distinct pages
    # can be filled; a page's weaker chunks would otherwise crowd out other
    # pages. Only the best-scoring passage of each page is kept.
    reranked = CohereReranker().rerank(
        query=question, results=candidates, top_n=len(candidates)
    )
    return one_per_page(reranked)[:k]


def search(
    question: str, *, limit: int | None = None, vendor: str | None = None
) -> list[Passage]:
    """Retrieval without generation, for callers that want to read the sources."""
    best_per_page = rerank_pages(question, limit=limit, vendor=vendor)

    passages = []
    for rank, result in enumerate(best_per_page, start=1):
        metadata = result.document.metadata
        heading = " > ".join(
            value
            for value in (
                metadata.get("h1"),
                metadata.get("h2"),
                metadata.get("h3"),
            )
            if value
        )
        passages.append(
            Passage(
                rank=rank,
                title=metadata.get("title", "Untitled"),
                heading=heading,
                url=metadata.get("source", ""),
                score=result.rerank_score,
                content=metadata.get("raw_content", result.document.page_content),
            )
        )
    return passages
