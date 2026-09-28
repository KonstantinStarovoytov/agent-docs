"""Fetching tolerates single-page failures and reports them."""

from src.ingestion import loader
from src.ingestion.sources import SourceConfig

CFG = SourceConfig(vendor="v", product="p", index_url="https://x/llms.txt")


def test_failed_pages_are_reported_not_fatal() -> None:
    pages = {
        "https://x/llms.txt": (200, "[A](https://x/a.md)\n[B](https://x/b.md)"),
        "https://x/a.md": (200, "# A\nbody"),
        "https://x/b.md": (404, ""),
    }

    result = loader.load_sources((CFG,), fetch=lambda url: pages[url])

    assert [d.url for d in result.documents] == ["https://x/a.md"]
    assert result.failures == {"https://x/b.md": "HTTP 404"}
    assert result.listed == {"p": 2}
    assert result.failed_products == {"https://x/b.md": "p"}


def test_unreachable_index_raises() -> None:
    import pytest

    with pytest.raises(RuntimeError, match="llms.txt"):
        loader.load_sources((CFG,), fetch=lambda url: (503, ""))
