"""Readable change reports, section-level diffs and the feed for programs."""

import json
from pathlib import Path
from typing import Any

import pytest

from src.ingestion import report


def test_section_diff_finds_added_and_removed_headings() -> None:
    old = "# Hooks\n## Setup\ntext\n## Old part\nx\n"
    new = "# Hooks\n## Setup\ntext\n## PermissionRequest hook\ny\n"

    d = report.section_diff(old, new)

    assert d.added == ["PermissionRequest hook"] and d.removed == ["Old part"]
    assert d.significant


def test_small_edit_is_minor() -> None:
    old = "# A\n" + "\n".join(f"line {i}" for i in range(50))
    new = old.replace("line 7", "line seven")

    d = report.section_diff(old, new)

    assert d.added == [] and d.removed == [] and not d.significant


def test_report_lists_every_kind_of_change() -> None:
    r = report.ChangeReport(
        day="2026-09-28",
        added=[report.PageLine("https://x/new.md", "New", "claude-code", "How to X.")],
        removed=["https://x/gone.md"],
        changed=[
            report.ChangedLine(
                "https://x/big.md",
                "Big",
                "cursor",
                "Adds a hook.",
                report.SectionDiff(["S"], [], 12, 40),
            ),
            report.ChangedLine(
                "https://x/tiny.md",
                "Tiny",
                "cursor",
                "",
                report.SectionDiff([], [], 1, 40),
            ),
        ],
        quarantined=[
            report.QuarantineLine(
                "https://x/blog.md",
                "Blog",
                "mcp",
                "A launch post.",
                ["model: marketing"],
            )
        ],
        fetch_failures={"https://x/err.md": "HTTP 500"},
        blocked={},
    )

    text = report.render_report(r)

    assert "Added (1)" in text and "How to X." in text and "https://x/new.md" in text
    assert "Removed (1)" in text and "Changed significantly (1)" in text
    assert "+ S" in text and "Adds a hook." in text
    assert "Minor edits: 1 page" in text
    assert "Quarantined (1)" in text and "A launch post." in text
    assert "HTTP 500" in text


def test_initial_build_reports_totals_only() -> None:
    r = report.ChangeReport(
        day="d",
        added=[report.PageLine(f"u{i}", "t", "p") for i in range(3)],
        removed=[],
        changed=[],
        quarantined=[],
        fetch_failures={},
        blocked={},
        initial_build=True,
    )

    text = report.render_report(r)

    assert "Initial build: 3 pages" in text and "u0" not in text


def test_quarantine_comment_lists_the_pages_and_points_to_the_list() -> None:
    body = report.render_quarantine_issue(
        [
            report.QuarantineLine(
                "https://x/blog.md",
                "Blog",
                "mcp",
                "A launch post.",
                ["model: marketing"],
            )
        ]
    )

    assert "https://x/blog.md" in body and "A launch post." in body
    assert "model: marketing" in body
    assert "issue description" in body


def test_change_summaries_use_the_injected_model() -> None:
    seen: list[str] = []

    def fake(prompt: str) -> str:
        seen.append(prompt)
        return "Adds a hook."

    assert (
        report.summarize_change("Hooks", "a\n", "b\n", summarize=fake) == "Adds a hook."
    )
    assert "-a" in seen[0] and "+b" in seen[0]


# --- the feed for programs (reports/docs-changes/feed.json) ------------------


def _feed_report(**overrides: Any) -> report.ChangeReport:
    fields: dict[str, Any] = {
        "day": "2026-11-14",
        "added": [],
        "removed": [],
        "changed": [],
        "quarantined": [],
        "fetch_failures": {},
        "blocked": {},
    }
    fields.update(overrides)
    return report.ChangeReport(**fields)


def _changed(url: str, diff: report.SectionDiff | None) -> report.ChangedLine:
    return report.ChangedLine(url, "Title", "claude-code", "A model summary.", diff)


