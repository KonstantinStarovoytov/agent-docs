"""Last fetched markdown per page, kept in Qdrant rather than git.

The repository is public and the documentation belongs to the vendors, so
the previous text needed for a readable diff lives in the private cluster.
"""

import uuid
from datetime import UTC, datetime

from qdrant_client import QdrantClient, models

from src.models import SourceDocument


def snapshot_collection(collection: str) -> str:
    return f"{collection}_pages"


def _point_id(url: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, url))


class SnapshotStore:
    def __init__(self, client: QdrantClient, collection: str) -> None:
        self.client = client
        self.collection = collection
        if not client.collection_exists(collection):
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

    def put(self, document: SourceDocument, sha256: str) -> None:
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
