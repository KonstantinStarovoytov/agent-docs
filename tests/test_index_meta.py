"""Index metadata is kept per collection, so a side build cannot relabel production."""

from typing import Any

from qdrant_client import QdrantClient, models

from src import reindex
from src.reindex import Manifest
from src.service import core


def _client(monkeypatch: Any) -> QdrantClient:
    client = QdrantClient(":memory:")
    client.close = lambda **_: None  # type: ignore[method-assign]
    monkeypatch.setattr(reindex, "get_qdrant_client", lambda: client)
    monkeypatch.setattr(core, "get_qdrant_client", lambda: client)
    return client


def test_meta_written_for_one_collection_is_not_read_for_another(monkeypatch) -> None:
    _client(monkeypatch)
    reindex.write_meta(Manifest(indexed_at="2026-10-12", documents={}), "side")

    monkeypatch.setattr(core.settings, "qdrant_hybrid_collection", "prod")
    assert core._read_index_meta() == {}
    monkeypatch.setattr(core.settings, "qdrant_hybrid_collection", "side")
    assert core._read_index_meta()["indexed_at"] == "2026-10-12"


def test_legacy_meta_point_is_still_read(monkeypatch) -> None:
    client = _client(monkeypatch)
    client.create_collection(
        core.META_COLLECTION,
        vectors_config=models.VectorParams(size=1, distance=models.Distance.DOT),
    )
    client.upsert(
        core.META_COLLECTION,
        points=[
            models.PointStruct(
                id=core.META_POINT_ID,
                vector=[0.0],
                payload={"indexed_at": "2026-10-11"},
            )
        ],
    )
    monkeypatch.setattr(core.settings, "qdrant_hybrid_collection", "prod")

    assert core._read_index_meta()["indexed_at"] == "2026-10-11"
