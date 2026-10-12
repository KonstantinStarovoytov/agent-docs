# One passage per page and top-score abstention (2026-10-13)

Stored Cohere scores only (eval score cache + the 2026-10-12 Langfuse runs and
`retrieval-diagnostics-2026-10-stored.json`); 0 Cohere calls. Pools rebuilt from
Qdrant `agent_docs_hybrid_v1`. Page hit = a result on a page that holds a
labelled chunk.

## search_docs, pool 20, before → after one passage per page

| Dataset | Items fully scored | limit | Page hit@limit | Distinct pages |
|---|---|---|---|---|
| retrieval-v3 | 47 / 47 | 5 | 0.936 → 0.979 (+2, −0) | 3.09 → 4.96 |
| retrieval-v3 | 47 / 47 | 8 | 0.979 → 0.979 | 4.40 → 7.38 |
| query-transform clean_en | 1 / 8 (64% of candidates scored) | 5 | 0.875 → 0.875* | 4.00 → 5.00* |
| query-transform clean_en | 1 / 8 | 8 | 1.000 → 1.000* | 4.88 → 7.00* |
| full-corpus-v1 | 0 / 20 (54% of candidates scored) | 5 | 1.000 → 1.000* | 3.20 → 4.30* |
| full-corpus-v1 | 0 / 20 | 8 | 1.000 → 1.000* | 4.15 → 5.05* |

\* Ranked among the scored candidates only; unscored candidates are left out,
so these rows are indicative, not a measurement.

## ask_docs, pool 10: best rerank score per question

| Set | Questions | Pool fully scored | Lowest top score |
|---|---|---|---|
| retrieval-v3 | 47 | 47 | 0.83 |
| query-transform (all 6 variants) | 48 | 22 | 0.64** |
| evidence-coverage-v1 | 16 | 16 | 0.73 |
| full-corpus-v1 | 20 | 10 | 0.90** |
| negative-v1 | 12 | 12 (stored production run) | 0.12 |

\*\* Lower bound: an unscored candidate can only raise the top score.

| Threshold | Margin to lowest answerable (0.64) | Answerable lost | Negatives caught |
|---|---|---|---|
| 0.35 (today's floor) | 0.29 | 0 | 5 / 12 |
| 0.50 | 0.14 | 0 | 8 / 12 |
| **0.55** | **0.09** | **0** | **8 / 12** |
| 0.60 | 0.04 | 0 | 9 / 12 |

Negative top scores: 0.12, 0.22, 0.24, 0.25, 0.26, 0.38, 0.47, 0.48 | 0.59, 0.79, 0.83, 0.90.

## Conclusion

- One passage per page fills the list with distinct pages and loses no page hit; on retrieval-v3 it adds two hits at limit 5.
- `MIN_TOP_RERANK_SCORE` = 0.55: the highest 0.05 step with margin ≥ 0.05 over every answerable question. It catches 8 of 12 negatives, 3 more than the 0.35 floor, and skips their LLM call.
- The lowest answerable top (0.64, "Cursor rules only for Python files") is a lower bound on a partly scored pool; the margin holds either way.
- Fixed author-written sets; watch real traffic for answerable questions with a best score of 0.55–0.65.
