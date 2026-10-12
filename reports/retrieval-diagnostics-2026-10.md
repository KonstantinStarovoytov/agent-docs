# Retrieval diagnostics and prefetch/pool screen (2026-10-12)

Follow-up to the failed full-corpus gate ([full-corpus-eval-2026-10.md](full-corpus-eval-2026-10.md)).
Question: where is the correct chunk lost, and does a deeper Qdrant prefetch or
a bigger rerank pool get it back?

**Short answer**

- On today's settings, 10 of 89 question/evidence groups miss the LLM context.
  7 are in the fused list but outside the pool of 10. 3 are not in either top-30
  list. **None is lost by the reranker once it is in the pool.**
- **Prefetch depth changes nothing.** Going from 30 to 150 moves no correct chunk
  into any pool of 10–60. **Pool size is what helps:** complete coverage in the
  pool goes from 0.625 (10) to 0.750 (20) and 0.875 (40).
- **The MRR drop is a ranking problem, not a recall problem.** 65% of the chunks
  ranked above the first correct one are *guide* pages: sibling features,
  another vendor's page for the same feature, or valid answers the labels miss.
  On the two MRR datasets, admin, enterprise, security and integration pages are
  21 of 78 (27%). A bigger pool cannot fix this.
- **The Cohere trial quota was already used up for October** (the first call
  returned the "1000 API calls / month" 429). So the rerank runs for new
  configurations (step 3) are **pending quota reset**. Defaults are unchanged and
  the gate is still **FAIL**.
