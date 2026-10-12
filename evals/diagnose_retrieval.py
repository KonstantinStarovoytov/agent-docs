"""Where does retrieval lose the correct chunk? Loss slices on the real index.

    uv run python -m evals.diagnose_retrieval slices     # step 1
    uv run python -m evals.diagnose_retrieval screen     # prefetch x pool grid
    uv run python -m evals.diagnose_retrieval threshold  # rerank score floor
    uv run python -m evals.diagnose_retrieval independence  # batch effect on scores
    uv run python -m evals.diagnose_retrieval summary
    uv run python -m evals.diagnose_retrieval recall --out X.json [--product-filter]

The collection is settings.qdrant_hybrid_collection (QDRANT_HYBRID_COLLECTION),
so the same command compares two indexes. `recall` needs no rerank data.

None of these call Cohere. The rerank slice is read from the full-corpus gate
runs stored in Langfuse (2026-10-12, same index, same settings): the
retrieval items keep the whole reranked pool with each chunk's pool rank, and
the rerank span of each coverage/negative trace keeps all ten scores. The
multi-query span keeps the exact rewrites the gate used; `slices` seeds them
into EVAL_CACHE_DIR so `screen` and later eval runs reuse them.

Questions: rag/retrieval-v3, rag/retrieval-query-transform-v1 (clean_en in
the main table; all variants are fetched) and rag/evidence-coverage-v1
(scored per evidence group). Targets come from the Langfuse datasets and
are matched like the evaluators (`evals.evidence_coverage.matches_target`).

Two retrieval paths are rebuilt exactly from Qdrant query results:

- production: one query, `search_hybrid(q, k=pool)`: Qdrant RRF over a dense
  and a BM25 prefetch of depth P, stable tie-break, cut at the pool. Today
  P = 30, pool = 10. English questions in production and the coverage runner.
- eval: `run_experiments.py`: rewrites (original + English + semantic
  variant), `search_hybrid(q_i, k=per_query_k)` per query, client-side RRF
  (k = 60), cut at the pool. Today per-query depth 60 (3 x 20), per_query_k
  20, pool 10. The gate's retrieval-v3 and query-transform metrics.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import cache
from pathlib import Path
from typing import Any

from langchain_core.documents import Document
from langfuse import Langfuse
from qdrant_client import models

from evals.eval_cache import cache_dir
from evals.evidence_coverage import group_targets, matches_target
from src.config import settings
from src.ingestion.ingest import get_hybrid_vector_store
from src.rag.context_selector import select_generation_context
from src.rag.multi_query_retriever import RRF_K
from src.rag.reranker import RerankResult
from src.rag.retriever import (
    SearchResult,
    _vendor_filter,
    document_key,
    search_hybrid,
)

REPORT_STEM = Path("reports/retrieval-diagnostics-2026-10")
DEEP = 150
PROD_PREFETCH = 30  # 3 x retrieval_top_k
EVAL_PREFETCH = 60  # 3 x per_query_k
EVAL_PER_QUERY_K = 20
TODAY_POOL = 10
PREFETCHES = (30, 60, 100, 150)
POOLS = (10, 20, 40, 60)
CONTEXT_K = 8
HIT_K = 5
MIN_SCORE = 0.35
DATASETS = {
    "retrieval-v3": "rag/retrieval-v3",
    "query-transform": "rag/retrieval-query-transform-v1",
    "evidence-coverage": "rag/evidence-coverage-v1",
    "negative": "rag/negative-v1",
}
# The full-corpus gate's "Now" runs (reports/full-corpus-eval-2026-10.md).
# Later runs that day belong to the per-page-cap experiment.
GATE_RUNS = {
    "retrieval-v3": "rewrite-hybrid-cohere-multisource-v1 - 2026-10-12T11:38",
    "query-transform": "rewrite-hybrid-cohere-multisource-v1 - 2026-10-12T11:00",
    "evidence-coverage": "answer-quality-baseline-k8 - 2026-10-12T12:02",
    "negative": "negative-abstention-k8 - 2026-10-12T11:26",
}
GATE_PATH = {
    "retrieval-v3": "eval",
    "query-transform": "eval",
    "evidence-coverage": "production",
    "negative": "production",
}
SINCE = datetime(2026, 10, 12, tzinfo=timezone.utc)
# The 35 curated pages indexed before the full corpus (git show
# 56deeaf^:src/ingestion/sources.py); everything else is "new".
OLD_PAGES = (
    "docs/en/features-overview.md",
    "docs/en/sub-agents.md",
    "docs/en/skills.md",
    "docs/en/plugins/create.md",
    "docs/en/mcp.md",
    "docs/en/memory.md",
    "docs/en/hooks.md",
    "docs/en/hooks-guide.md",
    "cursor.com/docs/customize-cursor.md",
    "cursor.com/docs/rules.md",
    "cursor.com/docs/skills.md",
    "cursor.com/docs/subagents.md",
    "cursor.com/docs/hooks.md",
    "cursor.com/docs/mcp.md",
    "cursor.com/docs/plugins.md",
    "cursor.com/docs/agent/prompting.md",
    "/agent-configuration/agents-md.md",
    "/agent-configuration/rules.md",
    "/agent-configuration/subagents.md",
    "/build-skills.md",
    "/customization/overview.md",
    "/extend/mcp.md",
    "chatgpt.com/docs/hooks.md",
    "chatgpt.com/docs/plugins.md",
    "chatgpt.com/docs/configuration.md",
    "/getting-started/intro.md",
    "/learn/architecture.md",
    "/learn/server-concepts.md",
    "/learn/client-concepts.md",
    "/learn/versioning.md",
    "/develop/build-server.md",
    "/develop/build-client.md",
    "/docs/2026-07-28/sdk.md",
    "/tutorials/security/authorization.md",
    "/tutorials/security/security_best_practices.md",
)


def is_new_page(url: str) -> bool:
    return not url.split("?", 1)[0].rstrip("/").endswith(OLD_PAGES)


# ---------------------------------------------------------------- cases


@dataclass
class Group:
    id: str
    targets: list[dict[str, Any]]


@dataclass
class Case:
    dataset: str
    case_id: str
    question: str
    groups: list[Group]
    variant: str = "clean_en"

    @property
    def english(self) -> bool:
        return self.variant in {"clean_en", "natural_en", "short_en"}


@cache
def langfuse() -> Langfuse:
    assert settings.langfuse_secret_key is not None
    return Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key.get_secret_value(),
        base_url=settings.langfuse_base_url,
    )


def load_cases() -> list[Case]:
    cases: list[Case] = []
    for item in langfuse().get_dataset(DATASETS["retrieval-v3"]).items:
        question = item.input["question"]
        groups = [Group("relevant", item.expected_output["relevant"])]
        cases.append(Case("retrieval-v3", _slug(question), question, groups))
    for item in langfuse().get_dataset(DATASETS["query-transform"]).items:
        variant = item.metadata["query_type"]
        cases.append(
            Case(
                "query-transform",
                f"{item.metadata['intent_id']}:{variant}",
                item.input["question"],
                [Group("relevant", item.expected_output["relevant"])],
                variant,
            )
        )
    for item in langfuse().get_dataset(DATASETS["evidence-coverage"]).items:
        groups = [
            Group(group["id"], group_targets(group))
            for group in item.expected_output["evidence_groups"]
        ]
        cases.append(
            Case(
                "evidence-coverage",
                item.metadata["intent_id"],
                item.input["question"],
                groups,
            )
        )
    for item in langfuse().get_dataset(DATASETS["negative"]).items:
        cases.append(
            Case("negative", item.metadata["intent_id"], item.input["question"], [])
        )
    return cases


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")[:60]


# ------------------------------------------------------------ matching


def row(metadata: dict[str, Any]) -> dict[str, Any]:
    heading = metadata.get("heading")
    if heading is None:
        heading = " > ".join(
            value
            for value in (metadata.get("h1"), metadata.get("h2"), metadata.get("h3"))
            if value
        )
    return {
        "vendor": metadata.get("vendor"),
        "product": metadata.get("product"),
        "title": metadata.get("title"),
        "heading": heading,
        "source": metadata.get("source", ""),
    }


def matches(metadata: dict[str, Any], group: Group) -> bool:
    candidate = row(metadata)
    return any(matches_target(candidate, target) for target in group.targets)


def path_type(url: str) -> str:
    """Coarse page type from the URL path; first matching rule wins."""
    path = url.split("://", 1)[-1].casefold()
    if re.search(
        r"/enterprise|/account/|admin|managed-|governance|compliance|/teams?[/.]"
        r"|sso|scim|billing|pricing|data-usage|legal-and|analytics|monitoring-usage"
        r"|organization|champion-kit|communications-kit|corporate-launcher|gateway"
        r"|self-hosted|network-config|rollouts|usage-limits|hipaa|zero-data-retention"
        r"|amazon-bedrock|google-vertex|microsoft-foundry|on-aws|service-accounts",
        path,
    ):
        return "admin-enterprise"
    if re.search(r"security|secure-|cyber|threat-model", path):
        return "security"
    if re.search(r"/api[/.]|-api\.md|/endpoints|/webhooks", path):
        return "api"
    if "sdk" in path:
        return "sdk"
    if re.search(
        r"reference|/specification/|schema|glossary|changelog|release-notes"
        r"|whats-new|env-vars|/models/|commands\.md|-sample|settings-example"
        r"|deprecated|/registry/|feature-availability|errors\.md",
        path,
    ):
        return "reference"
    if re.search(
        r"/integrations/|/third-party/|grok-bot|bugbot|/origin|/dots|/space"
        r"|slack|jira|linear|github-action|gitlab|jetbrains|vs-code|chrome|xcode",
        path,
    ):
        return "other"
    return "guide"


def _page(url: str) -> str:
    page = url.split("://", 1)[-1].split("?", 1)[0].rstrip("/")
    return page.removesuffix(".md")


def in_family(metadata: dict[str, Any], group: Group, expected: set[str]) -> bool:
    """Same page as an expected chunk (another section), a sibling/child page
    (`en/mcp` ~ `en/mcp-quickstart`, `en/plugins` ~ `en/plugins/create`), or a
    same-vendor section whose heading names the target page's topic
    (`customize-cursor > Skills` for target `skills`). Only a flag for manual
    review: a hit here may be an unlabelled correct answer."""
    source = metadata.get("source", "")
    if source in expected:
        return True
    vendors = {t.get("vendor") for t in group.targets if t.get("vendor")}
    if vendors and metadata.get("vendor") not in vendors:
        return False
    heading = row(metadata)["heading"].casefold()
    for target in group.targets:
        stem = _page(target.get("source_contains", "")).rpartition("/")[2]
        term = stem.removesuffix("s").replace("-md", ".md")
        if vendors and len(term) >= 4 and term in heading:
            return True
    page = _page(source)
    pages = {_page(s) for s in expected}
    pages |= {
        _page(t["source_contains"]) for t in group.targets if t.get("source_contains")
    }
    for other in pages:
        if not other:
            continue
        if f"{other}/" in page or f"{page}/" in other:
            return True
        other_parent, _, other_stem = other.rpartition("/")
        page_parent, _, page_stem = page.rpartition("/")
        if not other_parent or not page_parent:
            continue
        if page_parent.endswith(other_parent) or other_parent.endswith(page_parent):
            if page_stem.startswith(other_stem + "-") or other_stem.startswith(
                page_stem + "-"
            ):
                return True
    return False


# ---------------------------------------------------------- index probe


class IndexProbe:
    """Qdrant hybrid queries exactly as langchain-qdrant sends them, cached
    per (query, depth), with one embedding per query string."""

    def __init__(self) -> None:
        self.store = get_hybrid_vector_store()
        self.client = self.store.client
        self.collection = settings.qdrant_hybrid_collection
        self._vectors: dict[str, tuple[list[float], models.SparseVector]] = {}
        self._fused: dict[tuple[str, int, str | None], list[SearchResult]] = {}
        self._single: dict[tuple[str, str], list[str]] = {}

    def vectors(self, query: str) -> tuple[list[float], models.SparseVector]:
        if query not in self._vectors:
            dense = self.store.embeddings.embed_query(query)
            sparse = self.store.sparse_embeddings.embed_query(query)
            self._vectors[query] = (
                dense,
                models.SparseVector(indices=sparse.indices, values=sparse.values),
            )
        return self._vectors[query]

    def single(self, query: str, using: str) -> list[str]:
        """Point ids of the dense-only or BM25-only top 150."""
        key = (query, using)
        if key not in self._single:
            dense, sparse = self.vectors(query)
            vector: Any = dense if using == "dense" else sparse
            name = (
                self.store.vector_name
                if using == "dense"
                else self.store.sparse_vector_name
            )
            points = self.client.query_points(
                self.collection,
                query=vector,
                using=name,
                limit=DEEP,
                with_payload=False,
            ).points
            self._single[key] = [str(point.id) for point in points]
        return self._single[key]

    def fused(
        self, query: str, depth: int, vendor: str | None = None
    ) -> list[SearchResult]:
        """search_hybrid's order for langchain k = depth, before the cut."""
        key = (query, depth, vendor)
        if key not in self._fused:
            dense, sparse = self.vectors(query)
            where = _vendor_filter(vendor)
            points = self.client.query_points(
                self.collection,
                prefetch=[
                    models.Prefetch(
                        using=self.store.vector_name,
                        query=dense,
                        limit=depth,
                        filter=where,
                    ),
                    models.Prefetch(
                        using=self.store.sparse_vector_name,
                        query=sparse,
                        limit=depth,
                        filter=where,
                    ),
                ],
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=depth,
                with_payload=True,
            ).points
            rows = []
            for point in points:
                payload = point.payload or {}
                document = Document(
                    page_content=payload.get("page_content", ""),
                    metadata=dict(payload.get("metadata") or {}),
                )
                document.metadata["_id"] = str(point.id)
                rows.append(SearchResult(document, point.score))
            rows.sort(key=lambda r: (-r.score, document_key(r.document)))
            self._fused[key] = rows
        return self._fused[key]

    def production_pool(
        self, query: str, prefetch: int | None, pool: int, vendor: str | None = None
    ) -> list[SearchResult]:
        depth = 3 * pool if prefetch is None else max(prefetch, pool)
        return self.fused(query, depth, vendor)[:pool]

    def eval_pool(
        self,
        queries: list[str],
        prefetch: int | None,
        pool: int,
        vendor: str | None = None,
    ) -> list[SearchResult]:
        """per_query_k = max(20, pool); depth = prefetch, None = 3 x per_query_k;
        client RRF (k = 60) over the per-query lists; cut at pool."""
        per_query_k = max(EVAL_PER_QUERY_K, pool)
        depth = 3 * per_query_k if prefetch is None else max(prefetch, per_query_k)
        documents: dict[str, SearchResult] = {}
        scores: dict[str, float] = defaultdict(float)
        for query in queries:
            for rank, result in enumerate(
                self.fused(query, depth, vendor)[:per_query_k], 1
            ):
                key = document_key(result.document)
                documents[key] = result
                scores[key] += 1.0 / (RRF_K + rank)
        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        return [
            SearchResult(documents[key].document, score) for key, score in ranked[:pool]
        ]


