import re
from urllib.parse import urlsplit, urlunsplit

import httpx

from src.ingestion.sources import SOURCES, SourceConfig
from src.models import SourceDocument

MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)]\((https?://[^)\s]+)\)")

BARE_URL_RE = re.compile(r"https?://[^\s)>]+")


def _normalize_url(url: str) -> str:
    parts = urlsplit(url)

    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            parts.query,
            "",  # remove #fragment
        )
    )


def _fallback_title(url: str) -> str:
    path = urlsplit(url).path

    name = path.rsplit("/", 1)[-1]
    name = name.removesuffix(".md")

    return name.replace("-", " ").replace("_", " ").strip().title()


def _extract_links(
    index_content: str,
) -> list[tuple[str, str]]:
    links: dict[str, str] = {}

    # Normal Markdown links:
    # [Skills](https://.../skills.md)
    for title, url in MARKDOWN_LINK_RE.findall(index_content):
        normalized = _normalize_url(url)

        links[normalized] = title.strip()

    # Cursor llms.txt also contains plain URLs,
    # so support those as well.
    for url in BARE_URL_RE.findall(index_content):
        normalized = _normalize_url(url)

        links.setdefault(
            normalized,
            _fallback_title(normalized),
        )

    return [(title, url) for url, title in links.items()]


DATED_SEGMENT = r"(\d{4}-\d{2}-\d{2}|draft)/"


def newest_version(links: list[tuple[str, str]], prefix: str) -> str | None:
    """Newest `<prefix>YYYY-MM-DD/` segment present in the index, if any."""
    dated = re.compile(re.escape(prefix) + r"(\d{4}-\d{2}-\d{2})/")
    versions = {m.group(1) for _, url in links if (m := dated.search(url))}
    return max(versions) if versions else None


def _is_page(url: str) -> bool:
    return urlsplit(url).path.endswith(".md")


def _stale_version(
    path: str, config: SourceConfig, newest: dict[str, str | None]
) -> bool:
    for prefix in config.versioned_prefixes:
        m = re.match(re.escape(prefix) + DATED_SEGMENT, path)
        if m:
            return m.group(1) != newest[prefix]
    return False


def select_links(
    links: list[tuple[str, str]], config: SourceConfig
) -> list[tuple[str, str]]:
    """Every markdown page in llms.txt order, minus excludes and stale versions."""
    newest = {p: newest_version(links, p) for p in config.versioned_prefixes}
    excludes = [re.compile(p) for p in config.exclude]
    selected: dict[str, str] = {}
    for title, url in links:
        if url in selected or not _is_page(url):
            continue
        path = urlsplit(url).path
        if any(p.search(path) for p in excludes):
            continue
        if _stale_version(path, config, newest):
            continue
        selected[url] = title
    return [(title, url) for url, title in selected.items()]


def load_source(
    config: SourceConfig,
) -> list[SourceDocument]:
    documents: list[SourceDocument] = []

    with httpx.Client(
        timeout=30,
        follow_redirects=True,
    ) as client:
        index_response = client.get(config.index_url)
        index_response.raise_for_status()

        selected_links = select_links(_extract_links(index_response.text), config)

        print(f"{config.vendor}/{config.product}: {len(selected_links)} pages")

        for title, url in selected_links:
            response = client.get(url)
            response.raise_for_status()

            documents.append(
                SourceDocument(
                    title=title,
                    content=response.text,
                    url=url,
                    vendor=config.vendor,
                    product=config.product,
                )
            )

    return documents


def load_all_sources() -> list[SourceDocument]:
    documents: list[SourceDocument] = []

    for config in SOURCES:
        source_documents = load_source(config)

        documents.extend(source_documents)

    return documents


if __name__ == "__main__":
    documents = load_all_sources()

    for document in documents:
        print(
            document.vendor,
            document.product,
            document.title,
            document.url,
        )
