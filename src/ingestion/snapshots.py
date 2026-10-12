"""Last fetched markdown per page, kept in Qdrant rather than git.

The repository is public and the documentation belongs to the vendors, so
the previous text needed for a readable diff lives in the private cluster.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from qdrant_client import QdrantClient, models

from src.models import SourceDocument


def snapshot_collection(collection: str) -> str:
    return f"{collection}_pages"


def _point_id(url: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, url))


@dataclass(frozen=True, slots=True)
class PageSnapshot:
    url: str
    title: str
    product: str
    markdown: str
    # The page gate's one-sentence description; empty for allow-listed pages.
    summary: str


class SnapshotStore:
    def __init__(
        self, client: QdrantClient, collection: str, *, create: bool = True
    ) -> None:
        self.client = client
        self.collection = collection
        if create and not client.collection_exists(collection):
            # Payload-only in spirit; Qdrant still wants a vector per point.
            client.create_collection(
                collection,
                vectors_config=models.VectorParams(
                    size=1, distance=models.Distance.DOT
                ),
            )

    def get(self, url: str) -> str | None:
        points = self.client.retrieve(
            self.collection, [_point_id(url)], with_payload=True
        )
        return (
            str(points[0].payload["markdown"]) if points and points[0].payload else None
        )

    def pages(self, urls: list[str]) -> dict[str, PageSnapshot]:
        """Stored pages by URL, in one request; unknown URLs are left out."""
        points = self.client.retrieve(
            self.collection, [_point_id(url) for url in urls], with_payload=True
        )
        pages: dict[str, PageSnapshot] = {}
        for point in points:
            payload = point.payload or {}
            url = str(payload.get("url", ""))
            pages[url] = PageSnapshot(
                url=url,
                title=str(payload.get("title") or ""),
                product=str(payload.get("product") or ""),
                markdown=str(payload.get("markdown") or ""),
                summary=str(payload.get("summary") or ""),
            )
        return pages

    def set_summaries(self, summaries: dict[str, str]) -> int:
        """Write `summary` into stored pages' payloads; returns pages updated.

        Payload only: nothing is re-embedded. Empty summaries and pages that
        are not stored are skipped.
        """
        stored = self._urls()
        operations = [
            models.SetPayloadOperation(
                set_payload=models.SetPayload(
                    payload={"summary": summary}, points=[_point_id(url)]
                )
            )
            for url, summary in sorted(summaries.items())
            if summary and url in stored
        ]
        for start in range(0, len(operations), 100):
            self.client.batch_update_points(
                self.collection, operations[start : start + 100]
            )
        return len(operations)

    def put(self, document: SourceDocument, sha256: str, summary: str = "") -> None:
        self.client.upsert(
            self.collection,
            points=[
                models.PointStruct(
                    id=_point_id(document.url),
                    vector=[0.0],
                    payload={
                        "url": document.url,
                        "markdown": document.content,
                        "sha256": sha256,
                        "title": document.title,
                        "product": document.product,
                        "summary": summary,
                        "fetched_at": datetime.now(UTC).isoformat(),
                    },
                )
            ],
        )

    def delete(self, url: str) -> None:
        self.client.delete(
            self.collection,
            points_selector=models.PointIdsList(points=[_point_id(url)]),
        )

    def _urls(self) -> set[str]:
        urls: set[str] = set()
        offset = None
        while True:
            points, offset = self.client.scroll(
                self.collection, limit=256, offset=offset, with_payload=["url"]
            )
            urls.update(str(p.payload["url"]) for p in points if p.payload)
            if offset is None:
                return urls

    def all_texts(self) -> dict[str, str]:
        texts: dict[str, str] = {}
        offset = None
        while True:
            points, offset = self.client.scroll(
                self.collection,
                limit=256,
                offset=offset,
                with_payload=["url", "markdown"],
            )
            for p in points:
                if p.payload:
                    texts[str(p.payload["url"])] = str(p.payload["markdown"])
            if offset is None:
                return texts
