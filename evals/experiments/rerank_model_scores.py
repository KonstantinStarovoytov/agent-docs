"""Score distributions of two rerank models on the same candidates (experiment 28).

Run from the repo root with EVAL_CACHE_DIR set to the cache the gate runs
filled: answerable pools are served from it; only rag/negative-v1 costs calls
(12 per model). Writes reports/rerank-v5-2026-11-scores.json.
"""

import json
import sys
from pathlib import Path

from evals import negative_cases
from evals.eval_cache import EvalReranker, cohere_calls
from evals.evaluators import _is_relevant
from evals.evidence_coverage import group_targets, matches_target
from evals.run_experiments import _candidates, get_heading, langfuse
from src.rag.retriever import rerank_pool_size, search_hybrid

MODELS = sys.argv[1:] or ["rerank-v4.0-fast", "rerank-v5.0-fast"]
POOL = rerank_pool_size()


def row(result) -> dict:
    metadata = result.document.metadata
    return {
        "vendor": metadata.get("vendor"),
        "product": metadata.get("product"),
        "title": metadata.get("title"),
        "heading": get_heading(result.document),
        "source": metadata.get("source"),
        "score": result.rerank_score,
    }


def ranked(model: str, question: str, candidates) -> list[dict]:
    reranker = EvalReranker()
    reranker.model = model
    return [
        row(r) for r in reranker.rerank(question, candidates, top_n=len(candidates))
    ]


cases = []
for name, kind in (
    ("rag/retrieval-v3", "retrieval"),
    ("rag/full-corpus-v1", "retrieval"),
    ("rag/evidence-coverage-v1", "coverage"),
    (negative_cases.DATASET_NAME, "negative"),
):
    for item in langfuse.get_dataset(name).items:
        question = item.input["question"]
        candidates = (
            _candidates(question)
            if kind == "retrieval"
            else search_hybrid(question, k=POOL)
        )
        case = {"dataset": name, "kind": kind, "question": question, "models": {}}
        for model in MODELS:
            rows = ranked(model, question, candidates)
            if kind == "retrieval":
                for r in rows:
                    r["correct"] = _is_relevant(r, item.expected_output)
            elif kind == "coverage":
                for r in rows:
                    r["groups"] = [
                        g["id"]
                        for g in item.expected_output["evidence_groups"]
                        if any(matches_target(r, t) for t in group_targets(g))
                    ]
                    r["correct"] = bool(r["groups"])
            else:
                for r in rows:
                    r["correct"] = False
            case["models"][model] = rows
        cases.append(case)
        print(name, len(cases), cohere_calls(), flush=True)

out = Path("reports/rerank-v5-2026-11-scores.json")
out.write_text(json.dumps(cases, ensure_ascii=False, indent=1))
print("wrote", out, "cohere calls:", cohere_calls())
