"""Locate where multi-aspect evidence is lost between retrieval and generation.

Offline probe: one hybrid retrieval and one rerank per question, then several
context-selection variants over the same candidates, plus two diagnostics.

oracle@k asks whether any selection of k candidates could cover every evidence
group, which separates "the selector is wrong" from "the context is too small".
The judge matrix compares EvidencePlanner.sufficient against the ground-truth
completeness of the context it was shown.

Run: uv run python -m evals.experiments.probe_context_assembly
"""

import argparse
import time
from collections.abc import Callable
from itertools import combinations
from typing import Any, TypeVar

from cohere.errors.too_many_requests_error import TooManyRequestsError

from evals.evidence_coverage import CASES, coverage
from src.rag.context_selector import select_generation_context
from src.rag.planner import EvidencePlanner
from src.rag.reranker import CohereReranker, RerankResult
from src.rag.retriever import search_hybrid

CANDIDATE_POOL = 20
RERANK_TOP_K = 10
# Cohere trial keys allow 10 calls/minute; 6.5s (~9.2/min) was too close
# to the edge and tripped 429s mid-run. 10s keeps a safety margin.
COHERE_REQUEST_INTERVAL_SECONDS = 10.0


def _rows(results: list[RerankResult]) -> list[dict[str, Any]]:
    rows = []
    for result in results:
        metadata = result.document.metadata
        rows.append(
            {
                "vendor": metadata.get("vendor"),
                "product": metadata.get("product"),
                "title": metadata.get("title"),
                "heading": " > ".join(
                    value
                    for value in (
                        metadata.get("h1"),
                        metadata.get("h2"),
                        metadata.get("h3"),
                    )
                    if value
                ),
                "source": metadata.get("source"),
            }
        )
    return rows


def _complete(results: list[RerankResult], case: dict[str, Any]) -> float:
    measured = coverage(
        {"results": _rows(results)}, {"evidence_groups": case["evidence_groups"]}
    )
    return measured["complete"]


def oracle_complete(
    ranked: list[RerankResult], case: dict[str, Any], k: int
) -> tuple[float, str]:
    """Smallest set of candidates covering every group, capped at k."""
    rows = _rows(ranked)
    per_group = []
    for group in case["evidence_groups"]:
        hits = {
            index
            for index, row in enumerate(rows)
            if coverage({"results": [row]}, {"evidence_groups": [group]})["complete"]
        }
        if not hits:
            return 0.0, "group-not-in-pool"
        per_group.append(hits)

    universe = sorted(set().union(*per_group))
    for size in range(1, min(k, len(per_group)) + 1):
        for combo in combinations(universe, size):
            picked = set(combo)
            if all(hits & picked for hits in per_group):
                return 1.0, f"min={size}"
    return 0.0, f"needs>{k}"


T = TypeVar("T")


def with_cohere_retry(
    call: Callable[[], T],
    *,
    sleep: Callable[[float], None] = time.sleep,
    max_attempts: int = 5,
    initial_backoff: float = 10.0,
) -> T:
    """Retry a Cohere call through 429s with exponential backoff.

    A trial key's per-minute window can already be partly spent by an earlier
    run in the same minute, so even a conservative fixed interval can still
    open with a 429; this recovers instead of losing the whole run.
    """
    backoff = initial_backoff
    for attempt in range(1, max_attempts + 1):
        try:
            return call()
        except TooManyRequestsError:
            if attempt == max_attempts:
                raise
            sleep(backoff)
            backoff *= 2
    raise AssertionError("unreachable")


def coverage_curve(
    cases: list[dict[str, Any]],
    pools: list[int],
    retrieve_and_rank: Callable[[str, int], list[RerankResult]],
    on_pool_done: Callable[[int, float], None] | None = None,
) -> dict[int, float]:
    """Complete-coverage rate of the whole reranked pool, per pool size.

    Retrieval-only: this is the recall ceiling the selector works under, so
    the choice of retrieval_top_k rests on a curve rather than two points.
    `on_pool_done` fires after each pool size so a crash (e.g. a rate limit)
    partway through does not lose results already computed for smaller pools.
    """
    curve: dict[int, float] = {}
    for pool in pools:
        total = 0.0
        for case in cases:
            total += _complete(retrieve_and_rank(case["question"], pool), case)
        curve[pool] = total / len(cases)
        if on_pool_done is not None:
            on_pool_done(pool, curve[pool])
    return curve


