# rag-context-assembly: RAG architecture findings

Consolidated record of the literature review, the code changes derived from it, and the
measurements that supported or contradicted them. Written for external review: every
number is stated with the run it came from, and unverified claims are marked as such.

Date of the measurements: 2026-09-13/14. Corpus, prompts and code are as of that date.

Review correction: the historical probes below do not isolate rerank pool size.
`search_hybrid(k)` currently passes `3*k` to LangChain, which changes both dense
and sparse prefetch depth. A larger pool comparison therefore also changes retrieval.
Overfetch plus sorting improves observed stability but does not guarantee it when
ties cross the overfetch boundary. The new `evals/experiments/frozen_selection.py` experiment
captures one common pool and compares selectors offline; it does not reuse these
historical numbers as its control. Source coverage remains a proxy for answerability.

---

## 1. System under test

RAG over agent-tooling documentation (Claude Code, Cursor, Codex, MCP).

- Corpus: 996 chunks from 36 documents, 4 vendors (`anthropic`, `cursor`, `openai`,
  `model-context-protocol`). Qdrant collection `agent_docs_hybrid_v1`.
- Retrieval: hybrid, OpenAI dense embeddings + BM25 sparse, fused with RRF.
- Reranking: Cohere, against the **original** question (never against a rewritten query).
- Generation: answer with citations, context assembled by `select_generation_context`.
- Optional pre-retrieval translation of non-English queries to English.
- Optional bounded two-hop retrieval (`--iterative`), off by default.
- Tracing and datasets: Langfuse; prompts are managed with a `production` label and
  pinned by version in evals.

Relevant modules: `src/rag/{retriever,multi_query_retriever,reranker,context_selector,planner,iterative,pipeline}.py`,
`src/config.py`, `evals/evidence_coverage.py`, `evals/run_evidence_coverage_experiment.py`.

---

## 2. Literature input

### 2.1 Verification status (important for reviewers)

- `arXiv:2604.23783` — **S2G-RAG: Structured Sufficiency and Gap Judging for Iterative
  Retrieval-Augmented QA**. Title confirmed this session by fetching the arXiv abstract page.
- `arXiv:2608.13237` — **When Should Multi-Round RAG Stop? Structured Stopping Judgments
  and Retrieval Reduction in Search-R1**. Title confirmed this session the same way.
- `arXiv:2404.14043` — MIGRES / *LLMs Know What They Need* (COLING 2025). Read earlier in
  the session; **not re-verified** in this session.
- `arXiv:2407.01219` (Searching for Best Practices in RAG, EMNLP 2024),
  `arXiv:2403.14403` (Adaptive-RAG, NAACL 2024), `arXiv:2408.08067` (RAGChecker, NeurIPS 2024)
  — IDs carried over from the user's reading list; an arXiv API search for them returned
  HTTP 503 this session, so they are **unverified here**.
- Venue labels (ACL 2026 etc.) come from the user's review, not from independent checking.

The architectural descriptions below are summaries of what was read, not quotations.

### 2.2 What was taken from the papers

**S2G-RAG.** Separates two things that are usually merged: a judge decides whether the
current evidence is sufficient and, if not, emits structured gap items; a separate,
largely deterministic step turns a gap into a retrieval query by combining the gap's
target and slot and appending it to the original question. It also keeps a compact
sentence-level evidence context instead of accumulating whole passages. Motivation: an
iterative RAG system either answers on an incomplete evidence chain or accumulates
redundant and distracting context.

**MIGRES.** Retrieve, extract what is useful, identify what is still missing, generate a
targeted query for that gap, retrieve again. Includes sentence-level filtering and a
memory of queries that failed, to avoid repeating them and to avoid hard negatives.

**Searching for Best Practices in RAG.** Ablation-driven pipeline design: do not add a
stage without measuring it. Used here as the governing methodology.

**Adaptive-RAG.** Route queries by complexity between no retrieval, single-step and
iterative retrieval. Deferred: there is no labelled complexity signal in this project.

**Self-RAG.** Reflection and on-demand retrieval, but achieved by training the model with
reflection tokens. The concept is relevant, the implementation is not transferable to a
prompt-only setup.

