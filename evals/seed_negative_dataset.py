"""Seed the negative (unanswerable) question dataset in Langfuse."""

import argparse
from uuid import NAMESPACE_URL, uuid5

from langfuse import Langfuse

from evals.negative_cases import CASES, DATASET_NAME, expected_output
from src.config import settings


def main() -> None:
    assert settings.langfuse_secret_key is not None, "LANGFUSE_SECRET_KEY is unset"
    langfuse = Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key.get_secret_value(),
        base_url=settings.langfuse_base_url,
    )
    langfuse.create_dataset(
        name=DATASET_NAME,
        description=(
            "Questions the indexed documentation does not answer. The expected "
            "behaviour is an explicit abstention, scored by abstention_correct."
        ),
    )
    for case in CASES:
        langfuse.create_dataset_item(
            dataset_name=DATASET_NAME,
            id=str(uuid5(NAMESPACE_URL, f"{DATASET_NAME}:{case['id']}")),
            input={"question": case["question"]},
            expected_output=expected_output(case),
            metadata={
                "intent_id": case["id"],
                "why_outside": case["why_outside"],
                "review": "manual-v1",
            },
        )
    langfuse.flush()
    print(f"Seeded {len(CASES)} cases into '{DATASET_NAME}'")


if __name__ == "__main__":
    # Running writes to Langfuse; --help must not.
    argparse.ArgumentParser(description=__doc__).parse_args()
    main()
