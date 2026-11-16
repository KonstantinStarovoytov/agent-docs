"""End-to-end reindex behaviour with every side effect faked."""

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest

from src import reindex
from src.ingestion.decisions import Decision
from src.ingestion.gate import PageReview
from src.ingestion.loader import LoadResult
from src.models import SourceDocument

DAY = date(2026, 9, 28)


def _doc(url: str, content: str, product: str = "p") -> SourceDocument:
    return SourceDocument(
        title=url, content=content, url=url, vendor="v", product=product
    )


@dataclass
class FakeSnapshots:
    texts: dict[str, str] = field(default_factory=dict)
    summaries: dict[str, str] = field(default_factory=dict)

    def get(self, url: str) -> str | None:
        return self.texts.get(url)

    def put(self, document: SourceDocument, sha256: str, summary: str = "") -> None:
        self.texts[document.url] = document.content
        self.summaries[document.url] = summary

    def delete(self, url: str) -> None:
        self.texts.pop(url, None)

    def all_texts(self) -> dict[str, str]:
        return dict(self.texts)


def _deps(
    docs: list[SourceDocument],
    *,
    keep: bool = True,
    listed: int | None = None,
    failures: dict[str, str] | None = None,
    product_of: dict[str, str] | None = None,
) -> Any:
    added: list[Any] = []
    deleted: list[str] = []
    deps = reindex.Deps(
        load=lambda: LoadResult(
            docs,
            failures or {},
            {"p": listed if listed is not None else len(docs)},
            {u: "p" for u in (failures or {})},
        ),
        snapshots=FakeSnapshots(),
        delete_source=deleted.append,
        add_chunks=added.extend,
        product_of=lambda: product_of or {},
        review=lambda _p: PageReview(
            keep=keep,
            category="documentation" if keep else "marketing",
            summary="What it is.",
        ),
        summarize=lambda _p: "What changed.",
    )
    return deps, added, deleted


def _empty() -> reindex.Manifest:
    return reindex.Manifest(indexed_at=None, documents={})


def test_new_clean_page_is_indexed_and_reported() -> None:
    deps, added, _ = _deps([_doc("https://x/a.md", "# A\ntext")])

    result = reindex.run(_empty(), deps, today=DAY)

    assert result.exit_code == 0
    assert result.manifest.documents["https://x/a.md"].status == "indexed"
    assert added and result.report.added[0].summary == "What it is."


def test_flagged_page_is_quarantined_not_indexed() -> None:
    deps, added, _ = _deps([_doc("https://x/a.md", "# A\ntext")], keep=False)

    result = reindex.run(_empty(), deps, today=DAY)

    entry = result.manifest.documents["https://x/a.md"]
    assert entry.status == "quarantined" and entry.summary == "What it is."
    assert not added and result.report.quarantined[0].reasons == ["model: marketing"]


def test_report_only_gate_indexes_flagged_pages_but_lists_them() -> None:
    deps, added, _ = _deps([_doc("https://x/a.md", "# A\ntext")], keep=False)

    result = reindex.run(_empty(), deps, today=DAY, gate_report_only=True)

    assert added and result.manifest.documents["https://x/a.md"].status == "indexed"
    assert result.report.quarantined


def test_allow_listed_page_skips_the_gate(monkeypatch: Any) -> None:
    monkeypatch.setattr(reindex, "allowed_urls", lambda: {"https://x/a.md"})
    deps, added, _ = _deps([_doc("https://x/a.md", "# A\ntext")], keep=False)

    result = reindex.run(_empty(), deps, today=DAY)

    assert added and not result.report.quarantined


def test_significant_change_gets_a_summary() -> None:
    old, new = "# A\n## One\nx\n", "# A\n## One\nx\n## Two\ny\n"
    manifest = reindex.Manifest(
        indexed_at="d",
        documents={
            "https://x/a.md": reindex.ManifestEntry(
                sha256=reindex.fingerprint(old), chunks=1, title="A"
            )
        },
    )
    deps, _, _ = _deps([_doc("https://x/a.md", new)])
    deps.snapshots.texts["https://x/a.md"] = old

    result = reindex.run(manifest, deps, today=DAY)

    changed = result.report.changed[0]
    assert changed.diff is not None and changed.diff.added == ["Two"]
    assert changed.summary == "What changed."


