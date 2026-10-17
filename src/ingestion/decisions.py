"""Owner decisions on quarantined pages, ticked in the review issue.

The "Pages waiting for review" issue lists every quarantined page that waits
for the owner, with two boxes each. Ticking one runs the Page review workflow,
which records the decision here and rewrites the list. "Index" puts the URL on
the allow list (`allowed_urls` in src/reindex.py reads this file as well as
`allow` in sources.py), so the next reindex indexes it. "Decline" keeps it out
until its content changes; then it comes back to the list instead of going
through the gate again.
"""

import argparse
import json
import re
import sys
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

from src.ingestion.manifest import ManifestEntry, load_manifest, manifest_path

DECISIONS_PATH = Path("data/page-decisions.json")
INTRO = (
    "Pages the daily reindex did not index. Tick one box per page: **Index** "
    "indexes it on the next reindex; **Decline** keeps it out until the page "
    "changes, then it comes back here. Only the repository owner's ticks count."
)
BOXES = (("allow", "Index"), ("decline", "Decline"))
TICK = re.compile(r"^\s*[-*] \[[xX]\] .*<!-- review:(allow|decline) (\S+) -->\s*$")
Action = Literal["allow", "decline"]


@dataclass(frozen=True, slots=True)
class Decision:
    decision: Action
    date: str
    sha256: str = ""  # the page's fingerprint when it was declined


@dataclass(frozen=True, slots=True)
class Outcome:
    decisions: dict[str, Decision]
    body: str  # the issue's new description; empty when nothing waits
    comment: str
    changed: bool


def load_decisions(path: Path = DECISIONS_PATH) -> dict[str, Decision]:
    if not path.exists():
        return {}
    return {url: Decision(**raw) for url, raw in json.loads(path.read_text()).items()}


def save_decisions(decisions: dict[str, Decision], path: Path = DECISIONS_PATH) -> None:
    payload = {url: asdict(d) for url, d in sorted(decisions.items())}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def is_waiting(entry: ManifestEntry, decision: Decision | None) -> bool:
    if entry.status != "quarantined":
        return False
    if decision is None:
        return True
    # A declined page waits again once its content is no longer what was declined.
    return decision.decision == "decline" and decision.sha256 != entry.sha256


def render_issue(
    documents: Mapping[str, ManifestEntry], decisions: Mapping[str, Decision]
) -> str:
    waiting = [
        (url, entry)
        for url, entry in sorted(documents.items())
        if is_waiting(entry, decisions.get(url))
    ]
    if not waiting:
        return ""
    out = [INTRO, ""]
    for url, entry in waiting:
        out += [
            f"### {entry.title or url}",
            f"<{url}>",
            f"**What it is:** {entry.summary or 'no description'}",
            f"**Why flagged:** {entry.reason or 'not recorded'}",
            "",
            *(f"- [ ] {label} <!-- review:{a} {url} -->" for a, label in BOXES),
            "",
        ]
    return "\n".join(out)


def apply_ticks(
    body: str,
    documents: Mapping[str, ManifestEntry],
    decisions: Mapping[str, Decision],
    *,
    actor: str,
    owner: str,
    today: date,
) -> Outcome | None:
    """Record the owner's ticks; None when the edit ticked nothing."""
    ticked: dict[str, set[Action]] = {}
    for line in body.splitlines():
        if m := TICK.match(line):
            action: Action = "allow" if m.group(1) == "allow" else "decline"
            ticked.setdefault(m.group(2), set()).add(action)
    if not ticked:
        return None
    if actor.lower() != owner.lower():
        return Outcome(
            dict(decisions),
            render_issue(documents, decisions),
            f"Only @{owner} can decide; the boxes @{actor} ticked were cleared.",
            changed=False,
        )
    updated = dict(decisions)
    notes: list[str] = []
    for url, actions in sorted(ticked.items()):
        entry = documents.get(url)
        if entry is None or not is_waiting(entry, decisions.get(url)):
            continue  # not in the list any more; the rewrite drops the tick
        if len(actions) > 1:
            notes.append(f"Both boxes ticked for <{url}>; tick one box.")
        elif "allow" in actions:
            updated[url] = Decision("allow", today.isoformat())
            notes.append(f"Index: <{url}>. The next reindex indexes it.")
        else:
            updated[url] = Decision("decline", today.isoformat(), entry.sha256)
            notes.append(f"Decline: <{url}>. It comes back here if the page changes.")
    return Outcome(
        updated,
        render_issue(documents, updated),
        "\n".join(notes),
        changed=updated != dict(decisions),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--body-file", type=Path, required=True)
    parser.add_argument("--collection", required=True, help="Production index.")
    parser.add_argument("--actor", required=True, help="Who edited the issue.")
    parser.add_argument("--owner", required=True, help="The repository owner.")
    parser.add_argument(
        "--out", type=Path, required=True, help="Where body.md and comment.md go."
    )
    args = parser.parse_args(argv)

    manifest = load_manifest(manifest_path(args.collection))
    outcome = apply_ticks(
        args.body_file.read_text(),
        manifest.documents,
        load_decisions(),
        actor=args.actor,
        owner=args.owner,
        today=datetime.now(UTC).date(),
    )
    if outcome is None:
        print("no ticks")
        return 0
    if outcome.changed:
        save_decisions(outcome.decisions)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "body.md").write_text(outcome.body)
    if outcome.comment:
        (args.out / "comment.md").write_text(outcome.comment + "\n")
    print(outcome.comment or "ticks cleared")
    return 0


if __name__ == "__main__":
    sys.exit(main())