**RAGChecker / Agentic-R.** Aggregate answer metrics do not tell you whether retrieval or
generation failed; and a passage that is similar to the query is not necessarily useful
for the final answer. Motivated splitting retrieval-side metrics from answer quality.

---

## 3. Prior results carried into this work

From the earlier query-transformation rescore (dataset `rag/retrieval-query-transform-v1`,
48 cases = 8 intents x 6 language/phrasing variants; offline rescore, no new model calls):

| Variant | Hit@1 | Hit@5 | MRR |
|---|---|---|---|
| A: original query | 0.896 | 0.958 | 0.927 |
| B: + English translation | 0.938 | 1.000 | 0.969 |
| C: + semantic rewrite | 0.896 | 1.000 | 0.943 |
| D: English + semantic | 0.938 | 1.000 | 0.969 |

Conclusions encoded in `src/rag/policy.py`: translate non-English queries, no semantic
rewrite (it dropped one English Cursor-rules case from MRR 1.0 to 0.25), iterative
retrieval stays opt-in, no rewrite-after-miss (there were no residual misses at Hit@5).

Caveat: Hit@K on this dataset is satisfied by **one** relevant chunk. It cannot detect a
question whose answer needs two different documents. That limitation is what motivated
the dataset in section 5.

---

## 4. Code change: judge separated from query construction

Implemented per S2G-RAG §"sufficiency vs. gap-to-query".

Before: `EvidencePlanner.assess` returned `sufficient`, `missing_topics` and
`follow_ups[]`, where each follow-up contained a free-text `query` written by the model.

After (`src/rag/planner.py`):

- `RetrievalDecision = {sufficient: bool, gaps: list[Gap]}` (max 3 gaps; a sufficient
  decision may not carry gaps).
- `Gap = {category, target, slot, evidence_ids}` where `category` is restricted to
  `when_to_use | how_to_configure | vendor_constraint | comparison_aspect |
  concept_definition`. The Wikipedia-oriented categories from the paper (bridge entity,
  relation) were replaced with documentation-oriented ones.
- `gap_query(question, gap)` builds the retrieval query deterministically as
  `question + " " + target + " " + slot`. Appending to the original question (rather than
  replacing it) is deliberate: the sparse half of the hybrid retriever depends on product
  names such as `Cursor` or `mcp.json`, which a model-written paraphrase can drop.
- `evidence_ids` is retained from the previous design and is **stricter than the papers**:
  a gap whose cited chunk ids are not in the current context is discarded, which prevents
  follow-ups about capabilities the model invented.
- `src/prompts/evidence-planner.txt` rewritten accordingly ("do not write search queries").

Status: implemented, unit-tested, and exercised in the experiment in section 6. It did not
change the outcome metric — see section 8.

**Open item:** the local prompt now differs from `doc-bot/evidence-planner` v1 in Langfuse.
A new version must be published (`uv run python -m src.prompts.publish`) before tracing
runs are comparable.

---

## 5. New evaluation dataset: multi-aspect coverage

`rag/evidence-coverage-v1`, defined in `evals/evidence_coverage.py`. Expanded from 4 to
**16 cases / 34 evidence groups**. Each case is a question whose answer requires several
independent evidence groups; a group is covered only if a retrieved chunk matches its
target (vendor, source substring, optionally heading substring).

Two families were added deliberately:

- Same vendor, different vocabulary (for example skill vs. subagent in Claude Code, skill
  vs. rule in Cursor, AGENTS.md vs. rules in Codex, server-concepts vs. client-concepts in MCP).
- Cross-vendor comparisons (MCP SDK server plus Cursor registration, MCP config in Claude
  Code vs. Cursor, persistent instructions in Claude Code vs. Codex, hooks in Cursor vs. Codex).

Metrics: `evidence_coverage` = fraction of groups covered; `complete_evidence_coverage` =
1.0 only if every group is covered.

Ground truth was validated against the live Qdrant payloads: every target must resolve to
exactly one source document, and every `heading_contains` must exist in that document.
This found a pre-existing defect: in the older case `claude-plugin-composition`, the target
`plugins.md` matched both `code.claude.com/docs/en/plugins.md` and
`code.claude.com/docs/en/agent-sdk/plugins.md`, so the case could be scored as covered by
the wrong document. Fixed to `en/plugins.md`.

