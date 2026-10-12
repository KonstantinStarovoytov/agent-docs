"""Hybrid collection creation: BM25 needs the IDF modifier on the sparse vector."""

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_qdrant import QdrantVectorStore, RetrievalMode
from langchain_qdrant.sparse_embeddings import SparseEmbeddings, SparseVector
from qdrant_client import QdrantClient, models

from src.ingestion.ingest import (
    DENSE_VECTOR_NAME,
    SPARSE_VECTOR_NAME,
    ensure_hybrid_collection,
)


class _Dense(Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0] for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0, 0.0]


class _Sparse(SparseEmbeddings):
    def embed_documents(self, texts: list[str]) -> list[SparseVector]:
        return [SparseVector(indices=[1], values=[1.0]) for _ in texts]

    def embed_query(self, text: str) -> SparseVector:
        return SparseVector(indices=[1], values=[1.0])


def test_new_collection_has_idf_modifier_and_dense_params() -> None:
    client = QdrantClient(":memory:")

    created = ensure_hybrid_collection(client, "c", dense_size=3)

    assert created is True
    params = client.get_collection("c").config.params
    assert params.sparse_vectors is not None
    assert params.sparse_vectors[SPARSE_VECTOR_NAME].modifier == models.Modifier.IDF
    assert isinstance(params.vectors, dict)
    assert params.vectors[DENSE_VECTOR_NAME].size == 3
    assert params.vectors[DENSE_VECTOR_NAME].distance == models.Distance.COSINE


def test_existing_collection_is_left_alone() -> None:
    client = QdrantClient(":memory:")
    ensure_hybrid_collection(client, "c", dense_size=3)

    assert ensure_hybrid_collection(client, "c", dense_size=3) is False


def test_langchain_reuses_the_collection() -> None:
    client = QdrantClient(":memory:")
    ensure_hybrid_collection(client, "c", dense_size=3)
    store = QdrantVectorStore(
        client=client,
        collection_name="c",
        embedding=_Dense(),
        sparse_embedding=_Sparse(),
        retrieval_mode=RetrievalMode.HYBRID,
    )

    store.add_documents([Document(page_content="hello", metadata={"vendor": "x"})])

    assert client.count("c").count == 1
    params = client.get_collection("c").config.params
    assert params.sparse_vectors is not None
    assert params.sparse_vectors[SPARSE_VECTOR_NAME].modifier == models.Modifier.IDF
