from typing import Any

import pytest
from fastapi.testclient import TestClient

from pydantic import SecretStr

from src.config import settings
from src.service import app as app_module
from src.service import auth, core

TOKEN = "test-token"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(auth, "required_token", lambda: TOKEN)
    monkeypatch.setattr(app_module, "trace_url", lambda: None)
    monkeypatch.setattr(app_module, "flush", lambda: None)
    with TestClient(app_module.create_app()) as test_client:
        yield test_client


def _answer(*_args: Any, **_kwargs: Any) -> core.Answer:
    return core.Answer(
        answer="Skills load on demand [1].",
        sources=[
            core.Source(
                citation=1,
                title="Skills",
                heading="Overview",
                url="https://docs.test/skills.md",
                rerank_score=0.91,
            )
        ],
        strategy="hybrid",
        iterative=False,
    )


def test_health_needs_no_token(client: Any) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ask_without_token_is_rejected(client: Any) -> None:
    response = client.post("/ask", json={"question": "How do skills work?"})

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_ask_with_wrong_token_is_rejected(client: Any) -> None:
    response = client.post(
        "/ask",
        json={"question": "How do skills work?"},
        headers={"Authorization": "Bearer nope"},
    )

    assert response.status_code == 401


def test_guest_token_is_accepted_when_configured(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(core, "answer", _answer)
    monkeypatch.setattr(settings, "api_guest_token", SecretStr("guest-token"))

    response = client.post(
        "/ask",
        json={"question": "How do skills work?"},
        headers={"Authorization": "Bearer guest-token"},
    )

    assert response.status_code == 200


def test_guest_token_is_rejected_when_unset(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_guest_token", None)

    response = client.post(
        "/ask",
        json={"question": "How do skills work?"},
        headers={"Authorization": "Bearer guest-token"},
    )

    assert response.status_code == 401


def test_openapi_declares_bearer_auth(client: Any) -> None:
    """Swagger UI needs the scheme in the schema to show an Authorize button."""
    schema = client.get("/openapi.json").json()

    assert schema["components"]["securitySchemes"]["HTTPBearer"] == {
        "type": "http",
        "scheme": "bearer",
    }
    assert schema["paths"]["/ask"]["post"]["security"] == [{"HTTPBearer": []}]


def test_ask_returns_answer_and_sources(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(core, "answer", _answer)

    response = client.post(
        "/ask",
        json={"question": "How do skills work?"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == "Skills load on demand [1]."
    assert payload["sources"][0]["url"] == "https://docs.test/skills.md"
    assert payload["strategy"] == "hybrid"


def test_overlong_question_is_rejected_before_retrieval(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    called = False

    def fail(*_args: Any, **_kwargs: Any) -> core.Answer:
        nonlocal called
        called = True
        raise AssertionError("pipeline must not run")

    monkeypatch.setattr(core, "answer_question", fail)
    monkeypatch.setattr(app_module.settings, "api_max_question_chars", 10)

    response = client.post(
        "/ask",
        json={"question": "x" * 11},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 422
    assert called is False


def test_mcp_endpoint_requires_token(client: Any) -> None:
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers={"Accept": "application/json, text/event-stream"},
    )

    assert response.status_code == 401


def test_startup_fails_when_tracing_is_on_without_langfuse_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Otherwise /health says ok while every paid request raises."""
    monkeypatch.setattr(auth, "required_token", lambda: TOKEN)
    monkeypatch.setattr(app_module.settings, "tracing_enabled", True)
    monkeypatch.setattr(app_module.settings, "langfuse_public_key", None)
    monkeypatch.setattr(app_module.settings, "langfuse_secret_key", None)

    started = False
    with pytest.raises(ValueError, match="LANGFUSE_PUBLIC_KEY"):
        with TestClient(app_module.create_app()):
            started = True

    assert started is False, "must fail on startup, not on shutdown flush"


def test_requests_over_the_rate_limit_get_429(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(core, "search", lambda *_a, **_k: [])
    monkeypatch.setattr(app_module.settings, "api_rate_limit_per_minute", 2)
    app_module.reset_rate_limiter()

    codes = [
        client.post(
            "/search",
            json={"query": "hooks"},
            headers={"Authorization": f"Bearer {TOKEN}"},
        ).status_code
        for _ in range(3)
    ]

    assert codes == [200, 200, 429]


def test_health_is_not_rate_limited(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_module.settings, "api_rate_limit_per_minute", 1)
    app_module.reset_rate_limiter()

    codes = [client.get("/health").status_code for _ in range(3)]

    assert codes == [200, 200, 200]


def test_public_host_does_not_keep_localhost(monkeypatch: pytest.MonkeyPatch) -> None:
    """Behind a real domain only that domain is a valid Host or Origin."""
    monkeypatch.setattr(app_module.settings, "api_allowed_hosts", "docs.example.test")

    security = app_module._transport_security()

    assert security is not None
    assert not any("localhost" in host for host in security.allowed_hosts)
    assert not any("localhost" in origin for origin in security.allowed_origins)
    assert "docs.example.test" in security.allowed_hosts


def test_ask_passes_product_as_vendor(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    def answer(*args: Any, **kwargs: Any) -> core.Answer:
        seen.update(kwargs)
        return _answer()

    monkeypatch.setattr(core, "answer", answer)

    response = client.post(
        "/ask",
        json={"question": "How do skills work?", "product": "mcp"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 200
    assert seen["vendor"] == "model-context-protocol"


def test_ask_rejects_unknown_product(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(core, "answer", _answer)

    response = client.post(
        "/ask",
        json={"question": "q", "product": "copilot"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 422
