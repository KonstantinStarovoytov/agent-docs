"""Incremental re-index: fetch every source page, re-embed only what changed.

Runs from a daily GitHub Actions cron. The manifest under `data/` remembers a
fingerprint per page, so a run where nothing changed costs a few HTTP requests
and no embeddings. Pages that vanish from a vendor's index are reported, not
deleted: a rename looks the same as a removal, and that is a human decision.
"""

import argparse
import hashlib
import json
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

from langchain_core.documents import Document
from qdrant_client import QdrantClient, models

from src.config import settings
from src.ingestion.chunker import chunk_document
from src.ingestion.ingest import get_hybrid_vector_store, get_qdrant_client
from src.ingestion.loader import load_all_sources
from src.models import SourceDocument
from src.service.core import META_COLLECTION, META_POINT_ID

MANIFEST_DIR = Path("data/manifests")
SMOKE_K = 10


def manifest_path(collection: str) -> Path:
    return MANIFEST_DIR / f"{collection}.json"


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    sha256: str
    chunks: int
    title: str
    status: Literal["indexed", "quarantined"] = "indexed"
    reason: str = ""
    summary: str = ""


@dataclass(frozen=True, slots=True)
class Manifest:
    indexed_at: str | None
    documents: dict[str, ManifestEntry] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Plan:
    added: list[SourceDocument]
    changed: list[SourceDocument]
    unchanged: list[str]
    missing: list[str]

    @property
    def to_index(self) -> list[SourceDocument]:
        return [*self.added, *self.changed]


def fingerprint(content: str) -> str:
    """Hash of the markdown with cosmetic differences removed.

    CRLF and trailing spaces change between CDN nodes and deploys; they must
    not trigger a re-embed. The chunker's own logic version is folded in, so
    a cleaning-rule or contextual-prefix change invalidates every stored
    fingerprint and the next run re-embeds everything, even though the
    fetched source markdown is unchanged. Read lazily (not import-time) so
    tests can monkeypatch it.
    """
    from src.ingestion.chunker import CHUNKER_VERSION

    lines = (line.rstrip() for line in content.replace("\r\n", "\n").split("\n"))
    normalized = CHUNKER_VERSION + "\n" + "\n".join(lines)
    return hashlib.sha256(normalized.encode()).hexdigest()


def load_manifest(path: Path) -> Manifest:
    if not path.exists():
        return Manifest(indexed_at=None, documents={})
    raw = json.loads(path.read_text())
    return Manifest(
        indexed_at=raw.get("indexed_at"),
        documents={
            url: ManifestEntry(**entry) for url, entry in raw["documents"].items()
        },
    )


def save_manifest(manifest: Manifest, path: Path) -> None:
    payload = {
        "indexed_at": manifest.indexed_at,
        "documents": {
            url: asdict(entry) for url, entry in sorted(manifest.documents.items())
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def diff(manifest: Manifest, documents: list[SourceDocument]) -> Plan:
    added: list[SourceDocument] = []
    changed: list[SourceDocument] = []
    unchanged: list[str] = []
    seen: set[str] = set()
    for document in documents:
        seen.add(document.url)
        entry = manifest.documents.get(document.url)
        if entry is None:
            added.append(document)
        elif entry.status == "quarantined" and entry.sha256 == fingerprint(
            document.content
        ):
            unchanged.append(document.url)
        elif entry.status == "quarantined":
            added.append(document)
        elif entry.sha256 != fingerprint(document.content):
            changed.append(document)
        else:
            unchanged.append(document.url)
    missing = sorted(url for url in manifest.documents if url not in seen)
    return Plan(added=added, changed=changed, unchanged=unchanged, missing=missing)


def orphans(indexed_sources: set[str], documents: list[SourceDocument]) -> list[str]:
    """Sources still in the index that no config selects any more."""
    fetched = {document.url for document in documents}
    return sorted(indexed_sources - fetched)


def apply(
    plan: Plan,
    manifest: Manifest,
    *,
    delete_source: Callable[[str], None],
    add_chunks: Callable[[list[Document]], None],
    today: date,
) -> Manifest:
    """Replace the chunks of every added or changed page; leave the rest alone."""
    documents = dict(manifest.documents)
    for document in plan.to_index:
        chunks = chunk_document(document)
        delete_source(document.url)
        add_chunks(chunks)
        documents[document.url] = ManifestEntry(
            sha256=fingerprint(document.content),
            chunks=len(chunks),
            title=document.title,
        )
    indexed_at = today.isoformat() if plan.to_index else manifest.indexed_at
    return Manifest(indexed_at=indexed_at, documents=documents)


def _matches_expected(hit: dict[str, str], expected: dict[str, str]) -> bool:
    """Return whether a search hit satisfies one expected retrieval target."""
    if hit.get("vendor") != expected["vendor"]:
        return False

    source_contains = expected.get("source_contains")
    if source_contains and source_contains not in hit.get("source", ""):
        return False

    title = expected.get("title")
    if title and title != hit.get("title", ""):
        return False

    heading_contains = expected.get("heading_contains")
    if heading_contains:
        headings = " > ".join(
            hit.get(key, "") for key in ("h1", "h2", "h3") if hit.get(key)
        )
        if heading_contains.lower() not in headings.lower():
            return False

    return True


def smoke_failures(
    intents: list[dict[str, Any]],
    search: Callable[[str], list[dict[str, str]]],
) -> list[str]:
    """Intent ids with no relevant section among the top hits.

    `relevant` lists alternatives; one hit matching any of them is enough, the
    same hit@k rule the retrieval evals use.
    """
    failures: list[str] = []
    for intent in intents:
        hits = search(intent["variants"]["clean_en"])
        if not any(
            _matches_expected(hit, expected)
            for hit in hits
            for expected in intent["relevant"]
        ):
            failures.append(intent["id"])
    return failures


# --- wiring against the real index ------------------------------------------

# Qdrant refuses to filter on a payload key without an index. These are the
# keys the service filters on (vendor scope) and the re-index deletes by.
FILTERED_KEYS = ("metadata.source", "metadata.vendor")


def ensure_payload_indexes(client: QdrantClient, collection: str) -> None:
    """Idempotent: Qdrant accepts creating an index that already exists."""
    for key in FILTERED_KEYS:
        client.create_payload_index(
            collection_name=collection,
            field_name=key,
            field_schema=models.PayloadSchemaType.KEYWORD,
        )


def _delete_source(url: str) -> None:
    client = get_qdrant_client()
    try:
        client.delete(
            collection_name=settings.qdrant_hybrid_collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="metadata.source", match=models.MatchValue(value=url)
                        )
                    ]
                )
            ),
        )
    finally:
        client.close()


