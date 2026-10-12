"""Seed `rag/full-corpus-v1`: retrieval cases over pages new in the full corpus."""

from uuid import NAMESPACE_URL, uuid5

from langfuse import Langfuse

from evals.full_corpus_cases import CASES, DATASET_NAME
from src.config import settings

langfuse = Langfuse(
    public_key=settings.langfuse_public_key,
    secret_key=settings.langfuse_secret_key.get_secret_value(),
    base_url=settings.langfuse_base_url,
)


def main() -> None:
    langfuse.create_dataset(
        name=DATASET_NAME,
        description=(
            "Retrieval benchmark over pages added by the full-corpus index: "
            "CLI reference, settings and env vars, SDKs, administration, "
            "cloud agents, MCP registry and extensions. 5 cases per product."
        ),
        metadata={
            "version": "1",
            "type": "retrieval",
            "items": len(CASES),
        },
    )

    for case in CASES:
        # Deterministic ID:
        # rerunning this script updates the same item instead of duplicating it.
        item_id = str(
            uuid5(
                NAMESPACE_URL,
                f"{DATASET_NAME}:{case['question']}",
            )
        )

        langfuse.create_dataset_item(
            id=item_id,
            dataset_name=DATASET_NAME,
            input={
                "question": case["question"],
            },
            expected_output={
                "relevant": case["relevant"],
            },
            metadata={
                "category": case["category"],
                "difficulty": case["difficulty"],
                "evidence": case["evidence"],
            },
        )

    langfuse.flush()
    print(f"Seeded {len(CASES)} cases into '{DATASET_NAME}'")


if __name__ == "__main__":
    main()
