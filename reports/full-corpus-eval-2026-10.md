# Full-corpus eval gate (2026-10-12)

On 2026-10-11 `agent_docs_hybrid_v1` was rebuilt from 35 curated pages to the
full corpus (617 pages, 12,913 chunks) without running the gate. This report
runs it after the fact. The old index no longer exists, so each baseline is the
most recent Langfuse run recorded before 2026-10-11 on the same dataset with
the same pipeline.

Settings: generator `gpt-6-luna`, judge `gpt-6-sol`, `GENERATION_TOP_K=8`
(set explicitly), production retrieval path (query rewrite + hybrid +
multi-query RRF + Cohere rerank). No item failures and no Cohere 429s in any
run. Gate: a regression metric fails if it drops by more than 0.03.

**Verdict: FAIL.** hit@5 and faithfulness held, and so did abstention.
Ranking quality (MRR) and complete evidence coverage dropped. The new pages
are retrieved well (full-corpus hit@5 = 1.00).

## Results

### `rag/retrieval-v3` (47 cases), Cohere path

Baseline: `rewrite-hybrid-cohere-multisource-v1`, 2026-09-11 22:23. "Now" is
the run made after the label-gap fixes (2026-10-12 11:38). The first run
before those fixes scored hit@5 0.957 and MRR 0.784.

| Metric | Baseline | Now | Delta | Result |
|---|---|---|---|---|
| hit@5 | 0.979 | 0.957 | -0.022 | pass |
| MRR | 0.865 | 0.826 | -0.039 | **FAIL** |
| precision@8 | not recorded | 0.460 | n/a | n/a |

Without Cohere (`rewrite-hybrid-multisource-v1`, 2026-09-11 22:21), not the
production path: hit@5 0.979 → 0.957, MRR 0.813 → 0.758 (-0.055).

### `rag/retrieval-query-transform-v1` (48 cases)

The runner's schema matches this dataset (question + `relevant`), so
`run_experiments --dataset` was used. Matching-pipeline baseline:
`query-transform-v1`, 2026-09-11 22:52. The latest run before Oct 11 is the
`query-transform-original-semantic-v1` ablation (2026-09-12), with a different
query set: hit@5 1.000, MRR 0.943.

| Metric | Baseline | Now | Delta | Result |
|---|---|---|---|---|
| hit@5 | 0.875 | 0.979 | +0.104 | pass |
| MRR | 0.859 | 0.767 | -0.092 | **FAIL** (-0.176 vs the ablation run) |
| precision@8 | not recorded | 0.529 | n/a | n/a |

### `rag/evidence-coverage-v1` (16 cases)

Baseline: `answer-quality-baseline-k8`, 2026-09-23 00:37, which used the same
k=8 and the same judge. The older `evidence-coverage-baseline-v3` run
(2026-09-13, k=5) is not comparable. "Now" is after the label fixes. Before
them, complete coverage was 0.562 and faithfulness 0.980.

| Metric | Baseline | Now | Delta | Result |
|---|---|---|---|---|
| complete evidence coverage | 0.750 | 0.625 | -0.125 | **FAIL** |
| faithfulness | 0.994 | 0.987 | -0.007 | pass |

### `rag/negative-v1` (12 cases)

Baseline: `negative-abstention-k8`, 2026-09-23 00:43.

| Metric | Baseline | Now | Delta | Result |
|---|---|---|---|---|
| abstention_correct | 1.000 | 1.000 | 0.000 | pass |

Three of the 12 questions are new (see below), so this comparison is not
exactly like for like.

### New dataset `rag/full-corpus-v1` (20 cases, 5 per product)

| Metric | Now | Threshold | Result |
|---|---|---|---|
| hit@5 | 1.000 | ≥ 0.9 | pass |
| MRR | 0.975 | n/a | n/a |

The first run scored hit@5 0.950. Its only miss was a label gap in my own
draft, fixed below.

## Negative set re-audit

I ran `core.search(q, limit=3)` for each of the 12 questions and read the top
passages.

| Case | Decision | Evidence |
|---|---|---|
| claude-api-pricing | **replaced** → renovate-grouping | Cursor's pricing tables now list Claude Opus per-million-token rates (`cursor.com/docs/models-and-pricing.md`, score 0.94) |
| cursor-subscription-price | **replaced** → postgres-gin-index | `models-and-pricing.md > Plans`: "Pro \| $20/mo" |
| mcp-spec-2024-transport | **replaced** → sentry-django-tracing | `specification/.../streamable-http.md > Backward Compatibility > HTTP+SSE Transport (2024-11-05)` describes the old transport |
| claude-messages-api-streaming | kept | Top hits are Agent SDK streaming (`include_partial_messages`), not the Messages API. Borderline; worth watching |
| copilot, windsurf, python-decorator, openai-fine-tuning, langchain, jetbrains, launchdarkly, kubernetes | kept | Top passages are about other products or only share keywords (e.g. Codex `[features]` flags for LaunchDarkly) |

