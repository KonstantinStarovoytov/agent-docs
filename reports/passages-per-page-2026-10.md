# How many passages per page should search_docs return? (2026-10-14)

`search_docs` returns the best chunk of each page. The agent then sees one
heading per page, and can miss a second relevant section of the same page.
Four variants were compared on the same pools and the same Cohere scores:

| | Variant | Result slots |
|---|---|---|
| **A** | One passage per page (today) | one per page |
| **B** | Up to two passages per page | a second passage takes a slot |
| **C** | A second passage only if it scores ≥ 0.8 × the page's best and ≥ 0.35 | a second passage takes a slot |
| **D** | One passage per page, plus `other_sections`: the headings (no text) of the page's other chunks that scored ≥ 0.35, at most three | no extra slots |

## Method

- **Pools:** each question's `search_docs` pool, rebuilt from the live index
  `agent_docs_hybrid_v1` after the 2026-10-14 reindex. One query, pool 20,
  no product filter.
- **Scores:**
  - 3,271 pairs from the `rerank-candidates` spans that Langfuse kept for
    the 2026-10-11..13 eval runs;
  - 2,520 pairs from the eval score cache;
  - one Cohere call per question for the rest (83 calls).
- **Coverage:** every pool of every question is fully scored.
- **Labels:** page hit means a card on a page that holds a labelled chunk.
  Section hit means the labelled heading is visible: the card's own heading,
  or, in D, one of its `other_sections`. Only labels that name a heading
  count for section hit.
- **Tokens:** the size of a concise response, estimated as characters ÷ 4.
- **Check:** variant A reproduces the earlier measurements on the new index:
  retrieval-v3 page hit@5 is 0.979, as in experiment 22, and the
  evidence-coverage groups are 0.647 / 0.438, as in experiment 24.

Runner: `evals/experiments/passages_per_page.py`.

## Results

### retrieval-v3 (47 questions, 15 heading labels)

| limit | | Page hit | Section hit | Distinct pages | Tokens |
|---|---|---|---|---|---|
| 5 | A | 0.979 | 0.667 (10 / 15) | 4.96 | 726 |
| 5 | B | **0.957** | 0.800 | 3.85 | 731 |
| 5 | C | **0.957** | 0.800 | 3.85 | 731 |
| 5 | D | 0.979 | **0.867 (13 / 15)** | 4.96 | 802 |
| 8 | A | 0.979 | 0.667 | 7.45 | 1,079 |
| 8 | B | 0.979 | 0.800 | 5.98 | 1,151 |
| 8 | C | 0.979 | 0.800 | 6.06 | 1,151 |
| 8 | D | 0.979 | **0.867** | 7.45 | 1,169 |

### evidence-coverage-v1 (16 multi-part questions, 34 groups, 4 heading labels; one call per question)

| limit | | Group page hit | All groups of a question | Section hit | Tokens |
|---|---|---|---|---|---|
| 5 | A | 0.647 | 0.438 | 2 / 4 | 716 |
| 5 | B | **0.588** | **0.312** | 3 / 4 | 730 |
| 5 | C | **0.588** | **0.312** | 3 / 4 | 730 |
| 5 | D | 0.647 | 0.438 | **3 / 4** | 787 |
| 8 | A | 0.824 | 0.688 | 2 / 4 | 1,107 |
| 8 | B | **0.765** | **0.625** | 3 / 4 | 1,150 |
| 8 | C | **0.765** | **0.625** | 3 / 4 | 1,150 |
| 8 | D | 0.824 | 0.688 | **3 / 4** | 1,190 |

### full-corpus-v1 (20 questions, 2 heading labels)

The variants do not differ on hits: page hit is 1.000 and section hit is
2 / 2 in all of them. D adds 90 to 100 tokens.

## What changed per question

- **D found these sections; A did not:**
  - Claude Code features for reusable on-demand workflows;
  - packaging skills, hooks and subagents together;
  - where to configure a custom subagent;
  - MCP tool discovery and list changes.

  In each case the labelled section is a second chunk of a page already in
  the results. D names its heading; A hides it.
- **B gains the same sections except the subagent one. It loses pages in
  return:**
  - at limit 5, "What is AGENTS.md?";
  - the Cursor skill-vs-rule and MCP tool-discovery groups;
  - at limit 8, two multi-part groups (Codex skill delegation, Cursor
    hooks).

  Second passages push other pages out.
- **C behaves like B.** At 0.8 × best, most second chunks qualify, so the
  gap rule rarely changes the result.

## Conclusion

- **D is the only variant that improves section hit without losing a page.**
  Section hit on retrieval-v3 goes from 0.667 to 0.867, and evidence
  coverage from 2 / 4 to 3 / 4. Page hit, all-groups coverage and distinct
  pages are unchanged. The cost is +8 to +10% tokens per response.
- **B and C fail the gate.** All-groups coverage at limit 5 drops by 0.125,
  against a 0.03 tolerance, and page hit also falls.
- **A one-passage-per-page list stays right for finding pages.** The missing
  piece is a pointer to the page's other relevant sections, not their text.

**Limits:**

- Few labels name a heading: 21 in total. One case is 0.067 of section hit
  on retrieval-v3.
- D only shows headings, so the agent still has to call `read_section`.
  Whether agents use `other_sections` was not measured.

**Next:**

1. Add `other_sections` to `search_docs` passages. They come from the pool
   that is already reranked, so this needs no extra Cohere or Qdrant call.
2. Check on real agents that they call `read_section` on those headings.

**Follow-up:** `other_sections` shipped on 2026-10-14. The agent check is
[agent-other-sections-2026-10.md](agent-other-sections-2026-10.md) (experiment 26).
