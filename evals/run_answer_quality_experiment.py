"""Answer quality on the multi-aspect set, or abstention on the negative set.

uv run python -m evals.run_answer_quality_experiment            # 16 cases
uv run python -m evals.run_answer_quality_experiment --negative # abstentions
"""

import argparse
from typing import Any

from langfuse import Langfuse

from evals import negative_cases
from evals.answer_quality import (
    abstention_correct,
    answer_quality_metrics,
    judge_is_independent,
    judge_model,
)
from evals.eval_cache import EvalReranker, cache_dir, cohere_calls
from evals.evidence_coverage import (
    DATASET_NAME,
    complete_evidence_coverage,
    evidence_coverage,
)
from src.config import settings
from src.rag.context_selector import select_generation_context
from src.rag.generator import generate_from_selected
from src.rag.iterative import retrieve_two_hop
from src.rag.multi_query_retriever import search_queries_hybrid
from src.rag.planner import EvidencePlanner
from src.rag.reranker import RerankResult
from src.rag.retriever import SearchResult, rerank_pool_size, search_hybrid

# Defaults reproduce the September runs (pool 10, rerank top 10); RERANK_POOL,
# HYBRID_PREFETCH_DEPTH and RETRIEVAL_TOP_K change them like in production.
RETRIEVAL_TOP_K = settings.retrieval_top_k
RERANK_POOL = rerank_pool_size()
GENERATION_TOP_K = settings.generation_top_k
PER_QUERY_TOP_K = max(settings.per_query_top_k, RERANK_POOL)

langfuse = Langfuse(
    public_key=settings.langfuse_public_key,
    secret_key=settings.langfuse_secret_key.get_secret_value(),
    base_url=settings.langfuse_base_url,
)


def _rerank(question: str, candidates: list[SearchResult]) -> list[RerankResult]:
    # EvalReranker keeps calls below the free tier's rate and never falls back
    # to the second key (evals/eval_cache.py).
    return EvalReranker().rerank(question, candidates, top_n=RETRIEVAL_TOP_K)


def _context_rows(results: list[RerankResult]) -> list[dict[str, Any]]:
    rows = []
    for citation, result in enumerate(results, start=1):
        metadata = result.document.metadata
        rows.append(
            {
                "citation": citation,
                "title": metadata.get("title", "Untitled"),
                "heading": " > ".join(
                    value
                    for value in (
                        metadata.get("h1"),
                        metadata.get("h2"),
                        metadata.get("h3"),
                    )
                    if value
                ),
                "source": metadata.get("source", ""),
                "content": metadata.get("raw_content", result.document.page_content),
                "rerank_score": result.rerank_score,
            }
        )
    return rows


def _result_rows(results: list[RerankResult]) -> list[dict[str, Any]]:
    return [
        {
            "rank": result.rerank_rank,
            "vendor": result.document.metadata.get("vendor"),
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
            "rerank_score": result.rerank_score,
        }
        for result in results
    ]


def _answer_output(
    question: str,
    selected: list[RerankResult],
    *,
    rounds: int,
    stop_reason: str,
    follow_up_queries: list[str],
) -> dict[str, Any]:
    # Selection (with the relevance floor) already happened at the call
    # site; re-selecting here would silently diverge from the contexts
    # recorded below for the judge.
    generated = generate_from_selected(question, selected)
    return {
        "answer": generated.answer,
        "sources": [
            {
                "citation": source.citation,
                "title": source.title,
                "heading": source.heading,
                "url": source.url,
                "rerank_score": source.rerank_score,
            }
            for source in generated.sources
        ],
        "contexts": _context_rows(selected),
        "results": _result_rows(selected),
        "rounds": rounds,
        "stop_reason": stop_reason,
        "follow_up_queries": follow_up_queries,
    }