def _live_retrieve_and_rank(
    reranker: CohereReranker,
) -> Callable[[str, int], list[RerankResult]]:
    def run(question: str, pool: int) -> list[RerankResult]:
        candidates = search_hybrid(question, k=pool)
        ranked = with_cohere_retry(
            lambda: reranker.rerank(question, candidates, top_n=pool)
        )
        time.sleep(COHERE_REQUEST_INTERVAL_SECONDS)
        return ranked

    return run


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--curve",
        nargs="*",
        type=int,
        metavar="POOL",
        help="retrieval-only: complete coverage per candidate pool size "
        "(default 5 10 15 20 30) and exit",
    )
    parser.add_argument(
        "--pool",
        type=int,
        default=CANDIDATE_POOL,
        help="candidates retrieved before reranking (pipeline uses 10)",
    )
    parser.add_argument(
        "--skip-judge", action="store_true", help="coverage only, no LLM calls"
    )
    args = parser.parse_args()
    reranker = CohereReranker()
    if args.curve is not None:
        pools = args.curve or [5, 10, 15, 20, 30]
        print("pool  complete-coverage of the whole reranked pool")
        coverage_curve(
            CASES,
            pools,
            _live_retrieve_and_rank(reranker),
            on_pool_done=lambda pool, value: print(
                f"{pool:4}  {value:.3f}", flush=True
            ),
        )
        return
    planner = EvidencePlanner()
    variants = ["pool", "oracle5", "oracle8", "selected5", "selected8"]
    totals = dict.fromkeys(variants, 0.0)
    # Ground truth is whether the shown context covered every group.
    matrix = {
        "caught_gap": 0,  # incomplete context, judge said insufficient
        "accepted_complete": 0,  # complete context, judge said sufficient
        "missed_gap": 0,  # incomplete context, judge said sufficient
        "spurious_gap": 0,  # complete context, judge said insufficient
    }

    for case in CASES:
        ranked = reranker.rerank(
            case["question"],
            search_hybrid(case["question"], k=args.pool),
            top_n=args.pool,
        )
        time.sleep(COHERE_REQUEST_INTERVAL_SECONDS)

        selected8 = select_generation_context(ranked[:RERANK_TOP_K], 8)
        oracle5, reason = oracle_complete(ranked, case, 5)
        measured = {
            "pool": _complete(ranked, case),
            "oracle5": oracle5,
            "oracle8": oracle_complete(ranked, case, 8)[0],
            "selected5": _complete(
                select_generation_context(ranked[:RERANK_TOP_K], 5), case
            ),
            "selected8": _complete(selected8, case),
        }
        for key, value in measured.items():
            totals[key] += value

        context_is_complete = bool(measured["selected8"])
        judge_says_sufficient = None
        if not args.skip_judge:
            judge_says_sufficient = planner.assess(
                case["question"], selected8
            ).sufficient
            matrix[
                {
                    (False, False): "caught_gap",
                    (True, True): "accepted_complete",
                    (False, True): "missed_gap",
                    (True, False): "spurious_gap",
                }[(context_is_complete, judge_says_sufficient)]
            ] += 1

        print(
            f"{case['id']:42} pool={measured['pool']:.0f} "
            f"oracle5={oracle5:.0f}({reason}) selected5={measured['selected5']:.0f} "
            f"selected8={measured['selected8']:.0f} judge_sufficient={judge_says_sufficient}",
            flush=True,
        )

    print()
    print(f"candidate pool = {args.pool}")
    for key in variants:
        print(f"{key:10} complete={totals[key] / len(CASES):.3f}")
    if args.skip_judge:
        return
    print()
    print("judge vs. ground truth on the 8-chunk context")
    for key, value in matrix.items():
        print(f"  {key:19} {value}")


if __name__ == "__main__":
    main()