def test_vanished_page_is_deleted() -> None:
    entries = {
        f"https://x/{i}.md": reindex.ManifestEntry(
            sha256=reindex.fingerprint("c"), chunks=1, title="t"
        )
        for i in range(20)
    }
    docs = [_doc(u, "c") for u in list(entries)[1:]]
    deps, _, deleted = _deps(docs, product_of={u: "p" for u in entries})

    result = reindex.run(
        reindex.Manifest(indexed_at="d", documents=entries), deps, today=DAY
    )

    assert deleted == ["https://x/0.md"] and result.report.removed == ["https://x/0.md"]
    assert "https://x/0.md" not in result.manifest.documents


def test_blocked_removal_exits_3_and_deletes_nothing() -> None:
    entries = {
        f"https://x/{i}.md": reindex.ManifestEntry(
            sha256=reindex.fingerprint("c"), chunks=1, title="t"
        )
        for i in range(20)
    }
    docs = [_doc(u, "c") for u in list(entries)[5:]]
    deps, _, deleted = _deps(docs, product_of={u: "p" for u in entries})

    result = reindex.run(
        reindex.Manifest(indexed_at="d", documents=entries), deps, today=DAY
    )

    assert result.exit_code == 3 and deleted == [] and result.report.blocked


def test_dry_run_writes_nothing() -> None:
    deps, added, deleted = _deps([_doc("https://x/a.md", "# A\ntext")])

    result = reindex.run(_empty(), deps, today=DAY, dry_run=True)

    assert not added and not deleted and not deps.snapshots.texts
    assert result.report.added


def test_change_summaries_are_capped_per_run() -> None:
    old, new = "# A\n## One\nx\n", "# A\n## One\nx\n## Two\ny\n"
    urls = [f"https://x/{i}.md" for i in range(reindex.rep.MAX_CHANGE_SUMMARIES + 1)]
    manifest = reindex.Manifest(
        indexed_at="d",
        documents={
            u: reindex.ManifestEntry(
                sha256=reindex.fingerprint(old), chunks=1, title="A"
            )
            for u in urls
        },
    )
    deps, _, _ = _deps([_doc(u, new) for u in urls])
    calls: list[str] = []
    deps.summarize = lambda p: calls.append(p) or "What changed."
    for u in urls:
        deps.snapshots.texts[u] = old

    result = reindex.run(manifest, deps, today=DAY)

    assert len(calls) == reindex.rep.MAX_CHANGE_SUMMARIES
    assert (
        sum(1 for c in result.report.changed if c.summary)
        == reindex.rep.MAX_CHANGE_SUMMARIES
    )


def test_dry_run_does_not_create_the_snapshot_collection() -> None:
    from qdrant_client import QdrantClient

    client = QdrantClient(":memory:")

    store = reindex._snapshot_store(client, "snaps", dry_run=True)

    assert store.all_texts() == {} and not client.collection_exists("snaps")
    reindex._snapshot_store(client, "snaps", dry_run=False)
    assert client.collection_exists("snaps")


def test_failed_review_quarantines_page_without_manifest_entry() -> None:
    deps, added, _ = _deps(
        [_doc("https://x/a.md", "# A\ntext"), _doc("https://x/b.md", "# B\ntext")]
    )

    def review(prompt: str) -> PageReview:
        if "https://x/b.md" in prompt:
            raise TimeoutError("slow")
        return PageReview(keep=True, category="documentation", summary="What it is.")

    deps.review = review

    result = reindex.run(_empty(), deps, today=DAY)

    assert result.exit_code == 0
    assert result.manifest.documents["https://x/a.md"].status == "indexed"
    assert "https://x/b.md" not in result.manifest.documents
    assert {c.metadata["source"] for c in added} == {"https://x/a.md"}
    [line] = result.report.quarantined
    assert line.url == "https://x/b.md" and line.reasons == [
        "review failed: TimeoutError"
    ]


