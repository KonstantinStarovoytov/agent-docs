"""Rerank and query-rewrite helpers for eval runs on a small Cohere trial quota.

`EvalReranker` is a `CohereReranker` that
- never switches to the fallback key: a monthly-quota 429 stops the run
  (`QuotaExhausted`), a per-minute 429 waits 65 s and retries;
- with `EVAL_CACHE_DIR` set, keeps every (model, query, document) score on
  disk and sends Cohere only the documents it has not scored yet.

Cohere scores each query-document pair on its own: across the stored
2026-10-12 runs, 1,054 unambiguous chunks were scored in two or more calls
with different neighbours, 909 identically and none more than 0.008 apart
(reports/retrieval-diagnostics-2026-10.md). So a cached score stands in for a
repeat call. Without `EVAL_CACHE_DIR` nothing is cached.

`rewrite_queries` freezes the LLM query rewrite per question under the same
directory, so configurations compared in one session see the same rewrites.
"""

import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from cohere.errors.too_many_requests_error import TooManyRequestsError

from src.rag.reranker import CohereReranker

logger = logging.getLogger(__name__)

RATE_LIMIT_WAIT_SECONDS = 65.0
RATE_LIMIT_RETRIES = 3
# Spacing between real Cohere calls (trial: 10 per minute).
CALL_INTERVAL_SECONDS = 6.5


class QuotaExhausted(RuntimeError):
    """The Cohere key's monthly quota is gone; stop rather than burn another key."""


_lock = threading.RLock()
_exhausted = False
_calls = 0
_last_call = 0.0


def cohere_calls() -> int:
    """Real Cohere requests made by this process."""
    return _calls


def cache_dir() -> Path | None:
    value = os.environ.get("EVAL_CACHE_DIR")
    return Path(value) if value else None


def _is_monthly(error: TooManyRequestsError) -> bool:
    text = json.dumps(error.body, default=str).casefold()
    return "month" in text


def _key(model: str, query: str, document: str) -> str:
    raw = "\u0000".join((model, query, document))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class _ScoreCache:
    def __init__(self, path: Path | None) -> None:
        self.path = path
        self.scores: dict[str, float] = {}
        if path is not None and path.exists():
            for line in path.read_text().splitlines():
                if line.strip():
                    row = json.loads(line)
                    self.scores[row["key"]] = row["score"]

    def add(self, key: str, score: float) -> None:
        self.scores[key] = score
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a") as handle:
                handle.write(json.dumps({"key": key, "score": score}) + "\n")


_cache: _ScoreCache | None = None


def _score_cache() -> _ScoreCache:
    global _cache
    directory = cache_dir()
    path = directory / "rerank-scores.jsonl" if directory else None
    if _cache is None or _cache.path != path:
        _cache = _ScoreCache(path)
    return _cache


class EvalReranker(CohereReranker):
    def _rerank_with_fallback(self, query: str, documents: list[str], top_n: int):
        with _lock:
            return self._rerank_locked(query, documents, top_n)

    def _rerank_locked(self, query: str, documents: list[str], top_n: int):
        cache = _score_cache()
        keys = [_key(self.model, query, document) for document in documents]
        missing = [i for i, key in enumerate(keys) if key not in cache.scores]
        if missing:
            scores = self.score([documents[i] for i in missing], query)
            for i, score in zip(missing, scores):
                cache.add(keys[i], score)
        ranked = sorted(
            range(len(documents)), key=lambda i: (-cache.scores[keys[i]], i)
        )
        return SimpleNamespace(
            results=[
                SimpleNamespace(index=i, relevance_score=cache.scores[keys[i]])
                for i in ranked[: min(top_n, len(documents))]
            ]
        )

    def score(self, documents: list[str], query: str) -> list[float]:
        """One real Cohere call on the primary key; scores in input order."""
        global _exhausted, _calls, _last_call
        if _exhausted:
            raise QuotaExhausted("Cohere monthly quota already exhausted")
        for attempt in range(RATE_LIMIT_RETRIES + 1):
            wait = CALL_INTERVAL_SECONDS - (time.monotonic() - _last_call)
            if wait > 0:
                time.sleep(wait)
            try:
                _last_call = time.monotonic()
                _calls += 1
                response = self.client.rerank(
                    model=self.model,
                    query=query,
                    documents=documents,
                    top_n=len(documents),
                )
                break
            except TooManyRequestsError as error:
                if _is_monthly(error):
                    _exhausted = True
                    raise QuotaExhausted(str(error.body)) from error
                if attempt == RATE_LIMIT_RETRIES:
                    raise
                logger.warning("Cohere per-minute limit; waiting 65 s")
                time.sleep(RATE_LIMIT_WAIT_SECONDS)
        scores = [0.0] * len(documents)
        for item in response.results:
            scores[item.index] = float(item.relevance_score)
        return scores


def rewrite_queries(question: str) -> list[str]:
    """original + English + semantic variant, frozen per question when cached."""
    from src.rag.query_transformer import QueryTransformer

    directory = cache_dir()
    path = directory / "rewrites.json" if directory else None
    if path is None:
        return QueryTransformer().build_queries(question).unique_queries()
    with _lock:
        stored: dict[str, Any] = json.loads(path.read_text()) if path.exists() else {}
        if question in stored:
            return list(stored[question])
    queries = QueryTransformer().build_queries(question).unique_queries()
    with _lock:
        stored = json.loads(path.read_text()) if path.exists() else {}
        stored.setdefault(question, queries)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(stored, ensure_ascii=False, indent=1))
        return list(stored[question])
