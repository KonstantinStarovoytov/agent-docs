"""Incremental re-index: fetch every source page, re-embed only what changed.

Runs from a daily GitHub Actions cron. The manifest under `data/` remembers a
fingerprint per page, so a run where nothing changed costs a few HTTP requests
and no embeddings. New pages pass a quality gate (flagged ones are
quarantined), vanished pages are deleted unless a vendor's index looks broken,
and every run writes a readable change report.
"""

import argparse
import hashlib
import json
import statistics
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from langchain_core.documents import Document
from qdrant_client import QdrantClient, models

from src.config import settings
from src.ingestion.chunker import chunk_document
from src.ingestion.ingest import get_hybrid_vector_store, get_qdrant_client
from src.ingestion import report as rep
from src.ingestion.gate import PageReview, gate_page
from src.ingestion.loader import LoadResult, load_all_sources
from src.ingestion.snapshots import SnapshotStore, snapshot_collection
from src.ingestion.sources import SOURCES
from src.models import SourceDocument
from src.service.core import META_COLLECTION, META_POINT_ID

MANIFEST_DIR = Path("data/manifests")
SMOKE_K = 10
REMOVAL_GUARD = 0.10
SHRINK_GUARD = 0.5
FETCH_FAILURE_GUARD = 0.10


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


@dataclass(frozen=True, slots=True)
class RemovalDecision:
    delete: list[str]
    blocked: dict[str, str]


def decide_removals(
    manifest: Manifest,
    missing: list[str],
    load: LoadResult,
    product_of: dict[str, str],
) -> RemovalDecision:
    """Delete vanished pages, unless a vendor's index looks broken."""
    gone = [u for u in missing if u not in load.failures]
    indexed: dict[str, int] = {}
    for url, entry in manifest.documents.items():
        if entry.status == "indexed":
            product = product_of.get(url, "")
            indexed[product] = indexed.get(product, 0) + 1
    by_product: dict[str, list[str]] = {}
    for url in gone:
        by_product.setdefault(product_of.get(url, ""), []).append(url)
    delete: list[str] = []
    blocked: dict[str, str] = {}
    for product, urls in by_product.items():
        before = indexed.get(product, 0)
        listed = load.listed.get(product, 0)
        if before and listed < before * SHRINK_GUARD:
            blocked[product] = f"llms.txt lists {listed} pages, was {before}"
        elif before and len(urls) > before * REMOVAL_GUARD:
            blocked[product] = f"{len(urls)} of {before} pages would be removed"
        else:
            delete.extend(urls)
    return RemovalDecision(delete=sorted(delete), blocked=blocked)


def failing_vendors(load: LoadResult) -> dict[str, str]:
    failed: dict[str, int] = {}
    for product in load.failed_products.values():
        failed[product] = failed.get(product, 0) + 1
    return {
        product: f"{n} of {load.listed[product]} pages failed to fetch"
        for product, n in failed.items()
        if n > load.listed.get(product, 0) * FETCH_FAILURE_GUARD
    }


def orphans(indexed_sources: set[str], documents: list[SourceDocument]) -> list[str]:
    """Sources still in the index that no config selects any more."""
    fetched = {document.url for document in documents}
    return sorted(indexed_sources - fetched)


class Snapshots(Protocol):
    def get(self, url: str) -> str | None: ...
    def put(self, document: SourceDocument, sha256: str) -> None: ...
    def delete(self, url: str) -> None: ...
    def all_texts(self) -> dict[str, str]: ...


@dataclass
class Deps:
    load: Callable[[], LoadResult]
    snapshots: Snapshots
    delete_source: Callable[[str], None]
    add_chunks: Callable[[list[Document]], None]
    product_of: Callable[[], dict[str, str]]
    review: Callable[[str], PageReview] | None = None
    summarize: Callable[[str], str] | None = None


