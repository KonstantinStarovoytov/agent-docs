"""Seed `rag/retrieval-query-transform-v1`: the same needs in English, Russian, Polish and mixed queries."""

import argparse
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from functools import cache

from langfuse import Langfuse

from src.config import settings

DATASET_NAME = "rag/retrieval-query-transform-v1"


# Built on first use, not at import: tests import the constants from this
# module and must not need Langfuse credentials.
@cache
def langfuse_client() -> Langfuse:
    assert settings.langfuse_secret_key is not None, "LANGFUSE_SECRET_KEY is unset"
    return Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key.get_secret_value(),
        base_url=settings.langfuse_base_url,
    )


INTENTS: list[dict[str, Any]] = [
    {
        "id": "cursor-python-rules",
        "relevant": [
            {
                "vendor": "cursor",
                "source_contains": "rules",
            },
            # Scoping a skill with `paths: "**/*.py"` also answers the natural
            # wording; accepted on 2026-10-12 (full-corpus diagnostics).
            {
                "vendor": "cursor",
                "source_contains": "cursor.com/docs/skills.md",
                "heading_contains": "Scoping a skill",
            },
        ],
        "variants": {
            "clean_en": ("How do I configure Cursor rules only for Python files?"),
            "natural_en": (
                "I want Cursor to follow some instructions "
                "only when it works with Python files."
            ),
            "short_en": ("cursor rules python files only"),
            "ru": ("как сделать rules в Cursor только для python файлов"),
            "pl": ("jak ustawić rules w Cursor tylko dla plików python"),
            "mixed": ("как настроить Cursor rules only for python files"),
        },
    },
    {
        "id": "codex-repository-instructions",
        "relevant": [
            {
                "vendor": "openai",
                "source_contains": "agents-md",
            },
        ],
        "variants": {
            "clean_en": ("How do I provide repository-wide instructions to Codex?"),
            "natural_en": (
                "I want Codex to always know the rules "
                "and conventions of my repository."
            ),
            "short_en": ("codex repo instructions"),
            "ru": ("как задать Codex инструкции для всего репозитория"),
            "pl": ("jak ustawić instrukcje dla Codex dla całego repozytorium"),
            "mixed": ("как дать Codex repo-wide instructions"),
        },
    },
    {
        "id": "claude-on-demand-workflow",
        "relevant": [
            {
                "vendor": "anthropic",
                "source_contains": "skills",
            },
            {
                "vendor": "anthropic",
                "title": "Extend Claude Code",
                "heading_contains": "Compare similar features",
            },
        ],
        "variants": {
            "clean_en": (
                "What should I use in Claude Code "
                "for reusable workflows loaded on demand?"
            ),
            "natural_en": (
                "I have a reusable workflow but I don't want "
                "Claude to load it into context every session."
            ),
            "short_en": ("claude reusable workflow on demand"),
            "ru": (
                "что использовать в Claude Code "
                "для переиспользуемого workflow "
                "который нужен только иногда"
            ),
            "pl": (
                "czego użyć w Claude Code do workflow "
                "który ma być ładowany tylko gdy jest potrzebny"
            ),
            "mixed": (
                "что использовать в Claude Code для reusable workflow loaded on demand"
            ),
        },
    },
    {
        "id": "cursor-mcp",
        "relevant": [
            {
                "vendor": "cursor",
                "source_contains": "mcp",
            },
        ],
        "variants": {
            "clean_en": ("How can Cursor connect to external tools using MCP?"),
            "natural_en": (
                "I want Cursor's agent to use tools "
                "provided by another service through MCP."
            ),
            "short_en": ("cursor external tools mcp"),
            "ru": ("как подключить внешние инструменты к Cursor через MCP"),
            "pl": ("jak podłączyć zewnętrzne narzędzia do Cursor przez MCP"),
            "mixed": ("как Cursor подключает external tools через MCP"),
        },
    },
    {
        "id": "codex-mcp",
        "relevant": [
            {
                "vendor": "openai",
                "source_contains": "mcp",
            },
        ],
        "variants": {
            "clean_en": ("How do I connect Codex to an MCP server?"),
            "natural_en": (
                "I have an MCP server with tools and want Codex to be able to use it."
            ),
            "short_en": ("codex mcp server connect"),
            "ru": ("как подключить MCP server к Codex"),
            "pl": ("jak podłączyć serwer MCP do Codex"),
            "mixed": ("как connect Codex to MCP server"),
        },
    },
    {
        "id": "mcp-server-tools",
        "relevant": [
            {
                "vendor": "model-context-protocol",
                "title": "Architecture overview",
                "heading_contains": "Data Layer Protocol",
            },
            {
                "vendor": "model-context-protocol",
                "title": "Architecture overview",
                "heading_contains": "Example > Data Layer",
            },
            {
                "vendor": "model-context-protocol",
                "title": "Build an MCP client",
                "heading_contains": "How it works",
            },
        ],
        "variants": {
            "clean_en": ("How does an MCP server expose tools to clients?"),
            "natural_en": (
                "I'm building an MCP server and want clients "
                "to discover the actions it provides."
            ),
            "short_en": ("mcp server expose tools"),
            "ru": ("как MCP server предоставляет tools клиенту"),
            "pl": ("jak serwer MCP udostępnia tools klientowi"),
            "mixed": ("как MCP server expose tools клиенту"),
        },
    },
    {
        "id": "cursor-subagents",
        "relevant": [
            {
                "vendor": "cursor",
                "source_contains": "subagent",
            },
        ],
        "variants": {
            "clean_en": ("How can Cursor delegate work to specialized subagents?"),
            "natural_en": (
                "I want Cursor to hand certain tasks to specialized agents."
            ),
            "short_en": ("cursor specialized subagents"),
            "ru": ("как Cursor может делегировать задачи специализированным subagents"),
            "pl": ("jak Cursor może delegować zadania do wyspecjalizowanych subagents"),
            "mixed": ("как Cursor delegate tasks to specialized subagents"),
        },
    },
    {
        "id": "mcp-authorization",
        "relevant": [
            {
                "vendor": "model-context-protocol",
                "source_contains": "authorization",
            },
        ],
        "variants": {
            "clean_en": ("How should authorization be implemented for an MCP server?"),
            "natural_en": (
                "I need to protect my MCP server "
                "so clients have to authenticate properly."
            ),
            "short_en": ("mcp server authorization"),
            "ru": ("как настроить authorization для MCP server"),
            "pl": ("jak skonfigurować authorization dla serwera MCP"),
            "mixed": ("как сделать MCP server authorization"),
        },
    },
]


