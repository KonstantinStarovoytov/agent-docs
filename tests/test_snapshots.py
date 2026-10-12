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


def _doc(url: str, content: str = "# A\nbody") -> SourceDocument:
    return SourceDocument(title="T", content=content, url=url, vendor="v", product="p")


def test_put_stores_the_gate_summary_and_pages_reads_it_back() -> None:
    store = SnapshotStore(QdrantClient(":memory:"), "c_pages")
    store.put(_doc("https://x/a.md"), "sha", summary="Explains A.")
    store.put(_doc("https://x/b.md", "# B\ntext"), "sha")

    pages = store.pages(["https://x/a.md", "https://x/b.md", "https://x/none.md"])

    assert set(pages) == {"https://x/a.md", "https://x/b.md"}
    a = pages["https://x/a.md"]
    assert (a.url, a.title, a.product, a.markdown, a.summary) == (
        "https://x/a.md",
        "T",
        "p",
        "# A\nbody",
        "Explains A.",
    )
    assert pages["https://x/b.md"].summary == ""


def test_set_summaries_updates_payload_only_for_stored_pages() -> None:
    client = QdrantClient(":memory:")
    store = SnapshotStore(client, "c_pages")
    store.put(_doc("https://x/a.md"), "sha")
    store.put(_doc("https://x/b.md"), "sha", summary="Old.")

    updated = store.set_summaries(
        {"https://x/a.md": "New A.", "https://x/b.md": "", "https://x/gone.md": "G."}
    )

    assert updated == 1
    pages = store.pages(["https://x/a.md", "https://x/b.md"])
    assert pages["https://x/a.md"].summary == "New A."
    assert pages["https://x/a.md"].markdown == "# A\nbody"
    assert pages["https://x/b.md"].summary == "Old."
    assert store.get("https://x/gone.md") is None


def test_reader_does_not_create_the_collection() -> None:
    client = QdrantClient(":memory:")

    SnapshotStore(client, "c_pages", create=False)

    assert not client.collection_exists("c_pages")