**Caveats.** The cases were authored for this project, not drawn from an external
benchmark; the "correct" documents reflect one person's judgement. N = 16 is small, so a
difference of one case moves `complete_evidence_coverage` by 0.0625. No repeated runs, no
confidence intervals.

---

## 6. Experiment: single-pass vs. bounded two-hop

`evals/run_evidence_coverage_experiment.py`, 16 items each, Langfuse dataset runs on
2026-09-13T22:42 and 22:44 UTC. Retrieval top-10, generation top-5 (the default at the time),
Cohere rerank against the original question.

| Run | evidence_coverage | complete_evidence_coverage |
|---|---|---|
| baseline (single pass) | 0.625 | 0.250 |
| iterative (two hops) | 0.625 | 0.250 |

Identical, to three decimals.

The loop was not idle. Stop reasons across the 16 iterative items (2 items could not be
read back and are excluded from this tally): `round_limit` 10, `sufficient` 3,
`no_grounded_followups` 1. The deterministic gap queries were on-topic, for example:

- "How does configuring an MCP server differ between Claude Code and Cursor? **Cursor how
  to configure an MCP server, including the configuration file, schema, and supported
  connection settings**"
- "How do I build a Codex skill, and when should the work be delegated to a subagent
  instead? **subagents when to use subagents instead of a skill**"

So the second round retrieved additional, relevant documents and still produced no metric
change. That result pointed at the step after retrieval.

Per-case baseline coverage (recomputed locally from the stored outputs):

| coverage | case | missing groups |
|---|---|---|
| 0.33 | claude-plugin-composition | claude-plugin-package, claude-subagents |
| 0.50 | claude-skill-vs-subagent | claude-skills |
| 0.50 | codex-agents-md-vs-rules | codex-rules |
| 0.50 | codex-skills-and-subagents | codex-skills |
| 0.50 | cursor-hooks-and-subagents | cursor-hooks |
| 0.50 | cursor-skill-vs-rule | cursor-rules |
| 0.50 | mcp-config-claude-vs-cursor | cursor-mcp |
| 0.50 | mcp-discovery-updates-auth | mcp-authorization |
| 0.50 | mcp-server-and-client-concepts | mcp-client-concepts |
| 0.50 | mcp-versioning-and-client-build | mcp-build-client |
| 0.50 | persistent-instructions-claude-vs-codex | codex-agents-md |
| 0.67 | cursor-rules-mcp-subagents | cursor-python-rule-glob |
| 1.00 | codex-agents-mcp | — |
| 1.00 | hooks-cursor-vs-codex | — |
| 1.00 | mcp-authorization-and-hardening | — |
| 1.00 | mcp-build-then-connect-cursor | — |

**Measurement caveat.** For two items the Langfuse API returned an empty `output` on both
the trace and the observation endpoint. Recomputing those two locally gave 0.5 and 1.0;
with those values the per-case table averages to exactly 0.625, matching the run-level
score, so the run-level numbers are trusted and the API read is the unreliable part. Anyone
re-analysing item-level data should recompute locally rather than trust the API dump.

Failure shape, from the retrieved sources: the context fills with chunks of the document
covering the first aspect. In `persistent-instructions-claude-vs-codex` all five context
slots were chunks of `en/memory.md`; `agents-md.md` never appeared.

---

## 7. Experiment: where coverage is actually lost

Offline probe over the same 16 questions. One hybrid retrieval of 20 candidates and one
Cohere rerank per question; the variants differ only in how the final context is chosen.
Run twice (sections 7.1 and 7.2); shared variants reproduced identical values **on those
two consecutive runs**. That was later shown to be coincidence: hybrid RRF retrieval was
not deterministic until the fix in section 7.7. Treat 7.1–7.6 as noisy to about ±1 case
(0.0625 complete coverage).

### 7.1 Truncation vs. per-document cap

| Selection | evidence_coverage | complete |
|---|---|---|
| all 20 reranked candidates | 0.948 | 0.875 |
| top-10 | 0.792 | 0.562 |
| current selector, 5 chunks | 0.646 | 0.312 |
| 5 chunks, max 2 per document | 0.708 | 0.438 |

