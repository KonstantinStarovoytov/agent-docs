"""Create a clean-English control dataset for vendor-scoped retrieval."""

from uuid import NAMESPACE_URL, uuid5

from langfuse import Langfuse

from src.config import settings

SOURCE_DATASET_NAME = "rag/retrieval-query-transform-v1"
DATASET_NAME = "rag/retrieval-vendor-scope-clean-en-v1"


def main() -> None:
    langfuse = Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key.get_secret_value(),
        base_url=settings.langfuse_base_url,
    )
    source = langfuse.get_dataset(SOURCE_DATASET_NAME)
    clean_items = [
        item
        for item in source.items
        if (item.metadata or {}).get("query_type") == "clean_en"
    ]
    langfuse.create_dataset(
        name=DATASET_NAME,
        description=(
            "Clean-English subset of rag/retrieval-query-transform-v1 used to "
            "compare unscoped and explicit single-vendor hybrid retrieval."
        ),
    )
    for item in clean_items:
        metadata = item.metadata or {}
        langfuse.create_dataset_item(
            dataset_name=DATASET_NAME,
            id=str(uuid5(NAMESPACE_URL, f"{DATASET_NAME}:{metadata['intent_id']}")),
            input=item.input,
            expected_output=item.expected_output,
            metadata={
                "intent_id": metadata["intent_id"],
                "query_type": "clean_en",
                "language": "en",
            },
        )
    langfuse.flush()
    print(f"Seeded {len(clean_items)} cases into '{DATASET_NAME}'")


if __name__ == "__main__":
    main()
