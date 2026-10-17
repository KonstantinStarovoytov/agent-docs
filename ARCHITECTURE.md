# Architecture

How Agent Docs answers a question, how its index stays current, why it is
built this way, and what the experiments measured. Full numbers for each
experiment are in [reports/](reports/README.md); the September experiment log
is [docs/rag-findings.md](docs/rag-findings.md). Terms are explained in the
[glossary](#glossary) at the end.

**Contents:** [How a question is answered](#how-a-question-is-answered) ·
[How the index stays current](#how-the-index-stays-current) ·
[Decisions](#decisions) · [Experiments](#experiments) ·
[Evaluation](#evaluation) · [Limits and open questions](#limits-and-open-questions) ·
[Glossary](#glossary)

---

## How a question is answered

There are two ways in. Agents use two MCP tools and write the answer
themselves. Other clients call `/ask` over REST and get a written answer.
Both run in one process and go through the same code in `src/service/`, so
the two paths cannot drift apart.

### Agents: `search_docs` and `read_section`

1. `search_docs(query)` searches the index two ways at once: by meaning
   (embeddings) and by exact words (BM25). The two result lists are merged by
   rank (RRF). Ties are ordered by chunk id, so the same query always gives the
   same results.
2. The top 20 candidates go to a reranker (Cohere `rerank-v4.0-fast`). It reads
   each one together with the question and scores the match from 0 to 1.
3. Only the best passage of each page is kept, so one long page cannot fill
   the list. Each passage comes with its score, the page's one-line
   description, and the headings of up to three other sections of the same
   page that scored at least 0.35 (`other_sections`).
4. `read_section(url)` returns the page's outline. `read_section(url, heading)`
   returns that section in full, up to 8,000 characters per call, from the
   stored copy of the page. No model is called.

An optional `product` argument limits the search to one product. No language
model runs on this path.

### REST: `/ask`

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/diagrams/architecture-ask-path-dark.png">
  <img alt="The ask path, step by step" src="docs/diagrams/architecture-ask-path-light.png">
</picture>

<sub>Diagram source: [docs/diagrams/architecture-ask-path.mmd](docs/diagrams/architecture-ask-path.mmd)</sub>

| Step | What it does | Why |
|---|---|---|
| 1. Translation | Adds an English copy of Russian or Polish questions; both are searched. | The docs are in English. |
| 2. Hybrid search | The same search as above, for each query. With two queries, their lists are merged by rank once more. | |
| 3. Rerank | Cohere scores 10 candidates against the original question. | The search is fast but rough; the reranker is precise. |
| 4. Threshold | If the best candidate scores below 0.55, the answer is "the documentation does not cover this", and no model is called. Otherwise candidates below 0.35 are dropped. | So the bot refuses instead of guessing. |
| 5. Context selection | Keeps the 8 best chunks, at most 2 from one section. | So one section cannot fill the whole context. |
| 6. Answer | `gpt-6-luna` answers only from these 8 chunks and cites them as [1], [2]. | Every claim can be checked. |

Every chunk is stored with a short header (vendor, product, page, section)
that is embedded with it. Without it, "set `model` in settings" looks the same
for Cursor and Claude Code.

---

## How the index stays current

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/flow/reindex-flow-dark.gif">
  <img alt="Animation of the daily reindex" src="docs/flow/reindex-flow-light.gif">
</picture>

<sub>[Step by step](https://konstantinstarovoytov.github.io/agent-docs/?flow=reindex) · source: [docs/flow/flows/reindex.js](docs/flow/flows/reindex.js)</sub>

Every day at 06:00 UTC a GitHub Actions job reads each vendor's `llms.txt`
(its list of documentation pages), fetches every page and updates the index.

- **Which pages.** All of them, except translations, changelogs and release
  notes, weekly news, concatenated dumps, old MCP spec versions, community
  pages, MCP proposals, legal and marketing pages, and pages that only link
  elsewhere (`src/ingestion/sources.py`). Large reference pages (settings,
  environment variables, errors, SDK and API references, the MCP schema) are on
  an allow list, so the size check does not hold them back. Decisions per
  page: [reports/index-v2-2026-10.md](reports/index-v2-2026-10.md).
- **Only changes cost anything.** Each page has a fingerprint: a SHA-256 of its
  text plus the chunker version. Only new and changed pages are embedded again,
  so a new chunker version re-embeds every page once.
- **New pages are checked.** First for free: size, language, near-duplicates of
  indexed pages, suspicious paths. Then a short LLM call says in one sentence
  what the page is. A page that fails a check is quarantined: not indexed until
  the owner decides.
- **The owner decides in an issue.** Quarantined pages are listed in one
  "Pages waiting for review" issue, each with two boxes. **Index** puts the page
  on the allow list (`data/page-decisions.json`, read together with `allow` in
  `sources.py`), and the next run indexes it. **Decline** keeps it out until the
  page changes; then it comes back to the issue, not to the check. Only the
  repository owner's ticks count, and the issue closes when nothing is waiting.
- **Pages that disappear are deleted** from the chunks, the stored pages and
  the manifest: a page that leaves `llms.txt` or becomes excluded. If more than 10%
  of a vendor's pages would go at once, or its `llms.txt` lists fewer than half
  of them, nothing is deleted for that vendor and the run fails.
- **A failed download keeps the old copy.** If more than 10% of a vendor's pages
  fail, the run fails.
- **A smoke check runs after every change.** 8 known questions must still find
  their page in the top 10, or the run fails. A failed run opens a "Reindex
  needs attention" issue with the end of its log.
- **Each run writes a change report** of added, removed and significantly
  changed pages, to the run summary and `reports/docs-changes/`. Only our
  summaries and links go into git, never the vendors' text.
- **The free Qdrant cluster sleeps** after a week without requests, so the
  daily run always reads from it once.

---

## Decisions

### Search

| Decision | Why | Instead of | Evidence |
|---|---|---|---|
| Search by meaning and by exact words (hybrid) | The docs are full of exact names (`.cursorrules`, `claude mcp add`) that search by meaning blurs. | Search by meaning only | Design reasoning; on the first 35-page index every retrieval dataset reached Hit@5 = 1.0. |
| Merge the two lists by rank (RRF), with equal weights | Their scores are not comparable; ranks are. The reranker reorders the result anyway. | Tuned weights | Published results show small gains from tuning; the losses here happen after the rerank. |
| Ties ordered by chunk id, 3× overfetch | Without it, the same question returned different results. | Database order | Repeated runs moved coverage by ±1 case before, 0 after (experiment 12). |
| Rerank against the original question | The reranker should judge what the user asked, not a rewrite. | Rerank against rewritten queries | — |
| Translate questions, never rewrite them | A rewrite changes the meaning. | Rewriting the question | A rewrite dropped one English case from MRR 1.0 to 0.25 (experiment 2). |
| A header in every chunk | The same words mean different things in different products. | Plain text | Design reasoning; the answer judge also checks for citations to the wrong product. |
| Chunks of 3,000 characters, 300 overlap, split at headings first | The reranker judges whole paragraphs better; headings give each chunk an address. | Small chunks | 8 × 3,000 characters fits the model's context easily. |

### Agent tools (MCP)

| Decision | Why | Instead of | Evidence |
|---|---|---|---|
| Two tools and no language model on the agent path | Agents write the answer themselves; a second answer costs money and hides the sources. | `ask_docs` and `find_pages` as extra tools | Production traces over 30 days: agents called `search_docs` 103 times and `ask_docs` 11. `/ask` and `/pages` stay on REST. |
| `search_docs` returns one passage per page | Several chunks of one page filled the list. | All chunks in score order | Limit 5: distinct pages 3.1 → 5.0, page hit@5 0.936 → 0.979 (experiment 22). |
| Passages name the page's other matching sections (`other_sections`) | One passage per page hides a second relevant section of the same page. A heading points `read_section` at it without taking a result slot. | Two passages per page | Section hit 0.667 → 0.867, 8–10% more tokens (experiment 25). With real agents: the same correctness, fewer reads of guessed headings (7 → 1, 4 → 0; experiment 26). |
| `read_section` reads whole sections from a stored copy of the page | A 3,000-character chunk can cut a section in half. | Longer passages from `search_docs` | It returns the labelled section for 25 of 25 labels (experiment 24). |
| A compact outline: top-level sections with subsection counts, at most 40 lines; `outline_depth=3` adds subsections | The full outline of `hooks.md` was 166 headings, about 1,000 tokens per call. A section's text already includes its subsections. | Every heading | Over 617 pages: median 86 → 52 tokens, maximum 1,987 → 374; `hooks.md` 1,038 → 91. |
| Only tools, no MCP prompts or resources | Agents need actions; prompts belong in the client's plugin. | MCP prompts and resources | — |
| Typed tool errors | The agent should know whether to retry or to tell the user. | Generic errors | — |

### Answers (`/ask`)

| Decision | Why | Instead of | Evidence |
|---|---|---|---|
| 10 candidates for the reranker | More candidates pushed out the second topic of multi-part questions. | 20 | Complete coverage 0.750 vs 0.500 (experiment 7). |
| 8 chunks to the model | Multi-part questions need room for every part. | 5 | Complete coverage 0.250 → 0.750, faithfulness 0.938 → 0.956 (experiment 6). |
| At most 2 chunks per section | So one section cannot take every slot. | A per-page cap, MMR | Both broke questions where one page covers two topics (experiments 8, 9). |
| Drop candidates below 0.35 | A cheap way to refuse. | Always answer | The weakest truly relevant chunk scored 0.35 among 128 labelled chunks. A floor of 0.40 would add one refusal with only 0.016 to spare. |
| Refuse when the best candidate scores below 0.55 | Saves the model call when nothing fits. | A higher 0.35 floor | The lowest best score of 131 answerable questions is 0.64; 8 of 12 unanswerable ones fall below 0.55 (experiment 23). |
| One search pass; two-hop search off | It did not help on average. | Iterative search | The same coverage with and without it (experiment 3). |
| `gpt-6-luna` writes the answers | More faithful, equally relevant. | `gpt-5.6-luna` | Faithfulness 0.975 → 0.994, citations 0.980 → 0.994 (experiment 13). |

### Index, hosting and access

| Decision | Why | Instead of | Evidence |
|---|---|---|---|
| Index every page except the excluded ones, and check new pages | Users wanted the whole documentation; new pages arrive by themselves. | A hand-picked list | 35 → ~600 pages. |
| Free hosting: Render, Qdrant Cloud, Langfuse Hobby | No fixed cost and no bank card. | Paid hosting | See README → Cost. |
| Anyone can call the tools with their own Cohere key (`X-Cohere-Api-Key`) | Reranking is the only metered cost, and it moves to the caller. Embeddings cost almost nothing and are capped at 30 requests a minute per IP plus a global limit. The key is used for that request only and is never stored, logged or traced. | Guest tokens only | — |
| Only `tools/call` needs a key or token; `GET` and `DELETE /mcp` answer 405; `/.well-known/*` is public | Only a tool call costs money. MCP directories such as Glama check a server without a key: they list the tools, open a GET stream and look for OAuth metadata. The server keeps no session, so a GET stream would only hold a connection open; the spec allows 405. | Allowing only the discovery methods; storing a key in each directory | With only the discovery methods allowed, Glama's connection test still failed with 401. Anonymous requests share the 30-a-minute per-IP limit. |

---

## Experiments

Each row tests one idea. "Kept" means it is in production.

In short:

- When an answer misses part of a question, the search has usually found the
  right text. It gets lost later, when the candidates are cut down to what the
  model sees (experiments 4, 16).
- More candidates made multi-part answers worse: extra chunks about the first
  topic pushed out the second (experiments 7, 17).
- A single rerank against a multi-part question favours its first part: every
  chunk about part one outscores the best chunk about part two.
- MMR and per-page caps help on average but break questions where one page
  answers two parts (experiments 8, 9, 15).
- Without a fixed order for ties, the same eval gave different results from
  run to run (experiment 12).
- Two-hop search and question rewriting were built, measured and turned off
  (experiments 2, 3).

| # | Idea | How it was measured | Result | Verdict |
|---|---|---|---|---|
| 1 | Translating non-English questions helps | 48 questions × 4 variants, Hit@5 and MRR | Hit@5 0.958 → 1.000 | **Kept** |
| 2 | Rewriting questions helps | Same set | One English case: MRR 1.0 → 0.25 | Rejected |
| 3 | A second search round finds the missing parts | 16 multi-part questions, evidence coverage | 0.625 / 0.250 both ways | Off by default |
| 4 | Missing evidence is a search problem | Coverage among 20 candidates vs. in the final context | 0.948 found → 0.646 delivered | **Disproved:** the loss happens when chunks are picked |
| 5 | 5 chunks are enough room | The best possible pick of 5 vs. the actual pick | The best 5 cover 0.875; the actual pick 0.312 | The room is enough; the picking is the problem |
| 6 | More chunks help | 5 vs. 8 chunks, full pipeline with the judge | Complete coverage 0.250 → 0.750 | **Kept (8)** |
| 7 | More candidates help | 10 vs. 20 candidates | 0.750 → 0.500 | Rejected (stays at 10) |
| 8 | MMR diversifies the context | 5 chunks, λ = 0.6 | 0.688 vs. 0.771 for a plain top 8 | Rejected |
| 9 | A per-page cap diversifies the context | 5 chunks, at most 2 per page | Better on average; broke questions where one page covers two topics | Rejected (the per-section cap is kept) |
| 10 | Picking chunks per part of the question | Frozen candidates, offline | Complete coverage 0.50 → 0.69 | Not started: needs a holdout set. Would only affect `/ask`: agents get no context selection, and `search_docs` asks them to search one topic per call |
| 11 | The two-hop judge knows when the evidence is enough | The judge vs. ground truth on 16 contexts | Finds 7 of 8 real gaps, but calls 5 of 8 complete contexts incomplete | Too strict; not used |
| 12 | RRF is deterministic | Repeated identical queries | Results changed between calls | **Fixed** with the tie order |
| 13 | `gpt-6-luna` is at least as good as `gpt-5.6-luna` | 16 + 12 questions, a separate judge | Faithfulness 0.975 → 0.994 | **Kept** |
| 14 | Quality holds when the index grows to ~600 pages | See [Evaluation](#evaluation) | Ranking and multi-part coverage dropped | See [Evaluation](#evaluation) |
| 15 | Capping chunks per page among the candidates fixes that drop | Cap none / 2 / 3, same gate | Cap 2: MRR 0.825 → 0.739, Hit@5 0.957 → 0.872; no missing evidence came back | Rejected (setting kept, off by default) |
| 16 | The misses after the growth are a search problem | Where each correct chunk is lost, on the real index, with the gate's stored rerank scores (89 questions and evidence groups) | 10 misses: 7 found but outside the 10 candidates, 3 not in the top 30 of either search, 0 dropped by the reranker. 65% of the chunks ranked above the right one are guide pages | **Partly confirmed:** coverage is lost at the candidate cut; the ranking loss is among plausible pages, plus two correct answers the labels missed |
| 17 | Reading deeper or keeping more candidates brings the right chunk back | Recall for prefetch 30 / 60 / 100 / 150 × 10 / 20 / 40 / 60 candidates, no reranker; then 40 candidates with the reranker | Reading deeper changes nothing. 20 / 40 candidates: complete coverage among them 0.625 → 0.750 / 0.875. With the reranker (40 candidates, prefetch 60): hit@5 0.979 → 0.915, MRR 0.847 → 0.839, complete coverage 0.250 → 0.250 | **Rejected;** defaults unchanged |
| 18 | BM25 needs IDF (the v1 index has no `modifier=IDF`) | Index v2 built with IDF; recall among 10 / 20 / 40 candidates, no reranker | Recall unchanged on all four datasets; the first correct result ranks slightly lower before the rerank | **Pending:** a gate run with the reranker on v2 (November) |
| 19 | Excluding changelogs, legal, marketing and link-only pages cleans up the candidates | 40 quarantined pages excluded, 20 large references allowed; same recall run | The same groups were lost as in v1 | Kept for a cleaner index, in v1 too since the reindex of 2026-10-14; no effect on recall |
| 20 | One reference entry per chunk (split at `####`, tables in 12-row pieces with their header) | Chunk counts of large pages; same recall run | e.g. `hooks.md` 125 → 184 chunks, median 2,571 → 1,188 characters; recall unchanged | **Live in v1** since the reindex of 2026-10-14 re-chunked every page; its gate run with the reranker is still pending (November) |
| 21 | A product filter recovers evidence | v2 with the vendor the labels name (56 of 91 cases) | Coverage at 10 candidates 0.765 → 0.794, at 40: 0.912 → 0.941; `retrieval-v3` at 40 → 1.000 | **Accepted** as the optional `product` on `/ask` and `search_docs` |
| 22 | One passage per page makes `search_docs` show more pages | Stored Cohere scores, 20 candidates rebuilt from Qdrant; page hit@k before → after | `retrieval-v3` (47 questions): limit 5 hit 0.936 → 0.979, pages 3.1 → 5.0; limit 8 hit 0.979 → 0.979, pages 4.4 → 7.4. No hit lost on the partly scored datasets | **Kept** |
| 23 | The best rerank score shows when the docs do not cover a question | The best score on the `/ask` path (10 candidates), from stored scores: 131 answerable questions, 12 unanswerable | The lowest answerable is 0.64; 8 of 12 unanswerable fall below 0.55 (the 0.35 floor already empties 5) | **Kept**, threshold 0.55 |
| 24 | Page cards plus section reads find and return the right section | Stored Cohere scores, 20 candidates (no Cohere calls); `read_section` on the 25 labels that name a heading | Page hit@3 / @5: `retrieval-v3` 0.936 / 0.979; evidence groups (one call per question) 0.500 / 0.647. `read_section`: 25 of 25 once every page has a stored copy; median 1,415 characters, p95 7,941 | **Kept**; every v1 page has a stored copy since the reindex of 2026-10-14 (591 of 591) ([report](reports/find-pages-2026-10.md)) |
| 25 | More than one passage per page helps agents find the right section | Same candidates and scores (83 questions); A: one per page, B: up to two, C: a second only if ≥ 0.8 × the best, D: one per page plus the headings of the page's other chunks scoring ≥ 0.35 | D: section hit 0.667 → 0.867, page hit unchanged, 8–10% more tokens. B and C lose pages (all-groups coverage @5 0.438 → 0.312) | **Kept** as `other_sections` ([report](reports/passages-per-page-2026-10.md)) |
| 26 | Agents use `other_sections` and answer better with it | `gpt-6-luna` and `claude-haiku-5-5` with the real tools, with and without the field; `gpt-6-sol` grades against the labelled section; 12 Claude Code questions, two repeats (96 runs), plus a first run of 15 questions | The same correctness (luna 0.94 / 0.94, Haiku 0.92 / 0.94); 21–28% of reads open a heading from `other_sections`; failed reads of guessed headings 7 → 1 (luna) and 4 → 0 (Haiku) | **Partly confirmed:** used, fewer failed reads, no effect on correctness; field kept ([report](reports/agent-other-sections-2026-10.md)) |
| 27 | A cheaper model can replace `gpt-6-sol` as the answer judge | The 67 answers sol graded on 2026-10-12, graded again with the same rubric by Claude Haiku 5.5, `gpt-6-luna` and `gpt-5.6-luna`; six Haiku disagreements read against the docs | Haiku: faithfulness 0.988 → 0.810, citations 0.987 → 0.689; sol was right in 5 of 6 cases read; Haiku's scores contradict its own issue lists. The lunas follow sol on faithfulness and citations, but label 1 (`gpt-6-luna`) or 3 (`gpt-5.6-luna`) of 19 correct refusals as `none`. One gate run: sol ≈ $0.32, `gpt-6-luna` ≈ $0.02 | **Rejected** for the gate; sol is the default judge. `gpt-6-luna` is fine for cheap trial runs, compared only with each other ([report](reports/judge-agreement-2026-10.md)) |

---

## Evaluation

**Retrieval** is scored by code against pages labelled in advance: Hit@k,
MRR, precision@k, nDCG and evidence coverage.

**Answers** are scored by an LLM judge, `gpt-6-sol` (`JUDGE_MODEL`), while
`gpt-6-luna` writes them. The judge scores faithfulness, relevance, context
use and citations, labels how an answer failed (none, refusal, empty,
repeated, did not follow instructions), and checks that the 12 questions the
docs cannot answer are refused. Cheaper judges were tried and are not used for
the gate (experiment 27).

The datasets live in Langfuse: `rag/retrieval-v3`,
`rag/retrieval-query-transform-v1`, `rag/evidence-coverage-v1`,
`rag/negative-v1`, and `rag/full-corpus-v1` for the pages added in October.

**The gate:** a change fails if any metric drops by more than 0.03 against its
last run.

### Where quality stands (October 2026)

The index grew from 35 hand-picked pages to about 600:

| Dataset | Metric | Before | After | Gate |
|---|---|---|---|---|
| `retrieval-v3` | Hit@5 | 0.979 | 0.957 | pass |
| `retrieval-v3` | MRR | 0.865 | 0.826 | **fail** |
| `retrieval-query-transform-v1` | Hit@5 | 0.875 | 0.979 | pass |
| `retrieval-query-transform-v1` | MRR | 0.859 | 0.767 | **fail** |
| `evidence-coverage-v1` | Complete coverage | 0.750 | 0.625 | **fail** |
| `evidence-coverage-v1` | Faithfulness | 0.994 | 0.987 | pass |
| `negative-v1` | Correct refusals | 1.000 | 1.000 | pass |
| `full-corpus-v1` (new topics) | Hit@5 | — | 1.000 | pass (≥ 0.9) |

- The bot now answers questions it could not answer before (new topics: Hit@5
  1.000), still refuses questions outside the docs, and its answers still stick
  to the sources.
- The right page now ranks a little lower, and multi-part questions are fully
  covered less often. Of the 81 results ranked above the first correct one, 52
  came from newly added pages.
- Two of the misses were correct answers the labels did not list. With them
  added (2026-10-12), `retrieval-v3` MRR is 0.847 and passes the gate (0.835).
  What still fails is complete coverage of multi-part questions.

Before this comparison, three unanswerable questions were replaced because the
larger index now answers them, and seven labels were extended where a newly
indexed page was a valid answer. Each change and its evidence:
[reports/full-corpus-eval-2026-10.md](reports/full-corpus-eval-2026-10.md).

### What was tried

| Idea | Result | Details |
|---|---|---|
| Cap the chunks per page among the candidates (15) | Ranking got worse (cap 2: MRR 0.825 → 0.739, Hit@5 0.957 → 0.872), and no missing evidence came back. The setting stays, off by default. | [per-page cap](reports/per-page-cap-2026-10.md) |
| Trace where each missed chunk is lost (16) | 7 of 10 misses were found by the search but cut before the reranker; 3 were not in the top 30 of either search; the reranker dropped none. 65% of the chunks ranked above the right one are guide pages: a sibling feature, the same feature from another vendor, or a correct answer the labels miss. Enterprise, security and integration pages are 27%. | [diagnostics](reports/retrieval-diagnostics-2026-10.md) |
| Read deeper, or rerank more candidates (17) | Reading 30 → 150 results per search brought nothing back. 40 candidates (prefetch 60) with the reranker: hit@5 0.979 → 0.915, complete coverage unchanged. | [diagnostics](reports/retrieval-diagnostics-2026-10.md) |
| Rank guide pages above enterprise, integration, reference and spec pages | On hold: most pages ranked above the right one are guides themselves. | [per-page cap](reports/per-page-cap-2026-10.md) |
| Index v2: BM25 IDF, the new excludes, one chunk per reference entry (18–20) | Without the reranker, recall is the same as v1. | [index v2](reports/index-v2-2026-10.md) |
| A product filter (21) | The only change that brought evidence back (coverage at 10 candidates 0.765 → 0.794). Now an optional `product` argument. | [index v2](reports/index-v2-2026-10.md) |

No default changed. Two settings now separate how deep each search reads
(`HYBRID_PREFETCH_DEPTH`) from how many candidates go to the reranker
(`RERANK_POOL`); both default to today's behaviour.

### Index v2

v2 (`agent_docs_hybrid_v2`) was built on 2026-10-12 to test experiments 18–21.
Since then the daily reindex has brought its excludes and chunker to v1 too
(the run of 2026-10-14 deleted 40 pages and re-chunked every page;
[report](reports/docs-changes/2026-10-14.md)). The daily reindex only updates
v1, so v2 still holds its first build. Besides BM25 IDF, the page sets differ:
16 pages are only in v1, 1 only in v2, and 5 pages indexed in v1 are
quarantined in v2.

Production stays on v1. To switch: reindex v2 (the Reindex workflow with
`collection: agent_docs_hybrid_v2`), decide those 5 pages, pass the gate with
the reranker on v2, then set `QDRANT_HYBRID_COLLECTION=agent_docs_hybrid_v2`
on Render and in the reindex workflow variable.

### Next

In November, when the Cohere trial quota resets, run the gate with the
reranker on v1 and v2. Neither the new chunker (experiment 20, already live in
v1) nor BM25 IDF (experiment 18) has been checked with the reranker yet. Then
decide on v2. Picking chunks per part of the question (experiment 10) would
only affect `/ask` and needs a holdout set first.

---

## Limits and open questions

- **Small datasets.** 16 multi-part questions, with ground truth written by the
  author. One question is 0.0625 of complete coverage.
- **The answer model is not deterministic**, even with the same inputs.
- **Ranking dropped when the index grew** (see [Evaluation](#evaluation)).
  Hit@5 holds, but the right page ranks lower and multi-part coverage fell.
  Nothing tried so far brings it back (experiments 15, 17); the product filter
  helps when the product is known (experiment 21).
- **Free-tier limits.** The Cohere trial allows 1,000 calls a month per key and
  10 a minute. Render sleeps after 15 idle minutes (the first request then takes
  about a minute). One day of gate runs used up the whole October Cohere quota,
  so eval runs now stop on a monthly 429 instead of switching keys, and can
  reuse stored scores (`EVAL_CACHE_DIR`, `evals/eval_cache.py`).
- **Open:** a smarter context selector (experiment 10); answering without the
  reranker when the Cohere quota runs out; grading a sample of production
  traffic with the LLM judge.

---

## Glossary

| Term | Meaning |
|---|---|
| **RAG** (retrieval-augmented generation) | First find the relevant text, then let a language model answer only from that text. |
| **LLM** (large language model) | A model that writes text, such as GPT. Here `gpt-6-luna` writes the `/ask` answers. |
| **MCP** (Model Context Protocol) | A standard way for AI agents to call external tools. This project is an MCP server with two tools, `search_docs` and `read_section`. |
| **Chunk** | A piece of a documentation page, up to 3,000 characters, stored and searched on its own. |
| **Chunk overlap** | Neighbouring chunks share 300 characters, so a sentence cut at a border is whole in one of them. |
| **Embedding** | A list of numbers that represents the meaning of a text. Texts with similar meaning get similar numbers. |
| **Dense search** | Search by meaning, using embeddings. Finds "add a tool server" for "connect an MCP server". |
| **BM25** (sparse search) | Classic keyword search. Finds exact names such as `.cursorrules` or `claude mcp add`, which dense search blurs. |
| **Hybrid search** | Dense and BM25 search run together and their results are merged. |
| **RRF** (reciprocal rank fusion) | How the two result lists are merged: each result gets `1 / (60 + its rank)` from each list, and the points are added. It uses ranks, not scores, because the two kinds of score are not comparable. |
| **Tie order** | RRF often gives several chunks the same score. Ties are sorted by chunk id, so the same question always gets the same results. |
| **Overfetch** | Asking the database for 3× more results than needed, so a group of tied results is never cut in the middle. |
| **Prefetch depth** | How far down each list (dense and BM25) the database reads before merging. Today 3× the number of results asked for (30 for `/ask`). Setting: `HYBRID_PREFETCH_DEPTH`. |
| **Reranker** | A second, slower model that reads the question and each candidate together and scores the match from 0 to 1. Here Cohere `rerank-v4.0-fast`. |
| **Candidates** | The search results that go to the reranker: 10 for `/ask`, 20 for `search_docs`. Setting: `RERANK_POOL`. |
| **Recall among candidates** | The share of questions with at least one correct chunk among the candidates: the most the reranker can find. |
| **`generation_top_k`** | How many chunks the model sees when it writes an `/ask` answer (8). |
| **Grounded answer** | Every claim in the answer comes from the retrieved chunks and is cited as [1], [2]. |
| **Refusal (abstention)** | The bot says "the documentation does not cover this" instead of guessing. |
| **Hit@k** | Did at least one correct result appear in the first *k*? 1 = yes, 0 = no, averaged over questions. |
| **MRR** (mean reciprocal rank) | The average of `1 / rank of the first correct result`. 1.0 means the correct result is always first. |
| **Precision@k** | The share of the first *k* results that are relevant. |
| **nDCG** | Like precision, but a correct result at rank 1 counts more than at rank 8. |
| **Evidence coverage** | For a question with several parts: the share of parts for which a supporting chunk reached the model. "Complete" means every part was covered. |
| **LLM judge** | A second language model that grades answers against a written rubric. |
| **Faithfulness** | The share of an answer's claims that the retrieved text supports. |
| **MMR** (maximal marginal relevance) | A selection method that prefers results unlike those already chosen. Tested here, not used. |
| **Qdrant** | The vector database that stores the chunks, their embeddings and BM25 data. |
| **Langfuse** | Stores a trace of every search, the eval datasets and their results, and the versioned prompts. |
| **Stored page (snapshot)** | The last fetched Markdown of a page and its one-sentence description, kept in Qdrant (`<collection>_pages`). `read_section` reads from it. `python -m src.reindex --generate-missing-summaries` fills in missing descriptions. |
| **Quarantine** | A new page that failed a check: not indexed until the owner decides. |
