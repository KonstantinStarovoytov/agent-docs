"""Chunking: cleaning, section splitting, and the embedded contextual prefix."""

from src.ingestion.chunker import chunk_document
from src.models import SourceDocument


def _doc(content: str, **overrides: str) -> SourceDocument:
    base = dict(
        title="Hooks reference",
        content=content,
        url="https://code.claude.com/docs/en/hooks.md",
        vendor="anthropic",
        product="claude-code",
    )
    base.update(overrides)
    return SourceDocument(**base)  # type: ignore[arg-type]


def test_boilerplate_is_cleaned_before_splitting() -> None:
    doc = _doc(
        "> ## Documentation Index\n"
        "> Fetch the complete documentation index at: https://code.claude.com/docs/llms.txt\n"
        "> Use this file to discover all available pages before exploring further.\n"
        "\n"
        "# Hooks reference\n\nReal content.\n"
    )

    chunks = chunk_document(doc)

    assert all("Documentation Index" not in c.metadata["raw_content"] for c in chunks)
    assert all("llms.txt" not in c.metadata["raw_content"] for c in chunks)


def test_page_content_is_prefixed_for_embedding_and_bm25() -> None:
    doc = _doc(
        "# Hooks reference\n\n## Configuration\n\nSet ttlMs to control caching.\n"
    )

    chunks = chunk_document(doc)

    assert len(chunks) >= 1
    chunk = chunks[0]
    assert chunk.page_content.startswith(
        "Vendor: anthropic\nProduct: claude-code\nDocument: Hooks reference\n"
    )
    assert "Set ttlMs to control caching." in chunk.page_content


def test_raw_content_metadata_has_no_prefix() -> None:
    doc = _doc("# Hooks reference\n\nSet ttlMs to control caching.\n")

    chunk = chunk_document(doc)[0]

    assert chunk.metadata["raw_content"] == chunk.page_content.split("\n\n", 1)[-1]
    assert not chunk.metadata["raw_content"].startswith("Vendor:")


def test_raw_content_is_what_generator_and_reranker_should_display() -> None:
    """The contextual prefix must not duplicate the labels generator.py and
    reranker.py already add themselves from the same metadata."""
    doc = _doc("# Hooks reference\n\n## Configuration\n\nSet ttlMs.\n")

    chunk = chunk_document(doc)[0]

    assert "Vendor:" not in chunk.metadata["raw_content"]
    assert "Product:" not in chunk.metadata["raw_content"]


def _table(rows: int) -> str:
    lines = ["| Key | Description |", "| :- | :- |"]
    lines += [f"| `key{i}` | Does thing {i} |" for i in range(rows)]
    return "\n".join(lines)


def test_h4_headings_split_entries() -> None:
    doc = _doc(
        "# SDK\n\n## Functions\n\n### `tool()`\n\nMakes a tool.\n\n"
        "#### Parameters\n\nname, description\n\n#### Returns\n\nA definition.\n"
    )

    chunks = chunk_document(doc)

    raws = [c.metadata["raw_content"] for c in chunks]
    assert any("Parameters" in r and "Returns" not in r for r in raws)
    returns = next(c for c in chunks if "A definition." in c.metadata["raw_content"])
    assert returns.metadata["h3"] == "`tool()`"
    assert returns.metadata["h4"] == "Returns"
    assert "Section: SDK > Functions > `tool()` > Returns" in returns.page_content


def test_long_table_is_split_into_groups_repeating_the_header() -> None:
    doc = _doc(f"# Settings\n\n## Keys\n\nAll keys:\n\n{_table(30)}\n\nAfter text.\n")

    chunks = chunk_document(doc)

    table_chunks = [c for c in chunks if "`key" in c.metadata["raw_content"]]
    assert len(table_chunks) >= 2
    for chunk in table_chunks:
        raw = chunk.metadata["raw_content"]
        assert raw.lstrip().startswith("| Key | Description |\n| :- | :- |")
        assert raw.count("`key") <= 15
        assert chunk.metadata["h2"] == "Keys"
        assert "Section: Settings > Keys" in chunk.page_content
    seen = "".join(c.metadata["raw_content"] for c in table_chunks)
    assert all(f"`key{i}`" in seen for i in range(30))
    assert any("All keys:" in c.metadata["raw_content"] for c in chunks)
    assert any("After text." in c.metadata["raw_content"] for c in chunks)


def test_short_table_stays_with_its_text() -> None:
    doc = _doc(f"# Settings\n\nIntro.\n\n{_table(5)}\n\nOutro.\n")

    chunks = chunk_document(doc)

    assert len(chunks) == 1
    assert "Intro." in chunks[0].metadata["raw_content"]
    assert "`key4`" in chunks[0].metadata["raw_content"]


def test_table_cell_padding_is_collapsed() -> None:
    doc = _doc(
        "# T\n\n| a      | b        |\n| :-     | :-       |\n| x      | y        |\n"
    )

    raw = chunk_document(doc)[0].metadata["raw_content"]

    assert "| a | b |" in raw
    assert all("  " not in line for line in raw.splitlines() if line.startswith("|"))
