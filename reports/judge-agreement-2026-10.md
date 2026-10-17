# Judge agreement: gpt-6-sol vs claude-haiku-5-5 (2026-10-17)

Experiment 27. Can Claude Haiku 5.5 replace `gpt-6-sol` as the answer judge?
At published per-token prices it is about 20× cheaper, and it comes from another vendor than the generator
(`gpt-6-luna`), so it would not share the generator's habits.

## Setup

- **Answers:** every answer `gpt-6-sol` judged in the October runs of
  2026-10-12: three `answer-quality-baseline-k8` runs on
  `rag/evidence-coverage-v1` (48 answers) and two `negative-abstention-k8` runs
  on `rag/negative-v1` (24, of which 19 distinct). 67 distinct answers. The
  later runs that day ended in errors before judging and have no verdicts.
- **Why the stored verdicts are sol's:** Langfuse records 72 `gpt-6-sol`
  generations in October, exactly the 72 judged items, and
  [full-corpus-eval-2026-10.md](full-corpus-eval-2026-10.md) names sol as the
  judge of these runs.
- **Re-grading:** the same question, answer and contexts, the same rubric
  (`agent-docs/answer-evaluator`; its text is unchanged since 2026-09-16), one
  call per answer with `claude-haiku-5-5` through Anthropic's OpenAI-compatible
  API. The verdict comes back as a tool call, because that API rejects the
  JSON-schema response format for these scores.
- **Command:** `uv run python -m evals.experiments.judge_agreement --judge
  claude-haiku-5-5 --out <file outside git>`. Scores per answer:
  [judge-agreement-2026-10.json](judge-agreement-2026-10.json). The answers
  and documentation text stay out of git.

## Results

66 usable verdicts. One Haiku verdict was unusable: it left out the
summary and put markup in a field. Before the parser accepted a list sent as
a JSON string, a second verdict also failed.

| Score | sol mean | Haiku mean | Answers 0.25+ apart |
|---|---|---|---|
| Faithfulness | 0.988 | 0.810 | 10 |
| Answer relevance | 0.771 | 0.588 | 19 |
| Context utilisation | 0.561 | 0.549 | 12 |
| Citation correctness | 0.987 | 0.689 | 48 |

- **Abstention, the gate's negative metric:** both judge all 19 negative
  answers as refusals.
- **Failure mode:** same label on 52 of 66. All 14 differences are answers to
  answerable questions that cite sources; 13 of them also say some part is not
  covered. sol calls them `refusal`, Haiku `none`. The rubric allows either
  reading of a partial answer.

## Who is right where they disagree

Six disagreements were read against the retrieved documentation (by Claude
Opus 5.5 in the working session, not by a person):

| Case | Haiku's objection | Verdict |
|---|---|---|
| MCP discovery, list changes, authorization | A sentence cited `[2][5]` while "cacheable" is only in [2]; [5] supports the rest of the sentence | sol: a group citation is correct |
| Hook events for blocking, Cursor vs Codex | "No source says preToolUse can block" | sol: the answer says hooks can block (stated) and lists the "before" hooks (listed); it never says preToolUse alone blocks |
| Run a command on every Cursor agent event | `.cursor/hooks.json` "only appears for self-hosted workers" | sol, mostly: the context calls it the project hooks file, and the answer names the self-hosted case itself |
| Streaming from the Messages API (negative) | The answer gives Agent SDK code | sol: the answer says the docs cover the Agent SDK, not the Messages API, and labels the code; that is relevance, which both scored 0.3, not faithfulness |
| Cursor MCP, Python-only rules, subagents | "Ask Cursor to split a long task into subtasks" is not in the docs | Haiku: a small extrapolation. sol also docked faithfulness (0.92), Haiku more (0.6) |
| Same question, another run | Same pattern | sol: Haiku's own list calls each cited claim supported |

Patterns behind Haiku's lower scores:

- **Scores that do not follow its own findings.** Faithfulness is 0.8 for 35 of
  66 answers, whether it lists one minor issue or several. The rubric asks for
  the share of supported claims.
- **Issue lists that contradict the score.** Of the 22 answers it gives a
  citation score of 0.6 or less, 16 have issue lists that call the cited
  claims supported or correct.
- **Dimensions mixed.** Off-topic or wrong-product content lowers its
  faithfulness and citation scores, not only relevance.

sol has the opposite weakness: 54 of 66 answers get faithfulness 1.0, so the
score has little room to show an improvement. It still shows a drop, which is
what the gate checks.

## Decision

`gpt-6-sol` stays the judge and is now the default in code (`JUDGE_MODEL`), so
an eval run no longer falls back to the generator. Haiku 5.5 is not used as a
judge: its scores would move the gate's baselines without being more correct.

## Limits

- Six adjudicated cases, judged by one model, not by a person.
- One Haiku pass, through the OpenAI-compatible API with tool-call output.
  Anthropic's own API with native structured output was not tried and might
  behave differently.
- 67 answers from one day's runs, mostly multi-part and negative questions.
