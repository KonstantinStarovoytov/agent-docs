"""MCP checks through a real client session, not by calling the tool functions."""

import socket
import threading
import time
from collections.abc import Iterator
from typing import Any

import httpx2
import pytest
import uvicorn
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from pydantic import SecretStr

from src.config import settings
from src.service import app as app_module
from src.ingestion.snapshots import PageSnapshot
from src.service import core, pages
from src.service.mcp_server import build_mcp_server

TOKEN = "test-token"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def stub_pipeline(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    def search(
        query: str, *, limit: int | None = None, vendor: str | None = None
    ) -> list[core.Passage]:
        return [
            core.Passage(
                rank=1,
                title="Skills",
                heading="Overview",
                url="https://docs.test/skills.md",
                score=0.5,
                content=f"passage for {query} limit={limit} vendor={vendor}"
                + "x" * 400,
            )
        ]

    reads: list[list[str]] = []

    def snapshot_pages(urls: list[str]) -> dict[str, PageSnapshot]:
        reads.append(urls)
        return {
            "https://docs.test/skills.md": PageSnapshot(
                url="https://docs.test/skills.md",
                title="Skills",
                product="claude-code",
                markdown="# Skills\n\nSkills are folders.",
                summary="How skills package instructions.",
            )
        }

    monkeypatch.setattr(core, "search", search)
    monkeypatch.setattr(pages, "_snapshot_pages", snapshot_pages)
    return reads


@pytest.mark.anyio
async def test_client_sees_exactly_two_tools(stub_pipeline: Any) -> None:
    async with Client(build_mcp_server()) as client:
        tools = await client.list_tools()

    assert sorted(tool.name for tool in tools.tools) == ["read_section", "search_docs"]


@pytest.mark.anyio
async def test_tools_advertise_runlayer_metadata(stub_pipeline: Any) -> None:
    """Title, annotations, field docs and output schema must be on the wire."""
    async with Client(build_mcp_server()) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}

    search, read = tools["search_docs"], tools["read_section"]

    assert search.title == "Search official agent docs"
    for tool in (search, read):
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        assert tool.annotations.idempotent_hint is True
        # The index is a closed snapshot, not the open web.
        assert tool.annotations.open_world_hint is False
        assert tool.output_schema is not None
    search_text = " ".join((search.description or "").split())
    read_text = " ".join((read.description or "").split())
    # When to use comes first, then when not to; errors explain themselves in
    # the error responses, so the description no longer carries an Errors block.
    assert search_text.startswith("Search the official documentation")
    assert "Use it before answering" in search_text and "Not for" in search_text
    assert "One topic per call" in search_text and "read_section(url)" in search_text
    assert "Errors:" not in search_text
    assert "hasn't said which one, ask" in search_text
    assert "description" in search_text and "split multi-part questions" in search_text
    assert "relevance score" in search_text and "under ~0.5" in search_text
    assert "read_section(url)" in search_text
    assert "outline" in read_text and "next_offset" in read_text
    assert "subsection counts" in read_text and "outline_depth=3" in read_text
    depth = read.input_schema["properties"]["outline_depth"]
    assert depth["enum"] == [2, 3] and depth["default"] == 2
    for text in (search_text, read_text):
        assert "ask_docs" not in text and "find_pages" not in text

    query = search.input_schema["properties"]["query"]
    assert query["minLength"] == 1
    assert query["maxLength"] == 500
    assert "description" in query
    limit = search.input_schema["properties"]["limit"]
    assert limit["minimum"] == 1
    assert limit["maximum"] == 20
    assert "default 8" in limit["description"]
    fmt = search.input_schema["properties"]["response_format"]["description"]
    assert "tokens" in fmt and "Start concise" in fmt
    assert "e.g." in query["description"]
    product = search.input_schema["properties"]["product"]
    assert "leave it empty" in product["description"]
    assert "a wrong product hides the right ones" in product["description"]
    assert {"claude-code", "cursor", "codex", "mcp"} <= set(product["anyOf"][0]["enum"])
    assert "concise" in str(search.input_schema["properties"]["response_format"])
    assert "passages" in search.output_schema["properties"]  # type: ignore[index]
    assert "index_snapshot" in search.output_schema["properties"]  # type: ignore[index]
    assert "next_offset" in read.output_schema["properties"]  # type: ignore[index]


