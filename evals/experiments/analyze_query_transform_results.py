import json
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from langfuse import Langfuse

from src.config import settings

DATASET_NAME = "rag/retrieval-query-transform-v1"

BASELINE_EXPERIMENT_ID = "a63da7fc-fdd3-4f9d-8dba-e0e210b8aa6f"

REWRITE_EXPERIMENT_ID = "7b1c55b4-fbd1-478f-b5a1-16052dbf7746"

FROM_START_TIME = datetime(
    2026,
    9,
    1,
    tzinfo=UTC,
)

METRICS = (
    "hit_at_1",
    "hit_at_5",
    "hit_at_10",
    "reciprocal_rank",
)

QUERY_TYPES = (
    "clean_en",
    "natural_en",
    "short_en",
    "ru",
    "pl",
    "mixed",
)


langfuse = Langfuse(
    public_key=settings.langfuse_public_key,
    secret_key=(settings.langfuse_secret_key.get_secret_value()),
    base_url=settings.langfuse_base_url,
)


def build_dataset_index() -> dict[str, dict]:
    dataset = langfuse.get_dataset(DATASET_NAME)

    index = {}

    for item in dataset.items:
        metadata = item.metadata or {}
        input_data = item.input or {}

        index[item.id] = {
            "query_type": metadata.get(
                "query_type",
                "unknown",
            ),
            "intent_id": metadata.get(
                "intent_id",
            ),
            "question": (
                input_data.get("question")
                if isinstance(input_data, dict)
                else str(input_data)
            ),
        }

    return index


def to_dict(value: Any) -> dict:
    if value is None:
        return {}

    if isinstance(value, dict):
        return value

    if isinstance(value, str):
        try:
            parsed = json.loads(value)

            if isinstance(parsed, dict):
                return parsed

            return {
                "value": parsed,
            }

        except json.JSONDecodeError:
            return {
                "value": value,
            }

    if hasattr(value, "model_dump"):
        return value.model_dump()

    if hasattr(value, "dict"):
        return value.dict()

    if hasattr(value, "__dict__"):
        return vars(value)

    return {}


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

        response = langfuse.api.experiments.list_items(**kwargs)

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


def extract_scores(
    experiment_item: Any,
) -> dict[str, float]:
    data = to_dict(experiment_item)

    scores = data.get("scores") or []

    result = {}

    for score in scores:
        score_data = to_dict(score)

        name = score_data.get("name")

        value = score_data.get("value")

        if name in METRICS and value is not None:
            result[name] = float(value)

    return result


def load_results(
    experiment_id: str,
    dataset_index: dict[str, dict],
) -> dict[str, dict]:
    experiment_items = fetch_experiment_items(experiment_id)

    results = {}

    for item in experiment_items:
        data = to_dict(item)

        experiment_item_id = data.get("experiment_item_id")

        input_data = to_dict(data.get("input"))

        question = input_data.get("question")

        dataset_info = dataset_index.get(experiment_item_id)

        #
        # Fallback:
        # match by question if IDs differ
        #
        if dataset_info is None:
            dataset_info = next(
                (
                    value
                    for value in dataset_index.values()
                    if value.get("question") == question
                ),
                None,
            )

        if dataset_info is None:
            print(f"WARNING: could not match dataset item: {question}")

            dataset_info = {
                "query_type": "unknown",
                "intent_id": None,
                "question": question,
            }

        scores = extract_scores(item)

        query_type = dataset_info.get(
            "query_type",
            "unknown",
        )

        intent_id = dataset_info.get("intent_id")

        #
        # Logical key shared between
        # baseline and rewrite runs.
        #
        key = f"{intent_id}:{query_type}" if intent_id else question

        results[key] = {
            **dataset_info,
            **scores,
        }

    return results


def average(
    rows: list[dict],
    metric: str,
) -> float:
    values = [row[metric] for row in rows if metric in row]

    if not values:
        return 0.0

    return sum(values) / len(values)


