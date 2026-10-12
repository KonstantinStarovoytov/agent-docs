# Per-page cap on the candidate pool (2026-10-12)

Follow-up to [full-corpus-eval-2026-10.md](full-corpus-eval-2026-10.md),
whose first recommendation was to cap how many chunks one page may put into
the candidate pool before rerank.

## What was built

`MAX_CHUNKS_PER_SOURCE_IN_POOL` (`settings.max_chunks_per_source_in_pool`,
default `None`). `cap_per_source()` in `src/rag/retriever.py` walks the
candidates in RRF order, skips a chunk once its page (`metadata.source`) has
N chunks, and keeps filling from the 3× over-fetch, so the pool keeps its size
when enough distinct pages exist. It is applied in `search_hybrid` (answer
pipeline, `core.search`, and every eval runner, which call it directly) and
again on the fused list in `search_queries_hybrid`. Unit tests:
`tests/test_pool_source_cap.py`.

## Setup

Same as the failed gate: `agent_docs_hybrid_v1`, `GENERATION_TOP_K=8`, judge
`gpt-6-sol`, same datasets and runners (`run_experiments --dataset ...`,
`run_evidence_coverage_experiment`, `run_answer_quality_experiment` with and
without `--negative`). Runs were spaced 70 s apart. Cap = None was re-run in
the same session to re-establish today's numbers.

**The Cohere trial key ran out of its monthly quota (1000 calls) during the
cap = 2 runs.** From the cap = 2 evidence-coverage run onwards, every rerank
call returned 429 ("limited to 1000 API calls / month"); no fallback key is
configured. Those runs are invalid and are marked "n/a". Re-running them is
not possible until the quota resets.

## Results

Gate thresholds are the pre-Oct-11 baselines minus 0.03.

| Dataset / metric | Gate | None | Cap 2 | Cap 3 |
|---|---|---|---|---|
| retrieval-v3 hit@5 (Cohere) | ≥ 0.949 | 0.957 | **0.872** | n/a (47/47 items 429) |
| retrieval-v3 MRR (Cohere) | ≥ 0.835 | **0.825** | **0.739** | n/a |
| query-transform hit@5 (Cohere) | ≥ 0.845 | 0.938 | 0.896 | n/a (48/48 items 429) |
| query-transform MRR (Cohere) | ≥ 0.829 | **0.757** | **0.704** | n/a |
| evidence coverage, complete (k=8, answer runner) | ≥ 0.720 | **0.625** | n/a (16/16 items 429) | n/a |
| faithfulness | ≥ 0.964 | 0.998 | n/a | n/a |
| negative-v1 abstention | 1.000 | 1.000 | n/a (12/12 items 429) | n/a |
| full-corpus-v1 hit@5 (Cohere) | ≥ 0.9 | 1.000 | n/a (20/20 items 429) | n/a |

Same retrieval runs without Cohere (the runner's second arm, which does not
call Cohere, so it completed for every cap):

| Dataset / metric | None | Cap 2 | Cap 3 |
|---|---|---|---|
| retrieval-v3 hit@5 | 0.957 | 0.872 | 0.936 |
| retrieval-v3 MRR | 0.739 | 0.690 | 0.713 |
| query-transform hit@5 | 0.917 | 0.917 | 0.875 |
| query-transform MRR | 0.788 | 0.718 | 0.732 |
| full-corpus-v1 hit@5 | 0.950 | 0.950 | 1.000 |
| full-corpus-v1 MRR | 0.933 | 0.958 | 0.950 |

Pool-level evidence coverage (no Cohere, no LLM): does the evidence reach the
10-chunk rerank pool at all? (16 cases, `search_hybrid(question, k=10)`)

| Cap | Complete coverage in pool | Groups covered | Distinct pages in pool |
|---|---|---|---|
| None | 0.625 | 0.781 | 6.3 |
| 2 | 0.562 | 0.729 | 7.4 |
| 3 | 0.625 | 0.760 | 6.6 |

## Decision

**No cap ships. The default stays `None`.** (`render.yaml` carries retrieval
settings, but there is nothing to change.)

- Cap 2 was measured on the production (Cohere) path for both retrieval sets
  and is clearly worse: retrieval-v3 hit@5 0.957 → 0.872 and MRR 0.825 →
  0.739; query-transform MRR 0.757 → 0.704. It fails the gate by a wide margin
  regardless of the missing coverage numbers.
- Cap 3 could only be measured without Cohere. There it is also below None on
  both MRRs (0.739 → 0.713, 0.788 → 0.732) and does not put more evidence in
  the pool (0.625 both). There is no sign it would pass.
- The cap removes good second chunks from the right page and refills with
  neighbouring pages that the rerank then ranks above the target.

## Why the cap does not help: the evidence

The evidence that is missing from the pool is missing with or without the cap.
For the six cases still incomplete at cap = None, the pool usually already has
≤ 2 chunks per page; the expected page loses to sibling pages, not to one
dominant page:

- *cursor-hooks-and-subagents*: pool is `cloud-agent/mobile.md` (2),
  `agent/agent-review.md` (2), `cloud-agent/self-hosted/my-machines.md`,
  `self-hosted/pool.md`, `cloud-agent/setup.md`. Cap 2 adds nothing.
- *cursor-rules-mcp-subagents*: ten different pages already; `mcp.md` and the
  rules page are pushed out by the Python SDK, CLI and Agent SDK pages.
- *mcp-versioning-and-client-build*: seven spec / learn pages (`versioning`,
  `basic/index`, `streamable-http`, `architecture/index`); `build-client.md`
  is absent at every cap.
- *codex-agents-md-vs-rules*: `third-party/gitlab.md` and `github.md` take
  slots; cap 2 only adds `cursor/release-notes.md`.
- Where one page does dominate (*persistent-instructions*: `memory.md` 6 of
  10; *claude-plugin-composition*: `features-overview.md` 4 of 10), the cap's
  refill brings in more Claude pages (`best-practices.md`,
  `claude-directory.md`, `plugins/components.md`), not the missing Codex
  `AGENTS.md` or `sub-agents.md`.

## What the data supports next

The second recommendation of the full-corpus report: a **page-type prior or
tiered index** that ranks guide pages above enterprise / cloud-agent /
self-hosted, integration (`third-party/*`, `integrations/*`), SDK-reference
and spec pages unless the query asks for them. In every incomplete case above
the crowders are pages of those kinds, and the cap cannot push them out
because they are distinct pages. For cross-vendor questions
(*persistent-instructions-claude-vs-codex*) the pool is single-vendor, which
points to balancing by vendor rather than by page. Neither is implemented here.

## Concerns

- The Cohere trial quota is exhausted for October. Until it resets, or a
  production / fallback key is set, no rerank experiment can run. If Render
  uses the same key, production reranking is affected too; check
  `COHERE_API_KEY` / `COHERE_API_KEY_FALLBACK` there.
- Cap 3 and every coverage / faithfulness / abstention number for the caps are
  unmeasured. The decision rests on cap 2 retrieval (complete), cap 3 without
  rerank, and the pool-level coverage probe.
- The cap = None re-run reproduces the failed gate (MRR 0.825 vs 0.826,
  coverage 0.625), so the failure is stable, not noise.
