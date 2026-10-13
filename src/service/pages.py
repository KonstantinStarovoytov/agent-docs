"""Page descriptions, page cards and section reads, for agents that read sections.

`search` is `core.search` plus each page's one-sentence description, read from
the page snapshots in one Qdrant call. `find_pages` ranks pages exactly as
search does (one hybrid search, one Cohere call, one result per page) and
describes each page: the page gate's one-sentence summary and its heading
outline. `read_section` returns a section of the stored page markdown
(`<collection>_pages`, written by src/reindex.py), with no model call at all.
MCP and REST both call these functions.
"""

import logging
import re
from dataclasses import dataclass, replace

from src.config import settings
from src.ingestion.clean import clean_markdown
from src.ingestion.ingest import get_qdrant_client
from src.ingestion.snapshots import PageSnapshot, SnapshotStore, snapshot_collection
from src.service import core

logger = logging.getLogger(__name__)

OUTLINE_DEPTH = 2
OUTLINE_CAP = 40
ERROR_LEVELS = 3
DESCRIPTION_CHARS = 200
SECTION_CHARS = 8000
ERROR_HEADINGS = 40

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_LINK_RE = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s")
_COUNT_RE = re.compile(r"\s*\(\d+ subsections?\)\s*$")


class PageNotFound(core.QuestionRejected):
    """The URL is not a page of the index."""


class SectionNotFound(core.QuestionRejected):
    """No single heading of the page matches."""


@dataclass(frozen=True, slots=True)
class Heading:
    level: int
    text: str
    path: str
    line: int


@dataclass(frozen=True, slots=True)
class Section:
    path: str
    text: str


@dataclass(frozen=True, slots=True)
class PageCard:
    rank: int
    title: str
    url: str
    product: str
    score: float
    description: str
    outline: list[str]


@dataclass(frozen=True, slots=True)
class SectionRead:
    url: str
    title: str
    description: str
    outline: list[str]
    heading: str | None
    text: str
    offset: int
    next_offset: int | None
    total_chars: int


def _lines(markdown: str) -> list[str]:
    return clean_markdown(markdown).split("\n")


def headings(markdown: str) -> list[Heading]:
    """ATX headings of the cleaned page, outside code fences, in order."""
    found: list[Heading] = []
    stack: list[tuple[int, str]] = []
    fence: str | None = None
    for number, line in enumerate(_lines(markdown)):
        opener = _FENCE_RE.match(line)
        if opener:
            if fence is None:
                fence = opener.group(1)
            elif opener.group(1) == fence:
                fence = None
            continue
        if fence is not None:
            continue
        match = _HEADING_RE.match(line)
        if not match:
            continue
        level, text = len(match.group(1)), match.group(2).strip()
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, text))
        found.append(Heading(level, text, " > ".join(t for _, t in stack), number))
    return found


def _marked(heading: Heading) -> str:
    return f"{'#' * heading.level} {heading.text}"


def outline(markdown: str, *, depth: int = OUTLINE_DEPTH) -> list[str]:
    """The page's top-level sections as `## Text`, at most OUTLINE_CAP lines.

    Depth 2 lists h1 and h2, each h2 followed by its subsection count (the h2's
    text includes its subsections, so reading it covers them); depth 3 also
    lists the h3s. Past the cap, a final `+N more sections` line.
    """
    found = headings(markdown)
    items: list[str] = []
    for index, heading in enumerate(found):
        if heading.level > depth:
            continue
        line = _marked(heading)
        if heading.level == 2 and depth < 3:
            below = []
            for later in found[index + 1 :]:
                if later.level <= heading.level:
                    break
                below.append(later.level)
            count = below.count(min(below)) if below else 0
            if count:
                line += f" ({count} subsection{'s' if count != 1 else ''})"
        items.append(line)
    if len(items) > OUTLINE_CAP:
        return [*items[:OUTLINE_CAP], f"+{len(items) - OUTLINE_CAP} more sections"]
    return items


def description(summary: str, markdown: str) -> str:
    """The gate's summary, else the page's first prose sentence (≤200 chars)."""
    if summary.strip():
        return summary.strip()
    paragraph: list[str] = []
    fence = False
    for line in _lines(markdown):
        stripped = line.strip()
        if _FENCE_RE.match(line):
            fence = not fence
            continue
        prose = (
            stripped
            and not fence
            and not stripped.startswith(("#", "|", ">", "<", "!", "- ", "* ", "---"))
        )
        if prose:
            paragraph.append(stripped)
        elif paragraph:
            break
    text = _LINK_RE.sub(r"\1", " ".join(paragraph))
    text = _SENTENCE_END_RE.split(text, maxsplit=1)[0].strip()
    if len(text) > DESCRIPTION_CHARS:
        text = text[: DESCRIPTION_CHARS - 1].rsplit(" ", 1)[0] + "…"
    return text


def _norm(text: str) -> str:
    """Comparable heading text; an outline line's `(N subsections)` is dropped."""
    return " ".join(_COUNT_RE.sub("", text).lstrip("#").split()).casefold()


def _listing(items: list[str]) -> str:
    shown = items[:ERROR_HEADINGS]
    more = len(items) - len(shown)
    return "; ".join(shown) + (f"; +{more} more" if more > 0 else "")


