# rag-context-assembly

**Ask questions about Claude Code, Cursor, Codex and MCP — get answers grounded in their official docs, with citations.**

A hybrid RAG service that AI agents call as an MCP tool (or over REST). It
indexes ~600 pages of official documentation, refreshes itself daily, and every
design choice is backed by an experiment.

> Why it is built this way, what was tested, and a glossary of every term:
> **[ARCHITECTURE.md](ARCHITECTURE.md)**

---

## How it works

Your agent calls a **remote MCP server** with one of its tools. Every step
below runs in order, one after another.

```mermaid
flowchart TD
    A["Your agent<br/>Claude Code · Cursor · OpenWebUI"] -->|"remote MCP + Bearer token"| T{"Which tool?"}

    T -->|ask_docs| L{"Question in<br/>Russian or Polish?"}
    L -->|yes| TR["Add an English translation<br/>(2 queries)"]
    L -->|no| Q1["1 query"]
    TR --> S
    Q1 --> S

    T -->|search_docs| S

    S["Hybrid search in Qdrant<br/>dense (meaning) + BM25 (keywords)<br/>3x overfetch"] --> F["RRF fusion<br/>ties broken by chunk id"]
    F -->|"ask_docs: 10 candidates<br/>search_docs: 20 candidates"| R["Cohere rerank<br/>against the original question"]

    R -->|search_docs| P["Best passage of each page,<br/>ranked with scores"]
    R -->|ask_docs| TH{"Best candidate<br/>scores 0.55 or more?"}
    TH -->|no| NO["Answer: not covered<br/>by the documentation"]
    TH -->|yes| SEL["Pick 8 chunks<br/>at most 2 per section"]
    SEL --> G["gpt-6-luna writes the answer<br/>with citations 1, 2, 3"]
```

| Step | What happens | Why |
|---|---|---|
| **Translation** (`ask_docs` only) | Non-English questions get an English copy; both are searched. | The docs are in English. |
| **Hybrid search** | Each query is searched by meaning (embedding) and by exact words (BM25) in Qdrant. It asks for 3x more results than needed. | Meaning finds concepts; BM25 finds exact names like `.cursorrules`. |
| **RRF fusion** | The result lists are merged by rank; equal scores are ordered by chunk id. | Scores of the two searches are not comparable; ranks are. The tie-break makes the same question return the same results. |
| **Rerank** | Cohere reads the question with each candidate and scores the match. | Search is fast but rough; the reranker is precise. |
| **Threshold** (`ask_docs`) | If even the best candidate scores below 0.55, the bot says the docs do not cover it, without calling the model. Otherwise candidates below 0.35 are dropped. | This is how it refuses to guess. |
| **Context selection** | The 8 best chunks go to the model, at most 2 from one section. | One section must not fill the whole context. |
| **Answer** | gpt-6-luna answers only from those 8 chunks and cites them. | Every claim can be checked. |

`search_docs` stops after the rerank and returns the best passage of each
page, so one long page cannot fill the list. The calling
agent reads them itself, which is cheaper. Every request is traced in Langfuse.