- Score floor: **keep 0.35** (details in [section 6](#6-rerank-score-floor)).

## 1. Method

Two retrieval paths are rebuilt exactly from Qdrant query results
(`evals/diagnose_retrieval.py`). Neither makes a Cohere call.

| Path | Used by | Today |
|---|---|---|
| production | English questions in production; the evidence-coverage runner | 1 query, dense + BM25 prefetch 30 each, Qdrant RRF, stable tie-break, pool 10 |
| eval | `run_experiments.py`, which produced the gate's retrieval-v3 and query-transform numbers | LLM rewrite (original + English + paraphrase), per query prefetch 60 and top 20, client-side RRF, pool 10 |

- **Slices (a)–(c)** were measured live on `agent_docs_hybrid_v1` (617 pages,
  12,913 chunks): dense top-150, BM25 top-150, fused at prefetch 30/60/100/150,
  and the pool.
- **Slice (d), rerank,** is read from the gate's stored Cohere runs in Langfuse
  (2026-10-12, same index, same settings): retrieval-v3 11:38, query-transform
  11:00, answer-quality 12:02, negative 11:26. The retrieval items store the
  whole reranked pool with each chunk's pool rank. For coverage and negative,
  the rerank span stores all 10 scores. The gate's own rewrites come from the
  multi-query span.
- **Fidelity:** the rebuilt pool equals the stored pool, chunk for chunk, for
  70 of 71 main questions and 48 of 48 query-transform variants. The production
  rebuild is also asserted equal to `search_hybrid` for every production-path
  question.
- **Scope:** retrieval-v3 (47 questions), query-transform clean_en (8) and
  evidence-coverage (16 questions, 34 evidence groups). That is 89 "groups" in
  the main table. All 48 query-transform variants appear in the MRR analysis,
  because the gate's MRR covers all 48.
- **Cohere scores do not depend on the other documents in the call.** 1,054
  unambiguous chunks were scored in two or more of the day's runs, each time with
  different neighbours: 909 got identical scores and none differed by more than
  0.008 (`diagnose_retrieval independence`). So stored scores can be reused, and
  `EvalReranker` with `EVAL_CACHE_DIR` safely skips repeated pairs.

Outputs: [slices table](retrieval-diagnostics-2026-10-slices.md),
[screen](retrieval-diagnostics-2026-10-screen.md),
[threshold](retrieval-diagnostics-2026-10-threshold.md), JSON dumps
`retrieval-diagnostics-2026-10.json` (per question, every slice, the reranked
pool with labels) and `-stored.json` (the stored gate runs, in case Langfuse
Hobby's 30-day retention drops them).

## 2. Where the correct chunk is lost

Classes: **LOST_BEFORE_FUSION** means the chunk is in neither the dense nor the
BM25 top-*P* list (*P* = 30 on the production path, 60 per query on the eval
path). **LOST_IN_POOL** means it is in a prefetch list but not in the pool of 10.
**LOST_IN_RERANK** means it is in the pool but outside the window after rerank.
**LABEL_GAP** means a chunk ranked above it answers the question but is not
labelled.

| Window | Misses | Before fusion | In pool | In rerank | Label gap (manual) |
|---|---|---|---|---|---|
| LLM context (8 chunks, floor 0.35, 2 per section) | 10 / 89 | 3 (30%) | 6 (60%) | 0 (0%) | 1 (10%) |
| top 5 after rerank (hit@5) | 16 / 89 | 3 (19%) | 6 (38%) | 6 (38%) | 1 (6%) |

The 6 extra top-5 misses are coverage groups at rerank rank 6–7. They still
reach the context, so they do not cost coverage. The same classes on
query-transform (all 48 variants) give 1 miss: LOST_IN_POOL, and a label gap on
review.

Every miss, with the fused rank that shows how far outside the pool it sits:

| Dataset | Question / group | dense | BM25 | fused (p30 → p150) | Class | Manual check |
|---|---|---|---|---|---|---|
| retrieval-v3 | How can I give Cursor reusable instructions for a specific task? | 19 | 23 | – → 40 | IN_POOL | Auto-flagged by `customize-cursor > Skills` (a one-line link card) and `grok-bot/work > Skills and routines` (another product). **Not a gap.** |
| retrieval-v3 | When should I use a skill instead of a subagent? | 68 | 11 | 22 → 19 | IN_POOL → **LABEL_GAP** | The question names no product. Rank 1 is Cursor `subagents.md > When to use subagents`, a "use subagents when / use skills when" table. Rank 2 is Claude `sub-agents.md`: "Consider Skills instead when…". Both answer it. |
| query-transform (natural_en) | I want Cursor to follow some instructions only when it works with Python files | 35 | 3 | 5 → 5 | IN_POOL → **LABEL_GAP** | Rank 1 is `skills.md > Scoping a skill to specific files` (`paths: "**/*.py"`). It answers the question as worded. |
| coverage | persistent-instructions / codex-agents-md | 16 | – | 27 → 33 | IN_POOL | |
| coverage | mcp-versioning / build-client | 7 | 20 | 12 → 13 | IN_POOL | Spec `basic/versioning.md` and `streamable-http.md` fill the pool |
| coverage | codex-agents-md-vs-rules / codex-rules | 8 | 108 | 14 → 12 | IN_POOL | |
| coverage | cursor-hooks-and-subagents / cursor-subagents | 7 | 58 | 14 → 14 | IN_POOL | |
| coverage | claude-plugin-composition / claude-subagents | 17 | 17 | 30 → 29 | IN_POOL | `features-overview.md` takes 4 of 10 pool slots |
| coverage | cursor-hooks-and-subagents / cursor-hooks | 141 | 69 | – → 93 | BEFORE_FUSION | Auto-flagged by `customize-cursor > Hooks` (a link card) and `self-hosted/pool > Hooks` (another feature). **Not a gap.** |
| coverage | cursor-rules-mcp-subagents / cursor-mcp | 32 | 82 | – → 65 | BEFORE_FUSION | |
| coverage | cursor-rules-mcp-subagents / python-rule-glob | – | – | – → – | BEFORE_FUSION | The one labelled chunk (`rules.md > Glob pattern`) is in neither top 150 |

What this means:

- **No miss is fixed by a deeper prefetch.** The column "pool p150" in the
  slices table is empty for every miss.
- **6 of 7 IN_POOL misses would enter a pool of 40** (screen: 1 of 2
  retrieval-v3 misses and 5 of 5 coverage groups).
- **The 3 BEFORE_FUSION misses all come from two multi-part questions** (one
  with three parts, one with two). One embedding of a question that asks about
  several things misses the weaker aspects.

## 3. What ranks above the first correct chunk

Chunks reranked above the first correct one (chunks that answer another
evidence group of the same question are not counted). Path type is taken from
the URL, first rule wins:

- admin-enterprise: `/enterprise`, `/account/`, admin, managed-, gateway, self-hosted, SSO/SCIM, billing…
- security: `security`, cyber, threat-model
- api: `/api/`, `-api.md`, endpoints, webhooks
- sdk: `sdk`
- reference: `reference`, `/specification/`, glossary, changelog, release notes, `/models/`…
- other: integrations, third-party, Grok Bot, Bugbot, Origin, Slack/Jira/Linear…
- guide: everything else

"New" means outside the 35 curated pages indexed before October.

| Type | retrieval-v3 | query-transform (48) | coverage | all | of which new |
|---|---|---|---|---|---|
| guide | 28 | 23 | 64 | 115 (65%) | 49 |
| reference | 2 | 1 | 13 | 16 (9%) | 16 |
| sdk | 0 | 3 | 12 | 15 (8%) | 15 |
| other (integrations, Bugbot, Grok Bot) | 3 | 8 | 4 | 15 (8%) | 15 |
| admin-enterprise | 2 | 2 | 6 | 10 (6%) | 10 |
| security | 1 | 5 | 0 | 6 (3%) | 6 |
| **total** | 36 | 42 | 99 | 177 | 111 (63%) |

On retrieval-v3 + query-transform (the MRR datasets), 51 of 78 outrankers are
new pages. That matches the gate report's 52/81. But only 21 of the 78 are
admin, enterprise, security or integration pages; 51 are guides. The pages that
recur:

- **Sibling features of the same product:**
  - `code.claude.com/.../workflows.md` ("dynamic workflows") above skills for "reusable workflow"
  - `cursor.com/docs/cli/using.md` and `cloud-agent/best-practices.md` above `rules.md`
  - `features-overview.md` (11×) and `learn/architecture.md` (9×) taking several pool slots in coverage questions
- **Another vendor for a product-neutral question:** 18 of 36 retrieval-v3
  outrankers come from a different vendor. 13 of those are in questions that
  name no product.
- **Non-guide pages:**
  - `cursor.com/docs/agent/security.md` (5×) above `mcp.md` for every Cursor-MCP variant
  - `bugbot.md` (5×) above `rules.md`
  - `enterprise/model-and-integration-management.md`
  - Agent SDK pages that repeat guide content (`agent-sdk/claude-code-features.md` above `memory.md`)
  - MCP spec pages (versioning, changelog, `basic/index.md`) above the learn/develop guides

The query-transform MRR loss sits in three intents:

| Intent | MRR | Pushed down by |
|---|---|---|
| cursor-python-rules | 0.25 | skills, Bugbot, CLI |
| cursor-mcp | 0.47 | agent security page, enterprise page |
| claude-on-demand-workflow | 0.58 | workflows.md |

The other five intents score 0.92–1.0.

**What-if on the stored scores** (re-sorting the same reranked pools; no new
calls; the same questions, so the gains are optimistic):

| Re-ranking rule | rv3 MRR | QT MRR | coverage complete |
|---|---|---|---|
| today | 0.826 | 0.767 | 0.625 |
| non-guide pages (sdk, api, security, admin, other) × 0.9 | 0.851 | 0.816 | 0.562 |
| one product named → that vendor's pages first | 0.810 | 0.767 | 0.625 |

A flat page-type penalty would lift both MRRs but costs a coverage case: the
MCP authorization evidence lives under `tutorials/security/`. A penalty must
apply only when the question does not ask for that page type. Product routing,
as tried, does not help.

## 4. Prefetch × pool screen (no rerank)

recall@pool = share of questions (coverage: groups) whose candidate pool holds a
correct chunk. The coverage row also shows complete@pool (every group of the
question in the pool). Full grids: [screen](retrieval-diagnostics-2026-10-screen.md).

| Dataset / path | prefetch 30 / 60 / 100 / 150 (any) | pool 10 | pool 20 | pool 40 | pool 60 |
|---|---|---|---|---|---|
| retrieval-v3 / eval | identical at every prefetch | 0.957 | 0.957 | 0.979 | 1.000 |
| retrieval-v3 / production | identical | 0.957 | 0.957 | 0.979 | 1.000 |
| query-transform (48) / eval | identical | 0.979 | 1.000 | 1.000 | 1.000 |
| query-transform English (24) / production | identical | 0.917 | 0.958 | 1.000 | 1.000 |
| evidence-coverage groups / production | identical | 0.765 | 0.853 | 0.912 | 0.912 |
| evidence-coverage complete / production | identical | 0.625 | 0.750 | 0.875 | 0.875 |

Prefetch depth does not change a single recall cell. It moves the RRF-only MRR
(before rerank) by at most 0.04. The fused top 60 is decided by chunks that rank high in at
least one list, and Qdrant's RRF gives the deep tail too little weight to
reorder them.

**Picked for rerank confirmation:**

- **A: prefetch 60 / pool 20** (`HYBRID_PREFETCH_DEPTH=60 RERANK_POOL=20`)
- **B: prefetch 60 / pool 40** (`HYBRID_PREFETCH_DEPTH=60 RERANK_POOL=40`)

60 is the smallest prefetch that covers both pools; deeper prefetch adds latency
for no recall. Pool 60 gains only one retrieval-v3 question over 40, so it is not
worth 50% more rerank text.

## 5. Rerank runs: pending quota reset

The first Cohere call of this session returned 429, "limited to 1000 API calls /
month". The day's gate and per-page-cap runs had used the month's quota. No
other call was made, and the fallback key is not configured.

| Metric | Baseline (pre-Oct 11) | Gate threshold | Control = today (stored gate run) | A: p60/pool 20 | B: p60/pool 40 |
|---|---|---|---|---|---|
| retrieval-v3 hit@5 | 0.979 | ≥ 0.949 | 0.957 | pending | pending |
| retrieval-v3 MRR | 0.865 | ≥ 0.835 | **0.826** | pending | pending |
| retrieval-v3 precision@8 | – | – | 0.460 | pending | pending |
| query-transform hit@5 | 0.875 | ≥ 0.845 | 0.979 | pending | pending |
| query-transform MRR | 0.859 | ≥ 0.829 | **0.767** | pending | pending |
| query-transform precision@8 | – | – | 0.529 | pending | pending |
| complete evidence coverage | 0.750 | ≥ 0.720 | **0.625** | pending (≤ 0.750) | pending (≤ 0.875) |

**Gate: FAIL**, unchanged. The upper bounds in brackets are complete@pool:
rerank and selection can only keep or lose what the pool holds. Config A could
pass the coverage gate only if the reranker keeps every newly pooled group in the
top 8. Experiment 7 (pool 10 → 20 cut coverage from 0.750 to 0.500 on the small
corpus) is the warning. Neither config is expected to fix MRR (see section 3).

Stored scores cannot stand in for the run: only 51% (A) and 28% (B) of the
coverage pools' candidates have ever been scored.

When the quota resets, the two configs cost about 220 calls, fewer with the
cache. The gate rewrites are frozen in `EVAL_CACHE_DIR` and scores are
batch-independent, so a control rerun reproduces the stored gate run. Skip it
to save about 110 calls, or add it (no env overrides) if a same-session control
is required:

```bash
export EVAL_CACHE_DIR=<dir>  GENERATION_TOP_K=8  OPENAI_JUDGE_MODEL=gpt-6-sol  COHERE_API_KEY_FALLBACK=
uv run python -m evals.diagnose_retrieval slices          # seeds the gate rewrites (no Cohere)
for cfg in "60 20" "60 40"; do set -- $cfg
  HYBRID_PREFETCH_DEPTH=$1 RERANK_POOL=$2 uv run python -m evals.run_experiments --skip-no-rerank --name-suffix "-p$1-pool$2"
  sleep 65
  HYBRID_PREFETCH_DEPTH=$1 RERANK_POOL=$2 uv run python -m evals.run_experiments --dataset rag/retrieval-query-transform-v1 --skip-no-rerank --name-suffix "-p$1-pool$2"
  sleep 65
  HYBRID_PREFETCH_DEPTH=$1 RERANK_POOL=$2 uv run python -m evals.run_answer_quality_experiment --name-suffix "-p$1-pool$2"
  sleep 65
done
```

`EvalReranker` uses the primary key only, waits on a per-minute 429 and stops
on a monthly one.

## 6. Rerank score floor

All 1,230 reranked candidates of the stored gate runs, labelled. Full tables:
[threshold](retrieval-diagnostics-2026-10-threshold.md).

| Score | Correct | Incorrect (answerable sets) | negative-v1 |
|---|---|---|---|
| < 0.30 | 0 | 2 | 71 |
| 0.30–0.35 | 2 | 2 | 10 |
| 0.35–0.40 | 4 | 9 | 6 |
| 0.40–0.50 | 13 | 30 | 9 |
| 0.50–0.70 | 49 | 105 | 13 |
| 0.70–0.90 | 287 | 351 | 11 |
| ≥ 0.90 | 152 | 104 | 0 |

- **On answerable questions, correct and incorrect scores overlap almost
  completely.** Many "incorrect" chunks are valid answers on unlabelled pages. A
  floor cannot pick evidence; it only decides abstention.
- **What a floor must keep:** the weakest *best* correct chunk of any group
  scores **0.416**, and the next is 0.507. The lowest top score of any answerable
  question is **0.64**.
- **Negative questions' top scores:** 0.12, 0.22, 0.24, 0.25, 0.26 | 0.38 | 0.47,
  0.48 | 0.59 | 0.79, 0.83, 0.90 (the Copilot, JetBrains MCP and Messages-API
  streaming questions sit close to real docs).

| Rule | Answerable groups kept | Coverage complete-eligible | Negatives with no chunk |
|---|---|---|---|
| floor 0.30 | 118/118 | 10/16 | 5/12 |
| **floor 0.35 (today)** | 118/118 | 10/16 | 5/12 |
| floor 0.40 | 118/118 | 10/16 | 6/12 |
| floor 0.45 | 117/118 | 9/16 | 6/12 |
| floor 0.50 | 117/118 | 9/16 | 8/12 |
| floor 0.35 and ≥ 0.6 × best | 117/118 | 9/16 | 5/12 |

**Recommendation: keep `min_rerank_score = 0.35`.**

- 0.40 would make one more negative (Kubernetes/Helm, 0.38) abstain without the
  LLM, with no loss on these sets. But the margin to the weakest needed chunk is
  0.016, on 118 groups. negative-v1 abstention is already 12/12; the other 7
  abstain through the prompt. So the gain is mechanical, not a better score.
- Relative rules never help abstention (they always keep the best chunk) and
  cost evidence from 0.6 × best up.
- Worth testing later as a separate rule: abstain when the **top** score is
  below ≈ 0.6. On stored scores that empties 9 of 12 negatives and no answerable
  question (0.585 vs 0.64, a thin margin on author-written questions). It needs
  real traffic before it becomes a default.

## 7. Decision

- **No default changed.** `HYBRID_PREFETCH_DEPTH` and `RERANK_POOL` are new,
  default unset, which is today's behaviour. `render.yaml` is unchanged.
- **Recommended next default, pending rerank:** config B (`RERANK_POOL=40`,
  `HYBRID_PREFETCH_DEPTH=60`), if it keeps complete coverage ≥ 0.72 and does not
  lower either MRR; otherwise A. Recall@pool alone does not justify it, given
  experiment 7.
- `search_docs` already uses `max(limit, PER_QUERY_TOP_K, rerank pool)`, so it
  never reads fewer candidates than `ask_docs`.

## 8. Recommendations for the next step

1. **Labels first (owner decision, not auto-fixed).** Two misses are valid
   answers outside the labels:
   - retrieval-v3 "When should I use a skill instead of a subagent?": Cursor
     `subagents.md > When to use subagents` and Claude `sub-agents.md > Choose
     between subagents and main conversation`
   - query-transform cursor-python-rules natural_en: Cursor `skills.md > Scoping
     a skill to specific files`

   Accepting the first alone would move retrieval-v3 MRR from 0.826 to about
   0.847, past the gate. Its MRR gap is about one question.
2. **Fix BM25 before tuning around it.** The collection's sparse vector has no
   IDF modifier. langchain-qdrant creates `SparseVectorParams()` without one, and
   fastembed warns that `Qdrant/bm25` "is expected to be used with
   `modifier="idf"`". So the BM25 side weighs "cursor" as much as `.cursorrules`.
   Both BEFORE_FUSION misses with a BM25 rank had it at 69–82. IDF is applied at
   query time, so this needs a collection config change, not re-embedding. It
   was out of scope here (no collection changes); it is the cheapest retrieval
   experiment left.
3. **Per-aspect queries (experiment 10) before doc2query.** All 3 BEFORE_FUSION
   misses come from questions that ask about several things. Splitting the
   question into one query per aspect targets them directly. doc2query would need
   re-embedding and the data does not point to a vocabulary gap on single-topic
   questions: only 2 retrieval misses, both in the fused top 40.
4. **Query-aware page-type prior, not a blanket one.** On the MRR datasets,
   admin, security and integration pages are 21 of 78 outrankers (27%), and the
   agent-security, Bugbot and enterprise pages cause most of the
   query-transform losses. A flat penalty gains MRR (0.851 / 0.816 on stored
   scores) but breaks the MCP-authorization coverage case. Demote a type only
   when the question does not ask about it (security, admin, SDK, API).
5. **Reference-page chunking.** Reference pages are 9% of outrankers, mostly MCP
   spec pages (versioning, changelog, `basic/index.md`) and the Claude glossary.
   Glossary entries are tiny chunks that score high and are correct once (SKILL.md).
   Not a priority. Merging tiny glossary or spec sections into their parent
   chunk would reduce near-duplicate pool slots, but the coverage losses come
   from the pool cut, which a bigger pool addresses.
6. **Product routing**, done as "the named product's pages first", lowered
   retrieval-v3 MRR on stored scores (0.826 → 0.810). Most cross-vendor outrankers
   are in questions that name no product. Leave it.

## Code in this change

- `src/config.py`: `hybrid_prefetch_depth`, `rerank_pool` (both default `None`).
- `src/rag/retriever.py`: `prefetch_limit(k)`, `rerank_pool_size()`.
- `src/rag/pipeline.py`: the pool feeds Cohere (`top_n` stays `retrieval_top_k`); per-query k widens to the pool on the translated path and in two-hop mode.
- `src/service/core.py`: the `search_docs` pool is never smaller than the answer pool.
- Tests: `tests/test_prefetch_and_pool.py` (12), `tests/test_eval_cache.py` (3), all with fakes.
- Runners: `run_experiments.py` and `run_answer_quality_experiment.py` follow the settings and take `--name-suffix`; `run_experiments.py` also takes `--skip-no-rerank`.
- `evals/eval_cache.py`: quota-safe, cacheable `EvalReranker`; frozen rewrites.
- `evals/diagnose_retrieval.py`: `slices`, `screen`, `threshold`, `independence`, `summary`.

## Label decisions (2026-10-12)

The owner accepted both label gaps. The ground truth now lists the found pages
as additional valid answers (any match counts):

- "When should I use a skill instead of a subagent?" — added Cursor
  `subagents.md` > *When to use subagents* and Claude Code `sub-agents.md`.
- Query-transform "Python files" — added Cursor `skills.md` > *Scoping a skill*.

Both Langfuse datasets were re-seeded (47 and 48 items). The effect on MRR is
measured in the pending reranked run.