def main() -> None:
    langfuse_client().create_dataset(
        name=DATASET_NAME,
        description=(
            "Paired benchmark for query transformation. "
            "Same information needs expressed as clean English, "
            "natural English, short queries, Russian, Polish, "
            "and mixed-language queries."
        ),
    )

    count = 0

    for intent in INTENTS:
        for query_type, question in intent["variants"].items():
            item_id = str(
                uuid5(
                    NAMESPACE_URL,
                    (f"{DATASET_NAME}:{intent['id']}:{query_type}"),
                )
            )

            langfuse_client().create_dataset_item(
                dataset_name=DATASET_NAME,
                id=item_id,
                input={
                    "question": question,
                },
                expected_output={
                    "relevant": intent["relevant"],
                },
                metadata={
                    "intent_id": intent["id"],
                    "query_type": query_type,
                    "language": (
                        "ru"
                        if query_type == "ru"
                        else "pl"
                        if query_type == "pl"
                        else "mixed"
                        if query_type == "mixed"
                        else "en"
                    ),
                },
            )

            count += 1

    langfuse_client().flush()

    print(f"Seeded {count} cases into '{DATASET_NAME}'")


if __name__ == "__main__":
    # Running writes to Langfuse; --help must not.
    argparse.ArgumentParser(description=__doc__).parse_args()
    main()
