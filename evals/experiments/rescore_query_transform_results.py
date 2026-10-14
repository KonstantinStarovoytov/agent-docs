import json
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from functools import cache

from langfuse import Langfuse

from src.config import settings

DATASET_NAME = "rag/retrieval-query-transform-v1"

EXPERIMENT_IDS = {
    "A_original": "a63da7fc-fdd3-4f9d-8dba-e0e210b8aa6f",
    "B_english": "0cd4edc5-f784-49ed-a090-a840a146d1ca",
    "C_semantic": "b6dd2080-057c-420b-813e-1f5b373fccc7",
    "D_english_semantic": "7b1c55b4-fbd1-478f-b5a1-16052dbf7746",
}

FROM_START_TIME = datetime(
    2026,
    9,
    1,
    tzinfo=UTC,
)

QUERY_TYPES = (
    "clean_en",
    "natural_en",
    "short_en",
    "ru",
    "pl",
    "mixed",
)


# Built on first use, not at import: tests import the constants from this
# module and must not need Langfuse credentials.
@cache
def langfuse_client() -> Langfuse:
    assert settings.langfuse_secret_key is not None, "LANGFUSE_SECRET_KEY is unset"
    return Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key.get_secret_value(),
        base_url=settings.langfuse_base_url,
    )


CORRECTED_MCP_TOOLS_RELEVANT = [
    {
        "vendor": "model-context-protocol",
        "title": "Architecture overview",
        "heading_contains": "Data Layer Protocol",
    },
    {
        "vendor": "model-context-protocol",
        "title": "Architecture overview",
        "heading_contains": "Example > Data Layer",
    },
    {
        "vendor": "model-context-protocol",
        "title": "Build an MCP client",
        "heading_contains": "How it works",
    },
]


def parse_json(value: Any) -> Any:
    if value is None:
        return {}

    if isinstance(
        value,
        (dict, list),
    ):
        return value

    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value

    if hasattr(value, "model_dump"):
        return value.model_dump()

    if hasattr(value, "dict"):
        return value.dict()

    if hasattr(value, "__dict__"):
        return vars(value)

    return value


def fetch_experiment_items(
    experiment_id: str,
) -> list[Any]:
    items = []
    cursor = None

    while True:
        kwargs = {
            "experiment_id": experiment_id,
            "from_start_time": FROM_START_TIME,
            "fields": "io,scores",
            "limit": 100,
        }

        if cursor:
            kwargs["cursor"] = cursor

        response = langfuse_client().api.experiments.list_items(**kwargs)

        items.extend(response.data)

        meta = getattr(
            response,
            "meta",
            None,
        )

        cursor = getattr(
            meta,
            "cursor",
            None,
        )

        if not cursor:
            break

    return items


def build_dataset_index() -> dict[str, dict]:
    dataset = langfuse_client().get_dataset(DATASET_NAME)

    index = {}

    for item in dataset.items:
        metadata = item.metadata or {}

        input_data = parse_json(item.input)

        expected_output = parse_json(item.expected_output)

        question = (
            input_data.get("question")
            if isinstance(
                input_data,
                dict,
            )
            else str(input_data)
        )

        index[item.id] = {
            "question": question,
            "query_type": metadata.get(
                "query_type",
                "unknown",
            ),
            "intent_id": metadata.get(
                "intent_id",
            ),
            "expected_output": expected_output,
        }

    return index


def find_dataset_info(
    data: dict,
    dataset_index: dict[str, dict],
) -> dict | None:
    experiment_item_id = data.get("experiment_item_id")

    if experiment_item_id in dataset_index:
        return dataset_index[experiment_item_id]

    input_data = parse_json(data.get("input"))

    question = (
        input_data.get("question")
        if isinstance(
            input_data,
            dict,
        )
        else None
    )

    if question:
        for value in dataset_index.values():
            if value.get("question") == question:
                return value

    return None


