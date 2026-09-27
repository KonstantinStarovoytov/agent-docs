# Full documentation index: design

Status: approved in brainstorming on 2026-09-27; parts 4–7 pending spec review.

## Goal

Grow the index from 35 hand-picked pages to all product documentation of
Claude Code, Cursor, Codex and MCP, pick up new vendor pages automatically,
keep junk out, report every change in readable form, and switch production
only when the existing evals show no regression.

## Scope decisions

- In: all product documentation — guides, configuration, CLI, SDKs, references,
  administration. About 560 pages and 11,800 chunks (today 35 and 1,106).
- Out: Cursor help center (`/help/*`: billing, account, FAQ), changelogs and
  weekly "What's New" notes, translations, concatenated dumps, old and draft
  MCP spec versions, MCP community groups, MCP SEPs.
- Pages that vanish from a vendor's `llms.txt` are deleted automatically, behind
  a guard.
- Production switches only if old evals do not regress beyond noise and the new
  topics are found.

Measured on 2026-09-27 by fetching and chunking every link (no embeddings):

| | `llms.txt` links | kept | kept chunks |
|---|---|---|---|
| Claude Code | 221 | ~183 | ~5,700 |
| Cursor | 267 | ~152 | ~2,850 |
| Codex | 159 | ~147 | ~1,800 |
| MCP | 349 | ~76 | ~1,440 |

Embedding the kept corpus once: ~3.4M tokens, about $0.07. Qdrant: ~200 MB of
the 1 GB free cluster.

## 1. Corpus selection

`SourceConfig` drops the `include` allow-list and gains:

- `exclude: tuple[str, ...]` — regexes on the URL path; a match drops the page.
- `versioned_prefixes: tuple[str, ...]` — for each prefix with dated
  `<prefix>YYYY-MM-DD/` segments, only the newest date is kept; `draft` and
  older dates are dropped. Replaces the single `versioned_prefix`.
- `allow: tuple[str, ...]` — exact URLs indexed even when the page gate (§2)
  flags them. Starts empty.

Global rules in the loader:

- Only paths ending in `.md` are pages. This drops `llms-full.txt`,
  `openapi.yaml`, HTML endpoints and malformed links.
- `#fragment` is stripped as today. `?query` is kept: Codex serves different
  pages for `developer-commands.md?surface=cli` and `?surface=ide`.

Per-vendor excludes:

| Vendor | Exclude | Reason |
|---|---|---|
| Claude Code | `/docs/_llms/`, `/whats-new/`, `/changelog.md$` | localized indexes; weekly notes restate main pages; changelog is huge and changes daily |
| Cursor | `^/help/`, `^/[a-z]{2}(-[a-z]{2,4})?/`, `changelog` | help center out of scope; translations |
| Codex | `/codex-manual.md$` | concatenation of all other pages (1,019 chunks) |
| MCP | versioned `/docs/`, `/specification/`; `^/community/`, `^/seps/` | 198 duplicate pages across versions; groups and proposals are not documentation |

Kept on purpose: large references (MCP `schema.md`, Claude Code
`settings-reference`, `env-vars`, `errors`), because agents ask for exact
names. `schema.md` is the first exclusion candidate if evals show it floods the
candidate pool.

Metadata is unchanged: four products, and the MCP `product` filter works as
before. Agent SDK pages belong to `claude-code`; registry and extensions
belong to `mcp`.

The allow-list used to catch silent renames. The daily smoke check now does
that job: it fails when an expected page is missing from the top hits for the
query-transform intents.

## 2. Page gate (quarantine)

Runs in every reindex on pages that are not yet in the manifest.

Step 1, free checks:

- size: more than 150 chunks, or more than 5× the vendor median → "possible concatenation";
- language: a locale path segment, or more than 30% non-Latin letters → "translation";
- duplicate: ≥80% word-shingle overlap with an indexed page → "duplicate of <url>";
- path keywords: `changelog`, `release-notes`, `llms`, `full`, `blog`, `terms`,
  `privacy`, `proposal` → "probably not documentation".

Step 2, a cheap LLM (`REINDEX_REVIEW_MODEL`, default `gpt-4o-mini`) reads
the path, title and first ~1,500 characters. It returns `keep` or
`quarantine`, a category, and a one-sentence plain-language summary of what
the page is. About 1k tokens per page.

Outcome:

- No flag → the page is indexed.
- Any flag → quarantined: not indexed, stored in the manifest with its reason
  and summary, and not re-checked until its content changes.
- Pages on `allow` skip the gate.

Every quarantined page is listed in one open issue, "Pages waiting for review".
Each entry has:

- the link;
- one short sentence saying what the page is;
- why it was flagged;
- the two actions: add an `exclude` pattern (drop forever) or add the URL to
  `allow` (index it).