def test_server_instructions_describe_the_two_step_flow() -> None:
    flat = " ".join((build_mcp_server().instructions or "").split())

    assert "search_docs" in flat and "read_section" in flat
    assert "ask_docs" not in flat and "find_pages" not in flat


@pytest.mark.anyio
async def test_server_reports_a_version(stub_pipeline: Any) -> None:
    async with Client(build_mcp_server()) as client:
        info = client.server_info

    assert info is not None
    # Read from pyproject: the project is not installed as a package.
    assert info.version == "0.1.0"


@pytest.mark.anyio
async def test_search_docs_passes_limit_through(stub_pipeline: Any) -> None:
    async with Client(build_mcp_server()) as client:
        result = await client.call_tool("search_docs", {"query": "hooks", "limit": 3})

    payload = result.structured_content
    assert payload is not None
    assert payload["passages"][0]["content"].startswith("passage for hooks limit=3")


@pytest.mark.anyio
async def test_search_docs_is_concise_by_default(stub_pipeline: Any) -> None:
    """A 20-passage detailed answer is ~15k tokens; concise trims each chunk."""
    async with Client(build_mcp_server()) as client:
        concise = await client.call_tool("search_docs", {"query": "hooks"})
        detailed = await client.call_tool(
            "search_docs", {"query": "hooks", "response_format": "detailed"}
        )

    short = concise.structured_content["passages"][0]  # type: ignore[index]
    full = detailed.structured_content["passages"][0]  # type: ignore[index]
    assert len(short["content"]) <= 300 + len("…")
    assert short["truncated"] is True
    assert full["content"].endswith("x" * 400)
    assert full["truncated"] is False


@pytest.mark.anyio
async def test_search_docs_maps_product_to_vendor(stub_pipeline: Any) -> None:
    async with Client(build_mcp_server()) as client:
        result = await client.call_tool(
            "search_docs", {"query": "rules", "product": "codex"}
        )

    content = result.structured_content["passages"][0]["content"]  # type: ignore[index]
    assert "vendor=openai" in content


@pytest.mark.anyio
async def test_search_docs_passages_carry_the_page_description(
    stub_pipeline: list[list[str]],
) -> None:
    async with Client(build_mcp_server()) as client:
        result = await client.call_tool("search_docs", {"query": "skills"})

    passage = result.structured_content["passages"][0]  # type: ignore[index]
    assert passage["description"] == "How skills package instructions."
    assert stub_pipeline == [["https://docs.test/skills.md"]]


@pytest.mark.anyio
async def test_search_docs_passages_name_the_pages_other_sections(
    monkeypatch: pytest.MonkeyPatch, stub_pipeline: list[list[str]]
) -> None:
    monkeypatch.setattr(
        core,
        "search",
        lambda *_a, **_k: [
            core.Passage(
                1,
                "Skills",
                "Skills > Create",
                "https://docs.test/skills.md",
                0.9,
                "text",
                other_sections=("Skills > Share",),
            )
        ],
    )
    async with Client(build_mcp_server()) as client:
        result = await client.call_tool("search_docs", {"query": "skills"})

    passage = result.structured_content["passages"][0]  # type: ignore[index]
    assert passage["other_sections"] == ["Skills > Share"]