The documents needed for the second aspect are already present in the first retrieval:
0.948 coverage among 20 candidates. Roughly half of the loss happens at truncation to 10,
the rest at the selection of 5.

A per-document cap helps in aggregate but is not a correct fix: on
`mcp-discovery-updates-auth` it reduced coverage from 1.0 to 0.5, because both required
evidence groups legitimately live in the same document.

Note on the existing selector: `select_generation_context` caps chunks per **section**
(source + h1/h2/h3), not per document. A single document with many distinct headings can
therefore occupy the entire context, which is what happened in the `en/memory.md` case above.

### 7.2 Selection strategies

| Strategy | evidence_coverage | complete | chunks in context |
|---|---|---|---|
| current selector, 5 | 0.646 | 0.312 | 5 |
| current selector, 8 | 0.771 | 0.500 | 8 |
| current selector, 10 | 0.792 | 0.562 | 10 |
| aspect-based, 5 | 0.740 | 0.500 | 5 |
| MMR, 5 | 0.688 | 0.438 | 5 |

Method notes:

- Aspect-based: the question was split into independent aspects by an LLM (1–4 aspects,
  median 2), then each aspect ran **its own** hybrid retrieval and rerank, and the final
  context was filled round-robin from the per-aspect rankings. This is therefore **not
  cost-equal** to the other rows: it adds one LLM call and N retrieval+rerank calls per question.
- MMR: maximal marginal relevance over the top-10, relevance = Cohere rerank score,
  similarity = cosine of OpenAI embeddings of the chunk text, lambda = 0.6. Single, untuned setting.

Observations:

- Enlarging the context from 5 to 8 raises complete coverage from 0.312 to 0.500. Going to
  10 adds little (0.562) for double the context.
- Aspect-based selection reaches the same complete coverage as top-8 using 5 chunks, and it
  fails on **different** cases: it fixed `codex-agents-md-vs-rules`,
  `codex-skills-and-subagents`, `persistent-instructions-claude-vs-codex` and
  `cursor-skill-vs-rule` (0.5 to 1.0), but broke `mcp-discovery-updates-auth`,
  `codex-agents-mcp` and `mcp-authorization-and-hardening` (1.0 to 0.5). The regressions are
  cases where one document covers several aspects and round-robin over separate rankings
  displaced good chunks.
- MMR underperformed plain top-8 and regressed `cursor-rules-mcp-subagents` from 0.67 to
  0.33. Penalising similarity to already-selected chunks penalises neighbouring sections of
  one document, which in documentation are often the different aspects being asked about.
- `mcp-server-and-client-concepts` scored 0.0–0.5 under every *selection* variant in this
  20-candidate probe. A later inspection of the **pipeline** path (`search_hybrid(k=10)`
  then rerank) ranked `learn/server-concepts.md` 5th and `learn/client-concepts.md` 6th, so
  both groups are in the top-10 and the 8-chunk selector can cover them. The earlier
  universal miss was crowding from a 20-candidate rerank, not a missing or unchunked
  document.

---

## 7.3 Is the context too small, or is the selector wrong?

Comparing 0.948 coverage over 20 candidates with 0.646 over 5 selected chunks conflates two
things: selection error and capacity. The fair question is whether *any* selection of k
candidates could cover every group. Measured with `evals/experiments/probe_context_assembly.py`
(exhaustive minimum hitting set over the evidence groups, capped at k):

| Selection | complete_evidence_coverage |
|---|---|
| whole candidate pool (20) | 0.875 |
| oracle at 5 | 0.875 |
| oracle at 8 | 0.875 |
| current selector, 5 | 0.312 |
| current selector, 8 | 0.500 |

`oracle@5` equals the pool. There is no case in this dataset where five slots are
insufficient: the minimum covering set is 2 chunks in 12 of the 14 solvable cases and 3 in
one. The entire 0.875 -> 0.312 difference is selection error, not capacity. Enlarging the
context to 8 recovers part of it by accident, not by choosing better.

Two cases are unsolvable from the first retrieval: in `cursor-rules-mcp-subagents` and
`codex-agents-md-vs-rules` a required group is absent from the 20 candidates. These are the
only cases in the set where a second retrieval is the correct remedy: **2 of 16**.

