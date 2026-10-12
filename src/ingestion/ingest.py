from langchain_core.documents import Document
from langchain_qdrant import (
    QdrantVectorStore,
    RetrievalMode,
)
from qdrant_client import QdrantClient, models

from src.config import settings
from src.rag.embeddings import (
    get_embeddings,
    get_sparse_embeddings,
)


def get_qdrant_client() -> QdrantClient:
    """One place that knows how to reach Qdrant, local container or Cloud."""
    api_key = settings.qdrant_api_key

    return QdrantClient(
        url=settings.qdrant_url,
        api_key=api_key.get_secret_value() if api_key else None,
    )


# Names langchain-qdrant uses by default; the collection must match them.
DENSE_VECTOR_NAME = ""
SPARSE_VECTOR_NAME = "langchain-sparse"
# text-embedding-3-small
DENSE_SIZE = 1536


def ensure_hybrid_collection(
    client: QdrantClient, collection: str, *, dense_size: int = DENSE_SIZE
) -> bool:
    """Create the hybrid collection if missing; True when it was created.

    langchain-qdrant would otherwise create it without a sparse modifier, and
    fastembed's Qdrant/bm25 emits term frequencies only: the IDF half of BM25
    is computed by Qdrant and only when the sparse vector has modifier=IDF.
    """
    if client.collection_exists(collection):
        return False
    client.create_collection(
        collection_name=collection,
        vectors_config={
            DENSE_VECTOR_NAME: models.VectorParams(
                size=dense_size, distance=models.Distance.COSINE
            )
        },
        sparse_vectors_config={
            SPARSE_VECTOR_NAME: models.SparseVectorParams(modifier=models.Modifier.IDF)
        },
    )
    return True


def create_vector_store() -> QdrantVectorStore:
    return QdrantVectorStore(
        client=get_qdrant_client(),
        collection_name=settings.qdrant_collection,
        embedding=get_embeddings(),
    )


def get_hybrid_vector_store() -> QdrantVectorStore:
    return QdrantVectorStore(
        client=get_qdrant_client(),
        collection_name=(settings.qdrant_hybrid_collection),
        embedding=get_embeddings(),
        sparse_embedding=get_sparse_embeddings(),
        retrieval_mode=RetrievalMode.HYBRID,
    )


def add_documents(
    documents: list[Document],
) -> list[str]:
    store = create_vector_store()

    return store.add_documents(documents)


def get_vector_store() -> QdrantVectorStore:
    return QdrantVectorStore(
        client=get_qdrant_client(),
        collection_name=settings.qdrant_collection,
        embedding=get_embeddings(),
    )
