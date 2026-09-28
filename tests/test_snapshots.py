"""The snapshot store keeps the last fetched markdown per page."""

from qdrant_client import QdrantClient

from src.ingestion.snapshots import SnapshotStore, snapshot_collection
from src.models import SourceDocument


def test_put_get_delete_round_trip() -> None:
    store = SnapshotStore(QdrantClient(":memory:"), "c_pages")
    doc = SourceDocument(
        title="T", content="# A\nbody", url="https://x/a.md", vendor="v", product="p"
    )

    store.put(doc, "sha")

    assert store.get("https://x/a.md") == "# A\nbody"
    assert store.all_texts() == {"https://x/a.md": "# A\nbody"}
    store.delete("https://x/a.md")
    assert store.get("https://x/a.md") is None


def test_collection_name_follows_the_index() -> None:
    assert snapshot_collection("agent_docs_hybrid_v2") == "agent_docs_hybrid_v2_pages"
