import re

from langchain_core.documents import Document
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

from src.ingestion.clean import clean_markdown
from src.models import SourceDocument

HEADERS = [
    ("#", "h1"),
    ("##", "h2"),
    ("###", "h3"),
    # Reference pages put one entry (parameters, a type, a setting) under
    # each `####`; splitting there gives one entry per chunk.
    ("####", "h4"),
]

# A long reference table (settings keys, env vars, tool lists) becomes
# chunks of this many rows, each repeating the header row, so a row is
# retrieved with its column names instead of inside a 3000-char wall.
TABLE_ROWS = 12
_CELL_PADDING_RE = re.compile(r"[ \t]{2,}")

# Bumped whenever chunking/cleaning logic changes, so src.reindex can tell
# a page needs re-embedding even when its fetched markdown is unchanged.
CHUNKER_VERSION = "3-h4-and-table-rows"


def _heading_path(metadata: dict[str, str]) -> str:
    return " > ".join(
        value
        for value in (
            metadata.get("h1"),
            metadata.get("h2"),
            metadata.get("h3"),
            metadata.get("h4"),
        )
        if value
    )


def _is_table_line(line: str) -> bool:
    return line.lstrip().startswith("|")


def split_long_tables(text: str, max_rows: int = TABLE_ROWS) -> list[str]:
    """Cut `text` around tables longer than `max_rows` data rows.

    Text and short tables stay together; each long table becomes groups of
    `max_rows` rows that start with the table's header and separator rows.
    Cell padding is collapsed in every table line.
    """
    lines = text.split("\n")
    segments: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        if "\n".join(buffer).strip():
            segments.append("\n".join(buffer))
        buffer.clear()

    i = 0
    while i < len(lines):
        if not _is_table_line(lines[i]):
            buffer.append(lines[i])
            i += 1
            continue
        start = i
        while i < len(lines) and _is_table_line(lines[i]):
            i += 1
        table = [_CELL_PADDING_RE.sub(" ", line.strip()) for line in lines[start:i]]
        head, rows = table[:2], table[2:]
        if len(rows) <= max_rows:
            buffer.extend(table)
            continue
        flush()
        for n in range(0, len(rows), max_rows):
            segments.append("\n".join(head + rows[n : n + max_rows]))
    flush()
    return segments or [text]


def _contextualize(chunk: Document, *, vendor: str, product: str, title: str) -> None:
    """Prefix the embedded/BM25-indexed text with document context.

    Without this, a chunk's text alone rarely names the product it documents
    (only the first chunk of a section keeps its Markdown heading; later
    chunks of a long section carry none), so BM25 and dense retrieval cannot
    tell apart same-named concepts across vendors (`hooks`, `mcp`, `rules`).
    The raw text is kept in metadata for callers that build their own
    Title/Section/Product display (generator.py, reranker.py) and must not
    show the label twice.
    """
    heading = _heading_path(chunk.metadata)
    chunk.metadata["raw_content"] = chunk.page_content
    chunk.page_content = (
        f"Vendor: {vendor}\n"
        f"Product: {product}\n"
        f"Document: {title}\n"
        f"Section: {heading}\n\n"
        f"{chunk.page_content}"
    )


def chunk_document(
    document: SourceDocument,
) -> list[Document]:
    markdown_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=HEADERS,
        strip_headers=False,
    )

    sections = markdown_splitter.split_text(clean_markdown(document.content))

    for section in sections:
        section.metadata.update(
            {
                "vendor": document.vendor,
                "product": document.product,
                "title": document.title,
                "source": document.url,
            }
        )

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=3000,
        chunk_overlap=300,
    )

    pieces = [
        Document(page_content=segment, metadata=dict(section.metadata))
        for section in sections
        for segment in split_long_tables(section.page_content)
    ]
    chunks = text_splitter.split_documents(pieces)
    for chunk in chunks:
        _contextualize(
            chunk,
            vendor=document.vendor,
            product=document.product,
            title=document.title,
        )
    return chunks


def chunk_documents(
    documents: list[SourceDocument],
) -> list[Document]:
    chunks = []

    for document in documents:
        chunks.extend(chunk_document(document))

    return chunks
