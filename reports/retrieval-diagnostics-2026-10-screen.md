# Prefetch x pool screen (generated, no rerank)

recall@pool: share of questions (coverage: evidence groups) with a
correct chunk inside the candidate pool handed to Cohere. Coverage also
shows complete@pool (every group of the question in the pool).
`default` = today's prefetch (production 3 x pool, eval 3 x per-query k).

## evidence-coverage / production path: recall_at_pool (n=34)

| prefetch | pool 10 | pool 20 | pool 40 | pool 60 |
|---|---|---|---|---|
| default | 0.765 | 0.853 | 0.912 | 0.912 |
| 30 | 0.765 | 0.853 | n/a | n/a |
| 60 | 0.765 | 0.853 | 0.912 | 0.912 |
| 100 | 0.765 | 0.853 | 0.912 | 0.912 |
| 150 | 0.765 | 0.853 | 0.912 | 0.912 |

## evidence-coverage / production path: complete_at_pool (n=34)

| prefetch | pool 10 | pool 20 | pool 40 | pool 60 |
|---|---|---|---|---|
| default | 0.625 | 0.750 | 0.875 | 0.875 |
| 30 | 0.625 | 0.750 | n/a | n/a |
| 60 | 0.625 | 0.750 | 0.875 | 0.875 |
| 100 | 0.625 | 0.750 | 0.875 | 0.875 |
| 150 | 0.625 | 0.750 | 0.875 | 0.875 |

## query-transform / eval path: recall_at_pool (n=48)

| prefetch | pool 10 | pool 20 | pool 40 | pool 60 |
|---|---|---|---|---|
| default | 0.979 | 1.000 | 1.000 | 1.000 |
| 30 | 0.979 | 1.000 | 1.000 | 1.000 |
| 60 | 0.979 | 1.000 | 1.000 | 1.000 |
| 100 | 0.979 | 1.000 | 1.000 | 1.000 |
| 150 | 0.979 | 1.000 | 1.000 | 1.000 |

## query-transform / production path: recall_at_pool (n=24)

| prefetch | pool 10 | pool 20 | pool 40 | pool 60 |
|---|---|---|---|---|
| default | 0.917 | 0.958 | 1.000 | 1.000 |
| 30 | 0.917 | 0.958 | n/a | n/a |
| 60 | 0.917 | 0.958 | 1.000 | 1.000 |
| 100 | 0.917 | 0.958 | 1.000 | 1.000 |
| 150 | 0.917 | 0.958 | 1.000 | 1.000 |

## retrieval-v3 / eval path: recall_at_pool (n=47)

| prefetch | pool 10 | pool 20 | pool 40 | pool 60 |
|---|---|---|---|---|
| default | 0.957 | 0.957 | 0.979 | 1.000 |
| 30 | 0.957 | 0.957 | 0.979 | 1.000 |
| 60 | 0.957 | 0.957 | 0.979 | 1.000 |
| 100 | 0.957 | 0.957 | 0.979 | 1.000 |
| 150 | 0.957 | 0.957 | 0.979 | 1.000 |

## retrieval-v3 / production path: recall_at_pool (n=47)

| prefetch | pool 10 | pool 20 | pool 40 | pool 60 |
|---|---|---|---|---|
| default | 0.957 | 0.957 | 0.979 | 1.000 |
| 30 | 0.957 | 0.957 | n/a | n/a |
| 60 | 0.957 | 0.957 | 0.979 | 1.000 |
| 100 | 0.957 | 0.957 | 0.979 | 1.000 |
| 150 | 0.957 | 0.957 | 0.979 | 1.000 |