## 7.4 Judge accuracy

`EvidencePlanner.assess` was run on the 8-chunk context of each case; ground truth is
whether that context in fact covered every evidence group.

| | judge: insufficient | judge: sufficient |
|---|---|---|
| context incomplete (8 cases) | 7 | 1 |
| context complete (8 cases) | 5 | 3 |

The judge detects genuine gaps well (7 of 8) and rarely declares a deficient context
sufficient (1 of 8). Its failure mode is the opposite one: on 5 of 8 complete contexts it
still demanded more evidence. That explains the `round_limit` count of 10 in section 6 — the
loop usually ran because the judge nearly always finds something else to ask for, not
because evidence was genuinely missing.

Implication: the judge's criterion is closer to "is this topic exhaustively covered" than to
"is this enough to answer the question asked". That is a prompt-level problem and should be
fixed before the loop is developed further.

Caveat: 16 cases, one run, judged by `settings.openai_chat_model` at temperature 0; ground
truth is source-level coverage, which is a proxy for answerability, not the same thing.

## 7.5 Answer quality at 5 vs. 8 chunks

`evals/run_answer_quality_experiment.py` on the same 16 cases, run twice with
`GENERATION_TOP_K=5` and `=8`. Single pass, no iterative comparison.

| Metric | k=5 | k=8 |
|---|---|---|
| complete_evidence_coverage | 0.250 | 0.750 |
| evidence_coverage | 0.625 | 0.885 |
| answer_faithfulness | 0.938 | 0.956 |
| answer_relevance | 0.958 | 0.967 |
| citation_correctness | 0.961 | 0.961 |
| context_utilization | 0.866 | 0.826 |

The k=5 coverage matched the earlier Langfuse run (0.625 / 0.250). That match is weaker
evidence of determinism than it looked at the time (section 7.7). The 5→8 gap is still
large enough (eight cases) to attribute to context size rather than RRF tie noise. Faithfulness did not degrade; it improved slightly, which is
consistent with the model previously having to answer the second half of a question without
supporting evidence. The only regression is context utilisation, which is expected when the
context grows. The change from 5 to 8 is therefore kept.

### 7.6 Candidate pool size: a larger pool is worse

The discrepancy above was tested by re-running the probe with the pool the pipeline actually
uses (`--pool 10 --skip-judge`). Results side by side:

| complete coverage | pool = 10 | pool = 20 |
|---|---|---|
| whole pool | 0.812 | 0.875 |
| oracle at 5 | 0.812 | 0.875 |
| oracle at 8 | 0.812 | 0.875 |
| current selector, 5 | 0.312 | 0.312 |
| current selector, 8 | **0.750** | **0.500** |

Confirmed: with a 10-candidate pool the probe matched the pipeline (0.750) **on that run**, and
doubling the pool to 20 reduced delivered coverage by one third even though the ceiling rose from
0.812 to 0.875. Reranking 20 candidates promotes additional chunks of the first aspect's
document above the second aspect's document, so the extra recall is converted into extra
crowding. This is the same failure mode as the selection bottleneck, one stage earlier.
Repeats of the same probe before the 7.7 fix also produced 0.688, so the exact 0.750 vs
0.500 pair is directionally robust (several cases) but not a one-case-precise measurement.

Practical consequences:

- Do **not** raise `retrieval_top_k` above 10. The current value is correct, and now for a
  measured reason rather than by default.
- Against the 10-candidate pool the pipeline is close to optimal already: 0.750 delivered
  versus an 0.812 ceiling, a gap of one case. The workaround has nearly exhausted what this
  pool allows.
- The remaining opportunity is not a bigger context but a selector that can exploit a bigger
  pool: 0.875 is reachable at pool 20 and the current selector delivers 0.500 of it. Set
  selection is therefore worth roughly +0.125 over today, not +0.06.

