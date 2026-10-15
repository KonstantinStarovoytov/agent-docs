// The daily reindex, drawn as the ledger of one real run: stage tabs on top,
// the pages of the run of 14 Oct 2026 as rows that fill in step by step, and
// the stores and outputs below. Data only; the engine is index.html. Every
// rule is what src/reindex.py and .github/workflows/reindex.yml do; every row
// and outcome is from reports/docs-changes/2026-10-14.md and the manifest
// commit of that run (44a880b).
FLOW = {
  title: 'Agent Docs: daily reindex',
  h1: 'Daily reindex',
  lead: 'Agent Docs: how the index follows each vendor’s docs, every day.',
  legend: inverse => `Orange: this step. ${inverse}: a store in use. Rows: the run of 14 Oct 2026, pages grouped.`,
};

(() => {
// Stage tabs on top of the ledger; each step belongs to one stage.
const STAGES = ['06:00 UTC', 'llms.txt', 'Fetch', 'Compare', 'Apply', 'Smoke check', 'Report', 'Issues'];
const STAGE_OF = [-1, 0, 1, 2, 3, 4, 4, 4, 4, 5, 6, 7, 7];

// Columns of the ledger: [x, width, header].
const COLS = [[46, 330, 'Page'], [376, 140, 'Fetch'], [516, 170, 'Against the manifest'], [686, 110, 'Group'], [796, 244, 'Action']];
// Rows of the run of 14 Oct 2026. Each cell: [text, step it appears at].
const ROWS = [
  { page: ['cursor › Gemini 4 Argon', '…/docs/models/gemini-4-argon.md'], cells: [['fetched', 3], ['no entry', 4], ['new', 4], ['gate kept it: indexed', 6]] },
  { page: ['cursor › Publish', '…/docs/origin/apps/publish.md'], cells: [['fetched', 3], ['no entry', 4], ['new', 4], ['gate kept it: indexed', 6]] },
  { page: ['claude-code › Automate work with routines', '…/docs/en/routines.md'], cells: [['fetched', 3], ['differs', 4], ['changed', 4], ['re-embedded, summary', 7]] },
  { page: ['576 more pages', '23 significant, 553 minor'], cells: [['fetched', 3], ['differs', 4], ['changed', 4], ['re-embedded', 7]] },
  { page: ['claude-code › data-usage.md', 'now excluded (legal)'], cells: [['not selected', 3], ['has an entry', 4], ['gone', 4], ['deleted', 8]] },
  { page: ['39 more pages', 'now excluded, all vendors'], cells: [['not selected', 3], ['has an entry', 4], ['gone', 4], ['deleted', 8]] },
  { page: ['5 Codex pages', 'e.g. learn.chatgpt.com/docs.md'], cells: [['HTTP 404', 3], ['no entry', 4], ['none', 4], ['not indexed', 3]] },
];
const ROW_TOP = 268, ROW_H = 50;
// Run outcomes under the rows: [label, value, step, x, y].
const OUTCOMES = [
  ['Unchanged pages', 'none: a new chunker version changed all 577 fingerprints', 5, 46, 640],
  ['Smoke check', 'passed', 9, 46, 666],
  ['Change report', 'committed with the manifest', 10, 546, 666],
  ['Review issue', 'none: nothing quarantined', 11, 46, 692],
  ['Failure issue', 'none: the run succeeded', 12, 546, 692],
];

const tabs = [], cells = [], rowBands = [];

FLOW.zones = function () {
  // The ledger sheet with the stage tabs as its index tabs.
  el('rect', { x: 30, y: 214, width: 1020, height: 498, fill: C.zone });
  const tw = (1020 - 7 * 6) / 8;
  STAGES.forEach((label, i) => {
    const x = 30 + i * (tw + 6), y = 176, h = 38;
    const p = el('path', { d: `M${x},${y + h} L${x + 10},${y} H${x + tw - 10} L${x + tw},${y + h} Z` });
    const t = txt(x + tw / 2, y + h / 2 + 5, label, { 'font-family': FRANKLIN, 'font-weight': 700, 'font-size': 14, 'text-anchor': 'middle' });
    tabs.push({ p, t });
  });
  // Column headers.
  for (const [x, , header] of COLS) txt(x, 248, header, { 'font-family': FRANKLIN, 'font-weight': 700, 'font-size': 13, fill: C.muted });
  // Rows: a band per row (lit when the step is about it), the page, then the cells.
  ROWS.forEach((row, r) => {
    const y = ROW_TOP + r * ROW_H;
    rowBands.push(el('rect', { x: 38, y: y - 2, width: 1004, height: ROW_H - 4, fill: C.zone }));
    const page = el('g', {});
    txt(46, y + 19, row.page[0], { 'font-family': FRANKLIN, 'font-weight': 700, 'font-size': 14.5, fill: C.ink }, page);
    txt(46, y + 37, row.page[1], { 'font-family': MONO, 'font-size': 12.5, fill: C.muted }, page);
    cells.push({ g: page, step: 2, hl: null, t: null, row: r });
    row.cells.forEach(([text, step], c) => {
      const [x] = COLS[c + 1];
      const g = el('g', {});
      const t = txt(x + 6, y + 28, text, { 'font-family': FRANKLIN, 'font-size': 14 }, g);
      const hl = el('rect', { x, y: y + 9, width: 0, height: 26, fill: C.accent }, g);
      g.insertBefore(hl, t);
      cells.push({ g, step, hl, t, row: r, w: t.getComputedTextLength() + 12 });
    });
  });
  // Run outcomes.
  OUTCOMES.forEach(([label, value, step, x, yy]) => {
    const g = el('g', {});
    const t1 = txt(x, yy, label + ':', { 'font-family': FRANKLIN, 'font-weight': 700, 'font-size': 13.5, fill: C.ink }, g);
    const t = txt(x + t1.getComputedTextLength() + 6, yy, value, { 'font-family': FRANKLIN, 'font-size': 13.5 }, g);
    const hl = el('rect', { x: x - 4, y: yy - 16, width: 0, height: 22, fill: C.accent }, g);
    g.insertBefore(hl, t1);
    cells.push({ g, step, hl, t, t1, w: t1.getComputedTextLength() + t.getComputedTextLength() + 16 });
  });
  // Stores and outputs below the ledger.
  folder(30, 734, 500, 206, 46, 28, 'Stores', C.zone, { 'font-family': FRANKLIN, 'font-weight': 700 });
  folder(550, 734, 500, 206, 566, 28, 'Outputs', C.zone, { 'font-family': FRANKLIN, 'font-weight': 700 });
};
FLOW.labels = function () {};

FLOW.update = function (si, local) {
  const fade = clamp(local / 0.3), sweep = ease(clamp((local - 0.5) / 0.45));
  const stage = STAGE_OF[si];
  tabs.forEach(({ p, t }, i) => {
    const on = i === stage, done = si === 0 || i < stage;
    p.setAttribute('fill', on ? mix(C.zone, C.accent, fade) : done ? C.inner : C.zone);
    t.setAttribute('fill', on ? C['accent-ink'] : done ? C.ink : C.muted);
  });
  const lit = new Set(cells.filter(c => c.step === si && c.row !== undefined).map(c => c.row));
  rowBands.forEach((band, r) => band.setAttribute('fill', lit.has(r) ? mix(C.zone, C.inner, fade) : C.zone));
  for (const c of cells) {
    const shown = si === 0 || si >= c.step;
    const now = si !== 0 && si === c.step;
    c.g.setAttribute('opacity', shown ? (now ? fade : 1) : 0);
    if (!c.hl) continue;
    c.hl.setAttribute('width', now ? c.w * sweep : 0);
    const ink = now && sweep > 0.5 ? C['accent-ink'] : C.ink;
    c.t.setAttribute('fill', ink);
    if (c.t1) c.t1.setAttribute('fill', ink);
  }
};

// Stores and outputs: the engine colours them per step (n: this step, s: in use).
const NODES = {
  R_chunks:  [113, 845, 150, 50, 'Qdrant chunks', 'dense, BM25', 'store'],
  R_pages:   [280, 845, 150, 50, 'Qdrant pages', 'Markdown', 'store'],
  R_man:     [447, 845, 150, 50, 'Manifest', 'fingerprints, git', 'node'],
  O_report:  [633, 845, 150, 50, 'Change report', 'summary and git', 'node'],
  O_review:  [800, 845, 150, 50, 'Review issue', 'quarantine', 'node'],
  O_fail:    [967, 845, 150, 50, 'Failure issue', 'end of the log', 'node'],
};
const EDGES = {};

const ALL_STORES = ['R_chunks', 'R_pages', 'R_man'];
const STEPS = [
  { t: 'How the index stays fresh', d: 'Every day a GitHub Actions job reads each vendor’s llms.txt, updates only the pages that changed and reports what it did.', n: [], s: [], e: [], dur: 4.6 },
  { t: 'Every day at 06:00 UTC', d: 'A scheduled GitHub Actions job runs the reindex; GitHub may start it later. It can also be run by hand, as on 14 Oct.', n: [], s: [], e: [], dur: 4.0 },
  { t: 'Read each llms.txt', d: 'Each vendor lists its pages in llms.txt. Markdown pages count; translations, changelogs, notes and old spec versions are excluded.', n: [], s: [], e: [], dur: 4.8 },
  { t: 'Fetch every page', d: 'Six at a time. A failed page keeps its indexed copy if it has one; if more than 10% of a vendor’s pages fail, the run fails.', n: [], s: [], e: [], dur: 4.6 },
  { t: 'Compare fingerprints', d: 'Each page’s SHA-256 is compared with the manifest of the last run. Every page lands in one of four groups.', n: [], s: ['R_man'], e: [], dur: 4.8 },
  { t: 'Unchanged pages', d: 'Nothing more to do: the fetch was the only cost. On 14 Oct there were none, because a new chunker version changed every fingerprint.', n: [], s: [], e: [], dur: 4.6 },
  { t: 'New pages: the page gate', d: 'Free checks and the chat model look at every new page. Any flag sends it to quarantine; otherwise it is indexed.', n: [], s: ALL_STORES, e: [], dur: 5.2 },
  { t: 'Changed pages', d: 'Their old chunks are replaced and their stored Markdown is updated. A significant change also gets a one-sentence summary.', n: [], s: ALL_STORES, e: [], dur: 5.0 },
  { t: 'Gone pages: the removal guard', d: 'A page no longer listed, or now excluded, is deleted everywhere, unless too many of a vendor’s pages would go at once.', n: [], s: ALL_STORES, e: [], dur: 5.0 },
  { t: 'Smoke check', d: 'When the index changed, 8 known questions must still find their page in the top 10 of a search. A miss fails the run.', n: [], s: ['R_chunks'], e: [], dur: 4.4 },
  { t: 'Change report', d: 'Every run writes a readable report to the job summary. When something changed, it is committed to git with the manifest.', n: ['O_report'], s: ['R_man'], e: [], dur: 5.0 },
  { t: 'Review issue', d: 'Quarantined pages wait in one open issue. A person decides: exclude the page for good, or allow it.', n: ['O_review'], s: [], e: [], dur: 4.4 },
  { t: 'Failure issue', d: 'A guard trip, too many failed fetches, a failed smoke check or any failed step opens an issue with the end of the log.', n: ['O_fail'], s: [], e: [], dur: 4.4 },
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
    'a fetch fails               an indexed copy, if any, stays',
    '<i class=hl>more than 10% of a vendor</i>   the run fails',
    '',
    '<i class=c>14 Oct 2026: 5 Codex pages answered HTTP 404;</i>',
    '<i class=c>none had been indexed, so none was added</i>'] },
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
    '<i class=c>the manifest keeps its fingerprint</i>',
    '<i class=c>14 Oct 2026: none; the chunker version had changed</i>'] },
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
    '## Fetch failures (old version kept)       <i class=c>5 pages</i>',
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
