from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.prompts import managed


def test_runtime_fetches_production_chat_prompt_and_compiles_variables(monkeypatch):
    remote = Mock(version=7)
    remote.compile.return_value = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "Question: MCP"},
    ]
    client = Mock()
    client.get_prompt.return_value = remote
    monkeypatch.setattr(managed, "get_langfuse", lambda: client)

    prompt = managed.get_chat_prompt("answer", query="MCP", context="docs")

    client.get_prompt.assert_called_once_with(
        "agent-docs/answer",
        type="chat",
        label="production",
        cache_ttl_seconds=300,
    )
    remote.compile.assert_called_once_with(query="MCP", context="docs")
    assert prompt.version == 7
    assert prompt.source == "langfuse"
    assert prompt.langfuse_prompt is remote


def test_eval_fetches_exact_prompt_version_without_floating_label(monkeypatch):
    remote = Mock(version=4)
    remote.compile.return_value = [{"role": "user", "content": "MCP"}]
    client = Mock()
    client.get_prompt.return_value = remote
    monkeypatch.setattr(managed, "get_langfuse", lambda: client)

    prompt = managed.get_chat_prompt("translate", version=4, query="MCP")

    client.get_prompt.assert_called_once_with(
        "agent-docs/translate",
        type="chat",
        version=4,
        cache_ttl_seconds=300,
    )
    assert prompt.version == 4


def test_remote_failure_uses_local_fallback_with_hash(monkeypatch):
    monkeypatch.setattr(
        managed,
        "get_langfuse",
        Mock(side_effect=RuntimeError("offline")),
    )

    prompt = managed.get_chat_prompt("translate", query="как работает MCP")

    assert prompt.source == "local"
    assert prompt.version is None
    assert len(prompt.content_hash) == 64
    assert prompt.messages[0]["role"] == "system"
    assert prompt.messages[1] == {
        "role": "user",
        "content": "как работает MCP",
    }


def test_strict_prompt_fetch_does_not_mix_local_fallback_into_eval(monkeypatch):
    monkeypatch.setattr(
        managed,
        "get_langfuse",
        Mock(side_effect=RuntimeError("offline")),
    )

    with pytest.raises(RuntimeError, match="offline"):
        managed.get_chat_prompt(
            "answer",
            version=2,
            strict=True,
            query="MCP",
            context="docs",
        )


def test_unknown_prompt_is_rejected():
    with pytest.raises(ValueError, match="Unknown managed prompt"):
        managed.get_chat_prompt("missing")


def test_prompt_trace_metadata_is_stable():
    prompt = managed.ManagedPrompt(
        name="agent-docs/answer",
        messages=[],
        version=3,
        source="langfuse",
        content_hash="abc",
        langfuse_prompt=SimpleNamespace(),
    )

    assert prompt.metadata == {
        "prompt_name": "agent-docs/answer",
        "prompt_version": 3,
        "prompt_source": "langfuse",
        "prompt_hash": "abc",
    }


def test_publish_creates_all_production_chat_prompts():
    client = Mock()
    client.create_prompt.side_effect = [
        SimpleNamespace(version=1),
        SimpleNamespace(version=2),
        SimpleNamespace(version=3),
        SimpleNamespace(version=4),
    ]

    versions = managed.publish_managed_prompts(client)

    assert versions == {
        "agent-docs/answer": 1,
        "agent-docs/answer-evaluator": 2,
        "agent-docs/translate": 3,
        "agent-docs/evidence-planner": 4,
    }
    assert client.create_prompt.call_count == 4
    for call in client.create_prompt.call_args_list:
        assert call.kwargs["type"] == "chat"
        assert call.kwargs["labels"] == ["production"]


def test_publish_one_prompt_does_not_republish_unchanged_prompts():
    client = Mock()
    client.create_prompt.return_value = SimpleNamespace(version=8)

    name, version = managed.publish_managed_prompt("answer-evaluator", client)

    assert (name, version) == ("agent-docs/answer-evaluator", 8)
    client.create_prompt.assert_called_once()
    assert (
        client.create_prompt.call_args.kwargs["name"] == "agent-docs/answer-evaluator"
    )