def test_failed_summary_still_indexes_the_change() -> None:
    old, new = "# A\n## One\nx\n", "# A\n## One\nx\n## Two\ny\n"
    manifest = reindex.Manifest(
        indexed_at="d",
        documents={
            "https://x/a.md": reindex.ManifestEntry(
                sha256=reindex.fingerprint(old), chunks=1, title="A"
            )
        },
    )
    deps, added, _ = _deps([_doc("https://x/a.md", new)])
    deps.snapshots.texts["https://x/a.md"] = old

    def boom(_p: str) -> str:
        raise RuntimeError("api down")

    deps.summarize = boom

    result = reindex.run(manifest, deps, today=DAY)

    assert added and result.report.changed[0].summary == ""
    assert result.manifest.documents["https://x/a.md"].sha256 == reindex.fingerprint(
        new
    )


def test_allowing_a_quarantined_page_indexes_it_on_the_next_run(
    monkeypatch: Any,
) -> None:
    """The documented way out of quarantine is adding the URL to `allow`;
    that must work even though the page's content has not changed."""
    monkeypatch.setattr(reindex, "allowed_urls", lambda: {"https://x/q.md"})
    content = "# Q\ntext"
    manifest = reindex.Manifest(
        indexed_at="d",
        documents={
            "https://x/q.md": reindex.ManifestEntry(
                sha256=reindex.fingerprint(content),
                chunks=0,
                title="Q",
                status="quarantined",
                reason="model: marketing",
            )
        },
    )
    deps, added, _ = _deps([_doc("https://x/q.md", content)], keep=False)

    result = reindex.run(manifest, deps, today=DAY)

    assert added
    assert result.manifest.documents["https://x/q.md"].status == "indexed"
    assert not result.report.quarantined


def test_an_allow_decision_from_the_issue_counts_as_allow_listed(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        reindex,
        "load_decisions",
        lambda: {"https://x/q.md": Decision("allow", "2026-10-17")},
    )

    assert "https://x/q.md" in reindex.allowed_urls()


def test_a_declined_page_that_changed_comes_back_for_review(
    monkeypatch: Any,
) -> None:
    """The gate would keep the new version, but the owner said no once:
    it waits for the owner again instead of being indexed."""
    monkeypatch.setattr(
        reindex,
        "load_decisions",
        lambda: {"https://x/q.md": Decision("decline", "2026-10-17", "old")},
    )
    manifest = reindex.Manifest(
        indexed_at="d",
        documents={
            "https://x/q.md": reindex.ManifestEntry(
                sha256="old", chunks=0, title="Q", status="quarantined"
            )
        },
    )
    deps, added, _ = _deps([_doc("https://x/q.md", "# Q\nnew text")], keep=True)

    result = reindex.run(manifest, deps, today=DAY)

    entry = result.manifest.documents["https://x/q.md"]
    assert not added and entry.status == "quarantined"
    assert "declined on 2026-10-17" in entry.reason
    assert result.report.quarantined[0].url == "https://x/q.md"


def test_snapshot_keeps_the_gate_summary_for_new_and_changed_pages() -> None:
    deps, _, _ = _deps([_doc("https://x/a.md", "# A\ntext")])

    reindex.run(_empty(), deps, today=DAY)

    assert deps.snapshots.summaries["https://x/a.md"] == "What it is."

    old, new = "# B\nold\n", "# B\nnew\n"
    manifest = reindex.Manifest(
        indexed_at="d",
        documents={
            "https://x/b.md": reindex.ManifestEntry(
                sha256=reindex.fingerprint(old), chunks=1, title="B", summary="B is."
            )
        },
    )
    deps, _, _ = _deps([_doc("https://x/b.md", new)])

    reindex.run(manifest, deps, today=DAY)

    assert deps.snapshots.summaries["https://x/b.md"] == "B is."