def test_feed_day_names_each_page_by_address_and_product() -> None:
    r = _feed_report(
        added=[report.PageLine("https://x/new.md", "New", "codex", "What it is.")],
        removed=["https://x/gone.md", "https://x/unknown.md"],
        changed=[
            _changed("https://x/b.md", report.SectionDiff(["Two", "Three"], [], 9, 40)),
            _changed("https://x/a.md", report.SectionDiff([], ["Old"], 9, 40)),
            _changed("https://x/c.md", None),
        ],
        quarantined=[
            report.QuarantineLine(
                "https://x/blog.md", "Blog", "mcp", "A launch post.", ["marketing"]
            )
        ],
    )

    day = report.feed_day(r, {"https://x/gone.md": "cursor"})

    assert day == {
        "day": "2026-11-14",
        "added": [{"url": "https://x/new.md", "product": "codex"}],
        "removed": [
            {"url": "https://x/gone.md", "product": "cursor"},
            {"url": "https://x/unknown.md", "product": ""},
        ],
        "changed": [
            {"url": "https://x/a.md", "product": "claude-code", "new_sections": []},
            {
                "url": "https://x/b.md",
                "product": "claude-code",
                "new_sections": ["Two", "Three"],
            },
            {"url": "https://x/c.md", "product": "claude-code", "new_sections": []},
        ],
    }


def test_feed_day_holds_no_summary_title_or_page_text() -> None:
    r = _feed_report(
        added=[report.PageLine("https://x/new.md", "New", "codex", "What it is.")],
        removed=["https://x/gone.md"],
        changed=[_changed("https://x/a.md", report.SectionDiff(["S"], [], 9, 40))],
    )

    day = report.feed_day(r, {})

    assert day is not None
    assert set(day) == {"day", "added", "removed", "changed"}
    assert [set(e) for e in day["added"]] == [{"url", "product"}]
    assert [set(e) for e in day["removed"]] == [{"url", "product"}]
    assert [set(e) for e in day["changed"]] == [{"url", "product", "new_sections"}]
    text = json.dumps(day)
    assert "What it is." not in text and "A model summary." not in text
    assert "New" not in text and "Title" not in text


def test_feed_day_leaves_out_a_quarantined_page_that_was_not_indexed() -> None:
    r = _feed_report(
        added=[report.PageLine("https://x/new.md", "New", "codex")],
        quarantined=[
            report.QuarantineLine("https://x/q.md", "Q", "codex", "", ["marketing"])
        ],
    )

    day = report.feed_day(r, {})

    assert day is not None and day["added"] == [
        {"url": "https://x/new.md", "product": "codex"}
    ]


def test_feed_day_names_a_new_heading_once() -> None:
    r = _feed_report(
        changed=[
            _changed("https://x/a.md", report.SectionDiff(["S", "T", "S"], [], 9, 9))
        ]
    )

    day = report.feed_day(r, {})

    assert day is not None and day["changed"][0]["new_sections"] == ["S", "T"]


def test_feed_day_leaves_out_a_page_whose_text_did_not_change() -> None:
    # A new chunker version re-embeds every page with the same text.
    same = _changed("https://x/same.md", report.SectionDiff([], [], 0, 40))
    edited = _changed("https://x/edited.md", report.SectionDiff([], [], 1, 40))

    day = report.feed_day(_feed_report(changed=[same, edited]), {})

    assert day is not None
    assert [e["url"] for e in day["changed"]] == ["https://x/edited.md"]
    assert report.feed_day(_feed_report(changed=[same]), {}) is None


def test_feed_day_is_none_for_an_initial_build() -> None:
    r = _feed_report(
        added=[report.PageLine("https://x/new.md", "New", "codex")],
        initial_build=True,
    )

    assert report.feed_day(r, {}) is None


def test_feed_day_is_none_when_no_page_was_added_removed_or_changed() -> None:
    r = _feed_report(
        quarantined=[report.QuarantineLine("https://x/q.md", "Q", "codex")],
        fetch_failures={"https://x/err.md": "HTTP 500"},
        blocked={"cursor": "llms.txt lists 3 pages, was 90"},
    )

    assert report.feed_day(r, {}) is None


