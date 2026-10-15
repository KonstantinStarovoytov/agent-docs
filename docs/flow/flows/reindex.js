// The daily reindex: llms.txt, fetch, compare, the four groups of pages, the
// checks and the reports. Data only; the engine is index.html. Every step is
// what src/reindex.py and .github/workflows/reindex.yml do; dated lines quote
// the run of 14 Oct 2026 (reports/docs-changes/2026-10-14.md).
FLOW = {
  title: 'Agent Docs: daily reindex',
  h1: 'Agent Docs',
  lead: 'How the index stays fresh: every day, from each vendor’s llms.txt.',
  legend: inverse => `Orange: happening now. ${inverse}: a store being written or read. Lines: the order of the run.`,
  zones() {
    folder(30, 196, 300, 554, 46, 28, 'Daily job on GitHub Actions', C.zone, { 'font-family': FRANKLIN, 'font-weight': 700 });
    folder(360, 196, 360, 554, 376, 28, 'Each page', C.zone, { 'font-family': FRANKLIN, 'font-weight': 700 });
    folder(750, 196, 300, 554, 766, 28, 'Stores', C.zone, { 'font-family': FRANKLIN, 'font-weight': 700 });
    // The tab sits between the lines to Failure issue (x 660) and Smoke check (x 900).
    folder(30, 836, 1020, 104, 690, 28, 'Checks and reports', C.zone, { 'font-family': FRANKLIN, 'font-weight': 700 });
  },
  labels() {},
};

