"""Compare standard hybrid retrieval with bounded two-hop retrieval coverage."""

import argparse

from functools import lru_cache

from langfuse import Langfuse

from evals.eval_cache import EvalReranker, cache_dir, cohere_calls
from evals.evidence_coverage import (
    DATASET_NAME,
    complete_evidence_coverage,
    evidence_coverage,
)
from src.config import settings
from src.rag.context_selector import select_generation_context
from src.rag.iterative import retrieve_two_hop
from src.rag.multi_query_retriever import search_queries_hybrid
from src.rag.planner import EvidencePlanner
from src.rag.retriever import SearchResult, rerank_pool_size, search_hybrid

# The pool sent to Cohere follows RERANK_POOL / HYBRID_PREFETCH_DEPTH like the
# answer pipeline; the default (10) reproduces the earlier runs.
RETRIEVAL_TOP_K = rerank_pool_size()
GENERATION_TOP_K = settings.generation_top_k
PER_QUERY_TOP_K = 20


@lru_cache(maxsize=1)
def langfuse_client() -> Langfuse:
    """Built on first use, so importing this module needs no Langfuse keys."""
    secret = settings.langfuse_secret_key
    if secret is None:
        raise ValueError("LANGFUSE_SECRET_KEY must be set to run experiments")
    return Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=secret.get_secret_value(),
        base_url=settings.langfuse_base_url,
    )


def _result_row(result: SearchResult) -> dict:
    metadata = result.document.metadata
    return {
        "rank": result.rerank_rank,
        "vendor": metadata.get("vendor"),
        "product": metadata.get("product"),
        "title": metadata.get("title"),
        "heading": " > ".join(
            value
            for value in (metadata.get("h1"), metadata.get("h2"), metadata.get("h3"))
            if value
        ),
        "source": metadata.get("source"),
        "retrieval_score": result.retrieval_score,
        "rerank_score": result.rerank_score,
    }


def _rerank(question: str, candidates: list[SearchResult]) -> list[SearchResult]:
    # Primary key only, paced, stops on a monthly-quota 429, cached with
    # EVAL_CACHE_DIR (evals/eval_cache.py).
    return EvalReranker().rerank(question, candidates, top_n=RETRIEVAL_TOP_K)


def baseline_task(*, item, **_kwargs) -> dict:
    question = item.input["question"]
    ranked = _rerank(question, search_hybrid(question, k=RETRIEVAL_TOP_K))
    selected = select_generation_context(ranked, GENERATION_TOP_K)
    return {
        "results": [_result_row(result) for result in selected],
        "rounds": 1,
        "stop_reason": "single_pass",
        "follow_up_queries": [],
    }


def iterative_task(*, item, **_kwargs) -> dict:
    question = item.input["question"]
    outcome = retrieve_two_hop(
        question,
        [question],
        retrieve=lambda queries: search_queries_hybrid(
            queries, per_query_k=PER_QUERY_TOP_K, final_k=RETRIEVAL_TOP_K
        ),
        rerank=_rerank,
        assess=EvidencePlanner().assess,
        context_k=GENERATION_TOP_K,
    )
    return {
        "results": [_result_row(result) for result in outcome.results],
        "rounds": outcome.rounds,
        "stop_reason": outcome.stop_reason,
        "follow_up_queries": outcome.follow_up_queries,
        "planner_sufficient": [decision.sufficient for decision in outcome.decisions],
    }


def _metadata(mode: str) -> dict:
    return {
        "mode": mode,
        "retriever": "Qdrant hybrid dense+BM25 RRF",
        "reranker": settings.cohere_rerank_model,
        "retrieval_top_k": RETRIEVAL_TOP_K,
        "hybrid_prefetch_depth": settings.hybrid_prefetch_depth,
        "rerank_cache": cache_dir() is not None,
        "generation_top_k": GENERATION_TOP_K,
        "per_query_top_k": PER_QUERY_TOP_K if mode == "iterative" else None,
        "answer_prompt_version": settings.answer_prompt_version or "production:v1",
        "translate_prompt_version": settings.translate_prompt_version
        or "production:v1",
        "planner_prompt_version": (
            settings.evidence_planner_prompt_version or "production:v1"
        ),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evidence coverage experiments.")
    parser.add_argument(
        "--baseline-only",
        action="store_true",
        help="run only the single-pass baseline (one Cohere call per item)",
    )
    parser.add_argument(
        "--name-suffix",
        default="",
        help="appended to the run names, e.g. '-p60-pool40'",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    dataset = langfuse_client().get_dataset(DATASET_NAME)
    common = {
        "evaluators": [evidence_coverage, complete_evidence_coverage],
        "max_concurrency": 1,
    }
    baseline = dataset.run_experiment(
        name=f"evidence-coverage-baseline-v3-section-diverse{args.name_suffix}",
        description="Single-pass hybrid retrieval, Cohere rerank, and section-diverse final top-5 evidence coverage.",
        task=baseline_task,
        metadata=_metadata("baseline"),
        **common,
    )
    print(baseline.format())
    print(f"Cohere calls made by this process: {cohere_calls()}")
    if args.baseline_only:
        langfuse_client().flush()
        return
    iterative = dataset.run_experiment(
        name=f"evidence-coverage-iterative-v3-section-diverse{args.name_suffix}",
        description="Bounded two-hop hybrid retrieval and section-diverse final top-5 evidence coverage.",
        task=iterative_task,
        metadata=_metadata("iterative"),
        **common,
    )
    print(iterative.format())
    langfuse_client().flush()


if __name__ == "__main__":
    main()
