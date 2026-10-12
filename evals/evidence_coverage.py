"""Ground truth and scorers for multi-aspect retrieval coverage."""

from typing import Any

from langfuse import Evaluation

DATASET_NAME = "rag/evidence-coverage-v1"

# Each group is independently required. A single relevant source is not enough for
# a question that asks about several product capabilities.
CASES: list[dict[str, Any]] = [
    {
        "id": "cursor-rules-mcp-subagents",
        "question": (
            "How do I configure Cursor to use external MCP tools, apply instructions "
            "only to Python files, and delegate a long task to a subagent?"
        ),
        "evidence_groups": [
            {
                "id": "cursor-mcp",
                "target": {
                    "vendor": "cursor",
                    "source_contains": "cursor.com/docs/mcp.md",
                },
            },
            {
                "id": "cursor-python-rule-glob",
                "target": {
                    "vendor": "cursor",
                    "source_contains": "cursor.com/docs/rules.md",
                    "heading_contains": "Glob pattern",
                },
            },
            {
                "id": "cursor-subagents",
                "target": {
                    "vendor": "cursor",
                    "source_contains": "cursor.com/docs/subagents.md",
                },
            },
        ],
    },
    {
        "id": "claude-plugin-composition",
        "question": (
            "How should a Claude Code plugin divide a recurring test-failure "
            "investigation workflow among skills, subagents, hooks, and an MCP server?"
        ),
        "evidence_groups": [
            {
                "id": "claude-plugin-package",
                "target": {
                    "vendor": "anthropic",
                    "source_contains": "en/plugins.md",
                },
                # The page moved into a plugins/ section on 2026-09-27
                # (commit dc28368); create.md carries the same content.
                "alternatives": [
                    {"vendor": "anthropic", "source_contains": "en/plugins/create.md"},
                ],
            },
            {
                "id": "claude-feature-composition",
                "target": {
                    "vendor": "anthropic",
                    "source_contains": "features-overview.md",
                    "heading_contains": "Combine features",
                },
            },
            {
                "id": "claude-subagents",
                "target": {
                    "vendor": "anthropic",
                    "source_contains": "sub-agents.md",
                },
            },
        ],
    },
    {
        "id": "mcp-discovery-updates-auth",
        "question": (
            "For an MCP server, how should a client discover tools, handle "
            "tool-list changes, and implement authorization?"
        ),
        "evidence_groups": [
            {
                "id": "mcp-tools-and-notifications",
                "target": {
                    "vendor": "model-context-protocol",
                    "source_contains": "learn/architecture.md",
                    "heading_contains": "Data Layer Protocol",
                },
            },
            {
                "id": "mcp-authorization",
                "target": {
                    "vendor": "model-context-protocol",
                    "source_contains": "authorization.md",
                },
            },
        ],
    },
    {
        "id": "codex-agents-mcp",
        "question": (
            "How do I set persistent project guidance in AGENTS.md and connect "
            "Codex to a remote MCP server?"
        ),
        "evidence_groups": [
            {
                "id": "codex-agents-guidance",
                "target": {
                    "vendor": "openai",
                    "source_contains": "agents-md.md",
                },
            },
            {
                "id": "codex-mcp-server",
                "target": {
                    "vendor": "openai",
                    "source_contains": "extend/mcp.md",
                    "heading_contains": "Connect Codex to an MCP server",
                },
            },
        ],
    },
    # Same-vendor capability choices. The second aspect uses different wording from
    # the first, so a single retrieval tends to cover only one of them.
    {
        "id": "claude-skill-vs-subagent",
        "question": (
            "In Claude Code, when should a reusable workflow be a skill and when "
            "should it be a subagent with its own context?"
        ),
        "evidence_groups": [
            {
                "id": "claude-skills",
                "target": {"vendor": "anthropic", "source_contains": "en/skills.md"},
            },
            {
                "id": "claude-subagents",
                "target": {"vendor": "anthropic", "source_contains": "sub-agents.md"},
            },
        ],
    },
    {
        "id": "cursor-skill-vs-rule",
        "question": (
            "In Cursor, what is the difference between a skill and a rule, and how "
            "does each one get activated?"
        ),
        "evidence_groups": [
            {
                "id": "cursor-skills",
                "target": {
                    "vendor": "cursor",
                    "source_contains": "cursor.com/docs/skills.md",
                },
            },
            {
                "id": "cursor-rules",
                "target": {
                    "vendor": "cursor",
                    "source_contains": "cursor.com/docs/rules.md",
                },
            },
        ],
    },
    {
        "id": "cursor-hooks-and-subagents",
        "question": (
            "How do I run a command automatically on every Cursor agent event and "
            "also hand a long refactor to a separate agent?"
        ),
        "evidence_groups": [
            {
                "id": "cursor-hooks",
                "target": {
                    "vendor": "cursor",
                    "source_contains": "cursor.com/docs/hooks.md",
                },
            },
            {
                "id": "cursor-subagents",
                "target": {"vendor": "cursor", "source_contains": "subagents.md"},
            },
        ],
    },
    {
        "id": "codex-agents-md-vs-rules",
        "question": (
            "For Codex, what belongs in AGENTS.md and what should instead be a rule?"
        ),
        "evidence_groups": [
            {
                "id": "codex-agents-md",
                "target": {"vendor": "openai", "source_contains": "agents-md.md"},
            },
            {
                "id": "codex-rules",
                "target": {
                    "vendor": "openai",
                    "source_contains": "agent-configuration/rules.md",
                },
            },
        ],
    },
    {
        "id": "codex-skills-and-subagents",
        "question": (
            "How do I build a Codex skill, and when should the work be delegated to "
            "a subagent instead?"
        ),
        "evidence_groups": [
            {
                "id": "codex-skills",
                "target": {"vendor": "openai", "source_contains": "build-skills.md"},
            },
            {
                "id": "codex-subagents",
                "target": {
                    "vendor": "openai",
                    "source_contains": "agent-configuration/subagents.md",
                },
            },
        ],
    },
    {
        "id": "mcp-server-and-client-concepts",
        "question": (
            "What primitives does an MCP server expose, and what does the client "
            "side contribute to the same session?"
        ),
        "evidence_groups": [
            {
                "id": "mcp-server-concepts",
                "target": {
                    "vendor": "model-context-protocol",
                    "source_contains": "learn/server-concepts.md",
                },
                # Label gap, full corpus 2026-10-12: the spec's server overview
                # lists the same primitives (prompts, resources, tools).
                "alternatives": [
                    {
                        "vendor": "model-context-protocol",
                        "source_contains": "/server/index.md",
                    },
                ],
            },
            {
                "id": "mcp-client-concepts",
                "target": {
                    "vendor": "model-context-protocol",
                    "source_contains": "learn/client-concepts.md",
                },
            },
        ],
    },
    {
        "id": "mcp-authorization-and-hardening",
        "question": (
            "How should a remote MCP server authorize callers, and what other "
            "security mistakes must it avoid?"
        ),
        "evidence_groups": [
            {
                "id": "mcp-authorization",
                "target": {
                    "vendor": "model-context-protocol",
                    "source_contains": "security/authorization.md",
                },
            },
            {
                "id": "mcp-security-practices",
                "target": {
                    "vendor": "model-context-protocol",
                    "source_contains": "security_best_practices.md",
                },
            },
        ],
    },
    {
        "id": "mcp-versioning-and-client-build",
        "question": (
            "How does MCP handle protocol version negotiation, and what must a "
            "client implement to connect to a server?"
        ),
        "evidence_groups": [
            {
                "id": "mcp-versioning",
                "target": {
                    "vendor": "model-context-protocol",
                    "source_contains": "learn/versioning.md",
                },
            },
            {
                "id": "mcp-build-client",
                "target": {
                    "vendor": "model-context-protocol",
                    "source_contains": "develop/build-client.md",
                },
            },
        ],
    },
    # Cross-vendor questions. Each vendor uses its own vocabulary, so coverage here
    # is the clearest signal for whether a second retrieval round is needed.
    {
        "id": "mcp-build-then-connect-cursor",
        "question": (
            "How do I build an MCP server with the official SDK and then register "
            "it in Cursor?"
        ),
        "evidence_groups": [
            {
                "id": "mcp-build-server",
                "target": {
                    "vendor": "model-context-protocol",
                    "source_contains": "develop/build-server.md",
                },
            },
            {
                "id": "cursor-mcp",
                "target": {
                    "vendor": "cursor",
                    "source_contains": "cursor.com/docs/mcp.md",
                },
            },
        ],
    },
    {
        "id": "mcp-config-claude-vs-cursor",
        "question": (
            "How does configuring an MCP server differ between Claude Code and Cursor?"
        ),
        "evidence_groups": [
            {
                "id": "claude-mcp",
                "target": {"vendor": "anthropic", "source_contains": "en/mcp.md"},
            },
            {
                "id": "cursor-mcp",
                "target": {
                    "vendor": "cursor",
                    "source_contains": "cursor.com/docs/mcp.md",
                },
            },
        ],
    },
    {
        "id": "persistent-instructions-claude-vs-codex",
        "question": (
            "Where do persistent project instructions live for Claude Code and for "
            "Codex, and how is each file loaded?"
        ),
        "evidence_groups": [
            {
                "id": "claude-memory",
                "target": {"vendor": "anthropic", "source_contains": "en/memory.md"},
            },
            {
                "id": "codex-agents-md",
                "target": {"vendor": "openai", "source_contains": "agents-md.md"},
            },
        ],
    },
    {
        "id": "hooks-cursor-vs-codex",
        "question": (
            "Compare the hook events available in Cursor and in Codex for blocking "
            "an agent action before it runs."
        ),
        "evidence_groups": [
            {
                "id": "cursor-hooks",
                "target": {
                    "vendor": "cursor",
                    "source_contains": "cursor.com/docs/hooks.md",
                },
            },
            {
                "id": "codex-hooks",
                "target": {
                    "vendor": "openai",
                    "source_contains": "chatgpt.com/docs/hooks.md",
                },
            },
        ],
    },
]


