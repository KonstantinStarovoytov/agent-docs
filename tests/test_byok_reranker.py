"""Bring-your-own Cohere key: the caller's key reranks, and it never leaks."""

import logging
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
from cohere.errors.too_many_requests_error import TooManyRequestsError
from cohere.errors.unauthorized_error import UnauthorizedError
from langchain_core.documents import Document
from pydantic import SecretStr

from src import observability
from src.rag import reranker as reranker_module
from src.rag.reranker import (
    CallerKeyRateLimited,
    CallerKeyRejected,
    CohereReranker,
    caller_cohere_key,
)
from src.rag.retriever import SearchResult

CALLER_KEY = "caller-secret-KEY-1234567890"


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        cohere_api_key=SecretStr("server-primary"),
        cohere_api_key_fallback=SecretStr("server-fallback"),
        cohere_rerank_model="rerank-v4.0-fast",
    )


def _candidates() -> list[SearchResult]:
    return [SearchResult(document=Document(page_content="c0", metadata={}), score=1.0)]


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(reranker_module, "settings", _settings())
    reranker_module.reset_fallback_state()
    token = caller_cohere_key.set(CALLER_KEY)
    yield
    caller_cohere_key.reset(token)
    reranker_module.reset_fallback_state()


def _clients(monkeypatch: pytest.MonkeyPatch, caller: Mock) -> list[str]:
    seen: list[str] = []
    server = Mock()

    def fake_client_v2(*, api_key: str, **_kwargs: object) -> Mock:
        seen.append(api_key)
        return caller if api_key == CALLER_KEY else server

    monkeypatch.setattr(reranker_module.cohere, "ClientV2", fake_client_v2)
    return seen


def test_caller_key_is_the_only_client(monkeypatch: pytest.MonkeyPatch) -> None:
    caller = Mock()
    caller.rerank.return_value = SimpleNamespace(
        results=[SimpleNamespace(index=0, relevance_score=0.9)]
    )
    seen = _clients(monkeypatch, caller)

    CohereReranker().rerank("q", _candidates())

    assert seen == [CALLER_KEY]


def test_caller_quota_does_not_fall_back_or_mark_server_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caller = Mock()
    caller.rerank.side_effect = TooManyRequestsError(headers={}, body={})
    seen = _clients(monkeypatch, caller)

    with pytest.raises(CallerKeyRateLimited) as raised:
        CohereReranker().rerank("q", _candidates())

    assert seen == [CALLER_KEY]
    assert reranker_module._primary_exhausted is False
    assert "rate limit or quota" in str(raised.value)
    assert CALLER_KEY not in str(raised.value)


def test_rejected_caller_key_is_reported_without_the_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caller = Mock()
    caller.rerank.side_effect = UnauthorizedError(
        headers={}, body={"message": f"invalid api token {CALLER_KEY}"}
    )
    _clients(monkeypatch, caller)

    with pytest.raises(CallerKeyRejected) as raised:
        CohereReranker().rerank("q", _candidates())

    assert str(raised.value) == (
        "Your Cohere API key was rejected. Check the X-Cohere-Api-Key header."
    )
    assert CALLER_KEY not in repr(raised.value)
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True


def test_caller_key_never_reaches_traces_or_logs(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    recorded: list[Any] = []
    span = Mock()

    @contextmanager
    def observation(**kwargs: Any) -> Any:
        recorded.append(kwargs)
        yield span

    client = SimpleNamespace(
        start_as_current_observation=observation, get_current_trace_id=lambda: None
    )
    monkeypatch.setattr(
        observability, "settings", SimpleNamespace(tracing_enabled=True)
    )
    monkeypatch.setattr(observability, "get_langfuse", lambda: client)
    monkeypatch.setattr(observability, "_propagate_attributes", lambda **_: _null())
    caller = Mock()
    caller.rerank.side_effect = UnauthorizedError(headers={}, body={})
    _clients(monkeypatch, caller)

    with caplog.at_level(logging.DEBUG), pytest.raises(CallerKeyRejected):
        CohereReranker().rerank("q", _candidates())

    assert recorded, "the rerank span must still be traced"
    everything = repr(recorded) + repr(span.mock_calls) + caplog.text
    assert CALLER_KEY not in everything


@contextmanager
def _null() -> Any:
    yield