def pid(result: SearchResult) -> str:
    return str(result.document.metadata["_id"])


def catalog(probe: IndexProbe) -> dict[str, dict[str, Any]]:
    """Metadata (no text) of every chunk, to find every correct chunk."""
    rows: dict[str, dict[str, Any]] = {}
    offset = None
    selector = models.PayloadSelectorExclude(
        exclude=["page_content", "metadata.raw_content"]
    )
    while True:
        points, offset = probe.client.scroll(
            probe.collection,
            limit=1000,
            offset=offset,
            with_payload=selector,
            with_vectors=False,
        )
        for point in points:
            rows[str(point.id)] = dict((point.payload or {}).get("metadata") or {})
        if offset is None:
            return rows


# ------------------------------------------------------ stored gate runs


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _experiment_items(prefix: str) -> list[Any]:
    client = langfuse()
    runs = [
        e
        for e in client.api.experiments.list(from_start_time=SINCE, limit=100).data
        if e.name.startswith(prefix)
    ]
    if len(runs) != 1:
        raise RuntimeError(f"expected one run named {prefix!r}, found {len(runs)}")
    items: list[Any] = []
    cursor = None
    while True:
        kwargs: dict[str, Any] = {
            "from_start_time": SINCE,
            "experiment_id": runs[0].id,
            "fields": "io",
            "limit": 100,
        }
        if cursor:
            kwargs["cursor"] = cursor
        response = client.api.experiments.list_items(**kwargs)
        items.extend(response.data)
        cursor = getattr(getattr(response, "meta", None), "cursor", None)
        if not cursor:
            return items


