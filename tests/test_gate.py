"""The page gate flags junk before it reaches the index."""

from src.ingestion import gate
from src.models import SourceDocument


def _doc(
    url: str, content: str = "# Title\nplain english documentation text"
) -> SourceDocument:
    return SourceDocument(title="T", content=content, url=url, vendor="v", product="p")


def _keep(_: str) -> gate.PageReview:
    return gate.PageReview(keep=True, category="documentation", summary="How to use X.")


def test_clean_page_is_kept_with_a_summary() -> None:
    verdict = gate.gate_page(_doc("https://x/docs/a.md"), 10, 10.0, {}, review=_keep)

    assert verdict.keep and verdict.reasons == [] and verdict.summary == "How to use X."


def test_oversized_page_is_flagged() -> None:
    assert gate.heuristic_flags(_doc("https://x/a.md"), 151, 10.0, {}) == [
        "possible concatenation: 151 chunks"
    ]
    assert gate.heuristic_flags(_doc("https://x/a.md"), 60, 10.0, {}) == [
        "possible concatenation: 60 chunks"
    ]


def test_translation_is_flagged_by_path_or_script() -> None:
    assert (
        "translation"
        in gate.heuristic_flags(_doc("https://x/ja/docs/a.md"), 1, 10.0, {})[0]
    )
    cyr = _doc("https://x/docs/a.md", "# Заголовок\nтекст документации на русском")
    assert "translation" in gate.heuristic_flags(cyr, 1, 10.0, {})[0]
    assert gate.heuristic_flags(_doc("https://x/docs/en/a.md"), 1, 10.0, {}) == []


def test_duplicate_of_an_indexed_page_is_flagged() -> None:
    text = " ".join(f"word{i}" for i in range(200))
    flags = gate.heuristic_flags(
        _doc("https://x/b.md", text), 1, 10.0, {"https://x/a.md": text}
    )

    assert flags == ["duplicate of https://x/a.md"]


def test_non_doc_path_keywords_are_flagged() -> None:
    for path in ("release-notes.md", "blog/post.md", "terms.md", "llms-full.md"):
        assert gate.heuristic_flags(_doc(f"https://x/{path}"), 1, 10.0, {}), path


def test_model_quarantine_is_respected_and_reasons_combine() -> None:
    def junk(_: str) -> gate.PageReview:
        return gate.PageReview(
            keep=False, category="marketing", summary="A launch post."
        )

    verdict = gate.gate_page(_doc("https://x/blog/launch.md"), 1, 10.0, {}, review=junk)

    assert not verdict.keep
    assert verdict.reasons == ["probably not documentation: blog", "model: marketing"]
    assert verdict.summary == "A launch post."


def test_review_prompt_contains_path_title_and_head_only() -> None:
    seen: list[str] = []

    def capture(prompt: str) -> gate.PageReview:
        seen.append(prompt)
        return gate.PageReview(keep=True, category="documentation", summary="s")

    gate.review_page(_doc("https://x/docs/a.md", "# T\n" + "x" * 5000), review=capture)

    assert "https://x/docs/a.md" in seen[0] and len(seen[0]) < 2500
