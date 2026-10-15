"""Do agents use `other_sections`? An A/B run with real models and the real tools.

Experiment 25 showed that naming a page's other matching sections makes the
labelled section visible more often (section hit 0.667 -> 0.867). This checks
what agents do with it. Each model answers the 15 retrieval-v3 questions whose
label names a section, twice:

    with     search_docs as served, other_sections included
    without  other_sections removed from every result and from the tool
             description (the search_docs of before)

The tools are the real MCP server, in process (same descriptions and output
as production); search reranks through EvalReranker (primary key, waits on
the per-minute limit, stops on a monthly 429, reuses EVAL_CACHE_DIR). No
system prompt. A judge model grades each answer against the labelled
section's text.

    TRACING_ENABLED=false EVAL_CACHE_DIR=DIR \\
      uv run python -m evals.experiments.agent_other_sections --out DIR \
        [--only "substring" ...] [--prefix "In Claude Code: "] [--repeats N]

`--only` keeps the questions that contain one of the substrings; `--prefix`
names the product in each question, so the model need not ask which one.
`--repeats` runs each (question, model, arm) N times, to tell the field's
effect from the model's run-to-run variation.
"""

import argparse
import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any

from mcp import Client
from openai import OpenAI

from evals.diagnose_retrieval import DATASETS, langfuse
from evals.eval_cache import EvalReranker, cohere_calls
from src.config import settings
from src.service import core, pages
from src.service.mcp_server import build_mcp_server

MODELS = {
    "gpt-6-luna": None,
    "claude-haiku-5-5": "https://api.anthropic.com/v1/",
}
ARMS = ("with", "without")
JUDGE_MODEL = "gpt-6-sol"
MAX_STEPS = 8
REFERENCE_CHARS = 6000
VENDOR_HOSTS = {"anthropic": "code.claude.com", "cursor": "cursor.com"}
_HINT = re.compile(
    r"Call read_section\(url\), or read_section\(url, heading\) for one of the\s+"
    r"passage's other_sections\."
)


# ------------------------------------------------------------------- cases


def cases() -> list[dict[str, Any]]:
    out = []
    for item in langfuse().get_dataset(DATASETS["retrieval-v3"]).items:
        targets = [
            t for t in item.expected_output["relevant"] if t.get("heading_contains")
        ]
        if targets:
            out.append({"question": item.input["question"], "targets": targets})
    return out


def matches(target: dict[str, str], title: str, heading: str, url: str) -> bool:
    if target.get("title") and target["title"] != title:
        return False
    if target.get("source_contains") and target["source_contains"] not in url:
        return False
    return target["heading_contains"].casefold() in heading.casefold()


def reference(target: dict[str, str]) -> str:
    """The labelled section's text, read from the page snapshot (no model)."""
    manifest = json.loads(
        Path(f"data/manifests/{settings.qdrant_hybrid_collection}.json").read_text()
    )["documents"]
    host = VENDOR_HOSTS.get(target.get("vendor", ""), "")
    for url, entry in manifest.items():
        if entry.get("title") != target.get("title") or host not in url:
            continue
        if target.get("source_contains") and target["source_contains"] not in url:
            continue
        try:
            return pages.read_section(url, target["heading_contains"]).text
        except core.QuestionRejected:
            continue
    return ""


# ------------------------------------------------------------------- agent


def tools_for(listed: list[Any], arm: str) -> list[dict[str, Any]]:
    tools = []
    for tool in listed:
        description = tool.description or ""
        if arm == "without":
            description = _HINT.sub("Call read_section(url).", description)
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": description,
                    "parameters": tool.input_schema,
                },
            }
        )
    return tools


def client_for(model: str) -> OpenAI:
    base = MODELS[model]
    if base is None:
        return OpenAI(api_key=settings.openai_api_key.get_secret_value())
    return OpenAI(api_key=os.environ["ANTHROPIC_API_KEY"], base_url=base)


