"""Change detection and the incremental apply step, with fakes for the network."""

from datetime import date
from typing import Any

import pytest
from langchain_core.documents import Document

from src import reindex
from src.models import SourceDocument


def _doc(url: str, content: str, title: str = "T") -> SourceDocument:
    return SourceDocument(
        title=title, content=content, url=url, vendor="cursor", product="cursor"
    )


def test_fingerprint_ignores_line_endings_and_trailing_whitespace() -> None:
    assert reindex.fingerprint("# A\r\nbody  \r\n") == reindex.fingerprint(
        "# A\nbody\n"
    )
    assert reindex.fingerprint("# A\nbody\n") != reindex.fingerprint("# A\nbody!\n")


def test_diff_classifies_added_changed_unchanged_and_missing() -> None:
    manifest = reindex.Manifest(
        indexed_at="2026-09-01",
        documents={
            "u/same": reindex.ManifestEntry(
                sha256=reindex.fingerprint("same"), chunks=1, title="T"
            ),
            "u/changed": reindex.ManifestEntry(
                sha256=reindex.fingerprint("old"), chunks=1, title="T"
            ),
            "u/gone": reindex.ManifestEntry(
                sha256=reindex.fingerprint("x"), chunks=1, title="T"
            ),
        },
    )
    fetched = [_doc("u/same", "same"), _doc("u/changed", "new"), _doc("u/new", "n")]

    result = reindex.diff(manifest, fetched)

    assert [d.url for d in result.added] == ["u/new"]
    assert [d.url for d in result.changed] == ["u/changed"]
    assert result.unchanged == ["u/same"]
    assert result.missing == ["u/gone"]


def test_apply_replaces_only_changed_documents() -> None:
    deleted: list[str] = []
    added: list[Document] = []

    def delete_source(url: str) -> None:
        deleted.append(url)

    def add_chunks(chunks: list[Document]) -> None:
        added.extend(chunks)

    manifest = reindex.Manifest(indexed_at="2026-09-01", documents={})
    documents = [_doc("u/a", "# A\n\nalpha"), _doc("u/b", "# B\n\nbeta")]
    plan = reindex.diff(manifest, documents)

    updated = reindex.apply(
        plan,
        manifest,
        delete_source=delete_source,
        add_chunks=add_chunks,
        today=date(2026, 9, 15),
    )

    assert sorted(deleted) == ["u/a", "u/b"]
    assert {c.metadata["source"] for c in added} == {"u/a", "u/b"}
    assert updated.indexed_at == "2026-09-15"
    assert set(updated.documents) == {"u/a", "u/b"}
    assert updated.documents["u/a"].chunks == 1


def test_apply_keeps_missing_documents_in_manifest() -> None:
    """A page that vanished from the vendor index is a human decision."""
    manifest = reindex.Manifest(
        indexed_at="2026-09-01",
        documents={"u/gone": reindex.ManifestEntry(sha256="x", chunks=2, title="T")},
    )
    plan = reindex.diff(manifest, [])

    updated = reindex.apply(
        plan,
        manifest,
        delete_source=lambda _u: None,
        add_chunks=lambda _c: None,
        today=date(2026, 9, 15),
    )

    assert "u/gone" in updated.documents
    assert updated.indexed_at == "2026-09-01"  # nothing was re-indexed


def test_smoke_passes_when_any_relevant_target_is_hit() -> None:
    """`relevant` lists alternatives, as the evals' hit@k treats it."""
    intents: list[dict[str, Any]] = [
        {
            "id": "either",
            "relevant": [
                {"vendor": "anthropic", "source_contains": "skills"},
                {"vendor": "anthropic", "heading_contains": "compare similar"},
            ],
            "variants": {"clean_en": "q"},
        }
    ]
    hits = [
        {
            "vendor": "anthropic",
            "source": "https://code.claude.com/docs/en/features-overview.md",
            "title": "Extend Claude Code",
            "h1": "Extend Claude Code",
            "h2": "Compare Similar Features",
            "h3": "",
        }
    ]

    assert reindex.smoke_failures(intents, lambda _q: hits) == []