The three replacements scored low on retrieval (top score 0.26, 0.13 and
0.26). The old items were deleted with `dataset_items.delete` and the set was
re-seeded.

## Label-gap corrections

Each of these is a newly indexed page (or a renamed page) that answers the
question. Real regressions were not relabelled.

| Dataset / case | Added target | Evidence |
|---|---|---|
| retrieval-v3: "When should I move instructions from CLAUDE.md into a skill?" | `costs.md` > "Move instructions from CLAUDE.md to skills" | The section is this exact advice |
| retrieval-v3: "How do I add an MCP server to Claude Code?" | `mcp-quickstart.md` | "Add and verify a server" walks through registering a server |
| retrieval-v3: "What is SKILL.md used for?" | `glossary.md` > Skill | It defines a skill as a `SKILL.md` file with instructions, knowledge or a workflow |
| retrieval-v3: "How do skills affect Claude Code context usage?" | `how-claude-code-works.md` > The context window | It says skills load on demand and only descriptions load at start |
| evidence-coverage: mcp-server-concepts group | spec `server/index.md` | It lists the server primitives (prompts, resources, tools) and their control model |
| evidence-coverage: claude-plugin-package group | `en/plugins/create.md` | The page moved from `en/plugins.md` on 2026-09-27 (dc28368). This is a stale label, not a corpus gap |
| full-corpus-v1 (my draft): Cursor `--worktree` case | `cli/using.md` > CLI worktrees | It states the same flag and the `~/.cursor/worktrees/<reponame>/<name>` path |

To allow these, evidence groups can now carry `alternatives` (in
`evals/evidence_coverage.py`, with a test). After each fix the dataset was
re-seeded and re-run.

## What crowds out the expected pages

Across the retrieval-v3 and query-transform runs, 81 results ranked above
the first relevant hit. 52 of them come from newly indexed pages. Most are
enterprise, security, integration and sibling-feature pages that mention the
same feature:

- `cursor/agent/security.md` and `enterprise/model-and-integration-management.md` push down `cursor/mcp.md`
- `integrations/linear.md`, `grok-bot/work.md` and `bugbot.md` (rules) push down the Cursor rules and skills pages
- `claude workflows.md` ("dynamic workflows") pushes down "reusable workflow → skill"
- `desktop.md` and `mcp-quickstart.md` push down `mcp.md`

**`specification/.../schema.md` (495 chunks) never appears in any top-10.**
Excluding it would not fix the retrieval misses.

The evidence-coverage losses are caused by crowding within the 8-slot
context:

- *MCP versioning + client*: spec `basic/versioning.md` (2 chunks),
  `streamable-http.md`, `basic/index.md` (2) and `architecture/index.md` push
  `develop/build-client.md` out of the top 8.
- *Plugin workflow split*: `features-overview.md` takes 4 of 8 slots, and
  `plugins/create.md` takes 3 more, so `sub-agents.md` is missing.

## Recommendations

Retrieval code was not changed. The rebuilt index is already serving production; mitigations, in the order the evidence supports:

1. **Cap chunks per source in the candidate pool and in context selection**
   (e.g. ≤ 2 per page). This directly addresses both evidence-coverage
   failures, which are single pages or the spec cluster taking 3–4 of 8 slots.
2. **Tiered index or a page-type prior**: rank guide pages above
   enterprise/admin, integration and spec pages unless the query asks for them.
   This is the main cause of the MRR drop (52/81 crowders are new pages of this
   kind).
3. Excluding `schema.md` is cheap and reasonable for index size, but the
   evidence shows it has no effect on these metrics. Do not expect it to fix
   the gate.
4. After each change, re-run this gate. Also add precision@8 to the next
   baseline, since the September runs did not record it.

Smaller concerns:

- The query-transform MRR baseline is from a run made a month ago with an
  older query-rewrite setup. Part of the -0.09 may not be caused by the
  corpus.
- `claude-messages-api-streaming` is now a borderline negative.
- Baseline scores for runs made before September 13 are only available via
  `GET /traces/{id}`, which is rate-limited to about 5 calls per minute.
