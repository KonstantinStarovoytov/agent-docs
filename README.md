# rag-context-assembly

**Ask questions about Claude Code, Cursor, Codex and MCP — get answers grounded in their official docs, with citations.**

A hybrid RAG service that AI agents call through two MCP tools (or over REST). It
indexes ~600 pages of official documentation, refreshes itself daily, and every
design choice is backed by an experiment.

> Why it is built this way, what was tested, and a glossary of every term:
> **[ARCHITECTURE.md](ARCHITECTURE.md)**

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/flow/agent-docs-flow-dark.gif">
  <img alt="Animation: an agent asks how to create a skill; search_docs finds the page, read_section returns the section, Langfuse measures every step" src="docs/flow/agent-docs-flow-light.gif">
</picture>

**[Step through it at your own pace](https://konstantinstarovoytov.github.io/rag-context-assembly/)** (arrow keys work), or open the stills:

<details>
<summary>The 15 steps as still images</summary>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/flow/steps/step-01-dark.webp">
  <img alt="Step 1: The question" src="docs/flow/steps/step-01-light.webp">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/flow/steps/step-02-dark.webp">
  <img alt="Step 2: The agent plans the call" src="docs/flow/steps/step-02-light.webp">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/flow/steps/step-03-dark.webp">
  <img alt="Step 3: search_docs goes out" src="docs/flow/steps/step-03-light.webp">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/flow/steps/step-04-dark.webp">
  <img alt="Step 4: Hybrid search over chunks" src="docs/flow/steps/step-04-light.webp">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/flow/steps/step-05-dark.webp">
  <img alt="Step 5: Rank fusion" src="docs/flow/steps/step-05-light.webp">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/flow/steps/step-06-dark.webp">
  <img alt="Step 6: Rerank" src="docs/flow/steps/step-06-light.webp">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/flow/steps/step-07-dark.webp">
  <img alt="Step 7: One chunk per page" src="docs/flow/steps/step-07-light.webp">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/flow/steps/step-08-dark.webp">
  <img alt="Step 8: What the agent receives" src="docs/flow/steps/step-08-light.webp">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/flow/steps/step-09-dark.webp">
  <img alt="Step 9: read_section maps the page" src="docs/flow/steps/step-09-light.webp">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/flow/steps/step-10-dark.webp">
  <img alt="Step 10: read_section returns the section" src="docs/flow/steps/step-10-light.webp">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/flow/steps/step-11-dark.webp">
  <img alt="Step 11: A cited answer" src="docs/flow/steps/step-11-light.webp">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/flow/steps/step-12-dark.webp">
  <img alt="Step 12: Search is traced" src="docs/flow/steps/step-12-light.webp">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/flow/steps/step-13-dark.webp">
  <img alt="Step 13: Evals: code and an LLM judge" src="docs/flow/steps/step-13-light.webp">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/flow/steps/step-14-dark.webp">
  <img alt="Step 14: The regression gate" src="docs/flow/steps/step-14-light.webp">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/flow/steps/step-15-dark.webp">
  <img alt="Step 15: Refreshed every day" src="docs/flow/steps/step-15-light.webp">
</picture>

<sub>Source and how to rebuild: [docs/flow/](docs/flow/)</sub>

</details>

---

## How it works

Your agent calls a **remote MCP server** with two tools: `search_docs`, then
`read_section` when a passage is not enough. No model runs on this path; the
agent writes the answer itself. The animation at the top walks through it.

The `/ask` REST endpoint, for clients that are not agents, adds a few steps
after the rerank:

| Step | What happens | Why |
|---|---|---|
| **Translation** (`/ask` only) | Non-English questions get an English copy; both are searched. | The docs are in English. |
| **Hybrid search** | Each query is searched by meaning (embedding) and by exact words (BM25) in Qdrant. It asks for 3x more results than needed. | Meaning finds concepts; BM25 finds exact names like `.cursorrules`. |
| **RRF fusion** | The result lists are merged by rank; equal scores are ordered by chunk id. | Scores of the two searches are not comparable; ranks are. The tie-break makes the same question return the same results. |
| **Rerank** | Cohere reads the question with each candidate and scores the match. | Search is fast but rough; the reranker is precise. |
| **Threshold** (`/ask` only) | If even the best candidate scores below 0.55, the bot says the docs do not cover it, without calling the model. Otherwise candidates below 0.35 are dropped. | This is how it refuses to guess. |
| **Context selection** (`/ask` only) | The 8 best chunks go to the model, at most 2 from one section. | One section must not fill the whole context. |
| **Answer** (`/ask` only) | gpt-6-luna answers only from those 8 chunks and cites them. | Every claim can be checked. |

`search_docs` stops after the rerank and returns the best passage of each
page, so one long page cannot fill the list. Each passage carries the page's
one-line description and the headings of the page's other matching sections
(`other_sections`). The agent reads the passages itself, which is cheaper;
for a longer read, `read_section` returns a page's outline, then one section's
text from the stored page (no model call). Searches are traced in Langfuse;
`read_section`, which calls no model, is not.

## Fresh every day

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/diagrams/readme-daily-refresh-dark.png">
  <img alt="Daily refresh: discover, gate, index, report" src="docs/diagrams/readme-daily-refresh-light.png">
</picture>

<sub>Diagram source: [docs/diagrams/readme-daily-refresh.mmd](docs/diagrams/readme-daily-refresh.mmd)</sub>

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

Two ways in, one header each:

- **Your own Cohere key:** `X-Cohere-Api-Key: <key>`. A free trial key is at
  [dashboard.cohere.com](https://dashboard.cohere.com). Reranking runs on your
  key; the key is used for that request only and never stored or logged.
  Limit: 30 requests/min per IP.
- **A token from the owner:** `Authorization: Bearer <API_TOKEN>`.

**As an MCP server** (Claude Code, Cursor, OpenWebUI, any MCP client):

```json
{
  "mcpServers": {
    "agent-docs": {
      "url": "https://agent-docs-mcp.onrender.com/mcp/",
      "headers": { "X-Cohere-Api-Key": "<your Cohere key>" }
    }
  }
}
```

| Tool | Returns |
|---|---|
| `search_docs(query, limit=8, product=None, response_format="concise")` | Ranked passages, one per page, each with the page's one-line description and a Cohere relevance score. One call per part of a multi-part question. `product`: `claude-code`, `cursor`, `codex`, `mcp` |
| `read_section(url, heading=None, offset=0, outline_depth=2)` | No heading: page description and a compact outline (top-level sections with subsection counts; `outline_depth=3` adds subsections). With a heading: the full section text, up to 8,000 characters (`next_offset` for the rest). No model call |

REST also offers `/ask` (a written answer with citations) and `/pages` (page
cards) for clients that are not agents.

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
| `POST /search` | Passages with page descriptions |
| `POST /pages` | Page cards: description and outline |
| `POST /section` | One section of a page (`read_section`) |
| `POST /mcp/` | MCP (streamable HTTP) |
| `GET /docs` | Interactive API docs (use **Authorize** with the token) |

With your own key, replace the `Authorization` line in the curl with
`-H "X-Cohere-Api-Key: $COHERE_API_KEY"`.

**Try it.** The quickest way is your own free Cohere trial key (above), limited
to 30 requests a minute per IP. Or open an
[issue](https://github.com/KonstantinStarovoytov/rag-context-assembly/issues/new?title=Guest%20token%20request)
titled "Guest token request" for a shared guest token. The first request after
15 idle minutes takes about a minute while the free host wakes up.

Listed in the [official MCP Registry](https://registry.modelcontextprotocol.io)
as `io.github.KonstantinStarovoytov/agent-docs` ([server.json](server.json)).

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
| One answer (`/ask`) | **≈ $0.0007** (OpenAI; rerank on the free trial) |
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
| `src/prompts/` | Prompts, versioned in Langfuse |
| `evals/` | The eval gate: datasets, runners, scorers ([guide](evals/README.md)) |
| `reports/` | Experiment results and daily change reports ([index](reports/README.md)) |
| `docs/` | Diagrams, the animation, findings, publishing notes |
| `data/manifests/` | What each index holds, page by page |
| `scripts/` | Diagram rendering, Langfuse CLI with the project's keys |

Diagrams: edit `docs/diagrams/*.mmd`, then `uv run python scripts/render_diagrams.py`.
Animation: edit `docs/flow/index.html`, then `docs/flow/render.sh`.

## License

[MIT](LICENSE)