def baseline_task(*, item, **_kwargs) -> dict[str, Any]:
    question = item.input["question"]
    ranked = _rerank(question, search_hybrid(question, k=RERANK_POOL))
    selected = select_generation_context(
        ranked, GENERATION_TOP_K, min_rerank_score=settings.min_rerank_score
    )
    return _answer_output(
        question,
        selected,
        rounds=1,
        stop_reason="single_pass",
        follow_up_queries=[],
    )


def iterative_task(*, item, **_kwargs) -> dict[str, Any]:
    question = item.input["question"]
    outcome = retrieve_two_hop(
        question,
        [question],
        retrieve=lambda queries: search_queries_hybrid(
            queries, per_query_k=PER_QUERY_TOP_K, final_k=RERANK_POOL
        ),
        rerank=_rerank,
        assess=EvidencePlanner().assess,
        context_k=GENERATION_TOP_K,
    )
    return _answer_output(
        question,
        outcome.results,
        rounds=outcome.rounds,
        stop_reason=outcome.stop_reason,
        follow_up_queries=outcome.follow_up_queries,
    )


def _metadata(mode: str) -> dict[str, Any]:
    return {
        "mode": mode,
        "retriever": "Qdrant hybrid dense+BM25 RRF",
        "reranker": settings.cohere_rerank_model,
        "retrieval_top_k": RETRIEVAL_TOP_K,
        "rerank_pool": RERANK_POOL,
        "hybrid_prefetch_depth": settings.hybrid_prefetch_depth,
        "max_chunks_per_source_in_pool": settings.max_chunks_per_source_in_pool,
        "rerank_cache": cache_dir() is not None,
        "generation_top_k": GENERATION_TOP_K,
        "per_query_top_k": PER_QUERY_TOP_K if mode == "iterative" else None,
        "answer_model": settings.openai_chat_model,
        "evaluator_model": judge_model(),
        "evaluator_independent": judge_is_independent(),
        "evaluator_prompt": "doc-bot/answer-evaluator",
        "evaluator_prompt_version": (
            settings.answer_evaluator_prompt_version or "production"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compare-iterative", action="store_true")
    parser.add_argument(
        "--negative",
        action="store_true",
        help="run the unanswerable set and score whether the system abstained",
    )
    parser.add_argument("--name-suffix", default="", help="appended to the run names")
    args = parser.parse_args()
    suffix = args.name_suffix
    if args.negative:
        dataset = langfuse.get_dataset(negative_cases.DATASET_NAME)
        result = dataset.run_experiment(
            name=f"negative-abstention-k{GENERATION_TOP_K}{suffix}",
            description=(
                "Questions outside the corpus; the system should say the "
                "documentation does not cover them."
            ),
            task=baseline_task,
            metadata=_metadata("negative"),
            evaluators=[abstention_correct, answer_quality_metrics],
            max_concurrency=1,
        )
        print(result.format())
        langfuse.flush()
        return
    dataset = langfuse.get_dataset(DATASET_NAME)
    common = {
        "evaluators": [
            evidence_coverage,
            complete_evidence_coverage,
            answer_quality_metrics,
        ],
        "max_concurrency": 1,
    }
    baseline = dataset.run_experiment(
        name=f"answer-quality-baseline-k{GENERATION_TOP_K}{suffix}",
        description=(
            "Single-pass hybrid retrieval, Cohere rerank, answer generation, and "
            "strict groundedness/relevance/context/citation evaluation."
        ),
        task=baseline_task,
        metadata=_metadata("baseline"),
        **common,
    )
    print(baseline.format())
    print(f"Cohere calls made by this process: {cohere_calls()}")
    if not args.compare_iterative:
        langfuse.flush()
        return
    iterative = dataset.run_experiment(
        name=f"answer-quality-iterative-k{GENERATION_TOP_K}{suffix}",
        description=(
            "Bounded two-hop retrieval, answer generation, and strict "
            "groundedness/relevance/context/citation evaluation."
        ),
        task=iterative_task,
        metadata=_metadata("iterative"),
        **common,
    )
    print(iterative.format())
    langfuse.flush()


if __name__ == "__main__":
    main()
