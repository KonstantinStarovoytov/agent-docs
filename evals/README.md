# Evals

The datasets live in Langfuse. The scripts here seed them, run the pipeline
against them and score the results. What the numbers mean and which changes
they decided: [ARCHITECTURE.md → Evaluation](../ARCHITECTURE.md#evaluation).

Every runner writes to Langfuse and most call OpenAI and Cohere. `--help` is
always safe.

## The eval gate

A metric that drops by more than 0.03 against its last run fails the gate.

| Dataset | Measures | Run |
|---|---|---|
| `rag/retrieval-v3` | hit@k, MRR, precision@k | `uv run python -m evals.run_experiments` |
| `rag/retrieval-query-transform-v1` | the same, each need phrased six ways, Russian and Polish included | `uv run python -m evals.run_experiments --dataset rag/retrieval-query-transform-v1` |
| `rag/evidence-coverage-v1` | complete evidence for multi-part questions | `uv run python -m evals.run_evidence_coverage_experiment` |
| `rag/evidence-coverage-v1` | answer faithfulness, citations (LLM judge) | `uv run python -m evals.run_answer_quality_experiment` |
| `rag/negative-v1` | correct refusals (LLM judge) | `uv run python -m evals.run_answer_quality_experiment --negative` |
| `rag/full-corpus-v1` | hit@5 on pages added with the full index | `uv run python -m evals.run_experiments --dataset rag/full-corpus-v1` |

When a run misses, `uv run python -m evals.diagnose_retrieval slices` shows
where each correct chunk was lost (none of its commands call Cohere), and
`evals.inspect_failures` lists the failed cases of the last day's runs.

## Files

| File | Role |
|---|---|
| `evaluators.py`, `answer_quality.py`, `evidence_coverage.py` | Scorers: retrieval metrics, LLM judge, coverage |
| `eval_cache.py` | Reuses stored rerank scores so runs fit the Cohere trial quota |
| `negative_cases.py`, `full_corpus_cases.py` | Ground truth for two of the datasets |
| `seed_*.py` | Create or update a dataset in Langfuse |
| `run_*.py`, `diagnose_retrieval.py`, `inspect_failures.py` | Runners and diagnostics above |
| `experiments/` | One-off experiments that are finished; kept so their reports can be reproduced |
