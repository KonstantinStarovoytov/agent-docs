"""List the last day's experiment runs on a dataset and print their failed cases."""

import argparse
import json
from datetime import UTC, datetime, timedelta

from langfuse import Langfuse

from src.config import settings

DATASET_NAME = "rag/retrieval-v3"
EXPERIMENT_PREFIX = "dense-multisource-v1"

langfuse = Langfuse(
    public_key=settings.langfuse_public_key,
    secret_key=settings.langfuse_secret_key.get_secret_value(),
    base_url=settings.langfuse_base_url,
)


def parse_json(value):
    if value is None:
        return {}

    if isinstance(value, dict):
        return value

    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {"raw": value}

    return value


def main() -> None:
    from_start_time = datetime.now(UTC) - timedelta(days=1)

    # Resolve dataset first.
    dataset = langfuse.get_dataset(DATASET_NAME)

    print("Dataset:", dataset.name)
    print("Dataset ID:", dataset.id)
    print()

    # Get experiments belonging to this dataset.
    experiments = langfuse.api.experiments.list(
        from_start_time=from_start_time,
        dataset_id=dataset.id,
        fields=["core"],
        limit=100,
    )

    print("Available experiments:")

    for experiment in experiments.data:
        print(f"  {experiment.name}")

    print()

    # Actual run name contains timestamp:
    #
    # dense-cohere-v2 - 2026-09-11T14:21:42...
    candidates = [
        experiment
        for experiment in experiments.data
        if experiment.name.startswith(EXPERIMENT_PREFIX)
    ]

    if not candidates:
        raise RuntimeError(f"No experiment starting with '{EXPERIMENT_PREFIX}' found")

    # Latest matching run.
    experiment = max(
        candidates,
        key=lambda x: x.start_time,
    )

    print("Selected:")
    print(experiment.name)
    print("ID:", experiment.id)
    print()

    failures = []
    cursor = None

    while True:
        page = langfuse.api.experiments.list_items(
            from_start_time=from_start_time,
            # Current API works around dataset +
            # exact experiment/run name.
            dataset_id=dataset.id,
            experiment_name=experiment.name,
            fields=[
                "core",
                "io",
                "scores",
            ],
            limit=100,
            cursor=cursor,
        )

        for item in page.data:
            scores = {score.name: score.value for score in (item.scores or [])}

            if scores.get("hit_at_10") == 0:
                failures.append(item)

        cursor = page.meta.cursor

        if not cursor:
            break

    print(f"hit_at_10 failures: {len(failures)}")
    print()

    for index, item in enumerate(
        failures,
        start=1,
    ):
        print("=" * 100)
        print(f"FAIL #{index}")
        print()

        print("QUESTION")
        print(
            json.dumps(
                parse_json(item.input),
                indent=2,
                ensure_ascii=False,
            )
        )
        print()

        print("EXPECTED")
        print(
            json.dumps(
                parse_json(item.expected_output),
                indent=2,
                ensure_ascii=False,
            )
        )
        print()

        print("ACTUAL TOP 10")

        output = parse_json(item.output)
        results = output.get("results", [])

        for result in results[:10]:
            print(f"#{result.get('rank')} {result.get('title')}")

            print(f"  heading: {result.get('heading')}")

            print(f"  dense_rank: {result.get('dense_rank')}")

            print(f"  rerank_score: {result.get('rerank_score')}")

            print()

        print("SCORES")

        for score in item.scores or []:
            print(f"{score.name}: {score.value}")

        print()


if __name__ == "__main__":
    # Running writes to Langfuse; --help must not.
    argparse.ArgumentParser(description=__doc__).parse_args()
    main()
