"""How many passages per page should search_docs return? Four variants, stored scores.

search_docs returns the best chunk of each page (`core.one_per_page`). The
agent then sees one heading per page and can miss a second relevant section
of the same page. This compares, on the same pools and the same Cohere scores:

    A  one passage per page (today)
    B  up to two passages per page
    C  a second passage only when its score is close to the page's best
       (>= 0.8 x best and >= 0.35)
    D  one passage per page, plus the headings of the page's other chunks
       that scored >= 0.35 ("other_sections", no text; up to three)

B and C spend result slots on second passages; D does not.

    uv run python -m evals.experiments.passages_per_page scores --out DIR
    uv run python -m evals.experiments.passages_per_page run --out DIR \
        [--eval-cache EVAL_CACHE_DIR/rerank-scores.jsonl] [--score-missing]

`scores` reads every `rerank-candidates` observation that Langfuse kept for
the 2026-10-11..13 eval runs and stores (query, chunk text) -> score. Cohere
scores a pair on its own (evals/eval_cache.py), so a stored score stands in
for a new call. `--eval-cache` adds the scores an earlier run cached on disk.
`--score-missing` sends Cohere only the candidates no stored run scored (one
call per question, through EvalReranker: primary key, stops on a monthly 429)
and caches them under EVAL_CACHE_DIR, which must be the --eval-cache folder.
`run` rebuilds each question's search_docs pool (one query,
pool 20, no product filter) from the live index, looks every candidate up,
and scores the variants only on questions whose whole pool is scored.
0 Cohere calls; one embedding per question. Set TRACING_ENABLED=false so the
pool rebuild leaves no traces.
"""

import argparse
import hashlib
import json
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.diagnose_retrieval import DATASETS, Case, Group, langfuse, row
from evals.eval_cache import EvalReranker, QuotaExhausted, cohere_calls
from evals.eval_cache import _key as cache_key
from evals.eval_cache import _score_cache
from evals.evidence_coverage import group_targets, matches_target
from evals.full_corpus_cases import CASES as FULL_CORPUS_CASES
from src.config import settings
from src.rag.reranker import CohereReranker
from src.rag.retriever import SearchResult, search_hybrid

POOL = 20
LIMITS = (5, 8)
FLOOR = 0.35
GAP = 0.8
OTHER_SECTIONS = 3
PREVIEW_CHARS = 300
DESCRIPTION_CHARS = 120  # typical one-line page description
SCORES_FROM = datetime(2026, 10, 11, tzinfo=UTC)
SCORES_TO = datetime(2026, 10, 14, tzinfo=UTC)  # before the 2026-10-14 reindex
VARIANTS = ("A", "B", "C", "D")


def key(query: str, text: str) -> str:
    return hashlib.sha256(f"{query}\u0000{text}".encode()).hexdigest()


# ------------------------------------------------------------------ scores


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def fetch_scores(out: Path) -> None:
    client = langfuse()
    scores: dict[str, float] = {}
    cursor = None
    pages = observations = 0
    while True:
        for attempt in range(5):
            try:
                response = client.api.observations.get_many(
                    name="rerank-candidates",
                    from_start_time=SCORES_FROM,
                    to_start_time=SCORES_TO,
                    fields="core,io",
                    limit=50,
                    cursor=cursor,
                )
                break
            except Exception:  # Langfuse Hobby rate limit
                time.sleep(15 * (attempt + 1))
        else:
            raise RuntimeError("Langfuse observations unavailable")
        pages += 1
        for observation in response.data:
            query = (_json(observation.input) or {}).get("query")
            if not query:
                continue
            observations += 1
            for result in _json(observation.output) or []:
                if result.get("content") is not None:
                    scores[key(query, result["content"])] = result["rerank_score"]
        print(f"page {pages}: {observations} observations, {len(scores)} pairs")
        cursor = getattr(getattr(response, "meta", None), "cursor", None)
        if not cursor:
            break
    out.mkdir(parents=True, exist_ok=True)
    (out / "scores.json").write_text(json.dumps(scores))
    print(f"stored {len(scores)} scored pairs from {observations} observations")