def _match(all_headings: list[Heading], query: str) -> Heading:
    wanted = _norm(query)
    if " > " in query:
        parts = [_norm(part) for part in query.split(" > ")]
        found = [
            h
            for h in all_headings
            if [_norm(p) for p in h.path.split(" > ")][-len(parts) :] == parts
        ]
    else:
        found = [h for h in all_headings if _norm(h.text) == wanted]
        if not found:
            found = [h for h in all_headings if wanted in _norm(h.text)]
    if len(found) == 1:
        return found[0]
    if found:
        raise SectionNotFound(
            f"Heading {query!r} matches {len(found)} sections; pass one as a "
            f"path ('Parent > Heading'): {_listing([h.path for h in found])}"
        )
    available = [_marked(h) for h in all_headings if h.level <= ERROR_LEVELS]
    raise SectionNotFound(
        f"No heading matches {query!r}. Headings on this page: {_listing(available)}"
    )


def find_section(markdown: str, heading: str) -> Section:
    """From the matched heading to the next heading of the same or higher level.

    Exact heading text (case-insensitive, leading `#`s ignored) first, then a
    unique substring match; `Parent > Heading` picks one of equal headings.
    """
    all_headings = headings(markdown)
    target = _match(all_headings, heading)
    end: int | None = None
    for h in all_headings:
        if h.line > target.line and h.level <= target.level:
            end = h.line
            break
    lines = _lines(markdown)[target.line : end]
    return Section(path=target.path, text="\n".join(lines).strip())


def slice_text(
    text: str, offset: int, cap: int = SECTION_CHARS
) -> tuple[str, int | None]:
    """`cap` characters from `offset`, cut on a line break when one is near.

    Returns the slice and where the next call should start (None at the end).
    """
    rest = text[offset:]
    if len(rest) <= cap:
        return rest, None
    window = rest[:cap]
    cut = window.rfind("\n")
    if cut > cap // 2:
        return window[:cut], offset + cut + 1
    return window, offset + cap


def _snapshot_pages(urls: list[str]) -> dict[str, PageSnapshot]:
    client = get_qdrant_client()
    try:
        store = SnapshotStore(
            client, snapshot_collection(settings.qdrant_hybrid_collection), create=False
        )
        return store.pages(urls)
    finally:
        client.close()


def search(
    question: str, *, limit: int | None = None, vendor: str | None = None
) -> list[core.Passage]:
    """`core.search` with each passage's page description attached.

    One snapshot read covers every result page. A snapshot store that cannot be
    read costs the descriptions, not the search.
    """
    passages = core.search(question, limit=limit, vendor=vendor)
    urls = list(dict.fromkeys(p.url for p in passages if p.url))
    if not urls:
        return passages
    try:
        stored = _snapshot_pages(urls)
    except Exception:
        logger.warning("page snapshots unavailable; no descriptions", exc_info=True)
        return passages
    return [
        replace(p, description=description(page.summary, page.markdown))
        if (page := stored.get(p.url))
        else p
        for p in passages
    ]


def find_pages(
    question: str, *, limit: int = 5, vendor: str | None = None
) -> list[PageCard]:
    best = core.rerank_pages(question, limit=limit, vendor=vendor)
    urls = [str(r.document.metadata.get("source", "")) for r in best]
    stored = _snapshot_pages([url for url in urls if url]) if urls else {}
    cards = []
    for rank, (result, url) in enumerate(zip(best, urls), start=1):
        metadata = result.document.metadata
        page = stored.get(url)
        cards.append(
            PageCard(
                rank=rank,
                title=str(metadata.get("title") or (page.title if page else "")),
                url=url,
                product=str(metadata.get("product") or (page.product if page else "")),
                score=result.rerank_score,
                description=description(page.summary, page.markdown) if page else "",
                outline=outline(page.markdown) if page else [],
            )
        )
    return cards


def _page(url: str) -> PageSnapshot:
    url = url.strip()
    candidates = [url] if url.endswith(".md") else [url, url.rstrip("/") + ".md"]
    stored = _snapshot_pages(candidates)
    for candidate in candidates:
        if candidate in stored:
            return stored[candidate]
    raise PageNotFound(
        f"{url} is not a page of the index; use a url returned by search_docs."
    )


def read_section(
    url: str,
    heading: str | None = None,
    offset: int = 0,
    outline_depth: int = OUTLINE_DEPTH,
) -> SectionRead:
    if offset < 0:
        raise core.QuestionRejected("offset must not be negative")
    if outline_depth not in (2, 3):
        raise core.QuestionRejected("outline_depth must be 2 or 3")
    page = _page(url)
    about = description(page.summary, page.markdown)
    if heading is None or not heading.strip():
        return SectionRead(
            url=page.url,
            title=page.title,
            description=about,
            outline=outline(page.markdown, depth=outline_depth),
            heading=None,
            text="",
            offset=0,
            next_offset=None,
            total_chars=0,
        )
    section = find_section(page.markdown, heading)
    if offset and offset >= len(section.text):
        raise core.QuestionRejected(
            f"offset {offset} is past the end of the section "
            f"({len(section.text)} characters)"
        )
    text, next_offset = slice_text(section.text, offset)
    return SectionRead(
        url=page.url,
        title=page.title,
        description=about,
        outline=[],
        heading=section.path,
        text=text,
        offset=offset,
        next_offset=next_offset,
        total_chars=len(section.text),
    )