@dataclass(frozen=True, slots=True)
class RunResult:
    manifest: Manifest
    report: rep.ChangeReport
    exit_code: int


def allowed_urls() -> set[str]:
    return {url for config in SOURCES for url in config.allow}


def _medians(manifest: Manifest, product_of: dict[str, str]) -> dict[str, float]:
    per: dict[str, list[int]] = {}
    for url, entry in manifest.documents.items():
        if entry.status == "indexed":
            per.setdefault(product_of.get(url, ""), []).append(entry.chunks)
    return {p: float(statistics.median(c)) for p, c in per.items()}


def run(
    manifest: Manifest,
    deps: Deps,
    *,
    today: date,
    dry_run: bool = False,
    gate_report_only: bool = False,
) -> RunResult:
    load = deps.load()
    plan = diff(manifest, load.documents)
    product_of = deps.product_of()
    removals = decide_removals(manifest, plan.missing, load, product_of)
    broken = failing_vendors(load)
    documents = dict(manifest.documents)
    medians = _medians(manifest, product_of)
    indexed_texts = deps.snapshots.all_texts() if plan.added else {}
    allowed = allowed_urls()
    report = rep.ChangeReport(
        day=today.isoformat(),
        added=[],
        removed=[],
        changed=[],
        quarantined=[],
        fetch_failures=dict(load.failures),
        blocked={**removals.blocked, **broken},
        initial_build=not manifest.documents,
    )
    summaries = 0

    def index(document: SourceDocument, entry_summary: str) -> None:
        chunks = chunk_document(document)
        sha = fingerprint(document.content)
        if not dry_run:
            deps.delete_source(document.url)
            deps.add_chunks(chunks)
            deps.snapshots.put(document, sha)
        documents[document.url] = ManifestEntry(
            sha256=sha, chunks=len(chunks), title=document.title, summary=entry_summary
        )

    for document in plan.added:
        chunks = chunk_document(document)
        line = rep.PageLine(document.url, document.title, document.product)
        if document.url in allowed:
            index(document, "")
            report.added.append(line)
            continue
        try:
            verdict = gate_page(
                document,
                len(chunks),
                medians.get(document.product, float(len(chunks))),
                indexed_texts,
                review=deps.review,
            )
        except Exception as error:  # fail closed; no manifest entry, so it retries
            print(f"  gate failed for {document.url}: {type(error).__name__}")
            report.quarantined.append(
                rep.QuarantineLine(
                    document.url,
                    document.title,
                    document.product,
                    "",
                    [f"review failed: {type(error).__name__}"],
                )
            )
            continue
        line.summary = verdict.summary
        if verdict.keep or gate_report_only:
            index(document, verdict.summary)
            report.added.append(line)
        if not verdict.keep:
            report.quarantined.append(
                rep.QuarantineLine(
                    document.url,
                    document.title,
                    document.product,
                    verdict.summary,
                    verdict.reasons,
                )
            )
            if not gate_report_only:
                documents[document.url] = ManifestEntry(
                    sha256=fingerprint(document.content),
                    chunks=0,
                    title=document.title,
                    status="quarantined",
                    reason="; ".join(verdict.reasons),
                    summary=verdict.summary,
                )

    for document in plan.changed:
        old = deps.snapshots.get(document.url)
        line = rep.ChangedLine(document.url, document.title, document.product)
        if old is not None:
            line.diff = rep.section_diff(old, document.content)
            if line.diff.significant and summaries < rep.MAX_CHANGE_SUMMARIES:
                summaries += 1
                try:
                    line.summary = rep.summarize_change(
                        document.title, old, document.content, summarize=deps.summarize
                    )
                except Exception as error:
                    print(
                        f"  summary failed for {document.url}: {type(error).__name__}"
                    )
        index(document, documents[document.url].summary)
        report.changed.append(line)

    for url in removals.delete:
        if not dry_run:
            deps.delete_source(url)
            deps.snapshots.delete(url)
        documents.pop(url, None)
        report.removed.append(url)

    indexed_at = (
        today.isoformat() if (plan.to_index or removals.delete) else manifest.indexed_at
    )
    code = 4 if broken else 3 if removals.blocked else 0
    return RunResult(Manifest(indexed_at=indexed_at, documents=documents), report, code)


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


