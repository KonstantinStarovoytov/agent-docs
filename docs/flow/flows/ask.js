// The agent path: a question, search_docs, read_section, an answer, and how
// Langfuse measures it. Data only; the engine is index.html.
FLOW = {
  title: 'Agent Docs: query flow',
  h1: 'Query flow',
  lead: 'Agent Docs: how an agent’s question becomes a cited answer, and how each step is measured.',
  legend: inverse => `Orange: happening now. ${inverse}: a service at work. Dashed: a call or a trace.`,
  zones() {
    // Zones (large tabs), then the two tool groups (medium tabs)
    folder(30, 196, 300, 554, 46, 28, 'Agent and its own LLM', C.zone, { 'font-family': FRANKLIN, 'font-weight': 700 });
    folder(360, 196, 360, 554, 376, 28, 'Agent Docs MCP server', C.zone, { 'font-family': FRANKLIN, 'font-weight': 700 });
    folder(750, 196, 300, 554, 766, 28, 'Services', C.zone, { 'font-family': FRANKLIN, 'font-weight': 700 });
    folder(378, 238, 324, 322, 390, 22, 'search_docs', C.inner, { 'font-family': MONO, 'font-size': 13, 'font-weight': 600 }, 9);
    folder(378, 594, 324, 140, 390, 22, 'read_section', C.inner, { 'font-family': MONO, 'font-size': 13, 'font-weight': 600 }, 9);
    const lf = folder(30, 836, 1020, 104, 0, 28, 'Langfuse: traces and evals', C.zone, { 'font-family': FRANKLIN, 'font-weight': 700 });
    // Langfuse tab sits at the right end, out of the trace line's way
    lf.p.remove(); lf.t.remove();
    folder(30, 836, 1020, 104, 1050 - 16 - lf.tw, 28, 'Langfuse: traces and evals', C.zone, { 'font-family': FRANKLIN, 'font-weight': 700 });
  },
  labels() {
    txt(552, 818, 'trace spans', { 'font-family': FRANKLIN, 'font-size': 13, fill: C.muted });
  },
};