def test_backfill_copies_manifest_summaries_into_stored_pages() -> None:
    from qdrant_client import QdrantClient

    from src.ingestion.snapshots import SnapshotStore

    store = SnapshotStore(QdrantClient(":memory:"), "c_pages")
    store.put(_doc("https://x/a.md", "# A"), "sha")
    store.put(_doc("https://x/b.md", "# B"), "sha")
    manifest = reindex.Manifest(
        indexed_at="d",
        documents={
            "https://x/a.md": reindex.ManifestEntry("s", 1, "A", summary="A is."),
            "https://x/b.md": reindex.ManifestEntry("s", 1, "B"),
            "https://x/q.md": reindex.ManifestEntry(
                "s", 0, "Q", status="quarantined", summary="Q is."
            ),
        },
    )

    assert reindex.backfill_summaries(manifest, store) == 1
    pages = store.pages(["https://x/a.md", "https://x/b.md"])
    assert pages["https://x/a.md"].summary == "A is."
    assert pages["https://x/b.md"].summary == ""


def _fake_review(seen: list[str]) -> Any:
    def review(prompt: str) -> PageReview:
        seen.append(prompt)
        # A reviewer that would quarantine everything: only the summary may be used.
        return PageReview(keep=False, category="changelog", summary="Fresh summary.")

    return review


def test_generate_missing_summaries_fills_manifest_and_snapshots() -> None:
    from qdrant_client import QdrantClient

    from src.ingestion.snapshots import SnapshotStore

    store = SnapshotStore(QdrantClient(":memory:"), "c_pages")
    store.put(_doc("https://x/a.md", "# A\nbody"), "sha")
    store.put(_doc("https://x/b.md", "# B"), "sha", summary="B is.")
    store.put(_doc("https://x/c.md", "# C"), "sha")
    entries = {
        "https://x/a.md": reindex.ManifestEntry("s", 1, "A"),
        "https://x/b.md": reindex.ManifestEntry("s", 1, "B", summary="B is."),
        "https://x/q.md": reindex.ManifestEntry("s", 0, "Q", status="quarantined"),
        # indexed but with no stored page: skipped, not an error
        "https://x/gone.md": reindex.ManifestEntry("s", 1, "Gone"),
    }
    manifest = reindex.Manifest(indexed_at="d", documents=entries)
    prompts: list[str] = []

    updated, count = reindex.generate_missing_summaries(
        manifest, store, review=_fake_review(prompts)
    )

    assert count == 1 and len(prompts) == 1 and "# A" in prompts[0]
    assert updated.indexed_at == "d"
    a = updated.documents["https://x/a.md"]
    assert a.summary == "Fresh summary." and a.status == "indexed" and a.reason == ""
    assert updated.documents["https://x/b.md"].summary == "B is."
    assert updated.documents["https://x/q.md"].status == "quarantined"
    assert updated.documents["https://x/gone.md"].summary == ""
    stored = store.pages(["https://x/a.md", "https://x/b.md", "https://x/c.md"])
    assert stored["https://x/a.md"].summary == "Fresh summary."
    assert stored["https://x/a.md"].markdown == "# A\nbody"
    assert stored["https://x/b.md"].summary == "B is."
    assert stored["https://x/c.md"].summary == ""  # not in the manifest: untouched


def test_generate_missing_summaries_survives_a_failing_review() -> None:
    from qdrant_client import QdrantClient

    from src.ingestion.snapshots import SnapshotStore

    store = SnapshotStore(QdrantClient(":memory:"), "c_pages")
    for name in ("a", "b"):
        store.put(_doc(f"https://x/{name}.md", f"# {name}"), "sha")
    manifest = reindex.Manifest(
        indexed_at="d",
        documents={
            f"https://x/{n}.md": reindex.ManifestEntry("s", 1, n) for n in ("a", "b")
        },
    )

    def review(prompt: str) -> PageReview:
        if "# a" in prompt:
            raise RuntimeError("model down")
        return PageReview(keep=True, category="documentation", summary="B is.")

    updated, count = reindex.generate_missing_summaries(manifest, store, review=review)

    assert count == 1
    assert updated.documents["https://x/a.md"].summary == ""
    assert updated.documents["https://x/b.md"].summary == "B is."


def test_unchanged_page_without_a_snapshot_gets_one() -> None:
    """Pages indexed before the snapshot store existed have no snapshot;
    find_pages and read_section need one. Filling it must not re-embed."""
    content = "# A\ntext"
    manifest = reindex.Manifest(
        indexed_at="d",
        documents={
            "https://x/a.md": reindex.ManifestEntry(
                sha256=reindex.fingerprint(content), chunks=1, title="A", summary="S."
            )
        },
    )
    deps, added, deleted = _deps([_doc("https://x/a.md", content)])

    reindex.run(manifest, deps, today=DAY)

    assert deps.snapshots.texts["https://x/a.md"] == content
    assert not added and not deleted


