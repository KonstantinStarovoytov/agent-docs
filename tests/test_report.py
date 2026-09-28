"""Readable change reports and section-level diffs."""

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


def test_quarantine_issue_is_short_and_actionable() -> None:
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
    assert "exclude" in body and "allow" in body


def test_change_summaries_use_the_injected_model() -> None:
    seen: list[str] = []

    def fake(prompt: str) -> str:
        seen.append(prompt)
        return "Adds a hook."

    assert (
        report.summarize_change("Hooks", "a\n", "b\n", summarize=fake) == "Adds a hook."
    )
    assert "-a" in seen[0] and "+b" in seen[0]
