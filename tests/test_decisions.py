"""Owner decisions on quarantined pages, ticked in the review issue."""

import re
from datetime import date
from pathlib import Path
from typing import Any

from src.ingestion import decisions as dec
from src.ingestion.manifest import Manifest, ManifestEntry, save_manifest

DAY = date(2026, 10, 17)
URL = "https://x/q.md"
DOCS = {
    URL: ManifestEntry(
        sha256="s1",
        chunks=0,
        title="Security cookbook",
        status="quarantined",
        reason="possible concatenation: 70 chunks",
        summary="A guide for admins.",
    ),
    "https://x/i.md": ManifestEntry(sha256="s", chunks=3, title="Indexed"),
}


def _tick(body: str, action: str, url: str = URL) -> str:
    pattern = rf"- \[ \](.*review:{action} {re.escape(url)} -->)"
    ticked, n = re.subn(pattern, r"- [x]\1", body)
    assert n == 1, f"no {action} box for {url}"
    return ticked


def test_issue_lists_only_pages_waiting_for_a_decision() -> None:
    body = dec.render_issue(DOCS, {})

    assert URL in body and "https://x/i.md" not in body
    assert "A guide for admins." in body
    assert "possible concatenation: 70 chunks" in body
    assert body.count("- [ ] ") == 2


def test_nothing_waiting_renders_an_empty_issue() -> None:
    assert dec.render_issue({"https://x/i.md": DOCS["https://x/i.md"]}, {}) == ""


def test_decided_pages_leave_the_list_until_a_declined_one_changes() -> None:
    allowed = {URL: dec.Decision("allow", "2026-10-17")}
    declined = {URL: dec.Decision("decline", "2026-10-17", "s1")}
    declined_older = {URL: dec.Decision("decline", "2026-10-01", "s0")}

    assert dec.render_issue(DOCS, allowed) == ""
    assert dec.render_issue(DOCS, declined) == ""
    assert URL in dec.render_issue(DOCS, declined_older)


def test_owner_ticking_index_allows_the_page() -> None:
    body = _tick(dec.render_issue(DOCS, {}), "allow")

    outcome = dec.apply_ticks(body, DOCS, {}, actor="owner", owner="Owner", today=DAY)

    assert outcome is not None and outcome.changed
    assert outcome.decisions == {URL: dec.Decision("allow", "2026-10-17")}
    assert outcome.body == ""
    assert URL in outcome.comment


def test_owner_declining_records_the_page_fingerprint() -> None:
    body = _tick(dec.render_issue(DOCS, {}), "decline")

    outcome = dec.apply_ticks(body, DOCS, {}, actor="Owner", owner="Owner", today=DAY)

    assert outcome is not None
    assert outcome.decisions == {URL: dec.Decision("decline", "2026-10-17", "s1")}


def test_ticks_by_anyone_but_the_owner_are_cleared() -> None:
    body = _tick(dec.render_issue(DOCS, {}), "allow")

    outcome = dec.apply_ticks(body, DOCS, {}, actor="someone", owner="Owner", today=DAY)

    assert outcome is not None and not outcome.changed
    assert outcome.decisions == {}
    assert outcome.body == dec.render_issue(DOCS, {})
    assert "@Owner" in outcome.comment


def test_a_tick_for_a_page_not_waiting_is_ignored() -> None:
    body = dec.render_issue(DOCS, {}) + (
        "\n- [x] Index <!-- review:allow https://x/i.md -->\n"
    )

    outcome = dec.apply_ticks(body, DOCS, {}, actor="Owner", owner="Owner", today=DAY)

    assert outcome is not None and not outcome.changed
    assert outcome.decisions == {}


def test_both_boxes_ticked_decide_nothing() -> None:
    body = _tick(_tick(dec.render_issue(DOCS, {}), "allow"), "decline")

    outcome = dec.apply_ticks(body, DOCS, {}, actor="Owner", owner="Owner", today=DAY)

    assert outcome is not None and not outcome.changed
    assert outcome.decisions == {}
    assert URL in outcome.body and "one box" in outcome.comment


def test_an_edit_without_ticks_needs_no_action() -> None:
    body = dec.render_issue(DOCS, {})

    assert (
        dec.apply_ticks(body, DOCS, {}, actor="Owner", owner="Owner", today=DAY) is None
    )


def test_decisions_round_trip_through_json(tmp_path: Path) -> None:
    path = tmp_path / "decisions.json"
    decisions = {
        URL: dec.Decision("decline", "2026-10-17", "s1"),
        "https://x/a.md": dec.Decision("allow", "2026-10-17"),
    }

    dec.save_decisions(decisions, path)

    assert dec.load_decisions(path) == decisions
    assert dec.load_decisions(tmp_path / "missing.json") == {}


def test_cli_records_the_owner_tick_and_writes_the_new_issue(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.chdir(tmp_path)
    save_manifest(Manifest("d", dict(DOCS)), Path("data/manifests/c.json"))
    (tmp_path / "issue.md").write_text(_tick(dec.render_issue(DOCS, {}), "allow"))

    dec.main(
        [
            "--body-file",
            "issue.md",
            "--collection",
            "c",
            "--actor",
            "Owner",
            "--owner",
            "Owner",
            "--out",
            "out",
        ]
    )

    assert dec.load_decisions()[URL].decision == "allow"
    assert (tmp_path / "out/body.md").read_text() == ""
    assert URL in (tmp_path / "out/comment.md").read_text()
