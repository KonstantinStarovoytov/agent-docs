import argparse

from langchain_qdrant import (
    QdrantVectorStore,
    RetrievalMode,
)

from src.config import settings
from src.ingestion.chunker import chunk_documents
from src.ingestion.ingest import get_qdrant_client
from src.ingestion.loader import load_all_sources
from src.rag.embeddings import (
    get_embeddings,
    get_sparse_embeddings,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the hybrid index; existing collections require explicit replacement."
    )
    parser.add_argument(
        "--recreate", action="store_true", help="Replace the existing hybrid collection"
    )
    args = parser.parse_args()
    client = get_qdrant_client()
    try:
        exists = client.collection_exists(settings.qdrant_hybrid_collection)
    finally:
        client.close()
    if exists and not args.recreate:
        parser.error(
            "Collection already exists. Use --recreate only for an intentional full rebuild."
        )
    print("Loading sources...")

    documents = load_all_sources().documents

    print(f"Loaded {len(documents)} documents")

    print("Chunking...")

    chunks = chunk_documents(documents)

    print(f"Created {len(chunks)} chunks")

    print("Building hybrid Qdrant index...")

    api_key = settings.qdrant_api_key

    QdrantVectorStore.from_documents(
        documents=chunks,
        embedding=get_embeddings(),
        sparse_embedding=get_sparse_embeddings(),
        retrieval_mode=RetrievalMode.HYBRID,
        url=settings.qdrant_url,
        api_key=api_key.get_secret_value() if api_key else None,
        collection_name=(settings.qdrant_hybrid_collection),
        force_recreate=args.recreate,
    )

    print(f"Hybrid index created: {settings.qdrant_hybrid_collection}")


if __name__ == "__main__":
    main()
