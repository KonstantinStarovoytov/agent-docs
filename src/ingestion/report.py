"""A readable account of what changed in the vendors' documentation."""

import difflib
import re
from collections.abc import Callable
from dataclasses import dataclass, field

SIGNIFICANT_SHARE = 0.10
MAX_CHANGE_SUMMARIES = 20
DIFF_CHARS = 6000
HEADING = re.compile(r"^#{1,3}\s+(.+?)\s*$", re.MULTILINE)

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


def section_diff(old: str, new: str) -> SectionDiff:
    before, after = HEADING.findall(old), HEADING.findall(new)
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
            "## Fetch failures (old version kept)",
            *(f"- <{u}>: {why}" for u, why in r.fetch_failures.items()),
            "",
        ]
    return "\n".join(out).rstrip() + "\n"


def render_quarantine_issue(lines: list[QuarantineLine]) -> str:
    out = [
        "These new pages were not indexed. For each: add a pattern to `exclude` "
        "in `src/ingestion/sources.py` to drop it for good, or add the URL to "
        "`allow` to index it.",
        "",
    ]
    for q in lines:
        out += [
            f"- <{q.url}>",
            f"  **What it is:** {q.summary}",
            f"  **Why flagged:** {'; '.join(q.reasons)}",
        ]
    return "\n".join(out) + "\n"
