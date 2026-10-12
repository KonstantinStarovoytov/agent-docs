"""Unit tests use dummy credentials and never depend on the developer's .env."""

import os

for name in (
    "OPENAI_API_KEY",
    "COHERE_API_KEY",
):
    os.environ[name] = "test-placeholder"

# Langfuse credentials stay unset on purpose. With keys present, Langfuse
# registers a global OTel span processor, and the MCP SDK's own spans are then
# exported over the network from unit tests.
for name in (
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
):
    os.environ.pop(name, None)

os.environ["TRACING_ENABLED"] = "false"
os.environ["LANGFUSE_TRACING_ENABLED"] = "false"

# Most pipeline tests stub the reranker with bare objects that carry no score.
# The top-score abstain rule is tested on its own (test_abstain_top_score.py).
os.environ["MIN_TOP_RERANK_SCORE"] = ""
