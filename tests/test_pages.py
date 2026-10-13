"""Page outlines and section reads come from the stored page markdown."""

from typing import Any

import pytest

from src.ingestion.snapshots import PageSnapshot
from src.service import core, pages

PAGE = """> ## Documentation Index
> Fetch the complete documentation index at: https://x/llms.txt

# Hooks

Hooks run [shell commands](https://x/cmd) at fixed points. They are configured in settings.

## Configure hooks

Put them in `settings.json`.

```bash
# not a heading
echo hi
```

### Matchers

<Tip>Matchers are regexes.</Tip>

## Hook events

Intro to events.

### PreToolUse

Runs before a tool.

#### Input

Fields of the input.

### PostToolUse

Runs after a tool.

## Examples

### Matchers

Example matchers.
"""


def test_outline_shows_h1_and_h2_with_subsection_counts_skipping_code() -> None:
    assert pages.outline(PAGE) == [
        "# Hooks",
        "## Configure hooks (1 subsection)",
        "## Hook events (2 subsections)",
        "## Examples (1 subsection)",
    ]


def test_outline_does_not_annotate_an_h2_without_subsections() -> None:
    assert pages.outline("# T\n\n## A\ntext\n\n## B\n### C\n") == [
        "# T",
        "## A",
        "## B (1 subsection)",
    ]


def test_outline_depth_3_adds_h3_and_drops_the_counts() -> None:
    assert pages.outline(PAGE, depth=3) == [
        "# Hooks",
        "## Configure hooks",
        "### Matchers",
        "## Hook events",
        "### PreToolUse",
        "### PostToolUse",
        "## Examples",
        "### Matchers",
    ]


def test_outline_is_capped_with_a_more_sections_marker() -> None:
    markdown = "\n\n".join(f"## H{i}\ntext" for i in range(50))

    capped = pages.outline(markdown)

    assert capped[:40] == [f"## H{i}" for i in range(40)]
    assert capped[40] == "+10 more sections"
    assert len(capped) == 41


def test_outline_cap_applies_at_depth_3_too() -> None:
    markdown = "\n\n".join(f"## H{i}\n### S{i}" for i in range(30))

    capped = pages.outline(markdown, depth=3)

    assert len(capped) == pages.OUTLINE_CAP + 1
    assert capped[-1] == "+20 more sections"


def test_a_short_outline_has_no_marker() -> None:
    assert pages.outline("# T\n## A\n") == ["# T", "## A"]


def test_description_prefers_the_gate_summary() -> None:
    assert pages.description("Explains hooks.", PAGE) == "Explains hooks."


def test_description_falls_back_to_the_first_prose_sentence() -> None:
    assert pages.description("", PAGE) == "Hooks run shell commands at fixed points."


def test_description_fallback_is_at_most_200_chars() -> None:
    text = pages.description("", "# T\n\n" + "word " * 100)

    assert len(text) <= 200 and text.endswith("…")


def test_section_runs_to_the_next_heading_of_same_or_higher_level() -> None:
    section = pages.find_section(PAGE, "hook events")

    assert section.path == "Hooks > Hook events"
    assert section.text.startswith("## Hook events\n\nIntro to events.")
    assert "#### Input" in section.text and "### PostToolUse" in section.text
    assert "## Examples" not in section.text


def test_section_accepts_markdown_hashes_and_a_unique_contains_match() -> None:
    assert pages.find_section(PAGE, "### PreToolUse").path == (
        "Hooks > Hook events > PreToolUse"
    )
    assert pages.find_section(PAGE, "configure").path == "Hooks > Configure hooks"


def test_section_heading_inside_code_is_not_a_heading() -> None:
    section = pages.find_section(PAGE, "Configure hooks")

    assert "# not a heading" in section.text
    assert "### Matchers" in section.text


def test_ambiguous_heading_lists_the_paths_and_a_path_resolves_it() -> None:
    with pytest.raises(pages.SectionNotFound) as error:
        pages.find_section(PAGE, "Matchers")

    message = str(error.value)
    assert "Configure hooks > Matchers" in message
    assert "Examples > Matchers" in message
    assert pages.find_section(PAGE, "Examples > Matchers").text == (
        "### Matchers\n\nExample matchers."
    )


def test_missing_heading_lists_the_available_headings() -> None:
    with pytest.raises(pages.SectionNotFound) as error:
        pages.find_section(PAGE, "Pricing")

    assert "## Hook events" in str(error.value)
    assert isinstance(error.value, core.QuestionRejected)


