"""HTTP surface: a REST endpoint and the MCP streamable-HTTP transport.

Both live in one deployment so a single URL and a single token serve both an
`/ask` caller and an MCP client pointed at `/mcp`.
"""

import threading
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPBearer
from fastapi.responses import JSONResponse
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.responses import Response

from src.config import settings
from src.observability import flush, get_langfuse, trace_url
from src.rag.pipeline import RetrievalStrategy
from src.rag.reranker import CallerKeyRateLimited, CallerKeyRejected, caller_cohere_key
from src.service import auth, core, pages
from src.service.mcp_server import PRODUCT_VENDOR, Product, build_mcp_server

COHERE_KEY_HEADER = "x-cohere-api-key"

PUBLIC_PATHS = frozenset({"/health", "/docs", "/openapi.json", "/redoc"})


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=settings.api_max_question_chars)
    strategy: RetrievalStrategy | None = None
    iterative: bool = False
    # Restricts retrieval to one product's docs, as search_docs does.
    product: Product | None = None


class SourceResponse(BaseModel):
    citation: int
    title: str
    heading: str
    url: str
    rerank_score: float


class AskResponse(BaseModel):
    answer: str
    sources: list[SourceResponse]
    strategy: str
    iterative: bool
    trace_url: str | None = None


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=settings.api_max_question_chars)
    limit: int | None = Field(default=None, ge=1, le=50)


class PassageResponse(BaseModel):
    rank: int
    title: str
    heading: str
    url: str
    score: float
    content: str
    description: str
    other_sections: list[str]


class SearchResponse(BaseModel):
    passages: list[PassageResponse]


class PagesRequest(BaseModel):
    query: str = Field(min_length=1, max_length=settings.api_max_question_chars)
    limit: int = Field(default=5, ge=1, le=10)
    product: Product | None = None


class PageCardResponse(BaseModel):
    rank: int
    title: str
    url: str
    product: str
    score: float
    description: str
    outline: list[str]


class PagesResponse(BaseModel):
    pages: list[PageCardResponse]


class SectionRequest(BaseModel):
    url: str = Field(min_length=1, max_length=500)
    heading: str | None = Field(default=None, max_length=300)
    offset: int = Field(default=0, ge=0)
    outline_depth: Literal[2, 3] = 2


class SectionResponse(BaseModel):
    url: str
    title: str
    description: str
    outline: list[str]
    heading: str | None
    text: str
    offset: int
    next_offset: int | None
    total_chars: int


def _allowed_hosts() -> list[str]:
    return [
        host.strip() for host in settings.api_allowed_hosts.split(",") if host.strip()
    ]


