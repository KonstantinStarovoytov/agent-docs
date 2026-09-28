from langchain_qdrant import QdrantVectorStore

from src.config import settings
from src.ingestion.chunker import chunk_documents
from src.ingestion.loader import load_all_sources
from src.rag.embeddings import get_embeddings


def main() -> None:
    print("Loading Claude docs...")

    source_documents = load_all_sources().documents

    print(f"Loaded {len(source_documents)} documents")

    chunks = chunk_documents(source_documents)

    print(f"Created {len(chunks)} chunks")

    QdrantVectorStore.from_documents(
        documents=chunks,
        embedding=get_embeddings(),
        url=settings.qdrant_url,
        collection_name=settings.qdrant_collection,
    )

    print("Indexed successfully")


if __name__ == "__main__":
    main()
