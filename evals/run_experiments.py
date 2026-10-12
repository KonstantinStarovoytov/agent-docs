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

DATASET_NAME = "rag/retrieval-v3"

MULTI_QUERY_PER_QUERY_K = 20
MULTI_QUERY_FINAL_K = 10

RERANK_TOP_N = 10


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


def rewrite_hybrid_task(
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

    results = search_multi_query_hybrid(
        query=question,
        per_query_k=MULTI_QUERY_PER_QUERY_K,
        final_k=MULTI_QUERY_FINAL_K,
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
    args = parser.parse_args()

    dataset = langfuse.get_dataset(args.dataset)

    print("Running rewrite + hybrid...")

    rewrite_hybrid_result = dataset.run_experiment(
        name=("rewrite-hybrid-multisource-v1"),
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
        },
        max_concurrency=5,
    )

    print(rewrite_hybrid_result.format())

    print()
    print("Running rewrite + hybrid + Cohere...")

    rewrite_hybrid_cohere_result = dataset.run_experiment(
        name=("rewrite-hybrid-cohere-multisource-v1"),
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
        },
        max_concurrency=1,
    )

    print(rewrite_hybrid_cohere_result.format())

    langfuse.flush()


if __name__ == "__main__":
    main()
