# Frozen selection experiment

Run from the repository root:

```sh
uv run python -m evals.experiments.frozen_selection capture reports/frozen-selection-v1.json
uv run python -m evals.experiments.frozen_selection compare reports/frozen-selection-v1.json
uv run python -m evals.experiments.frozen_selection answers reports/frozen-selection-v1.json
```

Capture refuses to overwrite an existing snapshot. It stores questions, existing
source/heading labels, 20 candidates per question, exact chunk text and metadata,
and one common original-question Cohere ranking. Hybrid retrieval currently uses
branch depth 60. This is a candidate snapshot, not a full versioned corpus backup.

Compare calls the model once per uncached question, assigning supplied chunks to
requirements from that question. Gold evidence groups are never sent to the model.
A greedy selector maximizes newly covered predicted requirements, uses original
rank to break ties, and fills remaining slots by rank. No document cap is applied;
one chunk may satisfy multiple requirements.

Artifacts next to the snapshot:

- `.assignments.json`: frozen prompt, model, assignments, usage and duration.
- `.comparison.json`: content hashes, selected IDs, per-case coverage, approximate
  content token counts and oracle@5.

After all assignments exist, rerunning compare makes no model calls. Changes to
snapshot, prompt or model invalidate the cache. Partial progress is saved per case.
Token counts use cl100k_base and exclude headers, question and system prompt; they
are comparable context-size estimates, not billed generation token counts.

`answers` generates from the already stored selection IDs (`baseline8` vs `aspect8`).
It does not retrieve or rerank, and it does not run the section selector again, so a
greedy set is not silently truncated. Results go to `.answers.json` and resume per
case/variant. The judge is the same `answer-evaluator` prompt as the live answer-quality
experiment. Source coverage from compare is copied in for pairing, not re-scored.

Controls `baseline5/8` apply the existing section selector to the common reranked
top-10. `fullpool5/8` apply it to all 20; `aspect5/8` use those same 20. These are
paired controls within a pool-20 experiment, not a fresh measurement of production
retrieval-top-10. This experiment isolates selection, not candidate pool depth.

Promotion requires further validation: source coverage does not prove that the
selected text contains the needed facts. Review mandatory answer facts and allowed
alternative evidence, add unseen intents as a holdout, then compare generated
answers and total cost. An improved source-coverage score alone must not change
the runtime default.