def test_smoke_check_supports_source_and_heading_expectations() -> None:
    intents: list[dict[str, Any]] = [
        {
            "id": "source-ok",
            "relevant": [{"vendor": "cursor", "source_contains": "rules"}],
            "variants": {"clean_en": "cursor rules"},
        },
        {
            "id": "heading-ok",
            "relevant": [
                {
                    "vendor": "anthropic",
                    "title": "Extend Claude Code",
                    "heading_contains": "Compare similar features",
                }
            ],
            "variants": {"clean_en": "claude reusable workflow"},
        },
        {
            "id": "miss",
            "relevant": [{"vendor": "openai", "source_contains": "agents-md"}],
            "variants": {"clean_en": "codex agents"},
        },
    ]

    def search(query: str) -> list[dict[str, str]]:
        if query == "claude reusable workflow":
            return [
                {
                    "vendor": "anthropic",
                    "source": "https://code.claude.com/docs/en/features-overview.md",
                    "title": "Extend Claude Code",
                    "h1": "Extend Claude Code",
                    "h2": "Compare similar features",
                    "h3": "",
                }
            ]
        return [
            {
                "vendor": "cursor",
                "source": "https://cursor.com/docs/rules.md",
                "title": "",
                "h1": "",
                "h2": "",
                "h3": "",
            }
        ]

    assert reindex.smoke_failures(intents, search) == ["miss"]


def test_manifest_round_trips_through_json(tmp_path: Any) -> None:
    path = tmp_path / "m.json"
    manifest = reindex.Manifest(
        indexed_at="2026-09-15",
        documents={"u": reindex.ManifestEntry(sha256="abc", chunks=3, title="T")},
    )

    reindex.save_manifest(manifest, path)

    assert reindex.load_manifest(path) == manifest
    assert reindex.load_manifest(tmp_path / "absent.json") == reindex.Manifest(
        indexed_at=None, documents={}
    )


def test_ensure_payload_indexes_covers_every_filtered_key() -> None:
    created: list[tuple[str, str]] = []

    class FakeClient:
        def create_payload_index(
            self, collection_name: str, field_name: str, field_schema: Any
        ) -> None:
            created.append((collection_name, field_name))

    reindex.ensure_payload_indexes(FakeClient(), "col")  # type: ignore[arg-type]

    assert set(created) == {("col", "metadata.source"), ("col", "metadata.vendor")}


def test_orphans_are_indexed_sources_no_longer_fetched() -> None:
    indexed = {"u/keep", "u/sdk-page", "u/other-old"}
    documents = [_doc("u/keep", "k"), _doc("u/new", "n")]

    assert reindex.orphans(indexed, documents) == ["u/other-old", "u/sdk-page"]


def test_fingerprint_changes_when_the_chunker_logic_version_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A chunker-logic change (cleaning rules, prefix format) must invalidate
    every stored fingerprint so the next reindex re-embeds everything, even
    though the fetched source markdown itself did not change."""
    import src.ingestion.chunker as chunker_module

    before = reindex.fingerprint("same content")
    monkeypatch.setattr(chunker_module, "CHUNKER_VERSION", "next-version")
    after = reindex.fingerprint("same content")

    assert before != after


def test_manifest_path_follows_the_collection() -> None:
    assert str(reindex.manifest_path("agent_docs_hybrid_v2")) == (
        "data/manifests/agent_docs_hybrid_v2.json"
    )


def test_old_manifest_entries_load_as_indexed(tmp_path: Any) -> None:
    path = tmp_path / "m.json"
    path.write_text(
        '{"indexed_at": "2026-09-01", "documents": '
        '{"u": {"sha256": "s", "chunks": 1, "title": "T"}}}'
    )

    entry = reindex.load_manifest(path).documents["u"]

    assert entry.status == "indexed" and entry.reason == "" and entry.summary == ""


def test_quarantined_page_is_regated_only_when_content_changes() -> None:
    q = reindex.ManifestEntry(
        sha256=reindex.fingerprint("same"),
        chunks=0,
        title="T",
        status="quarantined",
        reason="size",
        summary="s",
    )
    manifest = reindex.Manifest(indexed_at=None, documents={"u/q": q})

    same = reindex.diff(manifest, [_doc("u/q", "same")])
    edited = reindex.diff(manifest, [_doc("u/q", "edited")])

    assert same.unchanged == ["u/q"] and not same.added
    assert [d.url for d in edited.added] == ["u/q"]


def test_touch_index_reads_the_hybrid_collection() -> None:
    """Qdrant Cloud suspends a free cluster after a week without requests and
    deletes it after four. A quiet week (no doc changes) made no Qdrant call
    at all, so every run must issue at least one cheap read."""
    from types import SimpleNamespace
    from unittest.mock import Mock

    client = Mock()
    client.count.return_value = SimpleNamespace(count=1106)

    points = reindex.touch_index(client, "agent_docs_hybrid_v1")

    client.count.assert_called_once_with("agent_docs_hybrid_v1")
    assert points == 1106