def get_expected_output(
    dataset_info: dict,
) -> dict:
    intent_id = dataset_info.get("intent_id")

    if intent_id == "mcp-server-tools":
        return {"relevant": CORRECTED_MCP_TOOLS_RELEVANT}

    return dataset_info.get("expected_output") or {}


def is_relevant(
    result: dict,
    expected_output: dict,
) -> bool:
    relevant_targets = expected_output.get(
        "relevant",
        [],
    )

    for target in relevant_targets:
        vendor = target.get("vendor")

        if vendor and result.get("vendor") != vendor:
            continue

        product = target.get("product")

        if product and result.get("product") != product:
            continue

        title = target.get("title")

        if title and result.get("title") != title:
            continue

        heading_contains = target.get("heading_contains")

        if heading_contains:
            heading = (
                result.get(
                    "heading",
                    "",
                )
                or ""
            )

            if heading_contains.lower() not in heading.lower():
                continue

        source_contains = target.get("source_contains")

        if source_contains:
            source = (
                result.get(
                    "source",
                    "",
                )
                or ""
            )

            if source_contains.lower() not in source.lower():
                continue

        return True

    return False


def calculate_scores(
    results: list[dict],
    expected_output: dict,
) -> dict[str, float]:
    ordered_results = sorted(
        results,
        key=lambda result: result.get(
            "rank",
            999999,
        ),
    )

    relevant_rank = None

    for position, result in enumerate(
        ordered_results,
        start=1,
    ):
        if is_relevant(
            result,
            expected_output,
        ):
            relevant_rank = position
            break

    if relevant_rank is None:
        return {
            "hit_at_1": 0.0,
            "hit_at_5": 0.0,
            "hit_at_10": 0.0,
            "reciprocal_rank": 0.0,
        }

    return {
        "hit_at_1": float(relevant_rank <= 1),
        "hit_at_5": float(relevant_rank <= 5),
        "hit_at_10": float(relevant_rank <= 10),
        "reciprocal_rank": (1.0 / relevant_rank),
    }


def load_and_rescore(
    experiment_id: str,
    dataset_index: dict[str, dict],
) -> dict[str, dict]:
    experiment_items = fetch_experiment_items(experiment_id)

    rescored = {}

    for item in experiment_items:
        data = parse_json(item)

        dataset_info = find_dataset_info(
            data,
            dataset_index,
        )

        if dataset_info is None:
            print("WARNING: could not match experiment item")
            continue

        output = parse_json(data.get("output"))

        if not isinstance(
            output,
            dict,
        ):
            print(f"WARNING: invalid output for {dataset_info['question']}")
            continue

        results = output.get("results") or []

        expected_output = get_expected_output(dataset_info)

        scores = calculate_scores(
            results,
            expected_output,
        )

        key = f"{dataset_info['intent_id']}:{dataset_info['query_type']}"

        rescored[key] = {
            **dataset_info,
            **scores,
        }

    return rescored


def average(
    rows: list[dict],
    metric: str,
) -> float:
    values = [row[metric] for row in rows if metric in row]

    if not values:
        return 0.0

    return sum(values) / len(values)


def summarize_runs(runs: dict[str, dict[str, dict]]) -> dict:
    if not runs:
        return {"shared_cases": 0, "overall": {}, "by_query_type": {}}
    shared_keys = set.intersection(*(set(rows) for rows in runs.values()))
    metrics = ("hit_at_1", "hit_at_5", "hit_at_10", "reciprocal_rank")

    overall = {
        strategy: {
            metric: average([rows[key] for key in shared_keys], metric)
            for metric in metrics
        }
        for strategy, rows in runs.items()
    }
    query_types = sorted(
        {
            runs[strategy][key].get("query_type", "unknown")
            for strategy in runs
            for key in shared_keys
        }
    )
    by_query_type = {}
    for query_type in query_types:
        by_query_type[query_type] = {}
        for strategy, rows in runs.items():
            selected = [
                rows[key]
                for key in shared_keys
                if rows[key].get("query_type", "unknown") == query_type
            ]
            by_query_type[query_type][strategy] = {
                metric: average(selected, metric) for metric in metrics
            }
    return {
        "shared_cases": len(shared_keys),
        "overall": overall,
        "by_query_type": by_query_type,
    }


