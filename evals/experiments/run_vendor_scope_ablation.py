"""Compare unscoped and explicit single-vendor hybrid + Cohere retrieval."""

import time

from langfuse import Langfuse

from evals.evaluators import (
    hit_at_1,
    hit_at_5,
    hit_at_10,
    ndcg_at_10,
    precision_at_8,
    reciprocal_rank,
)
from evals.experiments.seed_vendor_scope_dataset import DATASET_NAME
from src.config import settings
from src.rag.reranker import CohereReranker
from src.rag.retriever import SearchResult, search_hybrid
from src.rag.scope import infer_single_vendor

RETRIEVAL_TOP_K = 10
COHERE_REQUEST_INTERVAL_SECONDS = 6.5

langfuse = Langfuse(
    public_key=settings.langfuse_public_key,
    secret_key=settings.langfuse_secret_key.get_secret_value(),
    base_url=settings.langfuse_base_url,
)


def _output(results: list[SearchResult]) -> dict:
    return {
        "results": [
            {
                "rank": result.rerank_rank,
                "vendor": result.document.metadata.get("vendor"),
                "product": result.document.metadata.get("product"),
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
                "source": result.document.metadata.get("source"),
                "retrieval_score": result.retrieval_score,
                "rerank_score": result.rerank_score,
            }
            for result in results
        ]
    }


def _task(*, item, use_vendor_scope: bool, **_kwargs) -> dict:
    question = item.input["question"]
    vendor = infer_single_vendor(question) if use_vendor_scope else None
    candidates = search_hybrid(question, k=RETRIEVAL_TOP_K, vendor=vendor)
    reranked = CohereReranker().rerank(question, candidates, top_n=RETRIEVAL_TOP_K)
    time.sleep(COHERE_REQUEST_INTERVAL_SECONDS)
    return _output(reranked)


def main() -> None:
    dataset = langfuse.get_dataset(DATASET_NAME)
    evaluators = [
        hit_at_1,
        hit_at_5,
        hit_at_10,
        precision_at_8,
        ndcg_at_10,
        reciprocal_rank,
    ]
    common = {"evaluators": evaluators, "max_concurrency": 1}
    baseline = dataset.run_experiment(
        name="vendor-scope-unscoped-v1",
        description="Hybrid dense+BM25 RRF and Cohere rerank without metadata scope.",
        task=lambda **kwargs: _task(**kwargs, use_vendor_scope=False),
        metadata={
            "vendor_scope": "disabled",
            "retrieval_top_k": RETRIEVAL_TOP_K,
            "reranker": settings.cohere_rerank_model,
        },
        **common,
    )
    print(baseline.format())
    scoped = dataset.run_experiment(
        name="vendor-scope-explicit-single-vendor-v1",
        description=(
            "Use Qdrant metadata.vendor only when the question explicitly names "
            "one product; otherwise use unscoped hybrid retrieval."
        ),
        task=lambda **kwargs: _task(**kwargs, use_vendor_scope=True),
        metadata={
            "vendor_scope": "explicit-single-vendor-only",
            "retrieval_top_k": RETRIEVAL_TOP_K,
            "reranker": settings.cohere_rerank_model,
        },
        **common,
    )
    print(scoped.format())
    langfuse.flush()


if __name__ == "__main__":
    main()
