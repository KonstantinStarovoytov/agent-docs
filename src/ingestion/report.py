"""A readable account of what changed in the vendors' documentation.

Also a small feed of the same changes for programs (`feed.json`): addresses,
products and headings only.
"""

import contextlib
import difflib
import json
import os
import re
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, TypeGuard

SIGNIFICANT_SHARE = 0.10
MAX_CHANGE_SUMMARIES = 20
DIFF_CHARS = 6000
FEED_DAYS = 14
# Headings are vendor text (`headings()` already skips fenced code), so the
# feed keeps few and short ones.
FEED_HEADING_CHARS = 200
FEED_HEADINGS_MAX = 50
# The reader (kitden-sdlc's watcher) refuses a feed over 1 MB.
FEED_BYTES_MAX = 900 * 1024
HEADING = re.compile(r"^#{1,3}\s+(.+?)\s*$", re.MULTILINE)
FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})")
FENCE_CLOSE = re.compile(r"^ {0,3}(`{3,}|~{3,})\s*$")

CHANGE_PROMPT = """Here is a diff of one documentation page, "{title}".
In one short plain sentence, say what changed for a reader of this product.

{diff}"""


@dataclass(frozen=True, slots=True)
class SectionDiff:
    added: list[str]
    removed: list[str]
    changed_lines: int
    total_lines: int

    @property
    def significant(self) -> bool:
        return bool(
            self.added
            or self.removed
            or self.changed_lines >= SIGNIFICANT_SHARE * max(self.total_lines, 1)
        )


def headings(markdown: str) -> list[str]:
    """The page's headings, outside fenced code blocks (``` and ~~~).

    A `#` line in a code block is a comment, not a section. A fence closes on
    a line of the same character, at least as long. As in CommonMark, a fence
    that is never closed runs to the end of the page.
    """
    outside: list[str] = []
    fence = ""
    for line in markdown.splitlines():
        if fence:
            close = FENCE_CLOSE.match(line)
            if close and close[1][0] == fence[0] and len(close[1]) >= len(fence):
                fence = ""
            continue
        opening = FENCE_OPEN.match(line)
        if opening:
            fence = opening[1]
        else:
            outside.append(line)
    return HEADING.findall("\n".join(outside))


def section_diff(old: str, new: str) -> SectionDiff:
    before, after = headings(old), headings(new)
    old_lines, new_lines = old.splitlines(), new.splitlines()
    opcodes = difflib.SequenceMatcher(
        None, old_lines, new_lines, autojunk=False
    ).get_opcodes()
    changed = sum(
        (i2 - i1) + (j2 - j1) for tag, i1, i2, j1, j2 in opcodes if tag != "equal"
    )
    return SectionDiff(
        added=[h for h in after if h not in before],
        removed=[h for h in before if h not in after],
        changed_lines=changed,
        total_lines=max(len(old_lines), len(new_lines)),
    )


def _model_summary(prompt: str) -> str:
    from src.rag.llm import chat_model

    return str(chat_model().invoke(prompt).content).strip()


def summarize_change(
    title: str, old: str, new: str, summarize: Callable[[str], str] | None = None
) -> str:
    diff = "\n".join(
        difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=1)
    )[:DIFF_CHARS]
    return (summarize or _model_summary)(CHANGE_PROMPT.format(title=title, diff=diff))


@dataclass
class PageLine:
    url: str
    title: str
    product: str
    summary: str = ""


@dataclass
class ChangedLine(PageLine):
    diff: SectionDiff | None = None


@dataclass
class QuarantineLine(PageLine):
    reasons: list[str] = field(default_factory=list)


@dataclass
class ChangeReport:
    day: str
    added: list[PageLine]
    removed: list[str]
    changed: list[ChangedLine]
    quarantined: list[QuarantineLine]
    fetch_failures: dict[str, str]
    blocked: dict[str, str]
    initial_build: bool = False

    def empty(self) -> bool:
        return not (
            self.added
            or self.removed
            or self.changed
            or self.quarantined
            or self.fetch_failures
            or self.blocked
        )