def print_strategy_summary(summary: dict) -> None:
    print()
    print("OFFLINE A/B/C/D RESCORE")
    print("=" * 88)
    print(f"Shared cases: {summary['shared_cases']}")
    print(f"{'strategy':<24}{'H@1':>10}{'H@5':>10}{'H@10':>10}{'MRR':>10}")
    print("-" * 64)
    for strategy, metrics in summary["overall"].items():
        print(
            f"{strategy:<24}"
            f"{metrics['hit_at_1']:>10.3f}"
            f"{metrics['hit_at_5']:>10.3f}"
            f"{metrics['hit_at_10']:>10.3f}"
            f"{metrics['reciprocal_rank']:>10.3f}"
        )

    for query_type, strategies in summary["by_query_type"].items():
        print()
        print(query_type)
        for strategy, metrics in strategies.items():
            print(
                f"  {strategy:<22}"
                f"H@5={metrics['hit_at_5']:.3f} "
                f"MRR={metrics['reciprocal_rank']:.3f}"
            )


def print_query_type_comparison(
    baseline: dict[str, dict],
    rewrite: dict[str, dict],
) -> None:
    shared_keys = set(baseline) & set(rewrite)

    grouped = defaultdict(list)

    for key in shared_keys:
        b = baseline[key]
        r = rewrite[key]

        query_type = b.get(
            "query_type",
            "unknown",
        )

        grouped[query_type].append(
            {
                "baseline": b,
                "rewrite": r,
            }
        )

    print()
    print("RESCORED QUERY TYPE COMPARISON")
    print("=" * 112)

    print(
        f"{'type':<14}"
        f"{'n':>4}"
        f"{'B H@1':>9}"
        f"{'R H@1':>9}"
        f"{'Δ':>8}"
        f"{'B H@5':>9}"
        f"{'R H@5':>9}"
        f"{'Δ':>8}"
        f"{'B MRR':>10}"
        f"{'R MRR':>10}"
        f"{'Δ':>9}"
    )

    print("-" * 112)

    for query_type in QUERY_TYPES:
        pairs = grouped.get(
            query_type,
            [],
        )

        if not pairs:
            continue

        b_rows = [pair["baseline"] for pair in pairs]

        r_rows = [pair["rewrite"] for pair in pairs]

        b_h1 = average(
            b_rows,
            "hit_at_1",
        )

        r_h1 = average(
            r_rows,
            "hit_at_1",
        )

        b_h5 = average(
            b_rows,
            "hit_at_5",
        )

        r_h5 = average(
            r_rows,
            "hit_at_5",
        )

        b_mrr = average(
            b_rows,
            "reciprocal_rank",
        )

        r_mrr = average(
            r_rows,
            "reciprocal_rank",
        )

        print(
            f"{query_type:<14}"
            f"{len(pairs):>4}"
            f"{b_h1:>9.3f}"
            f"{r_h1:>9.3f}"
            f"{r_h1 - b_h1:>+8.3f}"
            f"{b_h5:>9.3f}"
            f"{r_h5:>9.3f}"
            f"{r_h5 - b_h5:>+8.3f}"
            f"{b_mrr:>10.3f}"
            f"{r_mrr:>10.3f}"
            f"{r_mrr - b_mrr:>+9.3f}"
        )

    print("-" * 112)

    b_rows = [baseline[key] for key in shared_keys]

    r_rows = [rewrite[key] for key in shared_keys]

    b_h1 = average(
        b_rows,
        "hit_at_1",
    )

    r_h1 = average(
        r_rows,
        "hit_at_1",
    )

    b_h5 = average(
        b_rows,
        "hit_at_5",
    )

    r_h5 = average(
        r_rows,
        "hit_at_5",
    )

    b_mrr = average(
        b_rows,
        "reciprocal_rank",
    )

    r_mrr = average(
        r_rows,
        "reciprocal_rank",
    )

    print(
        f"{'OVERALL':<14}"
        f"{len(shared_keys):>4}"
        f"{b_h1:>9.3f}"
        f"{r_h1:>9.3f}"
        f"{r_h1 - b_h1:>+8.3f}"
        f"{b_h5:>9.3f}"
        f"{r_h5:>9.3f}"
        f"{r_h5 - b_h5:>+8.3f}"
        f"{b_mrr:>10.3f}"
        f"{r_mrr:>10.3f}"
        f"{r_mrr - b_mrr:>+9.3f}"
    )


