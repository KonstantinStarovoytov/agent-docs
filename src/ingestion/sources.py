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
        r"/(data-usage|legal-and-compliance)\.md$",  # legal and policy
        r"/(communications|champion)-kit\.md$",  # internal adoption marketing
        r"/en/(platforms|third-party-integrations)\.md$",  # link hubs
        r"/agent-sdk/examples\.md$",  # list of external demos
    ),
    # Large references: one page, many entries; the size heuristic would
    # quarantine them as concatenations.
    allow=(
        # Owner decision 2026-10-12: comparison hub for parallel work.
        "https://code.claude.com/docs/en/agents.md",
        "https://code.claude.com/docs/en/settings-reference.md",
        "https://code.claude.com/docs/en/errors.md",
        "https://code.claude.com/docs/en/env-vars.md",
        "https://code.claude.com/docs/en/hooks.md",
        "https://code.claude.com/docs/en/claude-tag.md",
        "https://code.claude.com/docs/en/agent-sdk/typescript.md",
        "https://code.claude.com/docs/en/agent-sdk/python.md",
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
        r"/release-notes",  # release feed, 242 chunks of changelog
        r"^/docs\.md$",  # landing page
        r"/docs/(api|enterprise|origin|security-agents)\.md$",  # link hubs
        r"/enterprise/(admin-setup-guide|security-hardening)\.md$",  # link hubs
        r"/self-hosted/integrations\.md$",  # partner directory
        r"/grok-bot\.md$",  # marketing overview
        r"/teams/pricing\.md$",  # pricing, out of scope like /help/
        r"/enterprise/baa\.md$",  # legal
    ),
    allow=(
        "https://cursor.com/docs/api/origin/mcp/tools.md",
        "https://cursor.com/docs/sdk/typescript.md",
        "https://cursor.com/docs/sdk/python.md",
        "https://cursor.com/docs/cloud-agent/api/endpoints.md",
        "https://cursor.com/docs/account/teams/admin-api.md",
        "https://cursor.com/docs/enterprise/privacy-and-data-governance.md",
    ),
)


OPENAI_CODEX = SourceConfig(
    vendor="openai",
    product="codex",
    index_url="https://developers.openai.com/codex/llms.txt",
    exclude=(
        r"/codex-manual\.md$",  # concatenation of every other page
        r"/whats-new",  # dated announcements and their roundup
        r"/changelog\.md$",  # plugin changelog
        r"/docs/mcp-server\.md$",  # removal notice
        r"/docs/open-source\.md$",  # community programme
        r"/docs/sign-in-with-chatgpt\.md$",  # ChatGPT account overview
        # Landing pages that only link elsewhere.
        r"/docs/(administration|developers|features|security-administration)\.md$",
        r"/enterprise/governance\.md$",
    ),
    allow=(
        # Owner decision 2026-10-12: original-corpus page.
        "https://learn.chatgpt.com/docs/configuration.md",
        "https://learn.chatgpt.com/docs/app-server.md",
        "https://learn.chatgpt.com/docs/developer-commands.md?surface=cli",
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
        r"/changelog\.md$",  # spec revision diff
        r"^/registry/(terms-of-service|moderation-policy)\.md$",  # legal, policy
        r"^/development/roadmap\.md$",  # maintainers' priorities
        r"^/examples\.md$",  # directory of external servers
        r"^/extensions/auth/overview\.md$",  # link hub
    ),
    # Spec URLs carry the revision date: update these when it changes.
    allow=(
        # Owner decision 2026-10-12: original-corpus page and client matrix.
        "https://modelcontextprotocol.io/docs/2026-07-28/sdk.md",
        "https://modelcontextprotocol.io/extensions/client-matrix.md",
        "https://modelcontextprotocol.io/specification/2026-07-28/schema.md",
        "https://modelcontextprotocol.io/specification/2026-07-28/deprecated.md",
        # Evidence alternative in evidence-coverage-v1.
        "https://modelcontextprotocol.io/specification/2026-07-28/server/index.md",
    ),
)


SOURCES = (
    ANTHROPIC,
    CURSOR,
    OPENAI_CODEX,
    MCP,
)