def test_slice_cuts_long_text_on_a_line_break_and_points_to_the_rest() -> None:
    text = "\n".join("x" * 99 for _ in range(200))  # 19,999 chars

    first, next_offset = pages.slice_text(text, 0, cap=8000)

    assert len(first) <= 8000 and first.endswith("x")
    assert next_offset == len(first) + 1
    rest, end = pages.slice_text(text, 19_000, cap=8000)
    assert end is None and rest == text[19_000:]


def _store(monkeypatch: pytest.MonkeyPatch, *snapshots: PageSnapshot) -> None:
    by_url = {s.url: s for s in snapshots}
    monkeypatch.setattr(
        pages,
        "_snapshot_pages",
        lambda urls: {u: by_url[u] for u in urls if u in by_url},
    )


def _snapshot(url: str = "https://x/hooks.md", summary: str = "") -> PageSnapshot:
    return PageSnapshot(
        url=url, title="Hooks", product="claude-code", markdown=PAGE, summary=summary
    )


def test_read_section_without_heading_returns_the_compact_outline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _store(monkeypatch, _snapshot(summary="Explains hooks."))

    result = pages.read_section("https://x/hooks.md")

    assert result.description == "Explains hooks."
    assert result.outline == [
        "# Hooks",
        "## Configure hooks (1 subsection)",
        "## Hook events (2 subsections)",
        "## Examples (1 subsection)",
    ]
    assert result.heading is None and result.text == ""
    assert result.next_offset is None


def test_read_section_outline_depth_3_lists_subsections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _store(monkeypatch, _snapshot())

    result = pages.read_section("https://x/hooks.md", outline_depth=3)

    assert "### PreToolUse" in result.outline
    assert "#### Input" not in result.outline
    assert "## Hook events" in result.outline


def test_heading_read_is_unchanged_by_the_outline_depth_and_includes_subsections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _store(monkeypatch, _snapshot())

    plain = pages.read_section("https://x/hooks.md", "Hook events")
    deep = pages.read_section("https://x/hooks.md", "Hook events", outline_depth=3)

    assert plain == deep and plain.outline == []
    assert plain.text == pages.find_section(PAGE, "Hook events").text
    assert "### PreToolUse" in plain.text and "#### Input" in plain.text
    assert "## Examples" not in plain.text


def test_an_outline_line_with_its_count_is_accepted_as_a_heading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _store(monkeypatch, _snapshot())

    result = pages.read_section("https://x/hooks.md", "## Hook events (2 subsections)")

    assert result.heading == "Hooks > Hook events"


def test_read_section_rejects_an_unsupported_outline_depth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _store(monkeypatch, _snapshot())

    with pytest.raises(core.QuestionRejected):
        pages.read_section("https://x/hooks.md", outline_depth=4)


def test_read_section_returns_the_section_and_continues_from_offset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    long_page = "# T\n\n## Big\n\n" + "\n".join("y" * 79 for _ in range(150))
    _store(
        monkeypatch,
        PageSnapshot("https://x/big.md", "T", "p", long_page, ""),
    )

    first = pages.read_section("https://x/big.md", "Big")
    second = pages.read_section("https://x/big.md", "Big", offset=first.next_offset)

    assert first.heading == "T > Big"
    assert first.text.startswith("## Big") and len(first.text) <= pages.SECTION_CHARS
    assert first.next_offset is not None and second.offset == first.next_offset
    assert first.total_chars == second.total_chars
    assert second.next_offset is None
    assert first.text + "\n" + second.text == pages.find_section(long_page, "Big").text


def test_read_section_unknown_url_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _store(monkeypatch)

    with pytest.raises(pages.PageNotFound):
        pages.read_section("https://x/nope.md")


