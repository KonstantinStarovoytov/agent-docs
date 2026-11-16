# Reports

Outputs of the experiments in [ARCHITECTURE.md → Experiments](../ARCHITECTURE.md#experiments).
The number in brackets is the experiment's row there. Raw data sits next to
the report that reads it.

## October 2026: full index

| Report | What it decided |
|---|---|
| [full-corpus-eval-2026-10.md](full-corpus-eval-2026-10.md) | The eval gate from 35 to ~600 pages (14) |
| [per-page-cap-2026-10.md](per-page-cap-2026-10.md) | A per-page cap on candidates: rejected (15) |
| [retrieval-diagnostics-2026-10.md](retrieval-diagnostics-2026-10.md) | Where missed chunks are lost; prefetch and pool size (16, 17). Detail: [screen](retrieval-diagnostics-2026-10-screen.md), [slices](retrieval-diagnostics-2026-10-slices.md), [threshold](retrieval-diagnostics-2026-10-threshold.md) |
| [index-v2-2026-10.md](index-v2-2026-10.md) | Index v2: BM25 IDF, excludes, reference chunks, product filter (18–21); raw data in [index-v2/](index-v2/) |
| [dedup-abstain-2026-10.md](dedup-abstain-2026-10.md) | One passage per page, and refusing on a low top score (22, 23) |
| [find-pages-2026-10.md](find-pages-2026-10.md) | Page cards and `read_section` (24) |
| [passages-per-page-2026-10.md](passages-per-page-2026-10.md) | One passage per page vs. more; headings of the page's other sections (25) |
| [agent-other-sections-2026-10.md](agent-other-sections-2026-10.md) | Real agents with and without `other_sections` (26) |
| [judge-agreement-2026-10.md](judge-agreement-2026-10.md) | Cheaper answer judges (Haiku 5.5, gpt-6-luna, gpt-5.6-luna) instead of gpt-6-sol: not for the gate (27) |

## September 2026: first index

| Report | What it decided |
|---|---|
| [rag-sources-2026-09-16.md](rag-sources-2026-09-16.md), [rag-audit-2026-09-16.md](rag-audit-2026-09-16.md) | Literature review and the pipeline checked against it; summary in [docs/rag-findings.md](../docs/rag-findings.md) |
| [mcp-audit-2026-09-15.md](mcp-audit-2026-09-15.md) | MCP server audit (in Russian); sample output in [ask-mcp.txt](ask-mcp.txt) |
| [evidence-coverage-v1.md](evidence-coverage-v1.md) | First evidence-coverage run on multi-part questions (4–6; in Russian) |
| [answer-quality-v1.md](answer-quality-v1.md) | First LLM-judge run on answers |
| [vendor-scope-ablation.md](vendor-scope-ablation.md) | Scoping search to one vendor on clean English questions |
| [frozen-selection-v1.json](frozen-selection-v1.json) | Frozen candidate pool for context-selection tests (10); see [evals/experiments/FROZEN_SELECTION.md](../evals/experiments/FROZEN_SELECTION.md) |

## Every day

[docs-changes/](docs-changes/) holds one report per reindex that changed
something: pages added, removed and changed, with links. Only our summaries
go to git, never the vendors' text.

**For programs: `feed.json`.** The same run also keeps
[docs-changes/feed.json](docs-changes/feed.json): the pages added,
removed and changed in the last 14 days, newest day first, for a program to
read. It holds addresses, products and headings only: no summary (a model wrote
it), no title and no page text. `new_sections` lists the headings a changed
page gained, and is empty when it gained none; a page re-embedded with the same
text is left out. `checked` is the day of the last run that reached the end,
also on a day with no change, so a reader can tell a quiet day from a stopped
reindex. It moves on too when some pages failed to fetch (their indexed copy is
kept) or the smoke test failed. So a long outage at one vendor reads as
"nothing new" for that vendor; the workflow's "Open an issue on failure" step
covers it (a vendor whose pages fail beyond the limit, or a failed smoke test,
fails the run). A changed page lists at most 50 new headings, each cut to 200
characters. Only the run on the production index writes it.

```json
{"checked": "2026-11-14",
 "days": [{"day": "2026-11-14",
   "added": [{"url": "https://code.claude.com/docs/en/code-mode.md", "product": "claude-code"}],
   "removed": [{"url": "https://cursor.com/docs/context/rules.md", "product": "cursor"}],
   "changed": [{"url": "https://code.claude.com/docs/en/tools-reference.md",
                "product": "claude-code",
                "new_sections": ["Protect read-only files in Perforce"]}]}]}
```