def matches_target(result: dict[str, Any], target: dict[str, str]) -> bool:
    for field in ("vendor", "product", "title"):
        if target.get(field) and result.get(field) != target[field]:
            return False
    for field, result_field in (
        ("source_contains", "source"),
        ("heading_contains", "heading"),
    ):
        expected = target.get(field)
        if (
            expected
            and expected.casefold() not in str(result.get(result_field, "")).casefold()
        ):
            return False
    return True


def group_targets(group: dict[str, Any]) -> list[dict[str, str]]:
    """The group's target plus any recorded alternative sources (label gaps)."""
    return [group["target"], *group.get("alternatives", [])]


def coverage(output: dict[str, Any], expected_output: dict[str, Any]) -> dict[str, Any]:
    results = output.get("results", [])
    groups = expected_output["evidence_groups"]
    covered = [
        group["id"]
        for group in groups
        if any(
            matches_target(result, target)
            for result in results
            for target in group_targets(group)
        )
    ]
    missing = [group["id"] for group in groups if group["id"] not in covered]
    return {
        "covered": covered,
        "missing": missing,
        "value": len(covered) / len(groups),
        "complete": float(not missing),
    }


def evidence_coverage(*, output, expected_output, **_kwargs):
    measured = coverage(output, expected_output)
    return Evaluation(
        name="evidence_coverage",
        value=measured["value"],
        comment=f"covered={measured['covered']}; missing={measured['missing']}",
    )


def complete_evidence_coverage(*, output, expected_output, **_kwargs):
    measured = coverage(output, expected_output)
    return Evaluation(
        name="complete_evidence_coverage",
        value=measured["complete"],
        comment=f"missing={measured['missing']}",
    )
