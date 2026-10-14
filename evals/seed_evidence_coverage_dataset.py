"""Seed the manually reviewed multi-aspect retrieval dataset in Langfuse."""

import argparse
from uuid import NAMESPACE_URL, uuid5

from langfuse import Langfuse

from evals.evidence_coverage import CASES, DATASET_NAME
from src.config import settings


def main() -> None:
    langfuse = Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key.get_secret_value(),
        base_url=settings.langfuse_base_url,
    )
    langfuse.create_dataset(
        name=DATASET_NAME,
        description=(
            "Manually reviewed multi-aspect retrieval cases. Each item requires "
            "coverage of every independent evidence group, not one relevant chunk."
        ),
    )
    for case in CASES:
        langfuse.create_dataset_item(
            dataset_name=DATASET_NAME,
            id=str(uuid5(NAMESPACE_URL, f"{DATASET_NAME}:{case['id']}")),
            input={"question": case["question"]},
            expected_output={"evidence_groups": case["evidence_groups"]},
            metadata={"intent_id": case["id"], "language": "en", "review": "manual-v1"},
        )
    langfuse.flush()
    print(f"Seeded {len(CASES)} cases into '{DATASET_NAME}'")


if __name__ == "__main__":
    # Running writes to Langfuse; --help must not.
    argparse.ArgumentParser(description=__doc__).parse_args()
    main()
