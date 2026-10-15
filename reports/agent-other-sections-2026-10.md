# Do agents use `other_sections`? (2026-10-15)

Experiment 25 showed that naming each page's other matching sections makes the
labelled section visible more often. `search_docs` has returned them since
2026-10-14. This run checks what real models do with them.

## Method

- **Models:** gpt-6-luna (OpenAI Responses API, the way OpenWebUI calls it)
  and claude-haiku-5-5 (Anthropic's OpenAI-compatible endpoint). No system
  prompt; at most 8 steps per question.
- **Tools:** the real MCP server, in process, with the same descriptions and
  output as production.
- **Arms:**
  - *with*: `search_docs` as served;
  - *without*: `other_sections` removed from every result and from the tool
    description, as before 2026-10-14.
- **Search:** reranked through the eval reranker (primary Cohere key,
  per-minute limit respected, stored scores reused).
- **Judge:** gpt-6-sol grades each answer against the labelled section's
  text, read from the page snapshot. Grades are correct, partial or
  incorrect; the score counts 1, 0.5 and 0.
- **Runner:** `evals/experiments/agent_other_sections.py`.
- **Cohere calls:** 136 in total.

### Two runs

1. **Run 1:** the 15 retrieval-v3 questions whose label names a section, as
   written, one repeat (60 runs).
2. **Run 2:** the 12 of them about Claude Code, prefixed "In Claude Code: ",
   two repeats (96 runs).

## Results

### Run 1: questions as written

| Model | Arm | Correct | Partial | Incorrect | Reads | Reads from `other_sections` | Labelled section read |
|---|---|---|---|---|---|---|---|
| gpt-6-luna | with | 9 | 2 | 4 | 20 | 7 | 5 |
| gpt-6-luna | without | 13 | 1 | 1 | 17 | 0 | 4 |
| claude-haiku-5-5 | with | 11 | 2 | 2 | 8 | 2 | 4 |
| claude-haiku-5-5 | without | 11 | 2 | 2 | 4 | 0 | 2 |

**Every "incorrect" answer here is a clarifying question** ("Which product
do you mean: Claude Code, Cursor or Codex?"), not a wrong answer. Most of
these questions name no product, and the tool description tells the model to
ask in that case. In 7 of the 9 the model did not call a tool at all, so it
never saw `other_sections`. Luna asked 4 times with the field and once
without; Haiku asked twice in each arm. This run does not separate the field
from the model's choice to ask.

### Run 2: product named, two repeats

| Model | Arm | Correct | Partial | Incorrect | Score | Reads | Reads from `other_sections` | Failed reads* | Labelled section read |
|---|---|---|---|---|---|---|---|---|---|
| gpt-6-luna | with | 21 | 3 | 0 | 0.94 | 36 | 10 | **1** | 10 |
| gpt-6-luna | without | 21 | 3 | 0 | 0.94 | 45 | 0 | **7** | 10 |
| claude-haiku-5-5 | with | 20 | 4 | 0 | 0.92 | 34 | 7 | **0** | 8 |
| claude-haiku-5-5 | without | 21 | 3 | 0 | 0.94 | 36 | 0 | **4** | 10 |

\* `read_section` calls that returned an error, mostly a guessed heading the
page does not have ("What are skills?", "When to use subagents",
"Overview").

- **The arms score the same on 11 of the 12 questions.** The one difference
  is Haiku on "How do I restrict which tools a custom subagent can use?"
  (3.5 against 4 of 4). Both arms read the same section; in one repeat the
  "with" answer added a wrong detail about inherited tools.
- **Agents use the field:** 28% of luna's reads (10 of 36) and 21% of
  Haiku's (7 of 34) open a heading from `other_sections`.
- **Fewer guessed headings.** Failed reads fall from 7 to 1 for luna and
  from 4 to 0 for Haiku. Luna makes 36 reads instead of 45 for the same
  score.

## Conclusion

- `other_sections` **does not change answer correctness** in either
  direction on 96 runs.
- Agents **open those headings** in about a quarter of their reads.
- Agents **guess non-existent headings less often**, so they make fewer
  failed `read_section` calls.
- The field stays.

## Limits

- Small sample: 12 to 15 questions, two models, one or two repeats.
- One judge model.
- Labelled section read counts only the labelled heading. An answer drawn
  from a neighbouring section that says the same thing is graded correct but
  not counted as a labelled read.