def _add_chunks(chunks: list[Document]) -> None:
    get_hybrid_vector_store().add_documents(chunks)


def _indexed_sources() -> set[str]:
    """Every distinct `metadata.source` in the hybrid collection."""
    client = get_qdrant_client()
    sources: set[str] = set()
    try:
        offset = None
        while True:
            points, offset = client.scroll(
                settings.qdrant_hybrid_collection,
                limit=256,
                offset=offset,
                with_payload=["metadata.source"],
                with_vectors=False,
            )
            for point in points:
                payload = point.payload or {}
                source = payload.get("metadata", {}).get("source")
                if source:
                    sources.add(str(source))
            if offset is None:
                return sources
    finally:
        client.close()


def touch_index(client: QdrantClient, collection: str) -> int:
    """One cheap read per run, whether or not anything changed.

    Qdrant Cloud suspends a free cluster after a week without requests and
    deletes it after four. A run where no page changed used to make no Qdrant
    call at all, and /health deliberately never does; a quiet week would
    suspend the index while the manifest still said everything was indexed.
    """
    return int(client.count(collection).count)


def write_meta(manifest: Manifest) -> None:
    """One point the service reads to report when the index was built."""
    client = get_qdrant_client()
    try:
        if not client.collection_exists(META_COLLECTION):
            client.create_collection(
                META_COLLECTION,
                vectors_config=models.VectorParams(
                    size=1, distance=models.Distance.DOT
                ),
            )
        client.upsert(
            META_COLLECTION,
            points=[
                models.PointStruct(
                    id=META_POINT_ID,
                    vector=[0.0],
                    payload={
                        "indexed_at": manifest.indexed_at,
                        "document_count": len(manifest.documents),
                        "written_at": datetime.now(UTC).isoformat(),
                    },
                )
            ],
        )
    finally:
        client.close()


def _search(query: str) -> list[dict[str, str]]:
    from src.rag.retriever import search_hybrid

    return [
        {
            "vendor": str(r.document.metadata.get("vendor", "")),
            "source": str(r.document.metadata.get("source", "")),
            "title": str(r.document.metadata.get("title", "")),
            "h1": str(r.document.metadata.get("h1", "")),
            "h2": str(r.document.metadata.get("h2", "")),
            "h3": str(r.document.metadata.get("h3", "")),
        }
        for r in search_hybrid(query=query, k=SMOKE_K)
    ]


def main(argv: list[str] | None = None) -> int:
    from evals.seed_query_transform_dataset import INTENTS

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prune",
        action="store_true",
        help="Delete indexed pages that no source config selects any more "
        "(after a deliberate change to sources.py).",
    )
    args = parser.parse_args(argv)

    path = manifest_path(settings.qdrant_hybrid_collection)
    manifest = load_manifest(path)
    documents = load_all_sources().documents
    plan = diff(manifest, documents)

    client = get_qdrant_client()
    try:
        print(f"index points: {touch_index(client, settings.qdrant_hybrid_collection)}")
    finally:
        client.close()

    if args.prune:
        stale = orphans(_indexed_sources(), documents)
        print(f"prune: {len(stale)} orphaned pages")
        for url in stale:
            print(f"  delete {url}")
            _delete_source(url)
        manifest = Manifest(
            indexed_at=manifest.indexed_at,
            documents={u: e for u, e in manifest.documents.items() if u not in stale},
        )
        plan = diff(manifest, documents)
        if not plan.to_index:
            save_manifest(manifest, path)
    print(
        f"added={len(plan.added)} changed={len(plan.changed)} "
        f"unchanged={len(plan.unchanged)} missing={len(plan.missing)}"
    )
    for document in plan.to_index:
        print(f"  reindex {document.url}")

    if plan.to_index:
        client = get_qdrant_client()
        try:
            ensure_payload_indexes(client, settings.qdrant_hybrid_collection)
        finally:
            client.close()
        manifest = apply(
            plan,
            manifest,
            delete_source=_delete_source,
            add_chunks=_add_chunks,
            today=datetime.now(UTC).date(),
        )
        write_meta(manifest)
        save_manifest(manifest, path)
        failures = smoke_failures(INTENTS, _search)
        if failures:
            print(f"SMOKE FAILED: expected page missing from top hits for {failures}")
            return 1

    if plan.missing:
        print("MISSING from vendor index (not deleted; decide by hand):")
        for url in plan.missing:
            print(f"  {url}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
