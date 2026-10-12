import argparse

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
from evals.eval_cache import EvalReranker, cache_dir, cohere_calls, rewrite_queries
from src.config import settings
from src.rag.multi_query_retriever import search_queries_hybrid
from src.rag.retriever import rerank_pool_size

DATASET_NAME = "rag/retrieval-v3"

# Defaults reproduce the September runs: 20 per query, pool 10, rerank top 10.
# RERANK_POOL / HYBRID_PREFETCH_DEPTH / RETRIEVAL_TOP_K change them.
MULTI_QUERY_FINAL_K = rerank_pool_size()
MULTI_QUERY_PER_QUERY_K = max(settings.per_query_top_k, MULTI_QUERY_FINAL_K)

RERANK_TOP_N = settings.retrieval_top_k


langfuse = Langfuse(
    public_key=settings.langfuse_public_key,
    secret_key=(settings.langfuse_secret_key.get_secret_value()),
    base_url=settings.langfuse_base_url,
)


# Primary key only; stops on a monthly-quota 429 (evals/eval_cache.py).
reranker = EvalReranker()


def _candidates(question: str):
    # Same as search_multi_query_hybrid; the rewrite is frozen per question
    # when EVAL_CACHE_DIR is set.
    return search_queries_hybrid(
        queries=rewrite_queries(question),
        per_query_k=MULTI_QUERY_PER_QUERY_K,
        final_k=MULTI_QUERY_FINAL_K,
    )


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


def rewrite_hybrid_task(
    *,
    item,
    **kwargs,
):
    question = item.input["question"]

    results = _candidates(question)

    return {
        "results": [
            {
                "rank": rank,
                "vendor": (result.document.metadata.get("vendor")),
                "product": (result.document.metadata.get("product")),
                "title": (result.document.metadata.get("title")),
                "heading": get_heading(result.document),
                "source": (result.document.metadata.get("source")),
                "multi_query_rrf_score": (result.score),
            }
            for rank, result in enumerate(
                results,
                start=1,
            )
        ]
    }


def rewrite_hybrid_cohere_task(
    *,
    item,
    **kwargs,
):
    question = item.input["question"]

    results = _candidates(question)

    # EvalReranker keeps calls below the trial's 10 per minute.
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
    parser = argparse.ArgumentParser(description="Retrieval experiments.")
    parser.add_argument(
        "--dataset",
        default=DATASET_NAME,
        help=f"Langfuse dataset name (default: {DATASET_NAME})",
    )
    parser.add_argument(
        "--name-suffix",
        default="",
        help="appended to both run names, e.g. '-p150-pool40'",
    )
    parser.add_argument(
        "--skip-no-rerank",
        action="store_true",
        help="run only the Cohere experiment",
    )
    args = parser.parse_args()

    dataset = langfuse.get_dataset(args.dataset)
    pool_metadata = {
        "hybrid_prefetch_depth": settings.hybrid_prefetch_depth,
        "rerank_pool": MULTI_QUERY_FINAL_K,
        "max_chunks_per_source_in_pool": settings.max_chunks_per_source_in_pool,
        "frozen_rewrites_and_rerank_cache": cache_dir() is not None,
    }

    if args.skip_no_rerank:
        run_cohere(dataset, args.name_suffix, pool_metadata)
        return

    print("Running rewrite + hybrid...")

    rewrite_hybrid_result = dataset.run_experiment(
        name=f"rewrite-hybrid-multisource-v1{args.name_suffix}",
        description=(
            "Original + English + semantic "
            "variant, OpenAI dense + BM25 "
            "sparse + Qdrant RRF + "
            "multi-query RRF"
        ),
        task=rewrite_hybrid_task,
        evaluators=EVALUATORS,
        metadata={
            "query_strategy": ("original+english+semantic"),
            "retriever": ("multi-query-hybrid"),
            "dense_embedding": ("text-embedding-3-small"),
            "sparse_embedding": ("Qdrant/bm25"),
            "fusion": "RRF",
            "per_query_k": (MULTI_QUERY_PER_QUERY_K),
            "final_k": (MULTI_QUERY_FINAL_K),
            **pool_metadata,
        },
        max_concurrency=5,
    )

    print(rewrite_hybrid_result.format())

    print()
    run_cohere(dataset, args.name_suffix, pool_metadata)


def run_cohere(dataset, name_suffix: str, pool_metadata: dict) -> None:
    print("Running rewrite + hybrid + Cohere...")

    rewrite_hybrid_cohere_result = dataset.run_experiment(
        name=f"rewrite-hybrid-cohere-multisource-v1{name_suffix}",
        description=(
            "Original + English + semantic "
            "variant, OpenAI dense + BM25 "
            "sparse + Qdrant RRF + "
            "multi-query RRF + Cohere rerank"
        ),
        task=rewrite_hybrid_cohere_task,
        evaluators=EVALUATORS,
        metadata={
            "query_strategy": ("original+english+semantic"),
            "retriever": ("multi-query-hybrid"),
            "dense_embedding": ("text-embedding-3-small"),
            "sparse_embedding": ("Qdrant/bm25"),
            "fusion": "RRF",
            "reranker": ("rerank-v4.0-fast"),
            "per_query_k": (MULTI_QUERY_PER_QUERY_K),
            "final_k": (MULTI_QUERY_FINAL_K),
            "rerank_top_n": (RERANK_TOP_N),
            **pool_metadata,
        },
        max_concurrency=1,
    )

    print(rewrite_hybrid_cohere_result.format())
    print(f"Cohere calls made by this process: {cohere_calls()}")

    langfuse.flush()


if __name__ == "__main__":
    main()