def _day(day: str, **lists: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "day": day,
        "added": lists.get("added", []),
        "removed": lists.get("removed", []),
        "changed": lists.get("changed", []),
    }


def _page(url: str, product: str = "codex") -> dict[str, Any]:
    return {"url": url, "product": product}


def _section(url: str, *sections: str, product: str = "codex") -> dict[str, Any]:
    return {"url": url, "product": product, "new_sections": list(sections)}


def test_merge_feed_starts_a_feed_with_the_day() -> None:
    day = _day("2026-11-14", added=[_page("https://x/a.md")])

    feed = report.merge_feed(None, day, "2026-11-14")

    assert feed == {"checked": "2026-11-14", "days": [day]}


def test_a_day_with_no_change_adds_no_day_but_sets_checked() -> None:
    old = {"checked": "2026-11-14", "days": [_day("2026-11-14", added=[_page("u")])]}

    feed = report.merge_feed(old, None, "2026-11-15")

    assert feed == {"checked": "2026-11-15", "days": old["days"]}


def test_a_second_run_on_one_day_is_merged_into_that_day() -> None:
    first = _day(
        "2026-11-14",
        added=[_page("https://x/a.md"), _page("https://x/b.md", "cursor")],
        removed=[_page("https://x/gone.md", "")],
        changed=[_section("https://x/c.md", "One", "Two")],
    )
    second = _day(
        "2026-11-14",
        added=[_page("https://x/b.md", "claude-code"), _page("https://x/0.md")],
        changed=[
            _section("https://x/c.md", "Two", "Three", product="claude-code"),
            _section("https://x/d.md"),
        ],
    )

    feed = report.merge_feed(
        report.merge_feed(None, first, "2026-11-14"), second, "2026-11-14"
    )

    assert feed == {
        "checked": "2026-11-14",
        "days": [
            _day(
                "2026-11-14",
                added=[
                    _page("https://x/0.md"),
                    _page("https://x/a.md"),
                    _page("https://x/b.md", "claude-code"),
                ],
                removed=[_page("https://x/gone.md", "")],
                changed=[
                    _section(
                        "https://x/c.md", "One", "Two", "Three", product="claude-code"
                    ),
                    _section("https://x/d.md"),
                ],
            )
        ],
    }


def test_the_feed_keeps_the_newest_14_days_newest_first() -> None:
    feed: dict[str, Any] | None = None
    for n in range(1, 21):
        day = f"2026-11-{n:02d}"
        feed = report.merge_feed(feed, _day(day, added=[_page(f"u{n}")]), day)

    assert feed is not None and feed["checked"] == "2026-11-20"
    assert [d["day"] for d in feed["days"]] == [
        f"2026-11-{n:02d}" for n in range(20, 6, -1)
    ]


def test_a_day_older_than_14_days_is_dropped_on_a_quiet_day() -> None:
    old = {
        "checked": "2026-11-10",
        "days": [
            _day("2026-11-10", added=[_page("a")]),
            _day("2026-11-02", added=[_page("b")]),
            _day("2026-10-20", added=[_page("c")]),
        ],
    }

    feed = report.merge_feed(old, None, "2026-11-15")

    assert [d["day"] for d in feed["days"]] == ["2026-11-10", "2026-11-02"]


