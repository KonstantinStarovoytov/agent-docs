"""Decide whether a newly discovered page belongs in the index.

Runs only on pages the manifest has never seen, so it costs one short LLM
call per new page. Any flag, from the free checks or the model, sends the
page to quarantine for the owner to decide.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from src.models import SourceDocument

MAX_CHUNKS = 150
MEDIAN_FACTOR = 5
NON_LATIN_SHARE = 0.30
DUPLICATE_OVERLAP = 0.80
SHINGLE = 5
HEAD_CHARS = 1500
LOCALES = {
    "cn",
    "de",
    "es",
    "fr",
    "id",
    "it",
    "ja",
    "jp",
    "ko",
    "nl",
    "pl",
    "pt",
    "pt-br",
    "ru",
    "tr",
    "uk",
    "vi",
    "zh",
    "zh-cn",
    "zh-tw",
}
NON_DOC = re.compile(
    r"(?<![a-z])(changelog|release-notes|llms|full|blog|terms|privacy|proposal)(?![a-z])"
)

PROMPT = """You review one page found in a software vendor's documentation index.
Decide whether it is product documentation a coding agent would use to answer
how-to, configuration or reference questions. Quarantine changelogs, release
notes, marketing, legal text, community governance, translations and pages
that merely aggregate other pages.

Write `summary` as one short plain sentence saying what the page is, for a
human deciding whether to keep it.

URL: {url}
Title: {title}
Beginning of the page:
{head}"""


class PageReview(BaseModel):
    keep: bool
    category: Literal[
        "documentation",
        "reference",
        "changelog",
        "marketing",
        "legal",
        "community",
        "translation",
        "duplicate",
        "other",
    ]
    summary: str = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class GateVerdict:
    keep: bool
    reasons: list[str]
    summary: str


def _shingles(text: str) -> set[tuple[str, ...]]:
    words = text.lower().split()
    return {tuple(words[i : i + SHINGLE]) for i in range(len(words) - SHINGLE + 1)}


def heuristic_flags(
    document: SourceDocument,
    chunks: int,
    vendor_median: float,
    indexed_texts: dict[str, str],
) -> list[str]:
    path = urlsplit(document.url).path
    flags: list[str] = []
    if chunks > MAX_CHUNKS or chunks > MEDIAN_FACTOR * vendor_median:
        flags.append(f"possible concatenation: {chunks} chunks")
    segments = [s for s in path.lower().split("/") if s]
    letters = [c for c in document.content if c.isalpha()]
    non_latin = sum(1 for c in letters if not c.isascii())
    if any(s in LOCALES for s in segments) or (
        letters and non_latin / len(letters) > NON_LATIN_SHARE
    ):
        flags.append("translation")
    if m := NON_DOC.search(path.lower()):
        flags.append(f"probably not documentation: {m.group(1)}")
    mine = _shingles(document.content)
    if mine:
        for url, text in indexed_texts.items():
            theirs = _shingles(text)
            if theirs and len(mine & theirs) / len(mine | theirs) >= DUPLICATE_OVERLAP:
                flags.append(f"duplicate of {url}")
                break
    return flags


def _model_review(prompt: str) -> PageReview:
    from src.rag.llm import chat_model

    result = chat_model().with_structured_output(PageReview).invoke(prompt)
    return (
        result if isinstance(result, PageReview) else PageReview.model_validate(result)
    )


def review_page(
    document: SourceDocument, review: Callable[[str], PageReview] | None = None
) -> PageReview:
    prompt = PROMPT.format(
        url=document.url, title=document.title, head=document.content[:HEAD_CHARS]
    )
    return (review or _model_review)(prompt)


def gate_page(
    document: SourceDocument,
    chunks: int,
    vendor_median: float,
    indexed_texts: dict[str, str],
    review: Callable[[str], PageReview] | None = None,
) -> GateVerdict:
    flags = heuristic_flags(document, chunks, vendor_median, indexed_texts)
    verdict = review_page(document, review)
    if not verdict.keep:
        flags.append(f"model: {verdict.category}")
    return GateVerdict(keep=not flags, reasons=flags, summary=verdict.summary)