def print_mcp_tools_cases(
    baseline: dict[str, dict],
    rewrite: dict[str, dict],
) -> None:
    print()
    print("MCP SERVER TOOLS CASES")
    print("=" * 80)

    for query_type in QUERY_TYPES:
        key = f"mcp-server-tools:{query_type}"

        b = baseline.get(key)
        r = rewrite.get(key)

        if not b or not r:
            continue

        print()
        print(f"[{query_type}] {b['question']}")

        print(
            "Baseline: "
            f"H@1={b['hit_at_1']:.0f} "
            f"H@5={b['hit_at_5']:.0f} "
            f"MRR="
            f"{b['reciprocal_rank']:.3f}"
        )

        print(
            "Rewrite:  "
            f"H@1={r['hit_at_1']:.0f} "
            f"H@5={r['hit_at_5']:.0f} "
            f"MRR="
            f"{r['reciprocal_rank']:.3f}"
        )


def print_changed_cases(
    baseline: dict[str, dict],
    rewrite: dict[str, dict],
) -> None:
    shared_keys = set(baseline) & set(rewrite)

    improved = []
    degraded = []

    for key in shared_keys:
        b = baseline[key]
        r = rewrite[key]

        delta = r["reciprocal_rank"] - b["reciprocal_rank"]

        if abs(delta) < 1e-9:
            continue

        row = {
            "question": b["question"],
            "query_type": b["query_type"],
            "intent_id": b["intent_id"],
            "baseline": b["reciprocal_rank"],
            "rewrite": r["reciprocal_rank"],
            "delta": delta,
        }

        if delta > 0:
            improved.append(row)
        else:
            degraded.append(row)

    improved.sort(
        key=lambda row: row["delta"],
        reverse=True,
    )

    degraded.sort(
        key=lambda row: row["delta"],
    )

    print()
    print("IMPROVED AFTER RESCORE")
    print("=" * 80)

    if not improved:
        print("None")

    for row in improved:
        print()
        print(f"[{row['query_type']}] {row['intent_id']}")
        print(row["question"])
        print(
            f"MRR: {row['baseline']:.3f} -> {row['rewrite']:.3f}  ({row['delta']:+.3f})"
        )

    print()
    print("DEGRADED AFTER RESCORE")
    print("=" * 80)

    if not degraded:
        print("None")

    for row in degraded:
        print()
        print(f"[{row['query_type']}] {row['intent_id']}")
        print(row["question"])
        print(
            f"MRR: {row['baseline']:.3f} -> {row['rewrite']:.3f}  ({row['delta']:+.3f})"
        )


def main() -> None:
    print("Loading dataset...")

    dataset_index = build_dataset_index()

    print(f"Dataset items: {len(dataset_index)}")
    runs = {}
    for strategy, experiment_id in EXPERIMENT_IDS.items():
        print(f"Rescoring {strategy}...")
        runs[strategy] = load_and_rescore(experiment_id, dataset_index)
        print(f"{strategy} items: {len(runs[strategy])}")

    print_strategy_summary(summarize_runs(runs))
    baseline = runs["A_original"]
    for strategy in ("B_english", "C_semantic", "D_english_semantic"):
        print()
        print(f"A_original vs {strategy}")
        print_query_type_comparison(baseline, runs[strategy])
        print_changed_cases(baseline, runs[strategy])

    print_mcp_tools_cases(baseline, runs["D_english_semantic"])


if __name__ == "__main__":
    main()