def _observation(trace_id: str, name: str) -> Any:
    for attempt in range(4):
        try:
            data = (
                langfuse()
                .api.observations.get_many(
                    trace_id=trace_id, name=name, limit=5, fields="core,io"
                )
                .data
            )
            return data[0] if data else None
        except Exception:  # Langfuse Hobby rate limit
            time.sleep(15 * (attempt + 1))
    raise RuntimeError(f"observation {name} of {trace_id} unavailable")


def _header(content: str) -> dict[str, str]:
    """Vendor/Product/Document/Section lines of a chunk's context header."""
    fields = {}
    for line in content.split("\n\n", 1)[0].splitlines():
        key, _, value = line.partition(": ")
        fields[key.strip()] = value.strip()
    return fields


def fetch_stored() -> dict[str, dict[str, Any]]:
    """{dataset|question: {"ranked": [...], "queries": [...] | None}}."""
    stored: dict[str, dict[str, Any]] = {}
    for dataset, prefix in GATE_RUNS.items():
        for item in _experiment_items(prefix):
            question = _json(item.input)["question"]
            output = _json(item.output) or {}
            entry: dict[str, Any] = {"trace_id": item.trace_id, "queries": None}
            if GATE_PATH[dataset] == "eval":
                entry["ranked"] = [
                    {
                        "rerank_rank": r["rank"],
                        "pool_rank": r["multi_query_rank"],
                        "rerank_score": r["rerank_score"],
                        **{k: r.get(k) for k in ("vendor", "product", "title")},
                        "heading": r.get("heading", ""),
                        "source": r.get("source", ""),
                    }
                    for r in output.get("results", [])
                ]
                fusion = _observation(item.trace_id, "multi-query-fusion")
                entry["queries"] = _json(fusion.input)["kwargs"]["queries"]
            else:
                span = _observation(item.trace_id, "rerank-candidates")
                rows = _json(span.output) if span is not None else []
                entry["ranked"] = []
                for r in rows:
                    header = _header(r.get("content", ""))
                    entry["ranked"].append(
                        {
                            "rerank_rank": r["rerank_rank"],
                            "pool_rank": r["original_rank"],
                            "rerank_score": r["rerank_score"],
                            "vendor": header.get("Vendor"),
                            "product": header.get("Product"),
                            "title": r.get("title"),
                            "heading": header.get("Section", ""),
                            "source": r.get("source", ""),
                        }
                    )
                entry["answer"] = (output.get("answer") or "")[:240]
            stored[f"{dataset}|{question}"] = entry
            print(f"stored {dataset}: {question[:60]}", flush=True)
    return stored


