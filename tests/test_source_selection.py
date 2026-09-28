"""Which pages a source config picks out of a vendor's llms.txt."""

from src.ingestion import loader
from src.ingestion.sources import SOURCES, SourceConfig


def _cfg(**overrides: object) -> SourceConfig:
    base: dict[str, object] = {
        "vendor": "anthropic",
        "product": "claude-code",
        "index_url": "https://x/llms.txt",
    }
    base.update(overrides)
    return SourceConfig(**base)  # type: ignore[arg-type]


def _urls(selected: list[tuple[str, str]]) -> list[str]:
    return [url for _, url in selected]


def test_only_markdown_pages_are_selected() -> None:
    links = [
        ("A", "https://x/docs/a.md"),
        ("Full", "https://x/docs/llms-full.txt"),
        ("Spec", "https://x/docs/api/openapi.yaml"),
        ("Html", "https://x/docs/api/changelog"),
        ("Broken", "https://x/es/docs/bugbot.md`"),
    ]

    assert _urls(loader.select_links(links, _cfg())) == ["https://x/docs/a.md"]


def test_query_variants_are_distinct_pages() -> None:
    links = [
        ("CLI", "https://x/docs/developer-commands.md?surface=cli"),
        ("IDE", "https://x/docs/developer-commands.md?surface=ide"),
    ]

    assert len(loader.select_links(links, _cfg())) == 2


def test_exclude_patterns_match_the_url_path() -> None:
    links = [
        ("Keep", "https://x/docs/en/hooks.md"),
        ("Lang", "https://x/docs/_llms/fr.md"),
        ("News", "https://x/docs/en/whats-new/2026-w37.md"),
    ]
    cfg = _cfg(exclude=(r"^/docs/_llms/", r"/whats-new/"))

    assert _urls(loader.select_links(links, cfg)) == ["https://x/docs/en/hooks.md"]


def test_versioned_prefix_keeps_only_the_newest_date() -> None:
    links = [
        ("old", "https://m/docs/2025-11-25/learn/a.md"),
        ("new", "https://m/docs/2026-07-28/learn/a.md"),
        ("draft", "https://m/docs/draft/learn/a.md"),
        ("spec-old", "https://m/specification/2025-06-18/basic/b.md"),
        ("spec-new", "https://m/specification/2026-07-28/basic/b.md"),
        ("plain", "https://m/registry/about.md"),
    ]
    cfg = _cfg(versioned_prefixes=("/docs/", "/specification/"))

    assert _urls(loader.select_links(links, cfg)) == [
        "https://m/docs/2026-07-28/learn/a.md",
        "https://m/specification/2026-07-28/basic/b.md",
        "https://m/registry/about.md",
    ]


def test_duplicate_links_are_selected_once() -> None:
    links = [("A", "https://x/docs/a.md"), ("A again", "https://x/docs/a.md")]

    assert len(loader.select_links(links, _cfg())) == 1


def test_vendor_configs_exclude_known_junk() -> None:
    by_product = {c.product: c for c in SOURCES}
    cases = {
        "claude-code": [
            "https://code.claude.com/docs/_llms/fr.md",
            "https://code.claude.com/docs/en/whats-new/2026-w37.md",
            "https://code.claude.com/docs/en/changelog.md",
        ],
        "cursor": [
            "https://cursor.com/help/account-and-billing/refunds.md",
            "https://cursor.com/ja/docs/bugbot.md",
            "https://cursor.com/changelog.md",
        ],
        "codex": ["https://learn.chatgpt.com/docs/codex-manual.md"],
        "mcp": [
            "https://modelcontextprotocol.io/community/working-groups/auth.md",
            "https://modelcontextprotocol.io/seps/990-enable.md",
        ],
    }
    for product, urls in cases.items():
        links = [("t", u) for u in urls]
        assert loader.select_links(links, by_product[product]) == [], product


def test_vendor_configs_keep_real_docs() -> None:
    by_product = {c.product: c for c in SOURCES}
    keep = {
        "claude-code": "https://code.claude.com/docs/en/plugins/create.md",
        "cursor": "https://cursor.com/docs/rules.md",
        "codex": "https://learn.chatgpt.com/docs/hooks.md",
        "mcp": "https://modelcontextprotocol.io/registry/about.md",
    }
    for product, url in keep.items():
        assert _urls(loader.select_links([("t", url)], by_product[product])) == [url]
