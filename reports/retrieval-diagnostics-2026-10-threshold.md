# Rerank score distribution and floor (generated, stored scores only)

Every reranked candidate of the gate runs, labelled with the dataset
targets. Negative = rag/negative-v1 (all incorrect by definition).

| score | correct | incorrect (answerable sets) | negative-v1 |
|---|---|---|---|
| 0.00–0.10 | 0 | 0 | 16 |
| 0.10–0.20 | 0 | 0 | 23 |
| 0.20–0.30 | 0 | 2 | 32 |
| 0.30–0.35 | 2 | 2 | 10 |
| 0.35–0.40 | 4 | 9 | 6 |
| 0.40–0.50 | 13 | 30 | 9 |
| 0.50–0.60 | 25 | 51 | 5 |
| 0.60–0.70 | 24 | 54 | 8 |
| 0.70–0.80 | 79 | 124 | 4 |
| 0.80–0.90 | 208 | 227 | 7 |
| 0.90–1.00 | 152 | 104 | 0 |

Effect of a rule on the stored scores. *answerable groups kept* = evidence
groups / questions whose best correct chunk survives the rule (of those
whose correct chunk was reranked at all). *negatives emptied* = negative
questions left with no chunk, so the bot abstains without asking the LLM.

| rule | answerable groups kept | coverage questions complete-eligible | negatives emptied | mean chunks kept (negative) |
|---|---|---|---|---|
| floor 0.00 | 118/118 | 10/16 | 0/12 | 8.0 |
| floor 0.25 | 118/118 | 10/16 | 4/12 | 4.2 |
| floor 0.30 | 118/118 | 10/16 | 5/12 | 3.7 |
| floor 0.35 | 118/118 | 10/16 | 5/12 | 2.9 |
| floor 0.40 | 118/118 | 10/16 | 6/12 | 2.4 |
| floor 0.45 | 117/118 | 9/16 | 6/12 | 2.2 |
| floor 0.50 | 117/118 | 9/16 | 8/12 | 2.0 |
| floor 0.60 | 113/118 | 9/16 | 9/12 | 1.6 |
| floor 0.35 and ≥ 0.5·best | 118/118 | 10/16 | 5/12 | 2.9 |
| floor 0.35 and ≥ 0.6·best | 117/118 | 9/16 | 5/12 | 2.8 |
| floor 0.35 and ≥ 0.7·best | 116/118 | 9/16 | 5/12 | 2.2 |

| negative question | top score | scores ≥ 0.35 | stored answer |
|---|---|---|---|
| How do I deploy an MCP server on Kubernetes with a Helm chart? | 0.38 | 1 | The provided documentation doesn’t explain how to deploy an  |
| How do I set environment-specific feature flags in LaunchDarkly? | 0.48 | 2 | The provided documentation does not cover LaunchDarkly; it i |
| How do I add an MCP server to JetBrains AI Assistant? | 0.83 | 9 | The provided documentation doesn’t explain how to add an MCP |
| How do I enable Sentry performance tracing in a Django applicati | 0.26 | 0 | I couldn't find relevant documentation for this question. |
| How do I build a hybrid retriever with LangChain and Qdrant? | 0.24 | 0 | I couldn't find relevant documentation for this question. |
| How do I fine-tune an OpenAI model on my own dataset? | 0.58 | 6 | The provided documentation does not explain how to fine-tune |
| How do I write a decorator in Python that caches function result | 0.25 | 0 | I couldn't find relevant documentation for this question. |
| When should I use a GIN index instead of a B-tree index in Postg | 0.12 | 0 | I couldn't find relevant documentation for this question. |
| How do I stream a response from the Claude Messages API in Pytho | 0.90 | 10 | The provided documentation covers the **Claude Agent SDK**,  |
| How do I configure Renovate to group dependency updates into one | 0.22 | 0 | I couldn't find relevant documentation for this question. |
| Where do Windsurf Cascade rules live and how are they scoped? | 0.47 | 2 | The provided documentation is for **Cursor**, not Windsurf,  |
| How do I write custom instructions for GitHub Copilot in VS Code | 0.79 | 9 | The provided documentation does not explain how to write cus |