# ------------------------------------------------------------- slices


def _best(ids: list[str], correct: set[str]) -> int | None:
    for rank, point_id in enumerate(ids, 1):
        if point_id in correct:
            return rank
    return None


def _best_rows(rows: list[dict[str, Any]], group: Group) -> int | None:
    for rank, r in enumerate(rows, 1):
        if matches(r, group):
            return rank
    return None


def _context(ranked: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The 8 chunks the LLM would see: floor 0.35, max 2 per section."""
    results = [
        RerankResult(
            document=Document(
                page_content="",
                metadata={"source": r["source"], "h1": r["heading"], "_row": i},
            ),
            retrieval_score=0.0,
            rerank_score=r["rerank_score"],
            original_rank=r["pool_rank"],
            rerank_rank=r["rerank_rank"],
        )
        for i, r in enumerate(ranked)
    ]
    selected = select_generation_context(results, CONTEXT_K, min_rerank_score=MIN_SCORE)
    return [ranked[r.document.metadata["_row"]] for r in selected]


def classify(g: dict[str, Any], window: str, prefetch: int) -> str:
    rank = g["context_rank"] if window == "context" else g["rerank_rank"]
    if rank is not None and (window == "context" or rank <= HIT_K):
        return "OK"
    dense, bm25 = g["dense_rank"], g["bm25_rank"]
    if (dense is None or dense > prefetch) and (bm25 is None or bm25 > prefetch):
        return "LOST_BEFORE_FUSION"
    if g["pool_rank"] is None:
        return "LOST_IN_POOL"
    return "LOST_IN_RERANK"


def _shown(entry: dict[str, Any], window: str) -> list[dict[str, Any]]:
    ranked = entry["ranked"]
    return _context(ranked) if window == "context" else ranked[:HIT_K]


def diagnose_case(
    probe: IndexProbe,
    meta: dict[str, dict[str, Any]],
    case: Case,
    entry: dict[str, Any],
) -> dict[str, Any]:
    path = GATE_PATH[case.dataset]
    queries = entry["queries"] if path == "eval" else [case.question]
    prefetch = EVAL_PREFETCH if path == "eval" else PROD_PREFETCH
    ranked = sorted(entry["ranked"], key=lambda r: r["rerank_rank"])
    for r in ranked:
        r["correct"] = [group.id for group in case.groups if matches(r, group)]
        r["path_type"] = path_type(r["source"])
    by_pool = sorted(ranked, key=lambda r: r["pool_rank"])
    context = _context(ranked)

    if path == "eval":
        today = probe.eval_pool(queries, None, TODAY_POOL)
        deep = probe.eval_pool(queries, 150, TODAY_POOL)
    else:
        today = probe.production_pool(case.question, PROD_PREFETCH, TODAY_POOL)
        deep = probe.production_pool(case.question, 150, TODAY_POOL)
    rebuilt = [
        (r.document.metadata.get("source"), row(r.document.metadata)["heading"])
        for r in today
    ]
    stored_pool = [(r["source"], r["heading"]) for r in by_pool]

    groups = []
    for group in case.groups:
        correct = {point_id for point_id, md in meta.items() if matches(md, group)}
        expected = {meta[point_id].get("source", "") for point_id in correct}

        def best_over_queries(fn: Any) -> int | None:
            ranks = [fn(q) for q in queries]
            found = [r for r in ranks if r is not None]
            return min(found) if found else None

        g: dict[str, Any] = {
            "group": group.id,
            "corpus_matches": len(correct),
            "dense_rank": best_over_queries(
                lambda q: _best(probe.single(q, "dense"), correct)
            ),
            "bm25_rank": best_over_queries(
                lambda q: _best(probe.single(q, "sparse"), correct)
            ),
            **{
                f"fused_rank_p{d}": best_over_queries(
                    lambda q, d=d: _best([pid(r) for r in probe.fused(q, d)], correct)
                )
                for d in PREFETCHES
            },
            "pool_rank": _best_rows(by_pool, group),
            "pool_rank_p150": _best([pid(r) for r in deep], correct),
            "rerank_rank": _best_rows(ranked, group),
            "context_rank": _best_rows(context, group),
            "best_correct_score": max(
                (r["rerank_score"] for r in ranked if matches(r, group)), default=None
            ),
            "top_score": ranked[0]["rerank_score"] if ranked else None,
        }
        for window in ("context", "hit5"):
            verdict = classify(g, window, prefetch)
            g[f"class_{window}"] = verdict
            g[f"label_gap_{window}"] = verdict != "OK" and any(
                in_family(r, group, expected)
                for r in _shown(entry | {"ranked": ranked}, window)
                if not r["correct"]
            )
        stop = (g["rerank_rank"] - 1) if g["rerank_rank"] else CONTEXT_K
        g["outranked_by"] = [
            {
                "source": r["source"],
                "heading": r["heading"],
                "path_type": path_type(r["source"]),
                "rerank_score": r["rerank_score"],
                "same_family": in_family(r, group, expected),
                "new_page": is_new_page(r["source"]),
                "same_vendor": r.get("vendor")
                in {t.get("vendor") for t in group.targets},
            }
            for r in ranked[:stop]
            if not r["correct"]  # a chunk answering another group is no distractor
        ]
        groups.append(g)

    return {
        "dataset": case.dataset,
        "case_id": case.case_id,
        "question": case.question,
        "variant": case.variant,
        "path": path,
        "queries": queries,
        "pool_rebuilt_matches_stored": rebuilt == stored_pool,
        "pool_overlap_rebuilt_vs_stored": len(set(rebuilt) & set(stored_pool)),
        "groups": groups,
        "ranked": ranked,
        "answer": entry.get("answer"),
    }


def run_slices(args: argparse.Namespace) -> None:
    probe = IndexProbe()
    meta = catalog(probe)
    stored_path = Path(f"{REPORT_STEM}-stored.json")
    if stored_path.exists() and not args.refetch:
        stored = json.loads(stored_path.read_text())
    else:
        stored = fetch_stored()
        stored_path.write_text(json.dumps(stored, ensure_ascii=False, indent=1))
    _seed_rewrites(stored)
    results = []
    cases = load_cases()
    for index, case in enumerate(cases):
        entry = stored.get(f"{case.dataset}|{case.question}")
        if entry is None:
            print(f"no stored run for {case.dataset} {case.case_id}", file=sys.stderr)
            continue
        if args.verify and GATE_PATH[case.dataset] == "production":
            check = search_hybrid(case.question, k=TODAY_POOL)
            mine = probe.production_pool(case.question, PROD_PREFETCH, TODAY_POOL)
            assert [document_key(r.document) for r in check] == [
                document_key(r.document) for r in mine
            ], f"probe differs from search_hybrid for {case.question!r}"
        results.append(diagnose_case(probe, meta, case, entry))
        print(f"[{index + 1}/{len(cases)}] {case.dataset} {case.case_id}", flush=True)
    payload = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "collection": probe.collection,
        "gate_runs": GATE_RUNS,
        "today": {
            "production": {"prefetch": PROD_PREFETCH, "pool": TODAY_POOL},
            "eval": {
                "per_query_prefetch": EVAL_PREFETCH,
                "per_query_k": EVAL_PER_QUERY_K,
                "pool": TODAY_POOL,
            },
            "context_k": CONTEXT_K,
            "min_rerank_score": MIN_SCORE,
        },
        "cases": results,
    }
    Path(f"{REPORT_STEM}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1)
    )
    Path(f"{REPORT_STEM}-slices.md").write_text(slices_markdown(results))
    print(json.dumps(summarize(results), indent=1))


def _seed_rewrites(stored: dict[str, dict[str, Any]]) -> None:
    """Freeze the gate's rewrites so screens and reruns see the same queries."""
    directory = cache_dir()
    if directory is None:
        return
    path = directory / "rewrites.json"
    current = json.loads(path.read_text()) if path.exists() else {}
    for key, entry in stored.items():
        if entry.get("queries"):
            current[key.split("|", 1)[1]] = entry["queries"]
    directory.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, ensure_ascii=False, indent=1))


