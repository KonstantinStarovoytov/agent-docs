"""Does another judge grade the stored answers the way gpt-6-sol did?

Reads every judged answer of the October answer-quality and negative runs
from Langfuse (question, generated answer, the contexts it saw, and the
stored scores), grades the same answer again with `--judge`, and writes both
verdicts side by side. No retrieval, no generation, no Cohere calls: one
judge call per answer. Identical answers from repeated runs are judged once.

    uv run python -m evals.experiments.judge_agreement \
        --judge claude-haiku-5-5 --out /tmp/judge-agreement.json

The output holds the retrieved documentation text, so it stays out of git;
only the summary goes into reports/.
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

from evals.answer_quality import assess_answer_quality
from src.observability import get_langfuse

RUNS = (
    ("rag/evidence-coverage-v1", "answer-quality-baseline-k8"),
    ("rag/negative-v1", "negative-abstention-k8"),
)
SINCE = datetime(2026, 10, 1, tzinfo=UTC)
METRICS = (
    "answer_faithfulness",
    "answer_relevance",
    "context_utilization",
    "citation_correctness",
)
# The judge's field for each stored score.
FIELDS = dict(
    zip(
        METRICS,
        (
            "faithfulness",
            "answer_relevance",
            "context_utilization",
            "citation_correctness",
        ),
    )
)
CLOSE = 0.25  # two scores this close count as agreeing


def stored_answers() -> list[dict[str, Any]]:
    client = get_langfuse()
    seen: set[str] = set()
    answers: list[dict[str, Any]] = []
    for dataset_name, prefix in RUNS:
        dataset = client.get_dataset(dataset_name)
        runs = [
            run
            for run in client.api.experiments.list(
                from_start_time=SINCE, dataset_id=dataset.id, fields=["core"], limit=100
            ).data
            if run.name.startswith(prefix)
        ]
        for run in sorted(runs, key=lambda r: r.start_time):
            items = client.api.experiments.list_items(
                from_start_time=SINCE,
                dataset_id=dataset.id,
                experiment_name=run.name,
                fields=["core", "io", "scores"],
                limit=100,
            ).data
            for item in items:
                scores = {
                    s.name: s.value if s.value is not None else s.string_value
                    for s in item.scores or []
                }
                if "answer_faithfulness" not in scores:
                    continue  # the run failed (e.g. Cohere quota) or no answer
                question = json.loads(item.input)["question"]
                output = json.loads(item.output)
                key = json.dumps([question, output["answer"]], ensure_ascii=False)
                if key in seen:
                    continue
                seen.add(key)
                expected = item.expected_output
                if isinstance(expected, str):
                    expected = json.loads(expected)
                answers.append(
                    {
                        "dataset": dataset_name,
                        "run": run.name,
                        "question": question,
                        "answer": output["answer"],
                        "contexts": output.get("contexts", []),
                        "expect_abstention": bool(
                            (expected or {}).get("expect_abstention", False)
                        ),
                        "stored": scores,
                    }
                )
    return answers


def regrade(answer: dict[str, Any], judge: str) -> dict[str, Any]:
    result = assess_answer_quality(
        answer["question"], answer["answer"], answer["contexts"], judge=judge
    ).assessment
    return {
        **{metric: getattr(result, FIELDS[metric]) for metric in METRICS},
        "answer_failure_mode": result.failure_mode,
        "unsupported_claims": result.unsupported_claims,
        "citation_issues": result.citation_issues,
        "summary": result.summary,
    }


def summarize(all_rows: list[dict[str, Any]], judge: str) -> str:
    rows = [r for r in all_rows if "other" in r]
    lines = [
        f"{len(rows)} answers; stored judge vs {judge}; "
        f"{len(all_rows) - len(rows)} unusable verdicts from {judge}"
    ]
    for metric in METRICS:
        stored = [r["stored"][metric] for r in rows]
        other = [r["other"][metric] for r in rows]
        apart = sum(abs(a - b) >= CLOSE for a, b in zip(stored, other, strict=True))
        lines.append(
            f"  {metric:22} mean {mean(stored):.3f} vs {mean(other):.3f}; "
            f"{apart} answers {CLOSE}+ apart"
        )
    same_mode = sum(
        r["stored"].get("answer_failure_mode") == r["other"]["answer_failure_mode"]
        for r in rows
    )
    lines.append(f"  failure mode identical: {same_mode}/{len(rows)}")
    negatives = [r for r in rows if r["expect_abstention"]]
    if negatives:
        refused = sum(r["other"]["answer_failure_mode"] == "refusal" for r in negatives)
        stored = sum(
            r["stored"].get("answer_failure_mode") == "refusal" for r in negatives
        )
        lines.append(
            f"  negatives judged as refusals: stored {stored}/{len(negatives)}, "
            f"{judge} {refused}/{len(negatives)}"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--judge", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    rows = stored_answers()
    print(f"{len(rows)} distinct judged answers")
    for i, row in enumerate(rows, 1):
        try:
            row["other"] = regrade(row, args.judge)
        except Exception as error:  # an unusable verdict is a result too
            row["error"] = f"{type(error).__name__}: {str(error)[:300]}"
        print(f"  {i}/{len(rows)}", flush=True)
    args.out.write_text(
        json.dumps({"judge": args.judge, "rows": rows}, indent=2, ensure_ascii=False)
        + "\n"
    )
    print(summarize(rows, args.judge))


if __name__ == "__main__":
    main()
