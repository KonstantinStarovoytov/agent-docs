from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SourceConfig:
    vendor: str
    product: str
    index_url: str
    # Regexes searched in the URL path; a match drops the page. Everything
    # else a vendor lists in llms.txt is indexed, so new pages arrive on
    # their own and junk is kept out here or by the page gate.
    exclude: tuple[str, ...] = ()
    # Prefixes whose pages live under `<prefix>YYYY-MM-DD/`: only the newest
    # dated version is kept; `draft` and older dates are dropped.
    versioned_prefixes: tuple[str, ...] = ()
    # Exact URLs indexed even when the page gate flags them (owner decision).
    allow: tuple[str, ...] = ()


ANTHROPIC = SourceConfig(
    vendor="anthropic",
    product="claude-code",
    index_url="https://code.claude.com/docs/llms.txt",
    exclude=(
        r"^/docs/_llms/",  # localized llms.txt indexes, not documentation
        r"/whats-new/",  # weekly notes restating the main pages
        r"/changelog\.md$",  # huge and rewritten daily
    ),
)


CURSOR = SourceConfig(
    vendor="cursor",
    product="cursor",
    index_url="https://cursor.com/llms.txt",
    exclude=(
        r"^/help/",  # help center: billing and account, out of scope
        r"^/[a-z]{2}(-[a-z]{2,4})?/",  # translations: /es/, /ja/, /cn/ ...
        r"changelog",
    ),
)


OPENAI_CODEX = SourceConfig(
    vendor="openai",
    product="codex",
    index_url="https://developers.openai.com/codex/llms.txt",
    exclude=(
        r"/codex-manual\.md$",  # concatenation of every other page
    ),
)


MCP = SourceConfig(
    vendor="model-context-protocol",
    product="mcp",
    index_url="https://modelcontextprotocol.io/llms.txt",
    versioned_prefixes=("/docs/", "/specification/"),
    exclude=(
        r"^/community/",  # working and interest groups
        r"^/seps/",  # proposals; accepted ones are merged into the spec
    ),
)


SOURCES = (
    ANTHROPIC,
    CURSOR,
    OPENAI_CODEX,
    MCP,
)
