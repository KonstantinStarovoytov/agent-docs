"""What an index holds, page by page: data/manifests/<collection>.json.

Standard library only, so the page review workflow can read it without the
service's settings or API keys.
"""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

MANIFEST_DIR = Path("data/manifests")


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