@pytest.mark.parametrize(
    "old",
    [
        None,
        [],
        "feed",
        {},
        {"checked": "2026-11-13"},
        {"checked": 20261113, "days": []},
        {"checked": "2026-11-13", "days": {}},
        {"checked": "2026-11-13", "days": [], "note": "extra"},
        {"checked": "2026-11-13", "days": ["2026-11-13"]},
        {"checked": "2026-11-13", "days": [{"day": "2026-11-13"}]},
        {"checked": "2026-11-13", "days": [_day("13 November", added=[_page("u")])]},
        {"checked": "2026-11-13", "days": [_day("2026-11-13", added=[{"url": "u"}])]},
        {
            "checked": "2026-11-13",
            "days": [
                _day("2026-11-13", added=[{**_page("u"), "summary": "A summary."}])
            ],
        },
        {
            "checked": "2026-11-13",
            "days": [_day("2026-11-13", changed=[_page("u")])],
        },
        {
            "checked": "2026-11-13",
            "days": [_day("2026-11-13", changed=[{**_page("u"), "new_sections": "S"}])],
        },
        {
            "checked": "2026-11-13",
            "days": [_day("2026-11-13"), _day("2026-11-13")],
        },
    ],
)
def test_an_old_feed_of_another_shape_starts_a_new_one(old: Any) -> None:
    day = _day("2026-11-14", added=[_page("https://x/a.md")])

    assert report.merge_feed(old, day, "2026-11-14") == {
        "checked": "2026-11-14",
        "days": [day],
    }


def test_write_feed_sorts_keys_and_ends_with_a_newline(tmp_path: Path) -> None:
    path = tmp_path / "docs-changes" / "feed.json"
    feed = report.merge_feed(
        None, _day("2026-11-14", changed=[_section("u", "S")]), "2026-11-14"
    )

    report.write_feed(path, feed)

    text = path.read_text()
    assert text.endswith("}\n") and json.loads(text) == feed
    assert text == json.dumps(feed, sort_keys=True, indent=2) + "\n"
    assert text.index('"checked"') < text.index('"days"')
    assert sorted(p.name for p in path.parent.iterdir()) == ["feed.json"]


def test_a_failed_write_keeps_the_old_feed_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "feed.json"
    path.write_text('{"checked": "2026-11-13", "days": []}\n')

    def crash(src: str, dst: str) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(report.os, "replace", crash)
    with pytest.raises(OSError):
        report.write_feed(path, report.merge_feed(None, None, "2026-11-14"))

    assert path.read_text() == '{"checked": "2026-11-13", "days": []}\n'
    assert [p.name for p in tmp_path.iterdir()] == ["feed.json"]


def test_read_feed_gives_none_for_a_missing_or_broken_file(tmp_path: Path) -> None:
    path = tmp_path / "feed.json"
    assert report.read_feed(path) is None
    path.write_text("{not json")
    assert report.read_feed(path) is None
    path.write_bytes(b"\xff\xfe")
    assert report.read_feed(path) is None
    path.write_text('{"checked": "2026-11-13", "days": []}\n')
    assert report.read_feed(path) == {"checked": "2026-11-13", "days": []}


def test_feed_day_cuts_a_long_heading_to_200_characters() -> None:
    long = "x" * 250
    r = _feed_report(
        changed=[_changed("https://x/a.md", report.SectionDiff([long, "S"], [], 9, 9))]
    )

    day = report.feed_day(r, {})

    assert day is not None
    assert day["changed"][0]["new_sections"] == ["x" * 200, "S"]


def test_feed_day_keeps_the_first_50_new_headings_of_a_page() -> None:
    # Comment lines in fenced code count as headings today: one page "gained"
    # about 50 of them on 2026-11-02.
    headings = [f"# comment {n}" for n in range(80)]
    r = _feed_report(
        changed=[_changed("https://x/a.md", report.SectionDiff(headings, [], 90, 90))]
    )

    day = report.feed_day(r, {})

    assert day is not None and day["changed"][0]["new_sections"] == headings[:50]


def test_two_runs_on_one_day_keep_at_most_50_new_headings_of_a_page() -> None:
    first = _day("2026-11-14", changed=[_section("u", *(f"a{n}" for n in range(40)))])
    second = _day("2026-11-14", changed=[_section("u", *(f"b{n}" for n in range(40)))])

    feed = report.merge_feed(
        report.merge_feed(None, first, "2026-11-14"), second, "2026-11-14"
    )

    sections = feed["days"][0]["changed"][0]["new_sections"]
    assert sections == [f"a{n}" for n in range(40)] + [f"b{n}" for n in range(10)]