# ------------------------------------------------------------ reporting


def _fmt(value: Any) -> str:
    if value is None:
        return "–"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _main_table(case: dict[str, Any]) -> bool:
    return case["dataset"] != "negative" and (
        case["dataset"] != "query-transform" or case["variant"] == "clean_en"
    )


def slices_markdown(results: list[dict[str, Any]]) -> str:
    lines = [
        "# Retrieval loss slices (generated)",
        "",
        "Generated by `uv run python -m evals.diagnose_retrieval slices`. Each row",
        "is classified on the path that produced the gate metric: retrieval-v3 and",
        "query-transform on the eval path (rewrites, per-query prefetch 60, pool 10),",
        "evidence-coverage on the production path (prefetch 30, pool 10). The rerank",
        "columns come from the gate's stored Cohere runs. Ranks are the best rank of",
        "any correct chunk (– = absent). dense/bm25: top 150, best over the queries.",
        "`pool p150`: rank in the pool of 10 if the prefetch were 150.",
        "",
        "| dataset | case | group | dense | bm25 | fused p30 | fused p150 | pool | pool p150 | rerank | context | best score | @context | @hit5 | gap |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for case in results:
        if not _main_table(case):
            continue
        for g in case["groups"]:
            gap = "flag" if g["label_gap_context"] or g["label_gap_hit5"] else ""
            cells = [
                case["dataset"],
                case["case_id"][:44],
                g["group"],
                _fmt(g["dense_rank"]),
                _fmt(g["bm25_rank"]),
                _fmt(g["fused_rank_p30"]),
                _fmt(g["fused_rank_p150"]),
                _fmt(g["pool_rank"]),
                _fmt(g["pool_rank_p150"]),
                _fmt(g["rerank_rank"]),
                _fmt(g["context_rank"]),
                _fmt(g["best_correct_score"]),
                g["class_context"],
                g["class_hit5"],
                gap,
            ]
            lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    scopes = {
        "main (rv3 + qt clean_en + coverage groups)": [
            c for c in results if _main_table(c)
        ],
        "retrieval-v3": [c for c in results if c["dataset"] == "retrieval-v3"],
        "query-transform all 48": [
            c for c in results if c["dataset"] == "query-transform"
        ],
        "evidence-coverage": [
            c for c in results if c["dataset"] == "evidence-coverage"
        ],
    }
    for scope, cases in scopes.items():
        part: dict[str, Any] = {
            "groups": sum(len(c["groups"]) for c in cases),
            "pool_rebuilt_exactly": sum(
                c["pool_rebuilt_matches_stored"] for c in cases
            ),
            "cases": len(cases),
        }
        for window in ("context", "hit5"):
            counts: Counter[str] = Counter()
            gaps: Counter[str] = Counter()
            for case in cases:
                for g in case["groups"]:
                    counts[g[f"class_{window}"]] += 1
                    if g[f"label_gap_{window}"]:
                        gaps[g[f"class_{window}"]] += 1
            part[window] = {"classes": dict(counts), "label_gap_flags": dict(gaps)}
        types: Counter[str] = Counter()
        new_types: Counter[str] = Counter()
        pages: Counter[str] = Counter()
        family = new = cross_vendor = total = 0
        for case in cases:
            for g in case["groups"]:
                for other in g["outranked_by"]:
                    total += 1
                    types[other["path_type"]] += 1
                    pages[other["source"]] += 1
                    family += other["same_family"]
                    new += other["new_page"]
                    cross_vendor += not other["same_vendor"]
                    if other["new_page"]:
                        new_types[other["path_type"]] += 1
        part["outranked_total"] = total
        part["outranked_by_type"] = dict(types.most_common())
        part["outranked_new_pages"] = new
        part["outranked_new_pages_by_type"] = dict(new_types.most_common())
        part["outranked_other_vendor"] = cross_vendor
        part["outranked_same_family"] = family
        part["outranked_by_page"] = pages.most_common(12)
        part["first_correct_not_rank1"] = sum(
            1 for case in cases for g in case["groups"] if g["rerank_rank"] != 1
        )
        summary[scope] = part
    return summary


# --------------------------------------------------------------- recall

RECALL_POOLS = (10, 20, 40)
FULL_CORPUS = "full-corpus"


def case_vendor(case: Case) -> str | None:
    """The vendor every target names, or None (mixed or unlabelled)."""
    vendors = {t.get("vendor") for group in case.groups for t in group.targets}
    if len(vendors) != 1:
        return None
    return vendors.pop()


def loss_class(
    corpus_matches: int,
    in_pool: bool,
    dense_rank: int | None,
    bm25_rank: int | None,
    prefetch: int,
) -> str:
    """Where a group is lost without a reranker."""
    if corpus_matches == 0:
        return "NOT_IN_CORPUS"
    if in_pool:
        return "IN_POOL"
    if any(rank is not None and rank <= prefetch for rank in (dense_rank, bm25_rank)):
        return "LOST_IN_POOL"
    return "LOST_BEFORE_FUSION"


def recall_table(records: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """dataset -> pool -> share of evidence groups with a correct chunk in it."""
    hits: dict[str, dict[str, list[bool]]] = defaultdict(lambda: defaultdict(list))
    for record in records:
        for pool, values in record["hits"].items():
            hits[record["dataset"]][pool].extend(values)
    return {
        dataset: {pool: sum(v) / len(v) for pool, v in pools.items()}
        for dataset, pools in hits.items()
    }


def recall_cases() -> list[Case]:
    """retrieval-v3, query-transform clean_en, evidence-coverage, full-corpus."""
    from evals.full_corpus_cases import CASES

    cases = [
        c
        for c in load_cases()
        if c.dataset != "negative"
        and (c.dataset != "query-transform" or c.variant == "clean_en")
    ]
    for item in CASES:
        cases.append(
            Case(
                FULL_CORPUS,
                _slug(item["question"]),
                item["question"],
                [Group("relevant", item["relevant"])],
            )
        )
    return cases


def run_recall(args: argparse.Namespace) -> None:
    """recall-in-pool at pools 10/20/40 on the configured collection, no Cohere.

    retrieval-v3 and query-transform use the eval path with the gate's frozen
    rewrites; evidence-coverage and full-corpus the production path (one
    query). --product-filter scopes retrieval to the vendor the labels name.
    """
    stored = json.loads(Path(f"{REPORT_STEM}-stored.json").read_text())
    rewrites = {
        key.split("|", 1)[1]: entry["queries"]
        for key, entry in stored.items()
        if entry.get("queries")
    }
    probe = IndexProbe()
    meta = catalog(probe)
    records = []
    cases = recall_cases()
    for index, case in enumerate(cases):
        vendor = case_vendor(case) if args.product_filter else None
        eval_path = case.dataset in {"retrieval-v3", "query-transform"}
        queries = rewrites[case.question] if eval_path else [case.question]
        prefetch = EVAL_PREFETCH if eval_path else PROD_PREFETCH

        def pool_ids(pool: int) -> list[str]:
            if eval_path:
                results = probe.eval_pool(queries, None, pool, vendor)
            else:
                results = probe.production_pool(case.question, None, pool, vendor)
            return [pid(r) for r in results]

        pools = {pool: pool_ids(pool) for pool in RECALL_POOLS}
        hits: dict[str, list[bool]] = {str(p): [] for p in RECALL_POOLS}
        groups = []
        for group in case.groups:
            correct = {point_id for point_id, md in meta.items() if matches(md, group)}
            for pool, ids in pools.items():
                hits[str(pool)].append(bool(correct & set(ids)))
            dense = min(
                (r for q in queries if (r := _best(probe.single(q, "dense"), correct))),
                default=None,
            )
            bm25 = min(
                (
                    r
                    for q in queries
                    if (r := _best(probe.single(q, "sparse"), correct))
                ),
                default=None,
            )
            groups.append(
                {
                    "group": group.id,
                    "corpus_matches": len(correct),
                    "dense_rank": dense,
                    "bm25_rank": bm25,
                    "pool10_rank": _best(pools[10], correct),
                    "class_pool10": loss_class(
                        len(correct),
                        bool(correct & set(pools[10])),
                        dense,
                        bm25,
                        prefetch,
                    ),
                }
            )
        records.append(
            {
                "dataset": case.dataset,
                "case_id": case.case_id,
                "vendor_filter": vendor,
                "hits": hits,
                "groups": groups,
            }
        )
        print(f"[{index + 1}/{len(cases)}] {case.dataset} {case.case_id}", flush=True)
    out = Path(args.out)
    payload = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "collection": probe.collection,
        "product_filter": args.product_filter,
        "recall": recall_table(records),
        "cases": records,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1))
    print(recall_markdown(payload))