def _page(line: PageLine) -> str:
    text = f"- **{line.product} › {line.title}** — <{line.url}>"
    return f"{text}\n  {line.summary}" if line.summary else text


def render_report(r: ChangeReport) -> str:
    out = [f"# Documentation changes, {r.day}", ""]
    if r.initial_build:
        out += [
            f"Initial build: {len(r.added)} pages indexed, "
            f"{len(r.quarantined)} quarantined.",
            "",
        ]
    else:
        if r.added:
            out += [
                f"## Added ({len(r.added)}) — worth reading",
                *map(_page, r.added),
                "",
            ]
        if r.removed:
            out += [
                f"## Removed ({len(r.removed)})",
                *(f"- <{u}>" for u in r.removed),
                "",
            ]
        major = [c for c in r.changed if c.diff and c.diff.significant]
        minor = len(r.changed) - len(major)
        if major:
            out.append(f"## Changed significantly ({len(major)})")
            for c in major:
                assert c.diff is not None
                out.append(_page(c))
                sections = [f"+ {s}" for s in c.diff.added] + [
                    f"− {s}" for s in c.diff.removed
                ]
                detail = ", ".join(sections + [f"{c.diff.changed_lines} lines"])
                out.append(f"  _{detail}_")
            out.append("")
        if minor:
            out += [f"Minor edits: {minor} page{'s' if minor != 1 else ''}.", ""]
    if r.quarantined:
        out.append(f"## Quarantined ({len(r.quarantined)}) — needs a decision")
        for q in r.quarantined:
            out += [_page(q), f"  Flagged: {'; '.join(q.reasons)}"]
        out.append("")
    if r.blocked:
        out += [
            "## Removals blocked",
            *(f"- {p}: {why}" for p, why in r.blocked.items()),
            "",
        ]
    if r.fetch_failures:
        out += [
            "## Fetch failures (an indexed copy, if any, is kept)",
            *(f"- <{u}>: {why}" for u, why in r.fetch_failures.items()),
            "",
        ]
    return "\n".join(out).rstrip() + "\n"


def render_quarantine_issue(lines: list[QuarantineLine]) -> str:
    out = [
        "This run did not index these pages. Decide each one with the boxes in "
        "the issue description.",
        "",
    ]
    for q in lines:
        out += [
            f"- <{q.url}>",
            f"  **What it is:** {q.summary}",
            f"  **Why flagged:** {'; '.join(q.reasons)}",
        ]
    return "\n".join(out) + "\n"


# --- the feed for programs ---------------------------------------------------
#
# {"checked": "<day of the last run>",
#  "days": [{"day": "<day>",
#            "added":   [{"url", "product"}],
#            "removed": [{"url", "product"}],
#            "changed": [{"url", "product", "new_sections": [<headings>]}]}]}
#
# Days newest first, the last FEED_DAYS days only; each list sorted by address.
# No summary (a model wrote it), no title and no page text.

_PAGE_KEYS = frozenset({"url", "product"})
_CHANGED_KEYS = _PAGE_KEYS | {"new_sections"}
_DAY_KEYS = frozenset({"day", "added", "removed", "changed"})
_LISTS = ("added", "removed", "changed")