async def execute(
    mcp: Client, arm: str, name: str, args: dict[str, Any], seen_other: set[str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Call one tool; return the call record and the data the model sees."""
    record: dict[str, Any] = {"tool": name, "args": args}
    try:
        result = await mcp.call_tool(name, args)
        data = result.structured_content or {}
        if result.is_error:
            data = {"error": str(result.content)}
    except Exception as error:  # a tool error goes back to the model
        data = {"error": str(error)}
    if name == "search_docs":
        for passage in data.get("passages", []):
            others = passage.get("other_sections", [])
            record.setdefault("passages", []).append(
                {k: passage.get(k) for k in ("title", "heading", "url")}
                | {"other_sections": others}
            )
            if arm == "without":
                passage.pop("other_sections", None)
            else:
                seen_other.update(others)
    elif name == "read_section":
        heading = data.get("heading") or ""
        record["result"] = {
            "title": data.get("title", ""),
            "heading": heading,
            "url": data.get("url", ""),
        }
        record["from_other_sections"] = bool(heading) and (
            heading in seen_other or args.get("heading") in seen_other
        )
    return record, data


async def run_agent(
    mcp: Client, model: str, arm: str, tools: list[dict], question: str
) -> dict[str, Any]:
    """OpenAI models through the Responses API (as OpenWebUI calls them),
    others through Chat Completions."""
    llm = client_for(model)
    calls: list[dict[str, Any]] = []
    seen_other: set[str] = set()
    answer = ""
    if MODELS[model] is None:
        flat = [{"type": "function", **t["function"]} for t in tools]
        items: list[Any] = [{"role": "user", "content": question}]
        for _ in range(MAX_STEPS):
            response = llm.responses.create(model=model, input=items, tools=flat)
            pending = [o for o in response.output if o.type == "function_call"]
            if not pending:
                answer = response.output_text or ""
                break
            items += [o.model_dump(exclude_none=True) for o in response.output]
            for call in pending:
                args = json.loads(call.arguments or "{}")
                record, data = await execute(mcp, arm, call.name, args, seen_other)
                calls.append(record)
                items.append(
                    {
                        "type": "function_call_output",
                        "call_id": call.call_id,
                        "output": json.dumps(data),
                    }
                )
    else:
        messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
        for _ in range(MAX_STEPS):
            chat = llm.chat.completions.create(
                model=model, messages=messages, tools=tools
            )
            message = chat.choices[0].message
            if not message.tool_calls:
                answer = message.content or ""
                break
            messages.append(
                {
                    "role": "assistant",
                    "content": message.content or "",
                    "tool_calls": [c.model_dump() for c in message.tool_calls],
                }
            )
            for call in message.tool_calls:
                args = json.loads(call.function.arguments or "{}")
                record, data = await execute(
                    mcp, arm, call.function.name, args, seen_other
                )
                calls.append(record)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(data),
                    }
                )
    return {
        "model": model,
        "arm": arm,
        "question": question,
        "calls": calls,
        "answer": answer,
    }


# ------------------------------------------------------------------- judge


def judge(question: str, ref: str, answer: str) -> dict[str, Any]:
    llm = OpenAI(api_key=settings.openai_api_key.get_secret_value())
    prompt = (
        "Grade an answer to a question about developer documentation.\n\n"
        f"Question:\n{question}\n\nReference (the documentation section that answers it):\n"
        f"{ref[:REFERENCE_CHARS]}\n\nAnswer:\n{answer}\n\n"
        'Reply with JSON only: {"verdict": "correct" | "partial" | "incorrect", '
        '"reason": "<one sentence>"}. "correct": the answer gives what the reference '
        'says and nothing that contradicts it. "partial": right direction but missing '
        'or wrong in a detail that matters. "incorrect": wrong or no answer.'
    )
    response = llm.chat.completions.create(
        model=JUDGE_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content or "{}")


# ------------------------------------------------------------------ report


def score(run: dict[str, Any], targets: list[dict[str, str]]) -> dict[str, Any]:
    searches = [c for c in run["calls"] if c["tool"] == "search_docs"]
    reads = [c for c in run["calls"] if c["tool"] == "read_section"]
    visible = any(
        matches(t, p["title"], p["heading"], p["url"])
        for c in searches
        for p in c.get("passages", [])
        for t in targets
    )
    in_other = any(
        matches(t, p["title"], other, p["url"])
        for c in searches
        for p in c.get("passages", [])
        for other in p["other_sections"]
        for t in targets
    )
    read = any(
        matches(t, r["result"]["title"], r["result"]["heading"], r["result"]["url"])
        for r in reads
        if r.get("result")
        for t in targets
    )
    return {
        "searches": len(searches),
        "reads": len(reads),
        "reads_from_other": sum(1 for r in reads if r.get("from_other_sections")),
        "label_as_passage": visible,
        "label_in_other_sections": in_other,
        "label_read": read,
    }


def summary(runs: list[dict[str, Any]]) -> str:
    lines = [
        "| model | arm | runs | correct | partial | searches | reads"
        " | reads from other_sections | label read | label only in other_sections |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for model in MODELS:
        for arm in ARMS:
            rs = [r for r in runs if r["model"] == model and r["arm"] == arm]
            if not rs:
                continue
            n = len(rs)
            verdicts = [r["judge"].get("verdict") for r in rs]
            only_other = sum(
                1
                for r in rs
                if r["score"]["label_in_other_sections"]
                and not r["score"]["label_as_passage"]
            )
            lines.append(
                f"| {model} | {arm} | {n} | {verdicts.count('correct')} | "
                f"{verdicts.count('partial')} | "
                f"{sum(r['score']['searches'] for r in rs) / n:.1f} | "
                f"{sum(r['score']['reads'] for r in rs) / n:.1f} | "
                f"{sum(r['score']['reads_from_other'] for r in rs)} | "
                f"{sum(r['score']['label_read'] for r in rs)} | {only_other} |"
            )
    return "\n".join(lines) + "\n"


async def main_async(out: Path, only: list[str], prefix: str, repeats: int) -> None:
    core.CohereReranker = EvalReranker  # type: ignore[misc]
    out.mkdir(parents=True, exist_ok=True)
    path = out / "runs.json"
    runs: list[dict[str, Any]] = json.loads(path.read_text()) if path.exists() else []
    done = {(r["model"], r["arm"], r["question"], r.get("repeat", 0)) for r in runs}
    selected = cases()
    if only:
        selected = [c for c in selected if any(o in c["question"] for o in only)]
    references = {c["question"]: reference(c["targets"][0]) for c in selected}
    async with Client(build_mcp_server()) as mcp:
        listed = (await mcp.list_tools()).tools
        for case in selected:
            for repeat in range(repeats):
                for model in MODELS:
                    for arm in ARMS:
                        if (model, arm, case["question"], repeat) in done:
                            continue
                        run = await run_agent(
                            mcp,
                            model,
                            arm,
                            tools_for(listed, arm),
                            prefix + case["question"],
                        )
                        run["question"] = case["question"]
                        run["repeat"] = repeat
                        run["score"] = score(run, case["targets"])
                        run["judge"] = judge(
                            case["question"],
                            references[case["question"]],
                            run["answer"],
                        )
                        runs.append(run)
                        path.write_text(json.dumps(runs, indent=1))
                        print(
                            f"{model:18} {arm:7} {run['judge'].get('verdict', '?'):9} "
                            f"reads={run['score']['reads']} "
                            f"from_other={run['score']['reads_from_other']} "
                            f"cohere={cohere_calls()}  {case['question'][:50]}",
                            flush=True,
                        )
    (out / "summary.md").write_text(summary(runs))
    print(summary(runs))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--only", nargs="*", default=[])
    parser.add_argument("--prefix", default="")
    parser.add_argument("--repeats", type=int, default=1)
    args = parser.parse_args()
    asyncio.run(main_async(args.out, args.only, args.prefix, args.repeats))


if __name__ == "__main__":
    main()
