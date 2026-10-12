"""Application retrieval and generation orchestration."""

from typing import Literal

from src.config import settings
from src.observability import traced
from src.rag.generator import GeneratedAnswer, generate_answer
from src.rag.iterative import retrieve_two_hop
from src.rag.language import needs_english_translation
from src.rag.multi_query_retriever import search_queries_hybrid
from src.rag.planner import EvidencePlanner, translate_query
from src.rag.reranker import CohereReranker
from src.rag.retriever import rerank_pool_size, search, search_hybrid

RetrievalStrategy = Literal["dense", "hybrid", "hybrid-english"]


def _answer_trace_input(
    query: str, *, strategy: RetrievalStrategy | None = None, iterative: bool = False
) -> str:
    return query


def _answer_trace_metadata(
    _query: str, *, strategy: RetrievalStrategy | None = None, iterative: bool = False
) -> dict[str, object]:
    resolved = strategy or settings.retrieval_strategy
    return {
        "strategy": resolved,
        "iterative": iterative,
        "translate_non_english": settings.translate_non_english,
        "needs_english_translation": needs_english_translation(_query),
        "retrieval_top_k": settings.retrieval_top_k,
        "generation_top_k": settings.generation_top_k,
        "per_query_top_k": settings.per_query_top_k,
        "rerank_pool": rerank_pool_size(),
        "hybrid_prefetch_depth": settings.hybrid_prefetch_depth,
    }


def _translated_queries(query: str, *, always: bool) -> list[str]:
    if not always and not (
        settings.translate_non_english and needs_english_translation(query)
    ):
        return [query]
    translated = translate_query(query)
    if translated.casefold() == query.casefold():
        return [query]
    return [query, translated]


@traced(
    "answer-question",
    "chain",
    input_factory=_answer_trace_input,
    metadata_factory=_answer_trace_metadata,
)
def answer_question(
    query: str, *, strategy: RetrievalStrategy | None = None, iterative: bool = False
) -> GeneratedAnswer:
    query = query.strip()
    if not query:
        raise ValueError("Question must not be empty")
    strategy = strategy if strategy is not None else settings.retrieval_strategy
    # The pool is what Cohere reads; retrieval_top_k is what it returns.
    pool = rerank_pool_size()
    per_query_k = max(settings.per_query_top_k, pool)
    if iterative:
        if strategy == "dense":
            raise ValueError("Iterative mode requires hybrid retrieval")
        if strategy not in {"hybrid", "hybrid-english"}:
            raise ValueError(f"Unknown retrieval strategy: {strategy}")
        queries = _translated_queries(query, always=strategy == "hybrid-english")
        reranker = CohereReranker()
        outcome = retrieve_two_hop(
            query,
            queries,
            retrieve=lambda qs: search_queries_hybrid(
                qs,
                per_query_k=per_query_k,
                final_k=pool,
            ),
            rerank=lambda q, rs: reranker.rerank(q, rs, top_n=settings.retrieval_top_k),
            assess=EvidencePlanner().assess,
            context_k=settings.generation_top_k,
        )
        return generate_answer(
            query=query, results=outcome.results, top_k=settings.generation_top_k
        )
    if strategy == "dense":
        candidates = search(query=query, k=pool)
    elif strategy in {"hybrid", "hybrid-english"}:
        queries = _translated_queries(query, always=strategy == "hybrid-english")
        if len(queries) == 1:
            candidates = search_hybrid(query=queries[0], k=pool)
        else:
            candidates = search_queries_hybrid(
                queries=queries,
                per_query_k=per_query_k,
                final_k=pool,
            )
    else:
        raise ValueError(f"Unknown retrieval strategy: {strategy}")
    if not candidates:
        return generate_answer(query=query, results=[], top_k=settings.generation_top_k)
    reranked = CohereReranker().rerank(
        query=query,
        results=candidates,
        top_n=settings.retrieval_top_k,
    )
    return generate_answer(
        query=query, results=reranked, top_k=settings.generation_top_k
    )