# ------------------------------------------------------------------- cases


def load_cases() -> list[Case]:
    cases: list[Case] = []
    for item in langfuse().get_dataset(DATASETS["retrieval-v3"]).items:
        groups = [Group("relevant", item.expected_output["relevant"])]
        cases.append(Case("retrieval-v3", "", item.input["question"], groups))
    for item in langfuse().get_dataset(DATASETS["evidence-coverage"]).items:
        groups = [
            Group(group["id"], group_targets(group))
            for group in item.expected_output["evidence_groups"]
        ]
        question = item.input["question"]
        cases.append(Case("evidence-coverage", "", question, groups))
    for case in FULL_CORPUS_CASES:
        groups = [Group("relevant", case["relevant"])]
        cases.append(Case("full-corpus", "", case["question"], groups))
    return cases


# ---------------------------------------------------------------- variants


def card(result: SearchResult, score: float) -> dict[str, Any]:
    info = row(result.document.metadata)
    text = result.document.metadata.get("raw_content") or result.document.page_content
    return {**info, "score": score, "preview": min(len(text), PREVIEW_CHARS)}


def pages(scored: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_page: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in scored:
        by_page[entry["source"]].append(entry)
    return by_page


def variant(name: str, scored: list[dict[str, Any]], limit: int) -> list[dict]:
    """Cards in order; each may carry `other_sections` headings."""
    by_page = pages(scored)
    if name == "A":
        best = [chunks[0] for chunks in by_page.values()]
        return sorted(best, key=lambda c: -c["score"])[:limit]
    if name == "B":
        kept = [c for chunks in by_page.values() for c in chunks[:2]]
        return sorted(kept, key=lambda c: -c["score"])[:limit]
    if name == "C":
        kept = []
        for chunks in by_page.values():
            kept.append(chunks[0])
            if len(chunks) > 1:
                second = chunks[1]
                if second["score"] >= max(FLOOR, GAP * chunks[0]["score"]):
                    kept.append(second)
        return sorted(kept, key=lambda c: -c["score"])[:limit]
    best = sorted((chunks[0] for chunks in by_page.values()), key=lambda c: -c["score"])
    cards = []
    for top in best[:limit]:
        others: list[str] = []
        for chunk in by_page[top["source"]][1:]:
            heading = chunk["heading"]
            if chunk["score"] >= FLOOR and heading != top["heading"]:
                if heading not in others:
                    others.append(heading)
        cards.append({**top, "other_sections": others[:OTHER_SECTIONS]})
    return cards


# ----------------------------------------------------------------- metrics


def page_target(target: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in target.items() if k != "heading_contains"}


def visible(cards: list[dict]) -> list[dict[str, Any]]:
    """Every (page, heading) the agent can see, with or without text."""
    seen = []
    for c in cards:
        seen.append(c)
        for heading in c.get("other_sections", []):
            seen.append({**c, "heading": heading})
    return seen


def group_hits(group: Group, cards: list[dict]) -> tuple[bool, bool | None]:
    page = any(matches_target(c, page_target(t)) for c in cards for t in group.targets)
    sectioned = [t for t in group.targets if t.get("heading_contains")]
    if not sectioned:
        return page, None
    section = any(matches_target(c, t) for c in visible(cards) for t in sectioned)
    return page, section


def size(cards: list[dict]) -> int:
    """Approximate tokens of a concise search_docs response."""
    chars = 0
    for c in cards:
        chars += c["preview"] + len(c["heading"]) + len(c["source"])
        chars += DESCRIPTION_CHARS + 60  # title, rank, score, field names
        chars += sum(len(h) + 4 for h in c.get("other_sections", []))
    return chars // 4


def run(out: Path, eval_cache: Path | None, score_missing: bool) -> None:
    scores: dict[str, float] = json.loads((out / "scores.json").read_text())
    cached: dict[str, float] = {}
    if eval_cache is not None:
        for line in eval_cache.read_text().splitlines():
            if line.strip():
                entry = json.loads(line)
                cached[entry["key"]] = entry["score"]
    model = settings.cohere_rerank_model

    def lookup(question: str, result: SearchResult) -> float | None:
        # Langfuse spans keep page_content; the eval cache keys the text
        # Cohere actually read (title, heading and body).
        found = scores.get(key(question, result.document.page_content))
        if found is not None:
            return found
        text = CohereReranker._document_text(result.document)
        return cached.get(cache_key(model, question, text))

    records = []
    for case in load_cases():
        pool = search_hybrid(case.question, k=POOL)
        found = [lookup(case.question, r) for r in pool]
        if score_missing and None in found:
            # Seed the cache with the stored scores, so Cohere sees only gaps.
            store = _score_cache()
            for result, score in zip(pool, found):
                text = CohereReranker._document_text(result.document)
                cache_id = cache_key(model, case.question, text)
                if score is not None and cache_id not in store.scores:
                    store.add(cache_id, score)
            try:
                EvalReranker().rerank(case.question, pool, top_n=len(pool))
            except QuotaExhausted:
                print("Cohere monthly quota exhausted; stopping the scoring")
                score_missing = False
            cached.update(store.scores)
            found = [lookup(case.question, r) for r in pool]
        scored_share = sum(s is not None for s in found) / max(len(pool), 1)
        record: dict[str, Any] = {
            "dataset": case.dataset,
            "question": case.question,
            "scored": scored_share,
        }
        if scored_share == 1.0:
            entries = [card(r, s) for r, s in zip(pool, found) if s is not None]
            entries.sort(key=lambda c: -c["score"])
            for limit in LIMITS:
                for name in VARIANTS:
                    cards = variant(name, entries, limit)
                    hits = [group_hits(g, cards) for g in case.groups]
                    record[f"{name}@{limit}"] = {
                        "page": [h[0] for h in hits],
                        "section": [h[1] for h in hits],
                        "pages": len({c["source"] for c in cards}),
                        "cards": len(cards),
                        "tokens": size(cards),
                    }
        records.append(record)
        print(f"{case.dataset}: scored {scored_share:.0%}  {case.question[:60]}")
    print(f"Cohere calls: {cohere_calls()}")
    (out / "records.json").write_text(json.dumps(records, indent=1))
    (out / "summary.md").write_text(summary(records))
    print(summary(records))


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else float("nan")


def summary(records: list[dict[str, Any]]) -> str:
    lines = []
    for dataset in ("retrieval-v3", "evidence-coverage", "full-corpus"):
        rows = [r for r in records if r["dataset"] == dataset]
        full = [r for r in rows if r["scored"] == 1.0]
        lines.append(f"\n### {dataset}: {len(full)} of {len(rows)} fully scored\n")
        lines.append(
            "| limit | variant | page hit (groups) | all groups | section hit"
            " | section labels | pages | cards | tokens |"
        )
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for limit in LIMITS:
            for name in VARIANTS:
                cells = [r[f"{name}@{limit}"] for r in full]
                page = [h for c in cells for h in c["page"]]
                every = [all(c["page"]) for c in cells]
                section = [h for c in cells for h in c["section"] if h is not None]
                lines.append(
                    f"| {limit} | {name} | {_mean(page):.3f} | {_mean(every):.3f}"
                    f" | {_mean(section):.3f} | {len(section)}"
                    f" | {_mean([c['pages'] for c in cells]):.2f}"
                    f" | {_mean([c['cards'] for c in cells]):.2f}"
                    f" | {_mean([c['tokens'] for c in cells]):.0f} |"
                )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("scores", "run"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--eval-cache", type=Path)
    parser.add_argument("--score-missing", action="store_true")
    args = parser.parse_args()
    if args.command == "scores":
        fetch_scores(args.out)
    else:
        run(args.out, args.eval_cache, args.score_missing)


if __name__ == "__main__":
    main()
