"""Retrieval cases over pages added by the full-corpus index (2026-10-11).

Every target page was absent from the old 35-page corpus (`git show
72e5a26:src/ingestion/sources.py`). Each question was written from the page
markdown fetched on 2026-10-12; `evidence` quotes the passage that answers it
so a reviewer can check the label. Five cases per product, covering CLI
reference, settings and environment variables, SDKs, administration, cloud
agents, and the MCP registry and extensions.
"""

from typing import Any

DATASET_NAME = "rag/full-corpus-v1"

CASES: list[dict[str, Any]] = [
    # ============================================================
    # CLAUDE CODE
    # ============================================================
    {
        "question": (
            "Which claude CLI flag creates a new session ID when resuming "
            "instead of reusing the original one?"
        ),
        "category": "cli-reference",
        "difficulty": "easy",
        "evidence": "cli-reference.md: `--fork-session` ... create a new session ID",
        "relevant": [
            {"vendor": "anthropic", "source_contains": "/docs/en/cli-reference.md"},
        ],
    },
    {
        "question": (
            "What is the default timeout for a foreground Bash command in "
            "Claude Code, and which environment variable changes it?"
        ),
        "category": "env-vars",
        "difficulty": "easy",
        "evidence": "env-vars.md: BASH_DEFAULT_TIMEOUT_MS ... default: 120000",
        "relevant": [
            {"vendor": "anthropic", "source_contains": "/docs/en/env-vars.md"},
            # Time limits section restates the default and names the variable.
            {
                "vendor": "anthropic",
                "source_contains": "/docs/en/cloud-environments.md",
                "heading_contains": "Time limits",
            },
        ],
    },
    {
        "question": (
            "How can I resume a Claude Agent SDK session on a different host, "
            "such as a CI worker or an ephemeral container?"
        ),
        "category": "sdk",
        "difficulty": "semantic",
        "evidence": "agent-sdk/sessions.md > Resume across hosts: session store or move the .jsonl",
        "relevant": [
            {"vendor": "anthropic", "source_contains": "/agent-sdk/sessions.md"},
            {"vendor": "anthropic", "source_contains": "/agent-sdk/session-storage.md"},
        ],
    },
    {
        "question": (
            "How often does Claude Code check for updates to server-managed "
            "settings during an active session?"
        ),
        "category": "administration",
        "difficulty": "easy",
        "evidence": "server-managed-settings.md: polls for updates hourly during active sessions",
        "relevant": [
            {
                "vendor": "anthropic",
                "source_contains": "/docs/en/server-managed-settings.md",
            },
        ],
    },
    {
        "question": (
            "When does the setup script of a Claude Code cloud environment run "
            "again instead of using the cached snapshot?"
        ),
        "category": "cloud-agents",
        "difficulty": "semantic",
        "evidence": "cloud-environments.md > Environment caching: reruns on script/hosts change or ~7-day expiry",
        "relevant": [
            {
                "vendor": "anthropic",
                "source_contains": "/docs/en/cloud-environments.md",
            },
        ],
    },
    # ============================================================
    # CURSOR
    # ============================================================
    {
        "question": (
            "Which Cursor CLI option runs the agent in a new Git worktree, and "
            "where is that worktree created?"
        ),
        "category": "cli-reference",
        "difficulty": "easy",
        "evidence": "cli/reference/parameters.md: -w, --worktree ... ~/.cursor/worktrees/<reponame>/<name>",
        "relevant": [
            {
                "vendor": "cursor",
                "source_contains": "/docs/cli/reference/parameters.md",
            },
            # Added after the first run: cli/using.md > CLI worktrees states the
            # same flag and path ("Pass `-w` or `--worktree [name]` ...").
            {
                "vendor": "cursor",
                "source_contains": "/docs/cli/using.md",
                "heading_contains": "CLI worktrees",
            },
        ],
    },
    {
        "question": (
            "In what order does Cursor resolve the environment configuration "
            "for a cloud agent's repository?"
        ),
        "category": "cloud-agents",
        "difficulty": "easy",
        "evidence": "cloud-agent/setup.md > Environment resolution order: .cursor/environment.json, personal, team",
        "relevant": [
            {"vendor": "cursor", "source_contains": "/docs/cloud-agent/setup.md"},
        ],
    },
    {
        "question": (
            "With Cursor SCIM, which spend limit applies to a user who belongs "
            "to several directory groups?"
        ),
        "category": "administration",
        "difficulty": "easy",
        "evidence": "account/teams/scim.md > Spend management: highest applicable spend limit",
        "relevant": [
            {"vendor": "cursor", "source_contains": "/docs/account/teams/scim.md"},
        ],
    },
    {
        "question": (
            "How do I pass short-lived credentials as environment variables to "
            "a Cursor cloud agent created with the TypeScript SDK?"
        ),
        "category": "sdk",
        "difficulty": "semantic",
        "evidence": "sdk/typescript.md > Session environment variables: cloud.envVars",
        "relevant": [
            {"vendor": "cursor", "source_contains": "/docs/sdk/typescript.md"},
        ],
    },
    {
        "question": (
            "Why doesn't the Cursor CLI change files in print mode, and how do "
            "I let a script apply the edits?"
        ),
        "category": "cli-reference",
        "difficulty": "semantic",
        "evidence": "cli/headless.md: combine --print with --force; without it changes are only proposed",
        "relevant": [
            {"vendor": "cursor", "source_contains": "/docs/cli/headless.md"},
            {
                "vendor": "cursor",
                "source_contains": "/docs/cli/reference/parameters.md",
            },
        ],
    },
    # ============================================================
    # CODEX
    # ============================================================
    {
        "question": (
            "Which environment variable sets the root directory for Codex "
            "config, auth, logs and sessions, and what is its default?"
        ),
        "category": "env-vars",
        "difficulty": "easy",
        "evidence": "config-file/environment-variables.md: CODEX_HOME, default ~/.codex",
        "relevant": [
            {
                "vendor": "openai",
                "source_contains": "/config-file/environment-variables.md",
            },
            {"vendor": "openai", "source_contains": "/config-file/config-advanced.md"},
        ],
    },
    {
        "question": "What sandbox presets does the Codex Python SDK provide?",
        "category": "sdk",
        "difficulty": "easy",
        "evidence": "codex-sdk.md > Sandbox presets: read_only, workspace_write, full_access",
        "relevant": [
            {"vendor": "openai", "source_contains": "/docs/codex-sdk.md"},
        ],
    },
    {
        "question": (
            "In what order are Codex requirements.toml layers applied for local "
            "execution in a managed enterprise setup?"
        ),
        "category": "administration",
        "difficulty": "semantic",
        "evidence": "enterprise/managed-configuration.md > Locations and precedence: system file, Agent Security, legacy, MDM",
        "relevant": [
            {
                "vendor": "openai",
                "source_contains": "/enterprise/managed-configuration.md",
            },
        ],
    },
    {
        "question": (
            "What does the safety-strategy input of the Codex GitHub Action do "
            "by default?"
        ),
        "category": "ci",
        "difficulty": "easy",
        "evidence": "github-action.md > Manage privileges: default drop-sudo removes sudo",
        "relevant": [
            {"vendor": "openai", "source_contains": "/docs/github-action.md"},
        ],
    },
    {
        "question": (
            "How do I get started with Codex Cloud on my GitHub repositories, "
            "from choosing an environment to starting a task?"
        ),
        "category": "cloud-agents",
        "difficulty": "semantic",
        "evidence": "cloud.md > Getting started: select environment, let Codex prepare, review, start task",
        "relevant": [
            {"vendor": "openai", "source_contains": "/docs/cloud.md"},
            {
                "vendor": "openai",
                "source_contains": "/environments/cloud-environments.md",
            },
        ],
    },
    # ============================================================
    # MCP
    # ============================================================
    {
        "question": (
            "Which npm registry does the MCP Registry accept for npm packages, "
            "and what registryType goes in server.json?"
        ),
        "category": "registry",
        "difficulty": "easy",
        "evidence": "registry/package-types.md > npm Packages: registry.npmjs.org only, registryType npm",
        "relevant": [
            {
                "vendor": "model-context-protocol",
                "source_contains": "/registry/package-types.md",
            },
        ],
    },
    {
        "question": (
            "How do I log in to the MCP Registry with mcp-publisher using GitHub "
            "before publishing a server?"
        ),
        "category": "registry",
        "difficulty": "easy",
        "evidence": "registry/quickstart.md > Step 5: mcp-publisher login github",
        "relevant": [
            {
                "vendor": "model-context-protocol",
                "source_contains": "/registry/quickstart.md",
            },
            {
                "vendor": "model-context-protocol",
                "source_contains": "/registry/authentication.md",
            },
        ],
    },
    {
        "question": (
            "How does an MCP Apps tool tell the host which interactive UI to render?"
        ),
        "category": "extensions",
        "difficulty": "semantic",
        "evidence": "extensions/apps/overview.md > How MCP Apps work: _meta.ui.resourceUri -> ui:// resource",
        "relevant": [
            {
                "vendor": "model-context-protocol",
                "source_contains": "/extensions/apps/",
            },
        ],
    },
    {
        "question": (
            "When should an MCP integration use OAuth client credentials instead "
            "of the standard user authorization flow?"
        ),
        "category": "extensions",
        "difficulty": "semantic",
        "evidence": "extensions/auth/oauth-client-credentials.md > When to use it: no user present",
        "relevant": [
            {
                "vendor": "model-context-protocol",
                "source_contains": "/extensions/auth/oauth-client-credentials.md",
            },
        ],
    },
    {
        "question": (
            "How should I version a server.json update to the MCP Registry when "
            "the underlying package has not changed?"
        ),
        "category": "registry",
        "difficulty": "semantic",
        "evidence": "registry/versioning.md > Use Prerelease Versions for Registry-only Updates: 1.2.3-1",
        "relevant": [
            {
                "vendor": "model-context-protocol",
                "source_contains": "/registry/versioning.md",
            },
        ],
    },
]