Initial build: the gate runs in report-only mode over all ~560 pages (~$0.05)
to validate the exclude list. Flagged pages are reviewed with the owner before
the production switch.

## 3. Reindex mechanics

- **Discovery:** added pages pass the gate, then get indexed. Changed pages are
  re-embedded as today. Unchanged pages cost one HTTP request.
- **Removals:** a page missing from `llms.txt` is deleted from the index, the
  snapshot store and the manifest. **Guard:** if more than 10% of a vendor's
  indexed pages would be removed in one run, or the vendor's `llms.txt` yields
  fewer than half of its previous page count, nothing is deleted for that
  vendor, the run fails, and an issue is opened.
- **Fetch failures:** a page that fails to fetch (4xx/5xx, timeout) is skipped
  and its indexed version kept, with a warning in the report. More than 10%
  failures for one vendor fails the run.
- **Concurrency:** pages are fetched 6 at a time, so ~560 pages take about a
  minute.
- **Snapshot store:** a payload-only Qdrant collection `agent_docs_pages` keeps
  the last fetched markdown per URL, together with sha, title, product and
  fetch time. It feeds the diff in §4. It lives in Qdrant, not git, because
  the repository is public and the documentation belongs to the vendors.
- **Manifest:** entries gain `status` (`indexed` | `quarantined`), `reason` and
  `summary`. The manifest path follows the collection name
  (`data/manifests/<collection>.json`), so two collections never share one.

## 4. Change report

After every run that changed something:

- **Added**, with the gate's one-sentence summary and a link — worth reading.
- **Removed.**
- **Changed significantly**, with sections added or removed (from a heading
  diff), the number of changed lines, and one LLM sentence on what changed.
- **Minor edits**, collapsed to a count.
- **Quarantined**, with summary and reason.
- **Guard trips and fetch failures.**

A change is significant when a section is added or removed, or when ≥10% of
lines changed. LLM change summaries are capped at 20 per run. The initial
build reports only totals.

Outputs:

- the GitHub Actions job summary, on every run;
- `reports/docs-changes/YYYY-MM-DD.md`, committed only when something changed.
  It holds our summaries and links, never vendor text;
- an issue only when a decision is needed: quarantine or a guard trip.

## 5. Rollout

1. Build `agent_docs_hybrid_v2` next to v1 with the new reindex, through a
   manual workflow run with a `collection` input. Production stays on v1.
2. Review the report-only gate output together and adjust excludes.
3. Run the eval gate (§6) against v2 by overriding `QDRANT_HYBRID_COLLECTION`.
4. Switch: set `QDRANT_HYBRID_COLLECTION=agent_docs_hybrid_v2` in Render and in
   the reindex workflow.
5. Keep v1 for two weeks as rollback (one env var), then delete it.

## 6. Eval gate

Regression: run the existing datasets on v1 and v2 with the same code, prompt
and `GENERATION_TOP_K=8`:

- `rag/retrieval-v3`, `rag/retrieval-query-transform-v1`:
  hit@5, MRR, precision@8;
- `rag/evidence-coverage-v1`: complete evidence coverage, faithfulness;
- `rag/negative-v1`: abstention_correct.

A metric fails if it drops by more than 0.03. Every retrieval miss is
inspected. If a newly indexed page is a valid alternative source, the
expected targets are extended, with the evidence recorded; that is a label
gap, not a regression.

The negative set is re-audited first. Cases the new corpus can answer
(pricing pages are now in scope) are replaced by questions still outside it.

New coverage: a new dataset `rag/full-corpus-v1` with ~20 questions over
newly covered areas: CLI, settings and env vars, SDKs, administration, cloud
agents, MCP registry and extensions. I draft the ground truth from the pages
and the owner may skim it. Pass: hit@5 ≥ 0.9.

If the gate fails, apply these in order, re-running the gate after each:

1. inspect the misses;
2. exclude `schema.md` and other oversized references that crowd out other pages;
3. cap chunks per source in the candidate pool;
4. tiered index (brainstorming approach C).

## 7. Testing

Unit tests, no network. Each item gets a test first:

- selection: `.md` rule, excludes, newest version per prefix, `?query` kept,
  `allow`, checked against a fixture `llms.txt`;
- gate heuristics: size, language, duplicate, path keywords; the LLM step with
  a fake model;
- removal guard, fetch-failure tolerance, quarantine persistence and re-check
  on content change;
- diff significance and report rendering.

A dry-run mode (`--dry-run`) fetches, selects, gates and reports without
writing to Qdrant, for checking config changes.

## Out of scope

Cursor help center, changelogs and "What's New", weekly digest issue,
usage-based pruning from production traces, tiered index (kept as mitigation
only), re-chunking or retrieval changes.
