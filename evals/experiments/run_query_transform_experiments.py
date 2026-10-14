"""Retrieval on `rag/retrieval-query-transform-v1`, with and without query transformation."""

import argparse
import time

from langfuse import Langfuse

from evals.evaluators import (
    hit_at_1,
    hit_at_5,
    hit_at_10,
    ndcg_at_10,
    precision_at_5,
    precision_at_8,
    precision_at_10,
    reciprocal_rank,
)
from src.config import settings
from src.rag.multi_query_retriever import (
    search_multi_query_hybrid,
)
from src.rag.reranker import CohereReranker
from src.rag.retriever import search_hybrid

DATASET_NAME = "rag/retrieval-query-transform-v1"

RETRIEVE_K = 10
RERANK_TOP_N = 10

MULTI_QUERY_PER_QUERY_K = 20
MULTI_QUERY_FINAL_K = 10


langfuse = Langfuse(
    public_key=settings.langfuse_public_key,
    secret_key=(settings.langfuse_secret_key.get_secret_value()),
    base_url=settings.langfuse_base_url,
)

reranker = CohereReranker()


def get_heading(document) -> str:
    metadata = document.metadata

    return " > ".join(
        value
        for value in (
            metadata.get("h1"),
            metadata.get("h2"),
            metadata.get("h3"),
        )
        if value
    )


# ---------------------------------------------------------
# BASELINE
#
# Original query
# -> Dense + BM25
# -> RRF
# -> Cohere
# ---------------------------------------------------------


def hybrid_cohere_task(
    *,
    item,
    **kwargs,
):
    question = item.input["question"]

    results = search_hybrid(
        query=question,
        k=RETRIEVE_K,
    )

    # Cohere Trial:
    # max 10 requests / minute.
    time.sleep(6.5)

    reranked = reranker.rerank(
        query=question,
        results=results,
        top_n=RERANK_TOP_N,
    )

    return {
        "results": [
            {
                "rank": result.rerank_rank,
                "vendor": (result.document.metadata.get("vendor")),
                "product": (result.document.metadata.get("product")),
                "title": (result.document.metadata.get("title")),
                "heading": get_heading(result.document),
                "source": (result.document.metadata.get("source")),
                "hybrid_rank": (result.original_rank),
                "hybrid_score": (result.retrieval_score),
                "rerank_score": (result.rerank_score),
            }
            for result in reranked
        ]
    }


# ---------------------------------------------------------
# QUERY TRANSFORM
#
# Original
# + English translation
# + semantic variant
#
# -> hybrid search for each
# -> multi-query RRF
# -> Cohere
# ---------------------------------------------------------


def rewrite_hybrid_cohere_task(
    *,
    item,
    **kwargs,
):
    question = item.input["question"]

    results = search_multi_query_hybrid(
        query=question,
        per_query_k=MULTI_QUERY_PER_QUERY_K,
        final_k=MULTI_QUERY_FINAL_K,
    )

    time.sleep(6.5)

    reranked = reranker.rerank(
        query=question,
        results=results,
        top_n=RERANK_TOP_N,
    )

    return {
        "results": [
            {
                "rank": result.rerank_rank,
                "vendor": (result.document.metadata.get("vendor")),
                "product": (result.document.metadata.get("product")),
                "title": (result.document.metadata.get("title")),
                "heading": get_heading(result.document),
                "source": (result.document.metadata.get("source")),
                "multi_query_rank": (result.original_rank),
                "multi_query_rrf_score": (result.retrieval_score),
                "rerank_score": (result.rerank_score),
            }
            for result in reranked
        ]
    }


EVALUATORS = [
    hit_at_1,
    hit_at_5,
    hit_at_10,
    reciprocal_rank,
    precision_at_5,
    precision_at_8,
    precision_at_10,
    ndcg_at_10,
]


def main() -> None:
    dataset = langfuse.get_dataset(DATASET_NAME)

    # -----------------------------------------------------
    # A — no query transformation
    # -----------------------------------------------------

    print("Running Hybrid + Cohere baseline...")

    baseline = dataset.run_experiment(
        name="query-transform-baseline-v1",
        description=(
            "Original query only: OpenAI dense + BM25 sparse + Qdrant RRF + Cohere"
        ),
        task=hybrid_cohere_task,
        evaluators=EVALUATORS,
        metadata={
            "query_strategy": "original-only",
            "dense_embedding": ("text-embedding-3-small"),
            "sparse_embedding": ("Qdrant/bm25"),
            "retriever": "hybrid",
            "fusion": "RRF",
            "reranker": "rerank-v4.0-fast",
            "retrieve_k": RETRIEVE_K,
            "rerank_top_n": RERANK_TOP_N,
        },
        max_concurrency=1,
    )

    print(baseline.format())

    print()

    # -----------------------------------------------------
    # B — query transformation
    # -----------------------------------------------------

    print("Running Query Transform + Hybrid + Cohere...")

    transformed = dataset.run_experiment(
        name="query-transform-v1",
        description=(
            "Original + faithful English + "
            "semantic variant, "
            "OpenAI dense + BM25 sparse + "
            "Qdrant RRF + multi-query RRF + "
            "Cohere"
        ),
        task=rewrite_hybrid_cohere_task,
        evaluators=EVALUATORS,
        metadata={
            "query_strategy": ("original+english+semantic"),
            "dense_embedding": ("text-embedding-3-small"),
            "sparse_embedding": ("Qdrant/bm25"),
            "retriever": ("multi-query-hybrid"),
            "fusion": ("Qdrant-RRF+multi-query-RRF"),
            "reranker": "rerank-v4.0-fast",
            "per_query_k": (MULTI_QUERY_PER_QUERY_K),
            "final_k": (MULTI_QUERY_FINAL_K),
            "rerank_top_n": RERANK_TOP_N,
        },
        max_concurrency=1,
    )

    print(transformed.format())

    langfuse.flush()


if __name__ == "__main__":
    # Running writes to Langfuse; --help must not.
    argparse.ArgumentParser(description=__doc__).parse_args()
    main()