@pytest.mark.anyio
async def test_search_docs_reads_snapshots_once_for_all_passages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reads: list[list[str]] = []

    def search(
        query: str, *, limit: int | None = None, vendor: str | None = None
    ) -> list[core.Passage]:
        return [
            core.Passage(i, "T", "H", f"https://docs.test/{i}.md", 0.5, "c")
            for i in range(1, 4)
        ]

    def snapshot_pages(urls: list[str]) -> dict[str, PageSnapshot]:
        reads.append(urls)
        return {}

    monkeypatch.setattr(core, "search", search)
    monkeypatch.setattr(pages, "_snapshot_pages", snapshot_pages)
    async with Client(build_mcp_server()) as client:
        result = await client.call_tool("search_docs", {"query": "q"})

    assert len(reads) == 1 and len(reads[0]) == 3
    passages = result.structured_content["passages"]  # type: ignore[index]
    assert [p["description"] for p in passages] == ["", "", ""]


@pytest.mark.anyio
async def test_search_docs_survives_an_unavailable_snapshot_store(
    stub_pipeline: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(urls: list[str]) -> dict[str, PageSnapshot]:
        raise RuntimeError("qdrant down")

    monkeypatch.setattr(pages, "_snapshot_pages", broken)
    async with Client(build_mcp_server()) as client:
        result = await client.call_tool("search_docs", {"query": "skills"})

    assert result.is_error is False
    passage = result.structured_content["passages"][0]  # type: ignore[index]
    assert passage["description"] == "" and passage["url"].endswith("skills.md")


@pytest.mark.anyio
async def test_search_docs_backend_failure_tells_the_model_to_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(*_args: Any, **_kwargs: Any) -> list[core.Passage]:
        raise RuntimeError("openai down")

    monkeypatch.setattr(core, "search", explode)
    async with Client(build_mcp_server()) as client:
        result = await client.call_tool("search_docs", {"query": "q"})

    assert result.is_error is True
    text = result.content[0].text  # type: ignore[union-attr]
    assert "unavailable" in text and "retry" in text
    assert "openai down" not in text


@pytest.mark.anyio
async def test_results_carry_index_snapshot(
    stub_pipeline: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(core, "index_snapshot", lambda: "2026-09-01")
    async with Client(build_mcp_server()) as client:
        searched = await client.call_tool("search_docs", {"query": "q"})

    assert searched.structured_content["index_snapshot"] == "2026-09-01"  # type: ignore[index]


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture
def served_app(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Serve the real ASGI app, because the HTTP transport needs a real socket."""
    monkeypatch.setattr(settings, "api_token", SecretStr(TOKEN))
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(
            app_module.create_app(),
            host="127.0.0.1",
            port=port,
            log_level="warning",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    if not server.started:
        server.should_exit = True
        raise RuntimeError("test server did not start")
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


@pytest.mark.anyio
async def test_mounted_http_transport_serves_tools(
    stub_pipeline: Any, served_app: str
) -> None:
    """The deployed path: an MCP client over HTTP at /mcp, carrying the token."""
    async with httpx2.AsyncClient(
        headers={"Authorization": f"Bearer {TOKEN}"}
    ) as http_client:
        transport = streamable_http_client(
            f"{served_app}/mcp/", http_client=http_client
        )
        async with Client(transport) as client:
            tools = await client.list_tools()
            result = await client.call_tool("search_docs", {"query": "hooks"})

    assert sorted(tool.name for tool in tools.tools) == ["read_section", "search_docs"]
    payload = result.structured_content
    assert payload is not None
    assert payload["passages"][0]["url"] == "https://docs.test/skills.md"


async def _mcp_post(host: str, body: dict[str, Any]) -> int:
    """POST to the mounted transport with a chosen Host header."""
    app = app_module.create_app()
    transport = httpx2.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx2.AsyncClient(transport=transport) as http_client:
            response = await http_client.post(
                f"http://{host}/mcp/",
                json=body,
                headers={
                    "Authorization": f"Bearer {TOKEN}",
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                },
            )
    return response.status_code


INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "1"},
    },
}


@pytest.mark.anyio
async def test_declared_public_host_is_accepted(
    stub_pipeline: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A deployment behind a domain must not answer 421 to its own hostname.

    The MCP transport rejects unknown Host headers to block DNS rebinding, so
    the public hostname has to be declared in API_ALLOWED_HOSTS.
    """
    monkeypatch.setattr(settings, "api_token", SecretStr(TOKEN))
    monkeypatch.setattr(settings, "api_allowed_hosts", "docs.example.test")

    assert await _mcp_post("docs.example.test", INITIALIZE) == 200


@pytest.mark.anyio
async def test_undeclared_host_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "api_token", SecretStr(TOKEN))
    monkeypatch.setattr(settings, "api_allowed_hosts", "docs.example.test")

    assert await _mcp_post("attacker.test", INITIALIZE) == 421


@pytest.mark.anyio
async def test_mounted_http_transport_rejects_missing_token(served_app: str) -> None:
    async with httpx2.AsyncClient() as http_client:
        response = await http_client.post(
            f"{served_app}/mcp/",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"Accept": "application/json, text/event-stream"},
        )

    assert response.status_code == 401


@pytest.fixture
def stub_pages(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    def read_section(
        url: str, heading: str | None = None, offset: int = 0, outline_depth: int = 2
    ) -> pages.SectionRead:
        if url == "https://docs.test/missing.md":
            raise pages.PageNotFound(f"{url} is not a page of the index")
        seen.update(
            url=url, heading=heading, offset=offset, outline_depth=outline_depth
        )
        return pages.SectionRead(
            url=url,
            title="Hooks",
            description="Explains hooks.",
            outline=[],
            heading="Hooks > Configure hooks",
            text="## Configure hooks\nbody",
            offset=offset,
            next_offset=None,
            total_chars=24,
        )

    monkeypatch.setattr(pages, "read_section", read_section)
    return seen


@pytest.mark.anyio
async def test_read_section_returns_text_and_reports_unknown_pages(
    stub_pipeline: Any, stub_pages: dict[str, Any]
) -> None:
    async with Client(build_mcp_server()) as client:
        found = await client.call_tool(
            "read_section",
            {"url": "https://docs.test/hooks.md", "heading": "configure", "offset": 0},
        )
        missing = await client.call_tool(
            "read_section", {"url": "https://docs.test/missing.md"}
        )

    assert found.structured_content["text"].startswith("## Configure hooks")  # type: ignore[index]
    assert stub_pages["heading"] == "configure"
    assert stub_pages["outline_depth"] == 2
    assert missing.is_error is True
    assert "not a page of the index" in missing.content[0].text  # type: ignore[union-attr]


@pytest.mark.anyio
async def test_read_section_passes_outline_depth_and_rejects_others(
    stub_pipeline: Any, stub_pages: dict[str, Any]
) -> None:
    async with Client(build_mcp_server()) as client:
        deep = await client.call_tool(
            "read_section", {"url": "https://docs.test/hooks.md", "outline_depth": 3}
        )
        bad = await client.call_tool(
            "read_section", {"url": "https://docs.test/hooks.md", "outline_depth": 4}
        )

    assert deep.is_error is False and stub_pages["outline_depth"] == 3
    assert bad.is_error is True


@pytest.mark.anyio
async def test_mounted_transport_accepts_a_cohere_key_instead_of_a_token(
    served_app: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.rag.reranker import CallerKeyRejected, caller_cohere_key

    seen: list[str | None] = []

    def search(query: str, **_kwargs: Any) -> list[core.Passage]:
        seen.append(caller_cohere_key.get())
        raise CallerKeyRejected()

    monkeypatch.setattr(core, "search", search)
    key = "caller-secret-KEY-1234567890"
    async with httpx2.AsyncClient(headers={"X-Cohere-Api-Key": key}) as http_client:
        transport = streamable_http_client(
            f"{served_app}/mcp/", http_client=http_client
        )
        async with Client(transport) as client:
            result = await client.call_tool("search_docs", {"query": "hooks"})

    assert seen == [key]
    assert result.is_error
    text = result.content[0].text  # type: ignore[union-attr]
    assert "Your Cohere API key was rejected" in text
    assert key not in text