class _RateLimiter:
    """Fixed one-minute window over the whole server; enough for one machine."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._window_start = 0.0
        self._count = 0

    def allow(self, limit: int, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            if now - self._window_start >= 60:
                self._window_start = now
                self._count = 0
            if self._count >= limit:
                return False
            self._count += 1
            return True


class _PerKeyRateLimiter:
    """Fixed one-minute windows, one per key (a client IP)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._windows: dict[str, tuple[float, int]] = {}

    def allow(self, key: str, limit: int, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            if len(self._windows) > 10_000:
                # Drop expired windows so many one-off IPs cannot grow memory.
                self._windows = {
                    k: w for k, w in self._windows.items() if now - w[0] < 60
                }
            start, count = self._windows.get(key, (now, 0))
            if now - start >= 60:
                start, count = now, 0
            if count >= limit:
                self._windows[key] = (start, count)
                return False
            self._windows[key] = (start, count + 1)
            return True

    def retry_after(self, key: str, now: float | None = None) -> int:
        now = time.monotonic() if now is None else now
        with self._lock:
            start, _ = self._windows.get(key, (now, 0))
        return max(1, int(60 - (now - start) + 0.999))


_rate_limiter = _RateLimiter()
_byok_rate_limiter = _PerKeyRateLimiter()


def reset_rate_limiter() -> None:
    global _rate_limiter, _byok_rate_limiter
    _rate_limiter = _RateLimiter()
    _byok_rate_limiter = _PerKeyRateLimiter()


def client_ip(request: Request) -> str:
    """The caller's IP behind Render's proxy: the last X-Forwarded-For hop.

    Render's proxy appends the address it saw; earlier entries are supplied by
    the client and could be rotated to dodge the per-IP limit. If another proxy
    ever sits in front, the last hop becomes that proxy and the limit only gets
    stricter (shared bucket), never bypassable.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    last = forwarded.split(",")[-1].strip()
    if last:
        return last
    return request.client.host if request.client else "unknown"


def _transport_security() -> TransportSecuritySettings | None:
    """Declare the public hostname to the MCP transport.

    It answers 421 to unknown `Host` headers to block DNS rebinding, so a
    deployment behind a real domain must name that domain. Returning None keeps
    the library default, which allows localhost only. Behind a domain, only
    that domain is valid: localhost is not added on top.
    """
    hosts = _allowed_hosts()
    if not hosts:
        return None

    allowed_hosts: list[str] = []
    allowed_origins: list[str] = []
    for host in hosts:
        # Hosts usually send the bare domain; a proxy may append a port.
        allowed_hosts += [host, f"{host}:*"]
        allowed_origins += [f"https://{host}", f"https://{host}:*"]

    return TransportSecuritySettings(
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    )


def create_app() -> FastAPI:
    """Build a fresh app, including a fresh MCP session manager.

    The manager refuses to start twice, so it cannot be shared between app
    instances; anything that starts the app more than once needs its own.
    """
    # Stateless: no session state to lose across restarts or extra machines.
    mcp_app = build_mcp_server().streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        transport_security=_transport_security(),
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # Fail at startup, not on the first paying request: a missing token or
        # tracing enabled without Langfuse keys would otherwise leave /health
        # green while every tool call raises.
        auth.required_token()
        if settings.tracing_enabled:
            get_langfuse()
        # The MCP transport keeps its own task group; it must be started here.
        async with mcp_app.router.lifespan_context(mcp_app):
            yield
        flush()

    app = FastAPI(
        title="agent-docs-mcp",
        description=(
            "Hybrid RAG over the official Claude, Cursor, Codex and MCP "
            "documentation. The same pipeline is served as an MCP server at /mcp."
        ),
        lifespan=lifespan,
        # Declares the bearer scheme in the OpenAPI schema so Swagger UI shows
        # an Authorize button. The check itself stays in the middleware below;
        # auto_error=False keeps this dependency from ever rejecting anything.
        dependencies=[Depends(HTTPBearer(auto_error=False))],
    )

    @app.middleware("http")
    async def require_token(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path in PUBLIC_PATHS or request.method == "OPTIONS":
            return await call_next(request)
        cohere_key = request.headers.get(COHERE_KEY_HEADER, "").strip() or None
        has_token = auth.token_accepted(request.headers.get("authorization"))
        if not has_token and cohere_key is None:
            return JSONResponse(
                {"detail": "Missing or invalid bearer token"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not has_token:
            ip = client_ip(request)
            if not _byok_rate_limiter.allow(
                ip, settings.api_byok_rate_limit_per_minute
            ):
                return JSONResponse(
                    {"detail": "Rate limit exceeded for this IP; retry later"},
                    status_code=429,
                    headers={"Retry-After": str(_byok_rate_limiter.retry_after(ip))},
                )
        if not _rate_limiter.allow(settings.api_rate_limit_per_minute):
            return JSONResponse(
                {"detail": "Rate limit exceeded; retry in a minute"},
                status_code=429,
                headers={"Retry-After": "60"},
            )
        # Read by CohereReranker; the endpoint (and the MCP tool) run in a copy
        # of this context, so concurrent requests never see each other's key.
        context_token = caller_cohere_key.set(cohere_key)
        try:
            return await call_next(request)
        finally:
            caller_cohere_key.reset(context_token)

    @app.exception_handler(CallerKeyRejected)
    async def caller_key_rejected(_request: Request, error: Exception) -> Response:
        return JSONResponse({"detail": str(error)}, status_code=401)

    @app.exception_handler(CallerKeyRateLimited)
    async def caller_key_limited(_request: Request, error: Exception) -> Response:
        return JSONResponse(
            {"detail": str(error)}, status_code=429, headers={"Retry-After": "60"}
        )

    @app.get("/health")
    async def health() -> dict[str, Any]:
        """Liveness only: it must not call paid models or Qdrant.

        Async so it never waits on the thread pool the tools run in.
        """
        return {
            "status": "ok",
            "strategy": settings.retrieval_strategy,
            "generation_top_k": settings.generation_top_k,
            "retrieval_top_k": settings.retrieval_top_k,
        }

    @app.post("/ask", response_model=AskResponse)
    def ask(request: AskRequest) -> AskResponse:
        try:
            result = core.answer(
                request.question,
                strategy=request.strategy,
                iterative=request.iterative,
                vendor=PRODUCT_VENDOR[request.product] if request.product else None,
            )
        except core.QuestionRejected as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        finally:
            flush()

        return AskResponse(
            answer=result.answer,
            sources=[SourceResponse(**asdict(source)) for source in result.sources],
            strategy=result.strategy,
            iterative=result.iterative,
            trace_url=trace_url(),
        )

    @app.post("/search", response_model=SearchResponse)
    def search(request: SearchRequest) -> SearchResponse:
        """Retrieval without generation, so a caller can inspect the evidence."""
        try:
            passages = pages.search(request.query, limit=request.limit)
        except core.QuestionRejected as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        finally:
            flush()

        return SearchResponse(
            passages=[PassageResponse(**asdict(passage)) for passage in passages]
        )

    @app.post("/pages", response_model=PagesResponse)
    def find_pages(request: PagesRequest) -> PagesResponse:
        """Page cards (description + outline), ranked like /search."""
        try:
            cards = pages.find_pages(
                request.query,
                limit=request.limit,
                vendor=PRODUCT_VENDOR[request.product] if request.product else None,
            )
        except core.QuestionRejected as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        finally:
            flush()
        return PagesResponse(pages=[PageCardResponse(**asdict(card)) for card in cards])

    @app.post("/section", response_model=SectionResponse)
    def read_section(request: SectionRequest) -> SectionResponse:
        """One section of a stored page; no heading gives the outline."""
        try:
            result = pages.read_section(
                request.url, request.heading, request.offset, request.outline_depth
            )
        except pages.PageNotFound as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except core.QuestionRejected as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return SectionResponse(**asdict(result))

    app.mount("/mcp", mcp_app)
    return app


app = create_app()
