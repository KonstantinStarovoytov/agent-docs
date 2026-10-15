"""Versioned Langfuse chat prompts with deterministic local fallbacks."""

import json
import logging
import re
from dataclasses import dataclass
from hashlib import sha256
from collections.abc import Callable
from typing import Any

from src.observability import get_langfuse
from src.prompts import load_prompt

PROMPT_CACHE_TTL_SECONDS = 300


def _answer_messages() -> list[dict[str, str]]:
    return [
        {"role": "system", "content": load_prompt("answer")},
        {
            "role": "user",
            "content": (
                "Question:\n\n{{query}}\n\n"
                "Documentation context:\n\n{{context}}\n\n"
                "Answer the question using the documentation above."
            ),
        },
    ]


def _answer_evaluator_messages() -> list[dict[str, str]]:
    return [
        {"role": "system", "content": load_prompt("answer-evaluator")},
        {
            "role": "user",
            "content": (
                "Question:\n\n{{question}}\n\n"
                "Generated answer:\n\n{{answer}}\n\n"
                "Retrieved context, in citation order:\n\n{{contexts}}"
            ),
        },
    ]


def _translate_messages() -> list[dict[str, str]]:
    return [
        {"role": "system", "content": load_prompt("translate")},
        {"role": "user", "content": "{{query}}"},
    ]


def _evidence_planner_messages() -> list[dict[str, str]]:
    return [
        {"role": "system", "content": load_prompt("evidence-planner")},
        {"role": "user", "content": "{{payload}}"},
    ]


PROMPT_SPECS: dict[str, tuple[str, Callable[[], list[dict[str, str]]]]] = {
    "answer": ("agent-docs/answer", _answer_messages),
    "answer-evaluator": ("agent-docs/answer-evaluator", _answer_evaluator_messages),
    "translate": ("agent-docs/translate", _translate_messages),
    "evidence-planner": (
        "agent-docs/evidence-planner",
        _evidence_planner_messages,
    ),
}


@dataclass(frozen=True, slots=True)
class ManagedPrompt:
    name: str
    messages: list[dict[str, str]]
    version: int | None
    source: str
    content_hash: str
    langfuse_prompt: Any | None

    @property
    def metadata(self) -> dict[str, str | int | None]:
        return {
            "prompt_name": self.name,
            "prompt_version": self.version,
            "prompt_source": self.source,
            "prompt_hash": self.content_hash,
        }


def _compile_local(
    messages: list[dict[str, str]], variables: dict[str, Any]
) -> list[dict[str, str]]:
    compiled = []
    for message in messages:
        content = message["content"]
        content = re.sub(
            r"\{\{(\w+)\}\}",
            lambda m: str(variables[m[1]]) if m[1] in variables else m[0],
            content,
        )
        compiled.append({"role": message["role"], "content": content})
    return compiled


def _content_hash(messages: list[dict[str, str]]) -> str:
    encoded = json.dumps(
        messages, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return sha256(encoded).hexdigest()


def get_chat_prompt(
    name: str,
    *,
    version: int | None = None,
    strict: bool = False,
    **variables: Any,
) -> ManagedPrompt:
    if name not in PROMPT_SPECS:
        raise ValueError(f"Unknown managed prompt: {name}")

    remote_name, fallback_factory = PROMPT_SPECS[name]
    fallback = fallback_factory()
    try:
        client = get_langfuse()
        fetch = {
            "type": "chat",
            "cache_ttl_seconds": PROMPT_CACHE_TTL_SECONDS,
        }
        if version is None:
            fetch["label"] = "production"
        else:
            fetch["version"] = version
        remote = client.get_prompt(remote_name, **fetch)
        messages = remote.compile(**variables)
        normalized = [
            {"role": message["role"], "content": message["content"]}
            for message in messages
        ]
        return ManagedPrompt(
            name=remote_name,
            messages=normalized,
            version=remote.version,
            source="langfuse",
            content_hash=_content_hash(normalized),
            langfuse_prompt=remote,
        )
    except Exception:
        if strict:
            raise
        logging.getLogger(__name__).warning("Using local fallback for %s", remote_name)
        compiled = _compile_local(fallback, variables)
        return ManagedPrompt(
            name=remote_name,
            messages=compiled,
            version=None,
            source="local",
            content_hash=_content_hash(fallback),
            langfuse_prompt=None,
        )


def publish_managed_prompt(name: str, client: Any | None = None) -> tuple[str, int]:
    """Publish exactly one local fallback as a Langfuse production prompt."""
    if name not in PROMPT_SPECS:
        raise ValueError(f"Unknown managed prompt: {name}")
    client = client or get_langfuse()
    remote_name, fallback_factory = PROMPT_SPECS[name]
    prompt = client.create_prompt(
        name=remote_name,
        type="chat",
        prompt=fallback_factory(),
        labels=["production"],
        commit_message="Publish agent-docs prompt from local source",
    )
    return remote_name, prompt.version


def publish_managed_prompts(client: Any | None = None) -> dict[str, int]:
    versions: dict[str, int] = {}
    for name in PROMPT_SPECS:
        remote_name, version = publish_managed_prompt(name, client)
        versions[remote_name] = version
    return versions
