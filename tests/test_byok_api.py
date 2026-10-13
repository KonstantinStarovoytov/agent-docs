"""REST access with the caller's own Cohere key instead of a bearer token."""

import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.rag.reranker import CallerKeyRateLimited, CallerKeyRejected, caller_cohere_key
from src.service import app as app_module
from src.service import auth, core

TOKEN = "test-token"
KEY = "caller-secret-KEY-1234567890"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(auth, "required_token", lambda: TOKEN)
    monkeypatch.setattr(app_module, "trace_url", lambda: None)
    monkeypatch.setattr(app_module, "flush", lambda: None)
    app_module.reset_rate_limiter()
    with TestClient(app_module.create_app()) as test_client:
        yield test_client
    app_module.reset_rate_limiter()


def _post(client: Any, headers: dict[str, str], ip: str = "203.0.113.7") -> Any:
    return client.post(
        "/search",
        json={"query": "hooks"},
        headers={"X-Forwarded-For": f"10.0.0.1, {ip}", **headers},
    )


def test_cohere_key_header_replaces_bearer_and_reaches_the_reranker(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str | None] = []

    def search(*_a: Any, **_k: Any) -> list[core.Passage]:
        seen.append(caller_cohere_key.get())
        return []

    monkeypatch.setattr(core, "search", search)

    assert _post(client, {"X-Cohere-Api-Key": KEY}).status_code == 200
    assert _post(client, {"Authorization": f"Bearer {TOKEN}"}).status_code == 200
    assert seen == [KEY, None]
    assert caller_cohere_key.get() is None


def test_empty_cohere_key_header_still_needs_a_token(client: Any) -> None:
    assert _post(client, {"X-Cohere-Api-Key": " "}).status_code == 401


def test_section_is_reachable_with_a_cohere_key(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.service import pages

    def missing(*_a: Any, **_k: Any) -> Any:
        raise pages.PageNotFound("nope")

    monkeypatch.setattr(pages, "read_section", missing)
    response = client.post(
        "/section", json={"url": "https://x.test"}, headers={"X-Cohere-Api-Key": KEY}
    )
    assert response.status_code == 404


def test_byok_requests_are_limited_per_client_ip(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(core, "search", lambda *_a, **_k: [])
    monkeypatch.setattr(app_module.settings, "api_byok_rate_limit_per_minute", 2)
    byok = {"X-Cohere-Api-Key": KEY}

    codes = [_post(client, byok).status_code for _ in range(3)]
    other_ip = _post(client, byok, ip="198.51.100.9").status_code
    bearer = _post(client, {"Authorization": f"Bearer {TOKEN}"}).status_code
    limited = _post(client, byok)

    assert codes == [200, 200, 429]
    assert other_ip == 200
    assert bearer == 200
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) >= 1


def test_per_ip_limiter_window_resets() -> None:
    limiter = app_module._PerKeyRateLimiter()
    assert limiter.allow("a", 1, now=0.0)
    assert not limiter.allow("a", 1, now=30.0)
    assert limiter.retry_after("a", now=30.0) == 30
    assert limiter.allow("a", 1, now=61.0)


@pytest.mark.parametrize(
    ("error", "status", "phrase"),
    [
        (CallerKeyRejected(), 401, "Your Cohere API key was rejected"),
        (CallerKeyRateLimited(), 429, "Your Cohere key hit its rate limit or quota"),
    ],
)
def test_caller_key_errors_are_actionable_and_keyless(
    client: Any,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    error: Exception,
    status: int,
    phrase: str,
) -> None:
    def search(*_a: Any, **_k: Any) -> Any:
        raise error

    monkeypatch.setattr(core, "search", search)
    with caplog.at_level(logging.DEBUG):
        response = _post(client, {"X-Cohere-Api-Key": KEY})

    assert response.status_code == status
    assert phrase in response.json()["detail"]
    assert KEY not in response.text
    assert KEY not in caplog.text


def test_a_spoofed_first_forwarded_hop_does_not_dodge_the_ip_limit(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Render appends the real client address; earlier entries are whatever
    the client sent, so rotating them must not reset the per-IP counter."""
    monkeypatch.setattr(app_module.settings, "api_byok_rate_limit_per_minute", 2)
    monkeypatch.setattr(app_module.pages, "search", lambda *a, **k: [])
    statuses = [
        client.post(
            "/search",
            json={"query": "hooks"},
            headers={
                "X-Cohere-Api-Key": "k",
                "X-Forwarded-For": f"198.51.100.{i}, 203.0.113.7",
            },
        ).status_code
        for i in range(3)
    ]
    assert statuses[-1] == 429