(() => {
// id: [cx, cy, w, h, title, sub, kind]
const NODES = {
  A_q:      [180, 266, 260, 46, 'How do I create a skill?', '', 'quote'],
  A_plan:   [180, 334, 260, 50, 'Plans the call', 'keywords, one topic', 'node'],
  A_call1:  [180, 400, 260, 42, 'search_docs()', '', 'tool'],
  A_read:   [180, 516, 260, 50, 'Reads the previews', 'enough, or read more?', 'node'],
  A_call2:  [180, 652, 260, 42, 'read_section()', '', 'tool'],
  A_write:  [180, 718, 260, 50, 'Writes the answer', 'with links to the pages', 'node'],
  A_ans:    [180, 790, 260, 44, 'Answer with sources', '', 'quote'],
  S_hybrid: [540, 298, 280, 50, 'Hybrid search', 'dense 60 + BM25 60 chunks', 'node'],
  S_rrf:    [540, 364, 280, 50, 'Rank fusion', 'merge by rank, keep 20', 'node'],
  S_rerank: [540, 430, 280, 50, 'Rerank', 'Cohere scores all 20', 'node'],
  S_page:   [540, 516, 280, 50, 'Best chunk per page', 'up to 8 pages, 300-char previews', 'node'],
  S_read:   [540, 670, 280, 50, 'Section reader', 'the page’s Markdown, no LLM', 'node'],
  E_openai: [900, 298, 260, 50, 'OpenAI embeddings', 'text-embedding-3-small', 'node'],
  E_chunks: [900, 364, 260, 50, 'Qdrant chunks', 'dense and BM25 vectors', 'store'],
  E_cohere: [900, 430, 260, 50, 'Cohere rerank', 'rerank-v4.0-fast', 'node'],
  E_reindex:[900, 516, 260, 50, 'Daily reindex', 'llms.txt, gate, embed', 'node'],
  E_snap:   [900, 670, 260, 50, 'Qdrant pages', 'full Markdown of each page', 'store'],
  O_traces: [138, 904, 180, 50, 'Traces', 'search and rerank spans', 'node'],
  O_data:   [336, 904, 180, 50, 'Datasets', 'labelled questions', 'node'],
  O_metrics:[534, 904, 180, 50, 'Code metrics', 'hit@5, MRR, coverage', 'node'],
  O_judge:  [732, 904, 180, 50, 'LLM judge', 'faithfulness, refusals', 'node'],
  O_gate:   [930, 904, 180, 50, 'Gate', 'no drop over 0.03', 'node'],
};

const EDGES = {
  e_q_plan:        [[[180, 289], [180, 309]], 'solid'],
  e_plan_call1:    [[[180, 359], [180, 379]], 'solid'],
  e_call1_hyb:     [[[310, 400], [345, 400], [345, 298], [400, 298]], 'dash'],
  e_hyb_rrf:       [[[540, 323], [540, 339]], 'solid'],
  e_rrf_rerank:    [[[540, 389], [540, 405]], 'solid'],
  e_rerank_page:   [[[540, 455], [540, 491]], 'solid'],
  e_page_read:     [[[400, 516], [310, 516]], 'dash'],
  e_read_call2:    [[[180, 541], [180, 631]], 'solid'],
  e_call2_sread:   [[[310, 652], [400, 652]], 'dash'],
  e_sread_write:   [[[400, 686], [352, 686], [352, 718], [310, 718]], 'dash'],
  e_write_ans:     [[[180, 743], [180, 768]], 'solid'],
  e_hyb_openai:    [[[680, 298], [770, 298]], 'dash'],
  e_rrf_qdrant:    [[[680, 364], [770, 364]], 'dash'],
  e_rerank_cohere: [[[680, 430], [770, 430]], 'dash'],
  e_sread_snap:    [[[680, 670], [770, 670]], 'dash'],
  e_reindex_chunks:[[[1030, 516], [1041, 516], [1041, 364], [1030, 364]], 'dash'],
  e_reindex_snap:  [[[900, 541], [900, 633]], 'dash'],
  e_spans:         [[[540, 752], [540, 826], [138, 826], [138, 879]], 'dash'],
  e_ds_metrics:    [[[426, 904], [444, 904]], 'solid'],
  e_metrics_judge: [[[624, 904], [642, 904]], 'solid'],
  e_judge_gate:    [[[822, 904], [840, 904]], 'solid'],
};

const STEPS = [
  { t: 'How a question becomes a cited answer', d: 'An agent calls two MCP tools: one finds where the answer is, the other returns it whole. Langfuse measures every step.', n: [], s: [], e: [], dur: 4.4 },
  { t: 'The question', d: 'A user asks any agent, in any language. The agent can call two tools from Agent Docs.', n: ['A_q'], s: [], e: [], dur: 3.4 },
  { t: 'The agent plans the call', d: 'Its own LLM follows the tool descriptions: search in English, one topic per call, a product filter when the product is named.', n: ['A_plan'], s: [], e: ['e_q_plan'], dur: 4.2 },
  { t: 'search_docs goes out', d: 'The call reaches the MCP server on Render. The agent decides what to ask; the server only retrieves.', n: ['A_call1'], s: [], e: ['e_plan_call1', 'e_call1_hyb'], dur: 3.8 },
  { t: 'Hybrid search over chunks', d: 'Pages are cut into chunks in advance. Dense search matches the meaning, BM25 exact words like SKILL.md; each returns its top 60.', n: ['S_hybrid'], s: ['E_openai', 'E_chunks'], e: ['e_hyb_openai', 'e_rrf_qdrant'], dur: 4.8 },
  { t: 'Rank fusion', d: 'The lists merge by rank, ties sorted by chunk id. The top 20 go on: reading 3 × more means a tie is never cut in half.', n: ['S_rrf'], s: ['E_chunks'], e: ['e_hyb_rrf'], dur: 4.4 },
  { t: 'Rerank', d: 'Cohere reads the question with each of the 20 chunks and scores it from 0 to 1. Nothing is dropped here.', n: ['S_rerank'], s: ['E_cohere'], e: ['e_rrf_rerank', 'e_rerank_cohere'], dur: 4.0 },
  { t: 'One chunk per page', d: 'A passage is the best chunk of its page. The page’s other chunks that score 0.35 or more are named in other_sections, without text. Up to 8 pages come back.', n: ['S_page'], s: [], e: ['e_rerank_page'], dur: 4.8 },
  { t: 'What the agent receives', d: 'Each passage carries the page, the section, a link, a one-line description, a score, a 300-character preview and other_sections.', n: ['A_read'], s: [], e: ['e_page_read'], dur: 5.0 },
  { t: 'read_section maps the page', d: 'The preview cuts the steps short. The agent can open a heading from the passage or its other_sections, or ask for the page outline first.', n: ['A_call2', 'S_read'], s: ['E_snap'], e: ['e_read_call2', 'e_call2_sread', 'e_sread_snap'], dur: 4.4 },
  { t: 'read_section returns the section', d: 'With a heading it gets the section as the page’s own Markdown, subsections included, code and lists intact.', n: ['A_call2', 'S_read'], s: ['E_snap'], e: ['e_call2_sread', 'e_sread_snap'], dur: 5.4 },
  { t: 'A cited answer', d: 'The agent’s LLM answers from the official text, in the user’s language, and links the page it used.', n: ['A_write', 'A_ans'], s: [], e: ['e_sread_write', 'e_write_ans'], dur: 4.2 },
  { t: 'Search is traced', d: 'Every search_docs call leaves two observations in Langfuse: the hybrid search and the rerank, with inputs, outputs and timing.', n: ['O_traces'], s: [], e: ['e_spans'], dur: 4.2 },
  { t: 'Evals: code and an LLM judge', d: 'Labelled datasets. Code scores the retrieval; a different LLM grades faithfulness and refusals.', n: ['O_data', 'O_metrics', 'O_judge'], s: [], e: ['e_ds_metrics', 'e_metrics_judge'], dur: 4.8 },
  { t: 'The regression gate', d: 'Each change is run against labelled datasets. A metric that drops by more than 0.03 fails the gate. Two real verdicts:', n: ['O_gate'], s: [], e: ['e_judge_gate'], dur: 5.0 },
  { t: 'Refreshed every day', d: 'Every day a reindex job follows each vendor’s llms.txt. Only changed pages are embedded again; new pages pass a gate first.', n: ['E_reindex'], s: ['E_chunks', 'E_snap'], e: ['e_reindex_chunks', 'e_reindex_snap'], dur: 4.6 },
];

const ART = [
  { name: 'The two tools', ex: '', lines: [
    '<i class=h>search_docs</i>(query, product?, limit = 8)',
    '  dense search        top 60 chunks',
    '  BM25 search         top 60 chunks',
    '  RRF merge           60, the first 20 go on  <i class=c>3 × overfetch</i>',
    '  Cohere rerank       scores all 20',
    '  one per page        <i class=hl>up to 8 passages</i>, 300-char previews',
    '                      + other_sections: the page’s other headings',
    '<i class=h>read_section</i>(url, heading?, offset?)',
    '  no heading          the page outline',
    '  a heading           the section as <i class=hl>Markdown</i>, 8,000 chars a call',
    '',
    '<i class=c>a chunk is a piece of a page, up to 3,000 characters</i>'] },
  { name: 'The chat', ex: '', html: `<div class="chat"><div class="who" style="text-align:right">user</div>
     <div style="display:flex;justify-content:flex-end"><div class="bubble" style="background:var(--inverse);color:var(--inverse-ink);">How do I create a skill in Claude Code?</div></div>
     <div class="who" style="margin-top:28px">tools the agent can call</div>
     <div class="code lit" style="font-size:15px;line-height:26px"><span class="hl">search_docs</span>   find where the answer is<br><span class="hl">read_section</span>  read it whole</div></div>` },
  { name: 'The agent’s plan', ex: 'Example', lines: [
    '<i class=k>question</i>  <i class=s>"How do I create a skill in Claude Code?"</i>',
    '<i class=k>query</i>     keywords, in English as the tool asks',
    '<i class=k>topics</i>    one, so one call',
    '<i class=k>product</i>   Claude Code is named, so filter',
    '',
    '<i class=k>limit</i>     the default: up to 8 pages',
    '',
    '<i class=k>call</i>      <i class=hl>search_docs("create a skill",</i>',
    '          <i class=hl>  product="claude-code")</i>'] },
  { name: 'The MCP request', ex: 'Example', lines: [
    '{',
    '  <i class=k>"jsonrpc"</i>: <i class=s>"2.0"</i>, <i class=k>"id"</i>: 3,',
    '  <i class=k>"method"</i>: <i class=s>"tools/call"</i>,',
    '  <i class=k>"params"</i>: {',
    '    <i class=k>"name"</i>: <i class="s hl">"search_docs"</i>,',
    '    <i class=k>"arguments"</i>: {',
    '      <i class=k>"query"</i>: <i class=s>"create a skill"</i>,',
    '      <i class=k>"product"</i>: <i class=s>"claude-code"</i>',
    '    }',
    '  }',
    '}'] },
  { name: 'Inside Qdrant', ex: 'Real pages, example ranks', lines: [
    '<i class=c>every page, cut into</i> <i class=hl>chunks of ≤ 3,000 characters</i>',
    '',
    '<i class=h>dense: meaning</i>                <i class=h>BM25: exact words</i>',
    '1 claude-code/skills.md        1 cursor/skills.md',
    '  <i class=g>›</i> Create your first skill       <i class=g>›</i> <i class=hl>SKILL.md</i> file format',
    '2 agent-sdk/skills.md          2 claude-code/skills.md',
    '  <i class=g>›</i> Create skills                 <i class=g>›</i> Create your first skill',
    '3 cursor/skills.md             3 agent-sdk/skills.md',
    '  <i class=g>›</i> SKILL.md file format          <i class=g>›</i> Create skills',
    '<i class=c>… 60 in each list: 3 × the 20 the reranker takes</i>'] },
  { name: 'Rank fusion', ex: 'Example ranks', lines: [
    '<i class=c>score = 1/(60 + dense rank) + 1/(60 + BM25 rank)</i>',
    '',
    '<i class=h>chunk                               dense BM25     RRF</i>',
    'claude-code › Create your first skill   1    2  0.0325',
    'cursor › SKILL.md file format           3    1  0.0323',
    'agent-sdk › Create skills               2    3  0.0320',
    '<i class=c>…</i>',
    '',
    '<i class=c>ranks, because the two scores are not comparable</i>',
    '<i class=hl>ties sorted by chunk id: same question, same list</i>',
    '<i class=c>the first 20 of the 60 go on to the reranker</i>'] },
  { name: 'Cohere scores', ex: 'Real headings, example scores', html: `<div class="bars">
     ${[['0.91', 91, 'claude-code › Create your first skill'], ['0.86', 86, 'claude-code › Extend Claude with skills'], ['0.84', 84, 'claude-code › Frontmatter reference'], ['0.77', 77, 'cursor › SKILL.md file format'], ['0.62', 62, 'agent-sdk › Create skills'], ['0.35', 35, 'claude-code › Share skills']]
       .map(([s, w, l]) => `<div class="bar-row"><span class="sc">${s}</span><span class="track"><span class="fill" style="--w:${w}%"></span></span><span class="lbl">${l}</span></div>`).join('')}
     <div class="key" style="color:var(--muted)">Each chunk is read with the question. All 20 are scored.</div></div>` },
  { name: 'Pages, one chunk each', ex: 'Real headings, example scores', html: `<div class="sheets">
     <div class="sheet"><span class="ft">claude-code/skills.md</span><div class="pg">
       <div class="chunk best"><span>Create your first skill</span><span>0.91</span></div>
       <div class="chunk cand drop"><span>Extend Claude with skills</span><span>0.86</span></div>
       <div class="chunk cand drop"><span>Frontmatter reference</span><span>0.84</span></div>
       <div class="chunk cand drop"><span>Share skills</span><span>0.35</span></div></div></div>
     <div class="sheet"><span class="ft">cursor/skills.md</span><div class="pg">
       <div class="chunk best"><span>SKILL.md file format</span><span>0.77</span></div>
       <div class="chunk cand drop"><span>Skill directories</span><span>0.18</span></div></div></div>
     <div class="sheet"><span class="ft">agent-sdk/skills.md</span><div class="pg">
       <div class="chunk best"><span>Create skills</span><span>0.62</span></div></div></div>
     </div>
     <div class="key"><b>Orange</b> is a passage: the best chunk of its page.<br><b>Struck out</b>: same page; text dropped, heading kept<br>in other_sections at 0.35 or more (not Skill directories).</div>` },
  { name: 'One passage, as returned', ex: 'Index of 14 Oct 2026; rank, score and text are examples', lines: [
    '{',
    '  <i class=k>"rank"</i>: 1, <i class=k>"score"</i>: 0.91, <i class=k>"title"</i>: <i class=s>"Extend Claude with skills"</i>,',
    '  <i class=k>"heading"</i>: <i class=s>"… > Getting started > Create your first skill"</i>,',
    '  <i class=k>"url"</i>: <i class=s>"https://code.claude.com/docs/en/skills.md"</i>,',
    '  <i class=k>"description"</i>: <i class=s>"Explains how to create, manage, …"</i>,',
    N('  <i class=k>"content"</i>: <i class=s>"first 300 chars of the chunk"</i>,', 'a preview', 49),
    '  <i class=k>"truncated"</i>: true,',
    N('  <i class=k>"other_sections"</i>: [', 'pass one to read_section', 49),
    '    <i class="s hl">"Extend Claude with skills"</i>, <i class="s hl">"… > Configure skills</i>',
    '    <i class="s hl">> Frontmatter reference"</i>, <i class="s hl">"… > Share skills"</i>]',
    '}'] },
  { name: 'The page outline', ex: 'Index of 14 Oct 2026', lines: [
    '<i class=c>read_section(url)</i>',
    '{',
    '  <i class=k>"title"</i>: <i class=s>"Extend Claude with skills"</i>,',
    '  <i class=k>"outline"</i>: [',
    '    <i class=s>"# Extend Claude with skills"</i>,',
    '    <i class=s>"## Bundled skills (4 subsections)"</i>,',
    '    <i class="s hl">"## Getting started (3 subsections)"</i>,',
    '    <i class=s>"## Configure skills (7 subsections)"</i>,',
    '    <i class=c>… five more sections</i>',
    '  ]',
    '}',
    '<i class=c>the whole map is about 75 tokens</i>'] },
  { name: 'The section, as Markdown', ex: 'Index of 14 Oct 2026; text abridged', lines: [
    '<i class=c>read_section(url, "Create your first skill")</i>',
    '<i class=k>"heading"</i>: <i class=s>"… > Getting started > Create your first skill"</i>',
    N('<i class=k>"total_chars"</i>: 9478, <i class=k>"next_offset"</i>: <i class=hl>7952</i>', 'two calls to read it all', 46),
    '<i class=k>"text"</i>:',
    N('  <i class="g hl">###</i><i class=hl> </i><i class="h hl">Create your first skill</i>', 'the heading asked for', 46),
    '  <i class=c>…the paragraphs, as on the page…</i>',
    N('  <i class="g hl">```</i><i class=hl>bash</i>', 'code block, kept', 46),
    '  <i class=c>…</i>',
    '  <i class=g>```</i>',
    N('  <i class="g hl">| … | … |</i>', 'table, kept', 46),
    '  <i class=c>…three more code blocks…</i>'] },
  { name: 'The answer', ex: 'Example', html: `<div class="chat"><div class="who">agent</div>
     <div class="bubble" style="background:var(--node)">Create a folder <code>.claude/skills/&lt;name&gt;/</code> with a <code>SKILL.md</code> file, and set <code>name</code> and <code>description</code> in its frontmatter. Personal skills go in <code>~/.claude/skills/</code>.
     <div class="lit" style="margin-top:12px;font-size:15px">Source: <span class="hl" style="text-decoration:underline">Extend Claude with skills, Claude Code docs</span></div></div></div>` },
  { name: 'What Langfuse records', ex: '', lines: [
    '<i class=h>hybrid-search</i>',
    '  <i class=k>input</i>   query, k: 20, vendor scope',
    '  <i class=k>output</i>  20 chunks: page, heading, score',
    '<i class=h>rerank-candidates</i>',
    '  <i class=k>input</i>   query and the 20 chunks',
    '  <i class=k>output</i>  <i class=hl>rerank score, old rank, new rank</i>',
    '  <i class=k>model</i>   rerank-v4.0-fast',
    '',
    '<i class=c>each with its timing, tagged environment: production</i>',
    '<i class=c>read_section is not traced: it calls no model</i>',
    '<i class=c>a caller’s own Cohere key is never recorded</i>'] },
  { name: 'Eval results, October 2026', ex: '', lines: [
    '<i class=h>dataset               metric          score  by</i>',
    'retrieval-v3          hit@5           0.957  code',
    'retrieval-v3          MRR             0.826  code',
    'evidence-coverage-v1  faithfulness    0.987  <i class=hl>judge</i>',
    'negative-v1           correct refusal 1.000  <i class=hl>judge</i>',
    'full-corpus-v1        hit@5           1.000  code',
    '',
    '<i class=c>code scores retrieval against labelled pages</i>',
    '<i class=c>the judge is a different model from the generator</i>',
    '<i class=c>measured on the /ask path, which shares the search</i>'] },
  { name: 'The gate at work', ex: '', lines: [
    '<i class=h>rule</i>  a drop of more than 0.03 fails the gate',
    '',
    '<i class=h>one passage per page</i>      before  after',
    '  page hit@5                0.936   0.979  pass',
    '  distinct pages in top 5   3.1     5.0    pass',
    '  <i class="pass hl">kept</i>',
    '',
    '<i class=h>per-page cap in the pool</i>  before  after',
    '  MRR                       0.825   0.739  fail',
    '  <i class=hl>rejected</i>'] },
  { name: 'Reindex report', ex: 'Example run', lines: [
    '<i class=k>sources</i>    llms.txt of each of the 4 vendors',
    '<i class=k>unchanged</i>  601  one HTTP request each',
    '<i class=k>changed</i>     12  <i class=hl>chunked and embedded again</i>',
    '<i class=k>new</i>          3  page gate: 2 indexed, 1 quarantined',
    '<i class=k>removed</i>      1  guarded: at most 10% per vendor',
    '',
    '<i class=c>quarantined pages wait for a person to review</i>',
    '<i class=c>the change report lists every page added or removed</i>'] },
];

Object.assign(FLOW, { NODES, EDGES, STEPS, ART });
})();