class _EmptySnapshots:
    """Read-only stand-in so a dry run never creates the snapshot collection."""

    def get(self, url: str) -> str | None:
        return None

    def put(self, document: SourceDocument, sha256: str) -> None:
        pass

    def delete(self, url: str) -> None:
        pass

    def all_texts(self) -> dict[str, str]:
        return {}


def _snapshot_store(client: QdrantClient, collection: str, dry_run: bool) -> Snapshots:
    if dry_run and not client.collection_exists(collection):
        return _EmptySnapshots()
    return SnapshotStore(client, collection)


def _product_of() -> dict[str, str]:
    """URL -> product for every page in the hybrid collection."""
    client = get_qdrant_client()
    products: dict[str, str] = {}
    try:
        offset = None
        while True:
            points, offset = client.scroll(
                settings.qdrant_hybrid_collection,
                limit=256,
                offset=offset,
                with_payload=["metadata.source", "metadata.product"],
                with_vectors=False,
            )
            for p in points:
                meta = (p.payload or {}).get("metadata", {})
                if meta.get("source"):
                    products[str(meta["source"])] = str(meta.get("product", ""))
            if offset is None:
                return products
    finally:
        client.close()


def main(argv: list[str] | None = None) -> int:
    from evals.seed_query_transform_dataset import INTENTS

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prune",
        action="store_true",
        help="Also delete indexed pages no source config selects.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch, select, gate and report without writing anywhere.",
    )
    parser.add_argument(
        "--gate-report-only",
        action="store_true",
        help="Index flagged pages anyway but list them (initial build).",
    )
    parser.add_argument(
        "--out", default=".", help="Where report.md and quarantine.md go."
    )
    args = parser.parse_args(argv)

    collection = settings.qdrant_hybrid_collection
    path = manifest_path(collection)
    manifest = load_manifest(path)
    client = get_qdrant_client()
    try:
        print(f"index points: {touch_index(client, collection)}")
        if not args.dry_run:
            ensure_payload_indexes(client, collection)
        store = _snapshot_store(client, snapshot_collection(collection), args.dry_run)
        loaded = load_all_sources()  # fetched once, shared by run and prune
        deps = Deps(
            load=lambda: loaded,
            snapshots=store,
            delete_source=_delete_source,
            add_chunks=_add_chunks,
            product_of=_product_of,
        )
        result = run(
            manifest,
            deps,
            today=datetime.now(UTC).date(),
            dry_run=args.dry_run,
            gate_report_only=args.gate_report_only,
        )
        if args.prune and not args.dry_run:
            for url in orphans(_indexed_sources(), loaded.documents):
                print(f"  prune {url}")
                _delete_source(url)
                store.delete(url)
                result.manifest.documents.pop(url, None)
    finally:
        client.close()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    text = rep.render_report(result.report)
    (out / "report.md").write_text(text)
    if result.report.quarantined and not args.gate_report_only:
        (out / "quarantine.md").write_text(
            rep.render_quarantine_issue(result.report.quarantined)
        )
    print(text)
    if args.dry_run:
        return result.exit_code
    save_manifest(result.manifest, path)
    if not result.report.empty():
        daily = Path("reports/docs-changes") / f"{result.report.day}.md"
        daily.parent.mkdir(parents=True, exist_ok=True)
        daily.write_text(text)
    if result.manifest.indexed_at != manifest.indexed_at:
        write_meta(result.manifest)
        failures = smoke_failures(INTENTS, _search)
        if failures:
            print(f"SMOKE FAILED: expected page missing from top hits for {failures}")
            return 1
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