def test_dry_run_does_not_fill_missing_snapshots() -> None:
    content = "# A\ntext"
    manifest = reindex.Manifest(
        indexed_at="d",
        documents={
            "https://x/a.md": reindex.ManifestEntry(
                sha256=reindex.fingerprint(content), chunks=1, title="A"
            )
        },
    )
    deps, _, _ = _deps([_doc("https://x/a.md", content)])

    reindex.run(manifest, deps, today=DAY, dry_run=True)

    assert not deps.snapshots.texts


# --- the feed for programs ---------------------------------------------------


def test_the_feed_gets_the_product_of_a_removed_page_from_the_index() -> None:
    entries = {
        f"https://x/{i}.md": reindex.ManifestEntry(
            sha256=reindex.fingerprint("c"), chunks=1, title="t"
        )
        for i in range(20)
    }
    docs = [_doc(u, "c") for u in list(entries)[1:]]
    deps, _, _ = _deps(docs, product_of={u: "p" for u in entries})

    result = reindex.run(
        reindex.Manifest(indexed_at="d", documents=entries), deps, today=DAY
    )

    day = reindex.rep.feed_day(result.report, result.product_of)
    assert day is not None
    assert result.report.removed == ["https://x/0.md"]
    assert day["removed"] == [{"url": "https://x/0.md", "product": "p"}]


def test_a_quarantined_page_is_not_in_the_feed() -> None:
    deps, _, _ = _deps([_doc("https://x/a.md", "# A\ntext")], keep=False)
    manifest = reindex.Manifest(
        indexed_at="d",
        documents={
            "https://x/old.md": reindex.ManifestEntry(
                sha256=reindex.fingerprint("c"), chunks=1, title="t"
            )
        },
    )
    deps.load = lambda: LoadResult(
        [_doc("https://x/a.md", "# A\ntext"), _doc("https://x/old.md", "c")],
        {},
        {"p": 2},
        {},
    )

    result = reindex.run(manifest, deps, today=DAY)

    assert result.report.quarantined
    assert reindex.rep.feed_day(result.report, result.product_of) is None


class _FixedClock(datetime):
    @classmethod
    def now(cls, tz: Any = None) -> "_FixedClock":
        return cls(2026, 11, 14, 13, 0, tzinfo=tz)


@dataclass
class _Main:
    root: Path
    saved: list[reindex.Manifest] = field(default_factory=list)

    def run(self, *argv: str) -> int:
        return reindex.main(["--out", str(self.root / "out"), *argv])


