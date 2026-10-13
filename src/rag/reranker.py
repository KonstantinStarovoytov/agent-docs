import logging
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass

import cohere
from cohere.core.api_error import ApiError
from cohere.errors.too_many_requests_error import TooManyRequestsError
from langchain_core.documents import Document

from src.config import settings
from src.observability import traced
from src.rag.retriever import SearchResult


@dataclass(frozen=True, slots=True)
class RerankResult:
    document: Document

    retrieval_score: float
    rerank_score: float

    original_rank: int
    rerank_rank: int


def _rerank_trace_input(
    _self: object,
    query: str,
    results: list[SearchResult],
    top_n: int = 5,
) -> dict[str, object]:
    return {
        "query": query,
        "top_n": top_n,
        "candidates": [
            {
                "source": result.document.metadata.get("source"),
                "content": result.document.page_content,
                "title": result.document.metadata.get("title"),
                "retrieval_score": result.score,
                "original_rank": rank,
            }
            for rank, result in enumerate(results, start=1)
        ],
    }


def _rerank_trace_output(results: list[RerankResult]) -> list[dict[str, object]]:
    return [
        {
            "source": result.document.metadata.get("source"),
            "content": result.document.page_content,
            "title": result.document.metadata.get("title"),
            "retrieval_score": result.retrieval_score,
            "rerank_score": result.rerank_score,
            "original_rank": result.original_rank,
            "rerank_rank": result.rerank_rank,
        }
        for result in results
    ]


logger = logging.getLogger(__name__)

# Cohere's default is 300 s; reranking 20 chunks takes about a second.
RERANK_TIMEOUT_SECONDS = 30.0

# Sticky for the process once the primary key is seen exhausted (its trial
# quota resets monthly, not per request), so later CohereReranker instances
# - pipeline.py creates a fresh one per request - go straight to the
# fallback instead of paying for a doomed primary call each time.
_primary_exhausted = False


# The caller's own Cohere key (header X-Cohere-Api-Key), set per request by
# the HTTP auth layer. A ContextVar so concurrent requests cannot see each
# other's key; it is never traced, logged or put into an error message.
caller_cohere_key: ContextVar[str | None] = ContextVar(
    "caller_cohere_key", default=None
)

# 498 is Cohere's "invalid token" status.
_REJECTED_STATUSES = frozenset({401, 403, 498})


class CallerKeyRejected(Exception):
    def __init__(self) -> None:
        super().__init__(
            "Your Cohere API key was rejected. Check the X-Cohere-Api-Key header."
        )


class CallerKeyRateLimited(Exception):
    def __init__(self) -> None:
        super().__init__(
            "Your Cohere key hit its rate limit or quota; wait or use another key."
        )


def reset_fallback_state() -> None:
    """Test-only: clear the sticky exhausted flag between cases."""
    global _primary_exhausted
    _primary_exhausted = False


class CohereReranker:
    _caller_key = False

    def __init__(self) -> None:
        self.model = settings.cohere_rerank_model
        self._fallback_client: cohere.ClientV2 | None = None
        caller_key = caller_cohere_key.get()
        self._caller_key = caller_key is not None
        if caller_key is not None:
            # The caller pays: no fallback to, and no state on, the server keys.
            self.client = cohere.ClientV2(
                api_key=caller_key, timeout=RERANK_TIMEOUT_SECONDS, max_retries=1
            )
            return
        self.client = cohere.ClientV2(
            api_key=settings.cohere_api_key.get_secret_value(),
            timeout=RERANK_TIMEOUT_SECONDS,
            max_retries=1,
        )
        fallback_key = settings.cohere_api_key_fallback
        if fallback_key:  # SecretStr('') is falsy: an empty CI secret must not count
            self._fallback_client = cohere.ClientV2(
                api_key=fallback_key.get_secret_value(),
                timeout=RERANK_TIMEOUT_SECONDS,
                max_retries=1,
            )

    @traced(
        "rerank-candidates",
        "retriever",
        input_factory=_rerank_trace_input,
        metadata_factory=lambda self, *args, **kwargs: {"model": self.model},
        output_factory=_rerank_trace_output,
    )
    def rerank(
        self,
        query: str,
        results: list[SearchResult],
        top_n: int = 5,
    ) -> list[RerankResult]:
        if not results:
            return []

        documents = [self._document_text(result.document) for result in results]

        response = self._rerank_with_fallback(query, documents, top_n)

        reranked: list[RerankResult] = []

        for rerank_position, item in enumerate(
            response.results,
            start=1,
        ):
            original_index = item.index
            original_result = results[original_index]

            reranked.append(
                RerankResult(
                    document=original_result.document,
                    retrieval_score=original_result.score,
                    rerank_score=item.relevance_score,
                    original_rank=original_index + 1,
                    rerank_rank=rerank_position,
                )
            )

        return reranked

    def _rerank_with_fallback(
        self, query: str, documents: list[str], top_n: int
    ) -> cohere.v2.types.v2rerank_response.V2RerankResponse:
        global _primary_exhausted

        def call(
            client: cohere.ClientV2,
        ) -> cohere.v2.types.v2rerank_response.V2RerankResponse:
            return client.rerank(
                model=self.model,
                query=query,
                documents=documents,
                top_n=min(top_n, len(documents)),
            )

        if self._caller_key:
            return self._call_with_caller_key(call)

        if _primary_exhausted and self._fallback_client is not None:
            return call(self._fallback_client)

        try:
            return call(self.client)
        except TooManyRequestsError:
            if self._fallback_client is None:
                raise
            logger.warning(
                "Cohere primary key exhausted; switching to fallback key "
                "for the rest of this process."
            )
            _primary_exhausted = True
            return call(self._fallback_client)

    def _call_with_caller_key(
        self,
        call: Callable[
            [cohere.ClientV2], cohere.v2.types.v2rerank_response.V2RerankResponse
        ],
    ) -> cohere.v2.types.v2rerank_response.V2RerankResponse:
        # `from None`: Cohere's error text is not ours to show and must not
        # carry the request into a traceback.
        try:
            return call(self.client)
        except TooManyRequestsError:
            raise CallerKeyRateLimited() from None
        except ApiError as error:
            if error.status_code in _REJECTED_STATUSES:
                raise CallerKeyRejected() from None
            raise

    @staticmethod
    def _document_text(document: Document) -> str:
        metadata = document.metadata

        heading = " > ".join(
            value
            for value in (
                metadata.get("h1"),
                metadata.get("h2"),
                metadata.get("h3"),
            )
            if value
        )

        return (
            f"Title: {metadata.get('title', '')}\n"
            f"Section: {heading}\n"
            f"Product: {metadata.get('product', '')}\n\n"
            f"{metadata.get('raw_content', document.page_content)}"
        )
