import argparse

from src.config import settings
from src.ingestion.chunker import chunk_documents
from src.ingestion.ingest import (
    ensure_hybrid_collection,
    get_hybrid_vector_store,
    get_qdrant_client,
)
from src.ingestion.loader import load_all_sources


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the hybrid index; existing collections require explicit replacement."
    )
    parser.add_argument(
        "--recreate", action="store_true", help="Replace the existing hybrid collection"
    )
    args = parser.parse_args()
    client = get_qdrant_client()
    collection = settings.qdrant_hybrid_collection
    try:
        exists = client.collection_exists(collection)
        if exists and not args.recreate:
            parser.error(
                "Collection already exists. Use --recreate only for an intentional full rebuild."
            )
        if exists:
            client.delete_collection(collection)
        ensure_hybrid_collection(client, collection)
    finally:
        client.close()
    print("Loading sources...")

    documents = load_all_sources().documents

    print(f"Loaded {len(documents)} documents")

    print("Chunking...")

    chunks = chunk_documents(documents)

    print(f"Created {len(chunks)} chunks")

    print("Building hybrid Qdrant index...")

    get_hybrid_vector_store().add_documents(chunks)

    print(f"Hybrid index created: {settings.qdrant_hybrid_collection}")


if __name__ == "__main__":
    main()