@pytest.fixture
def fake_main(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Main:
    """`main()` with Qdrant, the vendors' sites, the models and the clock faked.

    One page is new (allow-listed, so no gate model runs) and one has vanished.
    """
    monkeypatch.chdir(tmp_path)
    fake = _Main(tmp_path)
    entries = {
        f"https://x/{i}.md": reindex.ManifestEntry(
            sha256=reindex.fingerprint("c"), chunks=1, title="t"
        )
        for i in range(20)
    }
    docs = [_doc(u, "c") for u in list(entries)[1:]]
    docs.append(_doc("https://x/new.md", "# New\ntext", product="codex"))

    class Client:
        def close(self) -> None:
            pass

    monkeypatch.setattr(reindex, "datetime", _FixedClock)
    monkeypatch.setattr(
        reindex,
        "load_manifest",
        lambda _path: reindex.Manifest(indexed_at="d", documents=dict(entries)),
    )
    monkeypatch.setattr(
        reindex, "save_manifest", lambda manifest, _path: fake.saved.append(manifest)
    )
    monkeypatch.setattr(reindex, "get_qdrant_client", Client)
    monkeypatch.setattr(reindex, "ensure_hybrid_collection", lambda *_: False)
    monkeypatch.setattr(reindex, "touch_index", lambda *_: 0)
    monkeypatch.setattr(reindex, "ensure_payload_indexes", lambda *_: None)
    monkeypatch.setattr(reindex, "_snapshot_store", lambda *_: FakeSnapshots())
    monkeypatch.setattr(
        reindex,
        "load_all_sources",
        lambda: LoadResult(docs, {}, {"p": len(docs) - 1, "codex": 1}, {}),
    )
    monkeypatch.setattr(reindex, "_product_of", lambda: {u: "p" for u in entries})
    monkeypatch.setattr(reindex, "_delete_source", lambda _url: None)
    monkeypatch.setattr(reindex, "_add_chunks", lambda _chunks: None)
    monkeypatch.setattr(reindex, "load_decisions", lambda: {})
    monkeypatch.setattr(reindex, "allowed_urls", lambda: {"https://x/new.md"})
    monkeypatch.setattr(reindex, "write_meta", lambda *_: None)
    monkeypatch.setattr(reindex, "smoke_failures", lambda *_: [])
    return fake


def test_main_writes_no_feed_without_the_flag(fake_main: _Main) -> None:
    assert fake_main.run() == 0

    assert fake_main.saved, "the run reached the manifest"
    assert (fake_main.root / "reports/docs-changes/2026-11-14.md").exists()
    assert not list(fake_main.root.rglob("*.json"))


def test_main_writes_the_feed_when_asked(fake_main: _Main) -> None:
    feed = fake_main.root / "reports/docs-changes/feed.json"

    assert fake_main.run("--feed", str(feed)) == 0

    assert json.loads(feed.read_text()) == {
        "checked": "2026-11-14",
        "days": [
            {
                "day": "2026-11-14",
                "added": [{"url": "https://x/new.md", "product": "codex"}],
                "removed": [{"url": "https://x/0.md", "product": "p"}],
                "changed": [],
            }
        ],
    }


def test_main_moves_checked_on_a_day_with_no_change(
    fake_main: _Main, monkeypatch: pytest.MonkeyPatch
) -> None:
    feed = fake_main.root / "feed.json"
    old = {
        "checked": "2026-11-12",
        "days": [
            {
                "day": "2026-11-12",
                "added": [{"url": "https://x/a.md", "product": "codex"}],
                "removed": [],
                "changed": [],
            }
        ],
    }
    feed.write_text(json.dumps(old))
    unchanged = [_doc(f"https://x/{i}.md", "c") for i in range(20)]
    monkeypatch.setattr(
        reindex, "load_all_sources", lambda: LoadResult(unchanged, {}, {"p": 20}, {})
    )

    assert fake_main.run("--feed", str(feed)) == 0

    assert not (fake_main.root / "reports/docs-changes/2026-11-14.md").exists()

    assert json.loads(feed.read_text()) == {**old, "checked": "2026-11-14"}


def test_a_dry_run_writes_no_feed(fake_main: _Main) -> None:
    feed = fake_main.root / "feed.json"

    assert fake_main.run("--dry-run", "--feed", str(feed)) == 0

    assert not feed.exists() and not fake_main.saved


def test_a_broken_feed_file_is_replaced_by_a_new_feed(
    fake_main: _Main, capsys: pytest.CaptureFixture[str]
) -> None:
    feed = fake_main.root / "feed.json"
    feed.write_text('{"checked": "2026-11-13", "days": [')

    assert fake_main.run("--feed", str(feed)) == 0

    written = json.loads(feed.read_text())
    assert written["checked"] == "2026-11-14"
    assert [d["day"] for d in written["days"]] == ["2026-11-14"]
    assert "is not a feed; starting a new one" in capsys.readouterr().out


def test_a_failed_smoke_check_still_writes_the_feed_and_exits_1(
    fake_main: _Main, monkeypatch: pytest.MonkeyPatch
) -> None:
    feed = fake_main.root / "feed.json"
    monkeypatch.setattr(reindex, "smoke_failures", lambda *_: ["intent-1"])

    assert fake_main.run("--feed", str(feed)) == 1

    written = json.loads(feed.read_text())
    assert written["checked"] == "2026-11-14"
    assert written["days"][0]["added"] == [
        {"url": "https://x/new.md", "product": "codex"}
    ]