**Original discrepancy note, retained for context.** The offline probe in 7.2 predicted 0.500
complete coverage at k=8; the pipeline measured 0.750. The two differ in how candidates are
produced: the pipeline reranks the RRF top-10 from `search_hybrid(k=10)`, while the probe
reranked 20 candidates and kept the best 10. The larger pre-rerank pool performed *worse*.
A plausible mechanism is that reranking 20 candidates promotes near-duplicates of the first
aspect into the top-10 and displaces the second aspect's document, whereas the RRF top-10 is
more diverse because it fuses two different signals. This is one comparison between two code
paths that also differ elsewhere; it is a hypothesis, not a result. It can be tested by
re-running the probe with a 10-candidate pool. That test was run: see 7.6, where the
hypothesis is confirmed.

Consequence for section 7.3: the oracle ceiling of 0.875 applies to a 20-candidate pool. For
the pipeline's 10-candidate pool the ceiling is 0.812.

## 7.7 Hybrid RRF retrieval was not deterministic

Repeating `evals/experiments/probe_context_assembly.py --pool 10 --skip-judge` after the 7.6 numbers
gave complete coverage 0.688, then 0.750, then 0.688. Pool-level complete coverage moved
between 0.750 and 0.812. Dense search of the same query was identical across calls;
`search_hybrid` was not.

Mechanism: Qdrant RRF scores take a small set of values (for example 0.2, 0.166667,
0.142857). Many chunks therefore tie. The client asked for exactly `k` results and kept
Qdrant's order, so the cut at `k` dropped a *different* tied document on each call. The
9th/10th slot of `mcp-server-and-client-concepts` swapped identity between repeats.

Fix (`src/rag/retriever.py`): request `k * 3` hybrid hits, sort by `(-score, document_key)`,
then take `k`. The same explicit tie-break is applied in client-side RRF in
`src/rag/multi_query_retriever.py`. After the fix, four hybrid searches of two queries
returned identical id lists. `document_key` lives in `retriever.py`;
`multi_query_retriever._document_key` is an alias.

Implication for earlier sections: treat differences of one case (0.0625 complete coverage)
as within RRF-tie noise unless they were re-measured after this fix. Differences of several
cases (k=5 vs k=8; pool 10 vs 20 at selected-8) remain large enough to keep.

Post-fix probe (`--skip-judge`, after the stable sort):

| complete coverage | pool = 10 | pool = 20 |
|---|---|---|
| whole pool | 0.812 | 0.875 |
| oracle at 5 | 0.812 | 0.875 |
| oracle at 8 | 0.812 | 0.875 |
| current selector, 5 | 0.312 | 0.312 |
| current selector, 8 | 0.750 | 0.500 |

The pool-10 vs pool-20 crowding result from 7.6 **reproduces after the fix**. Extra recall at 20 is real (`cursor-hooks-and-subagents` is absent from the 10-pool and present in the 20-pool) but the 8-chunk selector still converts it into a worse context. `mcp-server-and-client-concepts` is complete at selected-8 with pool 10 and incomplete with pool 20.

## 8. Conclusions

1. **Retrieval is not the bottleneck for multi-aspect questions; context assembly is.**
   0.948 coverage among 20 reranked candidates versus 0.646 after context selection, and
   `oracle@5` shows the five available slots would have sufficed in every solvable case
   (0.875, section 7.3). The loss is selection error, not capacity.
2. **The iterative loop did not help, and the measurement explains why.** It retrieves
   documents that were already among the candidates; the final rerank against the whole
   question then ranks them below the first aspect's chunks again. Two hops cannot fix a
   selection problem. `--iterative` stays opt-in. A second retrieval is the right remedy for
   2 of 16 cases (section 7.3), which is the size of the fallback role it should have.
3. **A single reranking against the whole question is structurally biased on compound
   questions.** Every chunk of the first aspect's document scores higher than the best chunk
   of the second aspect's document, so it wins all the slots. This is the Agentic-R point
   (local similarity is not usefulness for the final answer) observed directly.
4. **Context size is the cheapest available fix, and it is validated end to end.**
   `generation_top_k` changed from 5 to 8 (`src/config.py`); the eval scripts now read the
   setting instead of duplicating it. Measured on the pipeline (section 7.5): complete
   coverage 0.250 to 0.750, faithfulness 0.938 to 0.956, citations unchanged, context
   utilisation 0.866 to 0.826. It remains a workaround rather than a better selector.
