# find_pages and read_section (2026-10-13)

Stored Cohere scores only (the pools and scores of
[dedup-abstain-2026-10.md](dedup-abstain-2026-10.md): search pool 20, one query,
no product filter, rebuilt from Qdrant `agent_docs_hybrid_v1`); 0 Cohere calls.
`find_pages` ranks pages exactly like `search_docs`, so its page hit is the
same simulation. Page hit = a card on a page that holds a labelled chunk.

## find_pages page hit

| Dataset | Items fully scored | Page hit@3 | Page hit@5 |
|---|---|---|---|
| retrieval-v3 | 47 / 47 | 0.936 | 0.979 |
| query-transform clean_en | 1 / 8 (64% of candidates scored) | 0.750* | 0.875* |
| full-corpus-v1 | 0 / 20 (54% of candidates scored) | 1.000* | 1.000* |
| evidence-coverage-v1, per group (34 groups) | 16 / 16 | 0.500 | 0.647 |
| evidence-coverage-v1, all groups of a question | 16 / 16 | 0.188 | 0.438 |

\* Ranked among the scored candidates only; indicative, not a measurement.
Evidence coverage uses one call for the whole multi-part question; the tool
asks for one call per part, which has no stored scores and was not measured.

## read_section on labelled headings

25 labels in retrieval-v3 and evidence-coverage-v1 name a heading
(`heading_contains`), 18 distinct page + heading pairs. Each was read with
`read_section(url, heading_contains)` from the real snapshot store.

| Store | Labels returning the section | Pairs | Median length | p95 length | Longer than 8,000 |
|---|---|---|---|---|---|
| v1 `_pages` today | 11 / 25 | 9 / 18 | 1,580 | 7,941 | 2 |
| v1 with the 28 missing pages read from v2's identical snapshots (read only) | 25 / 25 | 18 / 18 | 1,415 | 7,941 | 3 (max 20,722) |

Every failure today is "not a page of the index": 28 of the 617 pages in v1
(the original hand-picked set, indexed before snapshots existed and unchanged
since) have no snapshot. They are also 104 of 439 top-5 cards on these sets
(53 of 126 correct-page cards), which get an empty description and outline.
v2 has a snapshot for all 572 pages; 27 of the 28 are byte-identical (same
fingerprint) to what v1 indexed.

Summaries backfilled into the payloads: v1 582 of 589 pages, v2 550 of 572; the
rest fall back to the page's first sentence.

## Conclusion

- `find_pages` finds the labelled page in the top 5 for 46 of 47 retrieval-v3 questions, with no Cohere call beyond `search_docs`'s one.
- `read_section` returns the labelled section every time the page has a snapshot; most sections fit one call (median ~1.5k chars), 3 of 18 need `next_offset`.
- Before agents rely on it on v1, the 28 missing v1 snapshots must be written (copy the 27 identical ones from v2, fetch the last one), or production must move to v2.