def print_group_table(
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
    print("QUERY TYPE COMPARISON")
    print("=" * 111)

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

    print("-" * 111)

    ordered_types = list(QUERY_TYPES)

    for query_type in grouped:
        if query_type not in ordered_types:
            ordered_types.append(query_type)

    for query_type in ordered_types:
        pairs = grouped.get(
            query_type,
            [],
        )

        if not pairs:
            continue

        baseline_rows = [pair["baseline"] for pair in pairs]

        rewrite_rows = [pair["rewrite"] for pair in pairs]

        b_h1 = average(
            baseline_rows,
            "hit_at_1",
        )

        r_h1 = average(
            rewrite_rows,
            "hit_at_1",
        )

        b_h5 = average(
            baseline_rows,
            "hit_at_5",
        )

        r_h5 = average(
            rewrite_rows,
            "hit_at_5",
        )

        b_mrr = average(
            baseline_rows,
            "reciprocal_rank",
        )

        r_mrr = average(
            rewrite_rows,
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

    print("-" * 111)

    all_baseline = [baseline[key] for key in shared_keys]

    all_rewrite = [rewrite[key] for key in shared_keys]

    b_h1 = average(
        all_baseline,
        "hit_at_1",
    )

    r_h1 = average(
        all_rewrite,
        "hit_at_1",
    )

    b_h5 = average(
        all_baseline,
        "hit_at_5",
    )

    r_h5 = average(
        all_rewrite,
        "hit_at_5",
    )

    b_mrr = average(
        all_baseline,
        "reciprocal_rank",
    )

    r_mrr = average(
        all_rewrite,
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


def print_changed_cases(
    baseline: dict[str, dict],
    rewrite: dict[str, dict],
) -> None:
    shared_keys = set(baseline) & set(rewrite)

    changed = []

    for key in shared_keys:
        b = baseline[key]
        r = rewrite[key]

        b_rr = b.get(
            "reciprocal_rank",
            0.0,
        )

        r_rr = r.get(
            "reciprocal_rank",
            0.0,
        )

        if abs(b_rr - r_rr) < 1e-9:
            continue

        changed.append(
            {
                "question": b.get("question"),
                "query_type": b.get("query_type"),
                "intent_id": b.get("intent_id"),
                "baseline_rr": b_rr,
                "rewrite_rr": r_rr,
                "baseline_h1": b.get(
                    "hit_at_1",
                    0,
                ),
                "rewrite_h1": r.get(
                    "hit_at_1",
                    0,
                ),
                "baseline_h5": b.get(
                    "hit_at_5",
                    0,
                ),
                "rewrite_h5": r.get(
                    "hit_at_5",
                    0,
                ),
            }
        )

    degraded = sorted(
        (row for row in changed if (row["rewrite_rr"] < row["baseline_rr"])),
        key=lambda row: row["rewrite_rr"] - row["baseline_rr"],
    )

    improved = sorted(
        (row for row in changed if (row["rewrite_rr"] > row["baseline_rr"])),
        key=lambda row: row["rewrite_rr"] - row["baseline_rr"],
        reverse=True,
    )

    print()
    print("DEGRADED CASES")
    print("=" * 80)

    if not degraded:
        print("None")

    for row in degraded:
        print()
        print(f"[{row['query_type']}] {row['question']}")

        print(f"MRR: {row['baseline_rr']:.3f} -> {row['rewrite_rr']:.3f}")

        print(f"Hit@1: {row['baseline_h1']:.0f} -> {row['rewrite_h1']:.0f}")

        print(f"Hit@5: {row['baseline_h5']:.0f} -> {row['rewrite_h5']:.0f}")

    print()
    print("IMPROVED CASES")
    print("=" * 80)

    if not improved:
        print("None")

    for row in improved:
        print()
        print(f"[{row['query_type']}] {row['question']}")

        print(f"MRR: {row['baseline_rr']:.3f} -> {row['rewrite_rr']:.3f}")

        print(f"Hit@1: {row['baseline_h1']:.0f} -> {row['rewrite_h1']:.0f}")

        print(f"Hit@5: {row['baseline_h5']:.0f} -> {row['rewrite_h5']:.0f}")


def main() -> None:
    print("Loading dataset...")

    dataset_index = build_dataset_index()

    print(f"Dataset items: {len(dataset_index)}")

    print("Loading baseline experiment...")

    baseline = load_results(
        BASELINE_EXPERIMENT_ID,
        dataset_index,
    )

    print(f"Baseline items: {len(baseline)}")

    print("Loading rewrite experiment...")

    rewrite = load_results(
        REWRITE_EXPERIMENT_ID,
        dataset_index,
    )

    print(f"Rewrite items: {len(rewrite)}")

    print_group_table(
        baseline,
        rewrite,
    )

    print_changed_cases(
        baseline,
        rewrite,
    )


if __name__ == "__main__":
    main()