5. **Separating the judge from query construction is justified on design grounds
   (testability, preserved product names), but it has not yet shown a metric gain.** It
   should be described as a refactor, not as an improvement.
6. **The judge over-reports gaps rather than missing them** (section 7.4): 5 of 8 complete
   contexts were called insufficient, against 1 missed gap. Its criterion needs to be
   narrowed to answerability before the loop is extended.
7. **More recall can reduce delivered coverage.** Doubling the pre-rerank candidate pool
   from 10 to 20 raised the ceiling (0.812 to 0.875) and reduced what reached the context
   (0.750 to 0.500), because reranking converts the extra recall into more chunks of the
   already-covered aspect (section 7.6). `retrieval_top_k` stays at 10.
8. **Naive diversity heuristics are not a substitute.** Both the per-document cap and MMR
   improved the average while breaking cases where one document legitimately carries several
   aspects.
9. **Hybrid RRF must break score ties with a stable key.** Otherwise the cut at `k` is a
   random drop among equals, and evals move by ±1 case for no architectural reason
   (section 7.7).
10. **Deferred, with reasons:** Adaptive-RAG routing (no labelled complexity classes);
    Self-RAG (requires training); sentence-level compression (solves a context-length problem
    that does not currently exist, and risks destroying procedural content such as numbered
    installation steps); NLI verification of claims (cost, and RAGChecker-style diagnosis
    should come first).

---

## 9. Known gaps in this evaluation

- Coverage is a **source-level retrieval metric** as well as (in 7.5) LLM-judged answer
  quality. The two are not the same quantity.
- N = 16, author-written ground truth. Runs before section 7.7 have ±1-case noise from RRF
  ties. Post-fix numbers replace the probe table in 7.7.
- `mcp-server-and-client-concepts` is not a chunking defect: both target docs appear in the
  hybrid top-10 (ranks 5–6 on inspection). It failed some 20-candidate selection variants
  because of crowding, not because the pages are missing.
- Langfuse item-level outputs were unreadable for 2 of 16 items in the iterative run.
- The aspect-based row is not cost-equal to the others.
- MMR was tested at a single lambda.
- Costs were not measured in any of these runs.
- The oracle in 7.3 is an upper bound over the retrieved pool only; it says a perfect
  selector could have reached 0.875, not that any implementable selector will.
- Judge accuracy (7.4) is scored against source-level coverage. A context can cover every
  required document and still be insufficient to answer, and vice versa, so the five
  "spurious gap" cases are an upper estimate of over-reporting.

## 10. Next steps, in order

1. Done (section 7.5): k=8 improves coverage and faithfulness, so it is kept.
2. Done (section 7.6): the 20-candidate configuration reduced delivered coverage versus 10.
   `retrieval_top_k` stays at 10; the ceiling for that pool is 0.812 and the pipeline
   delivers 0.750.
3. Done: `mcp-server-and-client-concepts` — both MCP concept pages are in the top-10;
   earlier misses were crowding, not a missing document (section 7.2 / 7.7).
4. Done (section 7.7): after the RRF tie-break, pool 10 still delivers selected-8 = 0.750
   and pool 20 still delivers 0.500.
5. Treat context assembly as **set selection, not ranking**: choose the set of chunks that
   maximises relevance plus coverage of not-yet-covered aspects, instead of taking the k
   highest independent scores. The target is the 0.875 reachable at pool 20, which the
   current selector converts to only 0.500; staying at pool 10 caps the gain at 0.812
   against 0.750 today (section 7.6). The cheapest
   concrete form is aspect-aware selection over a **single**
   retrieval: split the question into aspects, then distribute the existing 20 candidates
   across aspects at selection time rather than retrieving per aspect. This also targets the
   round-robin regressions seen in 7.2.
6. A related, untested variant: reuse the judge's structured gaps to rescore the existing
   candidate pool rather than to issue a new query. In 14 of 16 cases the missing evidence is
   already in the pool, so promoting it is cheaper than another retrieval.
7. Narrow the judge's criterion from topical exhaustiveness to answerability (section 7.4),
   and publish the new `doc-bot/evidence-planner` prompt version to Langfuse.
8. Only after the above: consider compact evidence (keep the number of sources, shorten the
   text), and only if context length or cost becomes a real constraint.