def test_read_section_accepts_the_url_without_md(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _store(monkeypatch, _snapshot())

    assert pages.read_section("https://x/hooks").url == "https://x/hooks.md"


def test_read_section_rejects_an_offset_past_the_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _store(monkeypatch, _snapshot())

    with pytest.raises(core.QuestionRejected):
        pages.read_section("https://x/hooks.md", "Examples", offset=10_000)


def _reranked(monkeypatch: pytest.MonkeyPatch, rows: list[tuple[str, float]]) -> list:
    from langchain_core.documents import Document

    from src.rag.reranker import RerankResult

    calls: list[Any] = []

    def rerank_pages(question: str, *, limit: int, vendor: str | None = None):
        calls.append((question, limit, vendor))
        return [
            RerankResult(
                Document(
                    page_content="c",
                    metadata={"source": url, "title": f"T {url}", "product": "cursor"},
                ),
                1.0,
                score,
                i,
                i,
            )
            for i, (url, score) in enumerate(rows[:limit], start=1)
        ]

    monkeypatch.setattr(core, "rerank_pages", rerank_pages)
    return calls


def test_find_pages_returns_cards_with_description_and_outline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _reranked(
        monkeypatch, [("https://x/hooks.md", 0.9), ("https://x/b.md", 0.4)]
    )
    _store(monkeypatch, _snapshot(summary="Explains hooks."))

    cards = pages.find_pages("hooks", limit=5, vendor="cursor")

    assert calls == [("hooks", 5, "cursor")]
    assert [(c.rank, c.url, c.score) for c in cards] == [
        (1, "https://x/hooks.md", 0.9),
        (2, "https://x/b.md", 0.4),
    ]
    assert cards[0].title == "T https://x/hooks.md" and cards[0].product == "cursor"
    assert cards[0].description == "Explains hooks."
    assert cards[0].outline[:2] == ["# Hooks", "## Configure hooks (1 subsection)"]
    # A page without a stored snapshot still gets a card.
    assert cards[1].description == "" and cards[1].outline == []


def test_snapshot_pages_reads_the_pages_collection_of_the_configured_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import Mock

    from qdrant_client import QdrantClient

    from src.ingestion.snapshots import SnapshotStore
    from src.models import SourceDocument

    client = QdrantClient(":memory:")
    SnapshotStore(client, "idx_pages").put(
        SourceDocument(
            title="T", content="# A", url="https://x/a.md", vendor="v", product="p"
        ),
        "sha",
        summary="A is.",
    )
    monkeypatch.setattr(core.settings, "qdrant_hybrid_collection", "idx")
    wrapper = Mock(wraps=client)
    monkeypatch.setattr(pages, "get_qdrant_client", lambda: wrapper)

    found = pages._snapshot_pages(["https://x/a.md"])

    assert found["https://x/a.md"].summary == "A is."
    wrapper.close.assert_called_once()


def _passages(monkeypatch: pytest.MonkeyPatch, *urls: str) -> None:
    def search(
        question: str, *, limit: int | None = None, vendor: str | None = None
    ) -> list[core.Passage]:
        return [
            core.Passage(i, "T", "H", url, 0.5, "text")
            for i, url in enumerate(urls, start=1)
        ]

    monkeypatch.setattr(core, "search", search)


def test_search_adds_each_pages_description_with_one_snapshot_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _passages(monkeypatch, "https://x/hooks.md", "https://x/b.md", "https://x/c.md")
    reads: list[list[str]] = []
    by_url = {
        "https://x/hooks.md": _snapshot(summary="Explains hooks."),
        # No gate summary: falls back to the page's first prose sentence.
        "https://x/b.md": _snapshot(url="https://x/b.md"),
    }

    def snapshot_pages(urls: list[str]) -> dict[str, PageSnapshot]:
        reads.append(urls)
        return {u: by_url[u] for u in urls if u in by_url}

    monkeypatch.setattr(pages, "_snapshot_pages", snapshot_pages)

    found = pages.search("hooks", limit=3, vendor="cursor")

    assert reads == [["https://x/hooks.md", "https://x/b.md", "https://x/c.md"]]
    assert [p.description for p in found] == [
        "Explains hooks.",
        "Hooks run shell commands at fixed points.",
        "",
    ]
    assert [(p.rank, p.url, p.score) for p in found] == [
        (1, "https://x/hooks.md", 0.5),
        (2, "https://x/b.md", 0.5),
        (3, "https://x/c.md", 0.5),
    ]


def test_search_survives_an_unavailable_snapshot_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _passages(monkeypatch, "https://x/hooks.md")

    def broken(urls: list[str]) -> dict[str, PageSnapshot]:
        raise RuntimeError("qdrant down")

    monkeypatch.setattr(pages, "_snapshot_pages", broken)

    found = pages.search("hooks")

    assert [p.description for p in found] == [""]


def test_search_without_results_reads_no_snapshots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _passages(monkeypatch)
    monkeypatch.setattr(
        pages, "_snapshot_pages", lambda urls: pytest.fail("no read expected")
    )

    assert pages.search("hooks") == []
