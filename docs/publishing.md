# Publishing the MCP server

Everything below runs from your own GitHub account. Nothing here exposes a
secret: `server.json` declares that a token is needed but does not contain one.

## Before you publish

- Keep **`API_GUEST_TOKEN`** set on Render. That token is what people get when
  they ask in an issue. To revoke it, clear the variable and redeploy.
- Every public request spends the **Cohere trial quota** (1,000/month per key).
  Hand out the guest token on request rather than publishing it.

## 1. Official MCP Registry

The registry hosts [server.json](../server.json). It was checked against the
2025-12-11 schema.

```bash
brew install mcp-publisher
cd rag-context-assembly
mcp-publisher login github      # opens a browser; uses your GitHub account
mcp-publisher publish           # reads ./server.json
```

Check that it is listed:

```bash
curl "https://registry.modelcontextprotocol.io/v0/servers?search=io.github.KonstantinStarovoytov/agent-docs"
```

To publish an update, bump `version` in `server.json` and run `publish` again.

## 2. Glama

Glama indexes public GitHub MCP servers automatically. If the server does not
appear on its own, add the repository URL at
<https://glama.ai/mcp/servers> ("Add server"), then claim it with your GitHub
account.

## 3. awesome-mcp-servers

Open a pull request to <https://github.com/punkpeye/awesome-mcp-servers> that
adds one line under the knowledge / documentation search category:

```markdown
- [KonstantinStarovoytov/rag-context-assembly](https://github.com/KonstantinStarovoytov/rag-context-assembly) 🐍 ☁️ - Hybrid RAG over the official docs of Claude Code, Cursor, OpenAI Codex and MCP (~600 pages, refreshed daily): `search_docs` returns one passage per page, `read_section` reads whole sections.
```

Follow that repository's legend for the emoji (language, hosting).

## 4. Portfolio card

**Agent Docs MCP.** A remote MCP server that lets coding agents search the
official documentation of Claude Code, Cursor, OpenAI Codex and MCP: about 600
pages, refreshed daily, with a gate that quarantines junk pages.

- **Retrieval:** hybrid search (embeddings + BM25, fused with RRF), then
  Cohere rerank; one passage per page.
- **Agent-first tools:** `search_docs`, then `read_section` for whole
  sections. There is no LLM on the agent path.
- **Measured:** every design decision has an experiment behind it. The main
  finding: the right page is almost always found, and the hard part is
  choosing what the model sees.
- **Ops:** runs on free tiers ($0/month) with a daily re-index, a readable
  change report and Langfuse tracing.

Links: [repository](https://github.com/KonstantinStarovoytov/rag-context-assembly) ·
[architecture and experiments](https://github.com/KonstantinStarovoytov/rag-context-assembly/blob/main/ARCHITECTURE.md) ·
MCP Registry entry `io.github.KonstantinStarovoytov/agent-docs`