(() => {
// id: [cx, cy, w, h, title, sub, kind]
const NODES = {
  A_cron:     [180, 270, 260, 44, 'Every day, 06:00 UTC', '', 'quote'],
  A_read:     [180, 350, 260, 50, 'Read each llms.txt', '4 vendors, Markdown pages', 'node'],
  A_fetch:    [180, 430, 260, 50, 'Fetch every page', 'six at a time', 'node'],
  A_diff:     [180, 510, 260, 50, 'Compare fingerprints', 'SHA-256, with the manifest', 'node'],
  B_same:     [540, 300, 280, 50, 'Unchanged', 'skipped', 'node'],
  B_new:      [540, 400, 280, 50, 'New', 'page gate: index or quarantine', 'node'],
  B_changed:  [540, 500, 280, 50, 'Changed', 'chunked and embedded again', 'node'],
  B_gone:     [540, 600, 280, 50, 'Gone', 'deleted, behind a guard', 'node'],
  C_chunks:   [900, 400, 260, 50, 'Qdrant chunks', 'dense and BM25 vectors', 'store'],
  C_pages:    [900, 500, 260, 50, 'Qdrant pages', 'Markdown of each page', 'store'],
  C_manifest: [900, 600, 260, 50, 'Manifest', 'fingerprints, in git', 'node'],
  D_report:   [180, 902, 220, 50, 'Change report', 'job summary and git', 'node'],
  D_review:   [420, 902, 220, 50, 'Review issue', 'pages in quarantine', 'node'],
  D_fail:     [660, 902, 220, 50, 'Failure issue', 'a guard or check fails', 'node'],
  D_smoke:    [900, 902, 220, 50, 'Smoke check', '8 questions, top 10', 'node'],
};

const EDGES = {
  e_cron_read:     [[[180, 292], [180, 325]], 'solid'],
  e_read_fetch:    [[[180, 375], [180, 405]], 'solid'],
  e_fetch_diff:    [[[180, 455], [180, 485]], 'solid'],
  e_diff_same:     [[[310, 510], [345, 510], [345, 300], [400, 300]], 'solid'],
  e_diff_new:      [[[310, 510], [345, 510], [345, 400], [400, 400]], 'solid'],
  e_diff_changed:  [[[310, 510], [345, 510], [345, 500], [400, 500]], 'solid'],
  e_diff_gone:     [[[310, 510], [345, 510], [345, 600], [400, 600]], 'solid'],
  e_new_store:     [[[680, 400], [770, 400]], 'dash'],
  e_changed_store: [[[680, 500], [770, 500]], 'dash'],
  e_gone_store:    [[[680, 600], [770, 600]], 'dash'],
  e_report:        [[[180, 750], [180, 877]], 'dash'],
  e_review:        [[[420, 750], [420, 877]], 'dash'],
  e_fail:          [[[660, 750], [660, 877]], 'dash'],
  e_smoke:         [[[900, 750], [900, 877]], 'dash'],
};

const ALL_STORES = ['C_chunks', 'C_pages', 'C_manifest'];
const STEPS = [
  { t: 'How the index stays fresh', d: 'Every day a GitHub Actions job reads each vendor’s llms.txt, updates only the pages that changed and reports what it did.', n: [], s: [], e: [], dur: 4.4 },
  { t: 'Every day at 06:00 UTC', d: 'A scheduled GitHub Actions job runs the reindex; GitHub may start it a little later. It can also be run by hand.', n: ['A_cron'], s: [], e: [], dur: 4.0 },
  { t: 'Read each llms.txt', d: 'Each vendor lists its pages in llms.txt. Markdown pages count; translations, changelogs, notes and old spec versions are excluded.', n: ['A_read'], s: [], e: ['e_cron_read'], dur: 4.8 },
  { t: 'Fetch every page', d: 'Six at a time. A page that fails keeps its indexed copy; if more than 10% of a vendor’s pages fail, the run fails.', n: ['A_fetch'], s: [], e: ['e_read_fetch'], dur: 4.4 },
  { t: 'Compare fingerprints', d: 'Each page’s SHA-256 is compared with the manifest of the last run. Every page lands in one of four groups.', n: ['A_diff'], s: ['C_manifest'], e: ['e_fetch_diff'], dur: 4.6 },
  { t: 'Unchanged', d: 'Nothing more to do: the fetch was the only cost. No chunking, no embedding, no model call.', n: ['B_same'], s: [], e: ['e_diff_same'], dur: 3.8 },
  { t: 'New page: the page gate', d: 'Free checks and the chat model look at every new page. Any flag sends it to quarantine; otherwise it is indexed.', n: ['B_new'], s: ALL_STORES, e: ['e_diff_new', 'e_new_store'], dur: 5.2 },
  { t: 'Changed page', d: 'Its old chunks are replaced and its stored Markdown is updated. A significant change also gets a one-sentence summary.', n: ['B_changed'], s: ALL_STORES, e: ['e_diff_changed', 'e_changed_store'], dur: 5.0 },
  { t: 'Gone page: the removal guard', d: 'A page no longer listed, or now excluded, is deleted everywhere, unless too many of a vendor’s pages would go at once.', n: ['B_gone'], s: ALL_STORES, e: ['e_diff_gone', 'e_gone_store'], dur: 5.0 },
  { t: 'Smoke check', d: 'When the index changed, 8 known questions must still find their page in the top 10 of a search. A miss fails the run.', n: ['D_smoke'], s: ['C_chunks'], e: ['e_smoke'], dur: 4.4 },
  { t: 'Change report', d: 'Every run writes a readable report to the job summary. When something changed, it is committed to git with the manifest.', n: ['D_report'], s: ['C_manifest'], e: ['e_report'], dur: 5.0 },
  { t: 'Review issue', d: 'Quarantined pages wait in one open issue. A person decides: exclude the page for good, or allow it.', n: ['D_review'], s: [], e: ['e_review'], dur: 4.4 },
  { t: 'Failure issue', d: 'A guard trip, too many failed fetches, a failed smoke check or any failed step opens an issue with the end of the log.', n: ['D_fail'], s: [], e: ['e_fail'], dur: 4.4 },
];

const ART = [
  { name: 'One run', ex: '', lines: [
    '<i class=h>for each vendor</i>   read llms.txt, fetch every page',
    '<i class=h>for each page</i>     compare its SHA-256 with the manifest',
    '  unchanged         skip',
    '  new               page gate: <i class=hl>index or quarantine</i>',
    '  changed           chunk and embed again',
    '  gone              delete, behind a guard',
    '<i class=h>then</i>              smoke check, change report, issues',
    '',
    '<i class=c>only new and changed pages cost embeddings</i>'] },
  { name: 'The schedule', ex: '', lines: [
    '<i class=c># .github/workflows/reindex.yml</i>',
    'on:',
    '  schedule:',
    '    - cron: <i class="s hl">"0 6 * * *"</i>       <i class=c># every day, 06:00 UTC</i>',
    '  workflow_dispatch:            <i class=c># or by hand</i>',
    '',
    '<i class=c>each run also reads the index once,</i>',
    '<i class=c>which keeps the free Qdrant cluster awake</i>'] },
  { name: 'The sources', ex: '', lines: [
    'code.claude.com/docs/llms.txt',
    'cursor.com/llms.txt',
    'developers.openai.com/codex/llms.txt',
    'modelcontextprotocol.io/llms.txt',
    '',
    '<i class=h>Markdown pages only; excluded, for example</i>',
    '  /whats-new/, /changelog.md      notes that restate pages',
    '  /help/, /es/, /ja/ …            help center, translations',
    '  /codex-manual.md                a copy of every page',
    '  older /specification/ versions  only the newest is kept',
    '',
    '<i class=c>the full list: src/ingestion/sources.py</i>'] },
  { name: 'Fetching', ex: '', lines: [
    '<i class=h>6 pages at a time</i>',
    '',
    'a fetch fails               the indexed copy stays',
    '<i class=hl>more than 10% of a vendor</i>   the run fails',
    '',
    '<i class=c>14 Oct 2026: 5 Codex pages answered HTTP 404;</i>',
    '<i class=c>their indexed copies stayed</i>'] },
  { name: 'Four groups', ex: '', lines: [
    '<i class=h>fingerprint</i> = SHA-256 of the Markdown and the chunker version',
    '',
    '<i class=h>compared with the manifest</i>     <i class=h>group</i>',
    'same fingerprint               <i class=k>unchanged</i>',
    'another fingerprint            <i class=k>changed</i>',
    'not in the manifest            <i class=k>new</i>',
    'in the manifest, not selected  <i class=k>gone</i>',
    '',
    '<i class=c>a new chunker version changes every fingerprint;</i>',
    '<i class=c>a quarantined page is looked at again only when it changes</i>'] },
  { name: 'Unchanged', ex: '', lines: [
    '<i class=h>cost</i>       one HTTP request',
    '<i class=h>no</i>         chunking, embedding or model call',
    '',
    '<i class=c>the manifest keeps its fingerprint</i>'] },
  { name: 'The page gate', ex: '', lines: [
    '<i class=h>free checks</i>; any one flags the page',
    '  more than 150 chunks, or 5 × the vendor’s median',
    '  more than 30% non-Latin letters',
    '  80% the same as an indexed page',
    '  changelog, blog, terms, privacy … in the path',
    '<i class=h>the chat model</i> reads the first 1,500 characters',
    '  keep or quarantine, and one sentence on what it is',
    '<i class=c>pages on the allow list skip the gate</i>',
    '',
    '<i class=c>14 Oct 2026, indexed: cursor › Gemini 4 Argon</i>',
    '<i class=hl>"Reference page describing Gemini 4 Argon’s effort</i>',
    '<i class=hl> levels, available tools, and pricing in Cursor."</i>'] },
  { name: 'A changed page', ex: '', lines: [
    'its old chunks are deleted, the new ones added',
    '  cut at headings down to ####; tables 12 rows a chunk',
    '  at most 3,000 characters, 300 overlap',
    '  OpenAI text-embedding-3-small, and BM25 in Qdrant',
    'its Markdown replaces the stored page (read_section)',
    '',
    '<i class=h>significant</i>: a section added or removed,',
    '             or at least 10% of the lines',
    '  <i class=hl>one sentence on what changed</i>, at most 20 a run',
    '<i class=c>14 Oct 2026: 24 significant, 553 minor: a new chunker</i>',
    '<i class=c>version made every page count as changed</i>'] },
  { name: 'The removal guard', ex: '', lines: [
    'deleted from Qdrant chunks, stored pages and the manifest',
    '',
    '<i class=h>guard, per vendor</i>: nothing is deleted, the run fails, if',
    '  more than 10% of its indexed pages would go, or',
    '  its llms.txt lists under half of its indexed pages',
    '',
    '<i class=c>gone = no longer in llms.txt, or now excluded</i>',
    '<i class=c>14 Oct 2026: 40 pages removed, all newly excluded</i>',
    '<i class=c>(legal pages, link hubs, release notes, weekly notes)</i>'] },
  { name: 'The smoke check', ex: '', lines: [
    '<i class=h>after the index changed</i>',
    '  8 known questions, hybrid search, top 10',
    '  each must find a section of its expected page',
    '  <i class=hl>a miss fails the run</i>',
    '',
    '<i class=c>the questions: rag/retrieval-query-transform-v1</i>',
    '<i class=c>no reranker, so no Cohere call</i>'] },
  { name: 'reports/docs-changes/2026-10-14.md', ex: 'Abridged', lines: [
    '<i class=h># Documentation changes, 2026-10-14</i>',
    '## Added (2) — worth reading',
    '- cursor › Gemini 4 Argon',
    '  Reference page describing Gemini 4 Argon’s effort …',
    '## Removed (40)',
    '## Changed significantly (24)',
    '- claude-code › Automate work with routines',
    '  Routine runs can publish new private artifacts …',
    'Minor edits: 553 pages.',
    '## Fetch failures (old version kept)',
    '',
    '<i class=c>our summaries and links only, never vendor text</i>'] },
  { name: 'Pages waiting for review', ex: 'The page is an example', lines: [
    '<i class=c>label: docs-review</i>',
    '',
    'These new pages were not indexed. For each: add a',
    'pattern to exclude to drop it for good, or add the',
    'URL to allow to index it.',
    '',
    '- &lt;https://…/new-page.md&gt;',
    '  <i class=k>What it is:</i> one sentence from the gate',
    '  <i class=k>Why flagged:</i> the checks that fired',
    '',
    '<i class=c>one open issue; later runs add comments</i>'] },
  { name: 'Reindex needs attention (date)', ex: '', lines: [
    '<i class=c>label: reindex</i>',
    '',
    'Run: a link to the GitHub Actions run',
    'the last 40 lines of the log',
    '',
    '<i class=h>opened when</i>',
    '  a removal guard trips',
    '  more than 10% of a vendor’s fetches fail',
    '  the smoke check misses',
    '  any step fails',
    '',
    '<i class=c>one open issue; later failures add comments</i>'] },
];

Object.assign(FLOW, { NODES, EDGES, STEPS, ART });
})();
