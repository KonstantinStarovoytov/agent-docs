"""Questions the indexed documentation does not answer.

The corpus is the Claude Code, Cursor, Codex and MCP documentation (617
pages since 2026-10-11; re-audited then, see reports/full-corpus-eval-2026-10.md). An
agent that has this MCP server connected will also ask about everything
around it; the correct answer then is "the documentation does not cover
this", and until now no eval measured whether the system says so. Each case
records why it is outside the corpus so a reviewer can disagree.
"""

from typing import Any

DATASET_NAME = "rag/negative-v1"

CASES: list[dict[str, str]] = [
    {
        "id": "copilot-custom-instructions",
        "question": "How do I write custom instructions for GitHub Copilot in VS Code?",
        "why_outside": "GitHub Copilot is not one of the indexed products.",
    },
    {
        "id": "windsurf-cascade-rules",
        "question": "Where do Windsurf Cascade rules live and how are they scoped?",
        "why_outside": "Windsurf is not an indexed product.",
    },
    # Replaced 2026-10-12 (full-corpus audit): "claude-api-pricing" is now
    # answered by Cursor's model-pricing tables (cursor.com/docs/models-and-pricing.md).
    {
        "id": "renovate-grouping",
        "question": "How do I configure Renovate to group dependency updates into one pull request?",
        "why_outside": "Renovate is not an indexed product.",
    },
    {
        "id": "claude-messages-api-streaming",
        "question": "How do I stream a response from the Claude Messages API in Python?",
        "why_outside": "Messages API reference is not indexed; only Claude Code pages are.",
    },
    # Replaced 2026-10-12: "cursor-subscription-price" is now answered by
    # cursor.com/docs/models-and-pricing.md > Plans ("Pro | $20/mo").
    {
        "id": "postgres-gin-index",
        "question": "When should I use a GIN index instead of a B-tree index in PostgreSQL?",
        "why_outside": "General database knowledge; no indexed product documents it.",
    },
    {
        "id": "python-decorator",
        "question": "How do I write a decorator in Python that caches function results?",
        "why_outside": "General programming; no product documentation involved.",
    },
    {
        "id": "openai-fine-tuning",
        "question": "How do I fine-tune an OpenAI model on my own dataset?",
        "why_outside": "OpenAI platform fine-tuning docs are not indexed; only Codex pages.",
    },
    {
        "id": "langchain-retriever",
        "question": "How do I build a hybrid retriever with LangChain and Qdrant?",
        "why_outside": "LangChain and Qdrant docs are not part of the corpus.",
    },
    # Replaced 2026-10-12: "mcp-spec-2024-transport" is now answered by the
    # current spec's streamable-http.md > Backward Compatibility > HTTP+SSE
    # Transport (2024-11-05).
    {
        "id": "sentry-django-tracing",
        "question": "How do I enable Sentry performance tracing in a Django application?",
        "why_outside": "Sentry and Django are not indexed products.",
    },
    {
        "id": "jetbrains-ai-assistant-mcp",
        "question": "How do I add an MCP server to JetBrains AI Assistant?",
        "why_outside": "JetBrains client docs are not indexed.",
    },
    {
        "id": "launchdarkly-feature-flags",
        "question": "How do I set environment-specific feature flags in LaunchDarkly?",
        "why_outside": "LaunchDarkly is unrelated to the indexed products.",
    },
    {
        "id": "kubernetes-deploy",
        "question": "How do I deploy an MCP server on Kubernetes with a Helm chart?",
        "why_outside": "Deployment tooling outside the spec and vendor docs.",
    },
]


def expected_output(case: dict[str, str]) -> dict[str, Any]:
    return {"expect_abstention": True}