def recall_markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"collection {payload['collection']}, product filter: {payload['product_filter']}",
        "",
        "| dataset | groups | " + " | ".join(f"pool {p}" for p in RECALL_POOLS) + " |",
        "|---|---|" + "---|" * len(RECALL_POOLS),
    ]
    for dataset, pools in sorted(payload["recall"].items()):
        n = sum(len(c["groups"]) for c in payload["cases"] if c["dataset"] == dataset)
        cells = [f"{pools[str(p)]:.3f}" for p in RECALL_POOLS]
        lines.append(f"| {dataset} | {n} | " + " | ".join(cells) + " |")
    classes: dict[str, Counter[str]] = defaultdict(Counter)
    for case in payload["cases"]:
        for g in case["groups"]:
            classes[case["dataset"]][g["class_pool10"]] += 1
    lines += ["", "Loss slices at pool 10:", ""]
    for dataset, counter in sorted(classes.items()):
        lines.append(f"- {dataset}: {dict(counter)}")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------- screen


def run_screen(args: argparse.Namespace) -> None:
    """recall@pool for every prefetch x pool cell, no Cohere."""
    directory = cache_dir()
    if directory is None or not (directory / "rewrites.json").exists():
        sys.exit("Run `slices` with EVAL_CACHE_DIR first: it freezes the rewrites.")
    rewrites = json.loads((directory / "rewrites.json").read_text())
    probe = IndexProbe()
    meta = catalog(probe)
    cases = [c for c in load_cases() if c.dataset != "negative"]
    cells: dict[tuple[str, str, int | None, int], dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for index, case in enumerate(cases):
        correct = [
            {point_id for point_id, md in meta.items() if matches(md, group)}
            for group in case.groups
        ]
        paths = []
        if case.english:
            paths.append("production")
        if case.dataset != "evidence-coverage":
            paths.append("eval")
        for path in paths:
            for prefetch in (None, *PREFETCHES):
                for pool in POOLS:
                    if path == "production":
                        if prefetch is not None and pool > prefetch:
                            continue
                        results = probe.production_pool(case.question, prefetch, pool)
                    else:
                        results = probe.eval_pool(
                            rewrites[case.question], prefetch, pool
                        )
                    ids = [pid(r) for r in results]
                    hits = [bool(set(ids) & group) for group in correct]
                    first = [_best(ids, group) for group in correct]
                    cell = cells[(case.dataset, path, prefetch, pool)]
                    cell["recall"].extend(float(h) for h in hits)
                    cell["complete"].append(float(all(hits)))
                    cell["rrf_mrr"].extend(1.0 / r if r else 0.0 for r in first)
                    cell["rrf_hit5"].extend(float(bool(r and r <= 5)) for r in first)
        print(f"[{index + 1}/{len(cases)}] {case.dataset} {case.case_id}", flush=True)
    rows = []
    for (dataset, path, prefetch, pool), cell in cells.items():
        rows.append(
            {
                "dataset": dataset,
                "path": path,
                "prefetch": prefetch,
                "pool": pool,
                "recall_at_pool": statistics.mean(cell["recall"]),
                "complete_at_pool": statistics.mean(cell["complete"]),
                "rrf_mrr": statistics.mean(cell["rrf_mrr"]),
                "rrf_hit5": statistics.mean(cell["rrf_hit5"]),
                "n": len(cell["recall"]),
            }
        )
    rows.sort(key=lambda r: (r["dataset"], r["path"], r["prefetch"] or 0, r["pool"]))
    Path(f"{REPORT_STEM}-screen.json").write_text(json.dumps({"rows": rows}, indent=1))
    markdown = screen_markdown(rows)
    Path(f"{REPORT_STEM}-screen.md").write_text(markdown)
    print(markdown)


def screen_markdown(rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Prefetch x pool screen (generated, no rerank)",
        "",
        "recall@pool: share of questions (coverage: evidence groups) with a",
        "correct chunk inside the candidate pool handed to Cohere. Coverage also",
        "shows complete@pool (every group of the question in the pool).",
        "`default` = today's prefetch (production 3 x pool, eval 3 x per-query k).",
    ]
    keys = sorted({(r["dataset"], r["path"]) for r in rows})
    for dataset, path in keys:
        subset = [r for r in rows if r["dataset"] == dataset and r["path"] == path]
        metrics = ["recall_at_pool"]
        if dataset == "evidence-coverage":
            metrics.append("complete_at_pool")
        for metric in metrics:
            lines += [
                "",
                f"## {dataset} / {path} path: {metric} (n={subset[0]['n']})",
                "",
                "| prefetch | " + " | ".join(f"pool {p}" for p in POOLS) + " |",
                "|---|" + "---|" * len(POOLS),
            ]
            for prefetch in (None, *PREFETCHES):
                cells = []
                for pool in POOLS:
                    hit = [
                        r
                        for r in subset
                        if r["prefetch"] == prefetch and r["pool"] == pool
                    ]
                    cells.append(f"{hit[0][metric]:.3f}" if hit else "n/a")
                label = "default" if prefetch is None else str(prefetch)
                lines.append(f"| {label} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------- threshold


def run_threshold(_args: argparse.Namespace) -> None:
    data = json.loads(Path(f"{REPORT_STEM}.json").read_text())
    cases = data["cases"]
    markdown = threshold_markdown(cases)
    Path(f"{REPORT_STEM}-threshold.md").write_text(markdown)
    print(markdown)


def _labelled(cases: list[dict[str, Any]]) -> list[tuple[str, bool, float]]:
    rows = []
    for case in cases:
        if case["dataset"] == "negative":
            rows += [("negative", False, r["rerank_score"]) for r in case["ranked"]]
            continue
        for r in case["ranked"]:
            rows.append((case["dataset"], bool(r.get("correct")), r["rerank_score"]))
    return rows


def _keep(scores: list[float], floor: float, relative: float) -> list[float]:
    if not scores:
        return []
    best = max(scores)
    return [s for s in scores if s >= floor and s >= relative * best]


def threshold_markdown(cases: list[dict[str, Any]]) -> str:
    rows = _labelled(cases)
    bins = [0.0, 0.1, 0.2, 0.3, 0.35, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0001]
    lines = [
        "# Rerank score distribution and floor (generated, stored scores only)",
        "",
        "Every reranked candidate of the gate runs, labelled with the dataset",
        "targets. Negative = rag/negative-v1 (all incorrect by definition).",
        "",
        "| score | correct | incorrect (answerable sets) | negative-v1 |",
        "|---|---|---|---|",
    ]
    for low, high in zip(bins, bins[1:]):

        def n(kind: str) -> int:
            return sum(
                1
                for dataset, correct, score in rows
                if low <= score < high
                and (
                    (kind == "correct" and correct)
                    or (kind == "wrong" and not correct and dataset != "negative")
                    or (kind == "negative" and dataset == "negative")
                )
            )

        lines.append(
            f"| {low:.2f}–{min(high, 1.0):.2f} | {n('correct')} | {n('wrong')} | {n('negative')} |"
        )
    positives = [c for c in cases if c["dataset"] != "negative"]
    negatives = [c for c in cases if c["dataset"] == "negative"]
    lines += [
        "",
        "Effect of a rule on the stored scores. *answerable groups kept* = evidence",
        "groups / questions whose best correct chunk survives the rule (of those",
        "whose correct chunk was reranked at all). *negatives emptied* = negative",
        "questions left with no chunk, so the bot abstains without asking the LLM.",
        "",
        "| rule | answerable groups kept | coverage questions complete-eligible | negatives emptied | mean chunks kept (negative) |",
        "|---|---|---|---|---|",
    ]
    rules = [(f, 0.0) for f in (0.0, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.60)]
    rules += [(0.35, x) for x in (0.5, 0.6, 0.7)]
    for floor, relative in rules:
        kept = total = 0
        complete = coverage_total = 0
        for case in positives:
            scores = [r["rerank_score"] for r in case["ranked"]]
            survivors = set(_keep(scores, floor, relative))
            all_groups = True
            for g in case["groups"]:
                if g["best_correct_score"] is None:
                    all_groups = False
                    continue
                total += 1
                ok = g["best_correct_score"] in survivors
                kept += ok
                all_groups &= ok
            if case["dataset"] == "evidence-coverage":
                coverage_total += 1
                complete += all_groups
        emptied = 0
        sizes = []
        for case in negatives:
            survivors = _keep(
                [r["rerank_score"] for r in case["ranked"]], floor, relative
            )
            emptied += not survivors
            sizes.append(min(len(survivors), CONTEXT_K))
        label = f"floor {floor:.2f}" + (
            f" and ≥ {relative:.1f}·best" if relative else ""
        )
        lines.append(
            f"| {label} | {kept}/{total} | {complete}/{coverage_total} | "
            f"{emptied}/{len(negatives)} | {statistics.mean(sizes):.1f} |"
        )
    lines += [
        "",
        "| negative question | top score | scores ≥ 0.35 | stored answer |",
        "|---|---|---|---|",
    ]
    for case in negatives:
        scores = [r["rerank_score"] for r in case["ranked"]]
        top = max(scores) if scores else 0.0
        lines.append(
            f"| {case['question'][:64]} | {top:.2f} | {sum(s >= MIN_SCORE for s in scores)} | "
            f"{(case.get('answer') or '')[:60].replace('|', '/')} |"
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------- independence


def run_independence(_args: argparse.Namespace) -> None:
    """Does a chunk's Cohere score depend on the other documents in the call?

    Every retrieval/coverage run stored on 2026-10-12 is read; a chunk is
    identified by (question, page, section) and kept only when that section is
    a single chunk in the index. Scores of the same chunk from different runs
    (different neighbours in the call) are compared.
    """
    probe = IndexProbe()
    count = Counter(
        (md.get("source"), row(md)["heading"]) for md in catalog(probe).values()
    )
    client = langfuse()
    seen: dict[tuple[str, str, str], dict[str, float]] = defaultdict(dict)
    for experiment in client.api.experiments.list(
        from_start_time=SINCE, limit=100
    ).data:
        cursor = None
        while True:
            kwargs: dict[str, Any] = {
                "from_start_time": SINCE,
                "experiment_id": experiment.id,
                "fields": "io",
                "limit": 100,
            }
            if cursor:
                kwargs["cursor"] = cursor
            response = client.api.experiments.list_items(**kwargs)
            for item in response.data:
                try:
                    output = _json(item.output)
                except ValueError:  # failed item: the error text, not JSON
                    continue
                if not isinstance(output, dict):
                    continue
                question = _json(item.input)["question"]
                for r in output.get("results", []):
                    if r.get("rerank_score") is None:
                        continue
                    if count.get((r.get("source"), r.get("heading")), 0) != 1:
                        continue
                    key = (question, r["source"], r["heading"])
                    seen[key][experiment.id] = float(r["rerank_score"])
            cursor = getattr(getattr(response, "meta", None), "cursor", None)
            if not cursor:
                break
    spreads = [
        max(runs.values()) - min(runs.values())
        for runs in seen.values()
        if len(runs) >= 2
    ]
    print(
        json.dumps(
            {
                "chunks_scored_in_2plus_runs": len(spreads),
                "identical": sum(spread < 1e-6 for spread in spreads),
                "max_difference": max(spreads, default=None),
            }
        )
    )


# ------------------------------------------------------------------ main


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    slices = sub.add_parser("slices")
    slices.add_argument(
        "--no-verify",
        dest="verify",
        action="store_false",
        help="skip checking the rebuilt production pool against search_hybrid",
    )
    slices.add_argument("--refetch", action="store_true")
    recall = sub.add_parser("recall")
    recall.add_argument("--out", required=True, help="JSON output path")
    recall.add_argument("--product-filter", action="store_true")
    sub.add_parser("screen")
    sub.add_parser("threshold")
    sub.add_parser("independence")
    summary = sub.add_parser("summary")
    summary.add_argument("--path", default=f"{REPORT_STEM}.json")
    args = parser.parse_args()
    if args.command == "slices":
        run_slices(args)
    elif args.command == "recall":
        run_recall(args)
    elif args.command == "screen":
        run_screen(args)
    elif args.command == "threshold":
        run_threshold(args)
    elif args.command == "independence":
        run_independence(args)
    else:
        data = json.loads(Path(args.path).read_text())
        print(json.dumps(summarize(data["cases"]), indent=1))


if __name__ == "__main__":
    main()