def _unique(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _new_sections(headings: Iterable[str]) -> list[str]:
    """Each heading once, cut to FEED_HEADING_CHARS, the first FEED_HEADINGS_MAX."""
    return _unique(h[:FEED_HEADING_CHARS] for h in headings)[:FEED_HEADINGS_MAX]


def _by_url(entries: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """One entry per address, the later one winning, sorted by address."""
    return sorted({e["url"]: e for e in entries}.values(), key=lambda e: e["url"])


def feed_day(report: ChangeReport, product_of: dict[str, str]) -> dict[str, Any] | None:
    """One day of the feed, or None when no page was added, removed or changed.

    `product_of` gives the product of a removed page (the report has its
    address only). A changed page whose text is the same as before (every page,
    after a new chunker version) is not a change for a reader and is left out.
    """
    if report.initial_build:
        return None
    changed = [c for c in report.changed if c.diff is None or c.diff.changed_lines]
    if not (report.added or report.removed or changed):
        return None
    return {
        "day": report.day,
        "added": _by_url({"url": p.url, "product": p.product} for p in report.added),
        "removed": _by_url(
            {"url": url, "product": product_of.get(url, "")} for url in report.removed
        ),
        "changed": _by_url(
            {
                "url": c.url,
                "product": c.product,
                "new_sections": _new_sections(c.diff.added if c.diff else []),
            }
            for c in changed
        ),
    }


def _is_day(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _is_entry(value: object, keys: frozenset[str]) -> bool:
    if not isinstance(value, dict) or set(value) != keys:
        return False
    if not (isinstance(value["url"], str) and isinstance(value["product"], str)):
        return False
    sections = value.get("new_sections", [])
    return isinstance(sections, list) and all(isinstance(s, str) for s in sections)


def is_feed(value: object) -> TypeGuard[dict[str, Any]]:
    """Whether `value` has exactly the feed's shape, with nothing else in it."""
    if not isinstance(value, dict) or set(value) != {"checked", "days"}:
        return False
    days = value["days"]
    if not (_is_day(value["checked"]) and isinstance(days, list)):
        return False
    seen: set[str] = set()
    for day in days:
        if not (isinstance(day, dict) and set(day) == _DAY_KEYS):
            return False
        if not _is_day(day["day"]) or day["day"] in seen:
            return False
        seen.add(day["day"])
        for name in _LISTS:
            keys = _CHANGED_KEYS if name == "changed" else _PAGE_KEYS
            entries = day[name]
            if not isinstance(entries, list):
                return False
            if not all(_is_entry(e, keys) for e in entries):
                return False
    return True


def _merge_day(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Two runs of one day: the pages of both, the later entry winning."""
    sections = {e["url"]: e["new_sections"] for e in old["changed"]}
    changed = [
        {
            **e,
            "new_sections": _new_sections(
                [*sections.get(e["url"], []), *e["new_sections"]]
            ),
        }
        for e in new["changed"]
    ]
    return {
        "day": new["day"],
        "added": _by_url([*old["added"], *new["added"]]),
        "removed": _by_url([*old["removed"], *new["removed"]]),
        "changed": _by_url([*old["changed"], *changed]),
    }


def merge_feed(
    old: object, day: dict[str, Any] | None, checked: str, keep: int = FEED_DAYS
) -> dict[str, Any]:
    """The feed after a run that reached its end on `checked`.

    `day` is that run's `feed_day`, None when nothing changed. An old feed of
    another shape (or none) starts a new one. Only days in the `keep` days up
    to `checked` stay, newest first.
    """
    days: dict[str, dict[str, Any]] = {}
    if is_feed(old):
        days = {d["day"]: d for d in old["days"]}
    if day is not None:
        before = days.get(day["day"])
        days[day["day"]] = day if before is None else _merge_day(before, day)
    today = date.fromisoformat(checked)
    recent = [d for d in days if 0 <= (today - date.fromisoformat(d)).days < keep]
    newest_first = [days[d] for d in sorted(recent, reverse=True)]
    feed: dict[str, Any] = {"checked": checked, "days": newest_first}
    while newest_first and len(feed_text(feed).encode()) > FEED_BYTES_MAX:
        newest_first.pop()  # the oldest day
    return feed


def feed_text(feed: dict[str, Any]) -> str:
    """The feed as written: sorted keys and a last newline keep the diff small."""
    return json.dumps(feed, sort_keys=True, indent=2) + "\n"


def read_feed(path: Path) -> object | None:
    """The feed as last written, or None when there is none or it is not JSON."""
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except OSError, UnicodeDecodeError, ValueError:
        return None
    return value


def write_feed(path: Path, feed: dict[str, Any]) -> None:
    """Write the whole file or nothing: a temporary file in the same folder,
    then a rename."""
    text = feed_text(feed)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        os.chmod(temp, 0o644)
        os.replace(temp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temp)
        raise