To read whole sections, an agent calls `find_pages` (same ranking, one card per
page: description and outline), picks 1–3 pages, then `read_section` (the
section's text from the stored page, no model call).

## Fresh every day

```mermaid
flowchart TD
    C["GitHub Actions, daily"] --> V["Read each vendor's llms.txt"]
    V --> N{"Compare with<br/>the last run"}
    N -->|new page| GATE{"Junk check<br/>size, language,<br/>duplicate, path, LLM"}
    GATE -->|looks fine| IDX["Embed and index"]
    GATE -->|suspicious| QR["Quarantine:<br/>review issue"]
    N -->|changed page| IDX
    N -->|page gone| GUARD{"More than 10%<br/>of a vendor gone?"}
    GUARD -->|no| DEL["Remove from index"]
    GUARD -->|yes| STOP["Remove nothing,<br/>open an issue"]
    IDX --> REP["Readable change report"]
    DEL --> REP
    QR --> REP
```

New pages are indexed automatically; suspicious ones wait for a human. Each run
writes a short report of what changed in the products: [reports/docs-changes/](reports/docs-changes/).

## What it covers

| Product | Source |
|---|---|
| Claude Code (incl. Agent SDK, plugins) | `code.claude.com/docs/llms.txt` |
| Cursor | `cursor.com/llms.txt` |
| Codex | `developers.openai.com/codex/llms.txt` |
| MCP (latest spec, registry, extensions) | `modelcontextprotocol.io/llms.txt` |

---

## Connect

**As an MCP server** (Claude Code, Cursor, OpenWebUI, any MCP client):

```json
{
  "mcpServers": {
    "agent-docs": {
      "url": "https://agent-docs-mcp.onrender.com/mcp/",
      "headers": { "Authorization": "Bearer <API_TOKEN>" }
    }
  }
}
```

| Tool | Returns |
|---|---|
| `ask_docs(question)` | A grounded answer with sources |
| `search_docs(query, limit=8, product=None, response_format="concise")` | Ranked passages only, one per page (cheaper; the agent reasons itself; one call per part of a multi-part question). `product`: `claude-code`, `cursor`, `codex`, `mcp` |
| `find_pages(query, product=None, limit=5)` | Ranked page cards: title, URL, one-sentence description, outline (h1–h3). One call per part of a question |
| `read_section(url, heading=None, offset=0)` | One section of a page, verbatim, up to 8,000 characters (`next_offset` for the rest); no heading gives the full outline |

**Over REST:**

```bash
curl -X POST https://agent-docs-mcp.onrender.com/ask \
  -H "Authorization: Bearer $API_TOKEN" -H 'content-type: application/json' \
  -d '{"question": "How do I add an MCP server in Claude Code?"}'
```

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness, no token |
| `POST /ask` | Answer with citations |
| `POST /search` | Passages only |
| `POST /pages` | Page cards (`find_pages`) |
| `POST /section` | One section of a page (`read_section`) |
| `POST /mcp/` | MCP (streamable HTTP) |
| `GET /docs` | Interactive API docs (use **Authorize** with the token) |

Want to try it? Ask the owner for a guest token. The first request after
15 idle minutes takes about a minute (free hosting wakes up).

**Locally, without a server** (stdio, no token):

```json
{ "mcpServers": { "agent-docs": { "command": "uv",
  "args": ["run", "--directory", "/path/to/rag-context-assembly", "rag-mcp"] } } }
```

---

## Where it runs

| Part | Service | Plan |
|---|---|---|
| API + MCP server | Render (`agent-docs-mcp.onrender.com`) | Free web service |
| Vector index | Qdrant Cloud | Free 1 GB cluster |
| Traces, eval datasets, prompts | Langfuse Cloud | Free Hobby |
| Daily re-index, CI | GitHub Actions | Free |
| Embeddings, answers | OpenAI (`text-embedding-3-small`, `gpt-6-luna`) | Pay per use |
| Rerank | Cohere (`rerank-v4.0-fast`) | Trial key + fallback key |

Deploys run only after CI passes. The whole service is defined in
[render.yaml](render.yaml).

**Deploy your own:** Render → New → Blueprint → this repo. Fill the secrets it
asks for (`OPENAI_API_KEY`, `COHERE_API_KEY`, optional `COHERE_API_KEY_FALLBACK`,
`QDRANT_URL`, `QDRANT_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`);
`API_TOKEN` is generated for you. If you change the host name, update
`API_ALLOWED_HOSTS` (the MCP transport rejects unknown hosts). Revoke a guest
by clearing `API_GUEST_TOKEN`.

## Cost

| What | Cost |
|---|---|
| Hosting, database, tracing, CI | **$0 / month** (free tiers) |
| One answer (`ask_docs`) | **≈ $0.0007** (OpenAI; rerank on the free trial) |
| One search (`search_docs`) | ≈ $0 (one embedding + one rerank) |
| Daily re-index, nothing changed | $0 |
| Daily re-index, a few pages changed | < $0.01 (embeddings + one short LLM check per new page) |
| Full rebuild of the index | ≈ $0.10–0.30 one-off (embeddings ≈ $0.07 + one short LLM check per page) |

Limits of the free setup: Cohere trial allows 1,000 reranks/month per key
(two keys) and 10/minute; the API is capped at 60 paid requests/minute.

---

## Key results

| Change | Measured effect |
|---|---|
| 8 chunks instead of 5 | Questions fully covered: 25% → 75% |
| English translation of non-English questions | Hit@5: 0.958 → 1.000 |
| Candidate pool 10, not 20 | Fully covered: 75% vs 50% (more recall pushed out the second topic) |
| `gpt-6-luna` instead of `gpt-5.6-luna` | Faithfulness: 0.975 → 0.994 |
| Stable tie-break in RRF | Same question → same results (was random) |

Main finding: **search finds the right page; the hard part is choosing what
the model sees.** Details and every experiment: [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Develop

```bash
uv sync --locked                      # Python 3.14
cp .env.example .env                  # OpenAI, Cohere, Qdrant, Langfuse keys
docker compose up -d                  # local Qdrant + API on :8080
uv run python -m src.ask "How do skills work?"
uv run pytest -q && uv run ruff check src evals tests && uv run mypy
```

Re-index locally: `uv run python -m src.reindex --dry-run --out /tmp/r`
(no writes) — or run the **Reindex** workflow in GitHub Actions.

| Folder | Contents |
|---|---|
| `src/ingestion/` | Page selection, chunking, junk gate, change report |
| `src/rag/` | Search, rerank, context selection, generation |
| `src/service/` | REST API and MCP server (one shared handler) |
| `evals/` | Datasets and experiment runners (Langfuse) |
| `reports/` | Experiment outputs and daily change reports |
