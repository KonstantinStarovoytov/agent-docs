# Full Documentation Index Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Index all product documentation of Claude Code, Cursor, Codex and MCP (~560 pages) with automatic discovery, a quarantine gate for junk, guarded removals, a readable change report, and an eval-gated switch to a new Qdrant collection.

**Architecture:** Page selection flips from an allow-list to "everything in `llms.txt` minus excludes". The reindex gains four focused modules: concurrent fetching with failure tolerance (`loader.py`), a page gate (`gate.py`), a snapshot store for diffs (`snapshots.py`), and a change report (`report.py`); `reindex.py` only wires them. The new corpus is built in `agent_docs_hybrid_v2` beside v1 and production switches by one env var after the eval gate.

**Tech Stack:** Python 3.12, uv, httpx, qdrant-client, langchain-openai (`chat_model()`), pytest, ruff, mypy (strict on `src/`), GitHub Actions, Langfuse datasets.

**Spec:** `docs/superpowers/specs/2026-09-27-full-docs-index-design.md`

## Global Constraints

- TDD: every code step starts with a failing test; tests never touch the network, Qdrant or OpenAI.
- Before each commit: `uv run ruff format src evals tests && uv run ruff check src evals tests && uv run mypy && uv run pytest -q`.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Before opening a PR: `git fetch && git rebase origin/main`, re-run the checks, then `gh pr create`.
- Vendor documentation text is never committed to git (the repository is public). Reports hold only our summaries and links.
- One LLM everywhere: the gate and change summaries call `src.rag.llm.chat_model()` (`OPENAI_CHAT_MODEL`, today `gpt-6-luna`); never pass `temperature`.
- The user's uncommitted edits in `evals/run_answer_quality_experiment.py`, `src/prompts/managed.py`, `tests/test_answer_quality.py`, `tests/test_managed_prompts.py`, `tests/test_prompt_callsites.py` are not part of this work: never `git add -A`/`-a`; stage explicit paths.
- Thresholds (verbatim from the spec): gate size > 150 chunks or > 5× vendor median; non-Latin letters > 30%; shingle overlap ≥ 80%; removal guard > 10% of a vendor's indexed pages or listed pages < half of previous; fetch failures > 10% per vendor fail the run; significant change = section added/removed or ≥ 10% lines; ≤ 20 LLM change summaries per run; eval regression tolerance 0.03; new dataset pass hit@5 ≥ 0.9; fetch concurrency 6.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/ingestion/sources.py` (modify) | `SourceConfig` with `exclude`, `versioned_prefixes`, `allow`; the four vendor configs |
| `src/ingestion/loader.py` (modify) | Link extraction, selection rules, concurrent fetch returning `LoadResult` |
| `src/ingestion/gate.py` (create) | Heuristic flags and LLM page review → `GateVerdict` |
| `src/ingestion/snapshots.py` (create) | Qdrant payload-only store of last fetched markdown per URL |
| `src/ingestion/report.py` (create) | Section diff, significance, `ChangeReport` rendering, quarantine issue body |
| `src/reindex.py` (modify) | Manifest v2, removal guard, orchestration, CLI flags, output files |
| `.github/workflows/reindex.yml` (modify) | `collection` input, report commit, job summary, quarantine issue |
| `evals/negative_cases.py` (modify) | Re-audited unanswerable cases |
| `evals/full_corpus_cases.py`, `evals/seed_full_corpus_dataset.py` (create) | New-coverage dataset |
| `evals/run_experiments.py` (modify) | `--dataset` argument |
| `README.md` (modify) | Corpus, gate, report, rollout |

---

### Task 1: Selection by excludes

**Files:**
- Modify: `src/ingestion/sources.py`
- Modify: `src/ingestion/loader.py` (`select_links`, `newest_version`)
- Test: `tests/test_source_selection.py` (rewrite)

**Interfaces:**
- Produces: `SourceConfig(vendor, product, index_url, exclude: tuple[str, ...] = (), versioned_prefixes: tuple[str, ...] = (), allow: tuple[str, ...] = ())`; `loader.select_links(links: list[tuple[str, str]], config: SourceConfig) -> list[tuple[str, str]]` (keeps llms.txt order, de-duplicated by URL); `loader.newest_version(links, prefix) -> str` unchanged.

- [ ] **Step 1: Replace the tests with the new selection rules**

Replace the whole of `tests/test_source_selection.py`:

```python
"""Which pages a source config picks out of a vendor's llms.txt."""

from src.ingestion import loader
from src.ingestion.sources import SOURCES, SourceConfig


def _cfg(**overrides: object) -> SourceConfig:
    base: dict[str, object] = {
        "vendor": "anthropic",
        "product": "claude-code",
        "index_url": "https://x/llms.txt",
    }
    base.update(overrides)
    return SourceConfig(**base)  # type: ignore[arg-type]


def _urls(selected: list[tuple[str, str]]) -> list[str]:
    return [url for _, url in selected]


def test_only_markdown_pages_are_selected() -> None:
    links = [
        ("A", "https://x/docs/a.md"),
        ("Full", "https://x/docs/llms-full.txt"),
        ("Spec", "https://x/docs/api/openapi.yaml"),
        ("Html", "https://x/docs/api/changelog"),
        ("Broken", "https://x/es/docs/bugbot.md`"),
    ]

    assert _urls(loader.select_links(links, _cfg())) == ["https://x/docs/a.md"]


def test_query_variants_are_distinct_pages() -> None:
    links = [
        ("CLI", "https://x/docs/developer-commands.md?surface=cli"),
        ("IDE", "https://x/docs/developer-commands.md?surface=ide"),
    ]

    assert len(loader.select_links(links, _cfg())) == 2


def test_exclude_patterns_match_the_url_path() -> None:
    links = [
        ("Keep", "https://x/docs/en/hooks.md"),
        ("Lang", "https://x/docs/_llms/fr.md"),
        ("News", "https://x/docs/en/whats-new/2026-w37.md"),
    ]
    cfg = _cfg(exclude=(r"^/docs/_llms/", r"/whats-new/"))

    assert _urls(loader.select_links(links, cfg)) == ["https://x/docs/en/hooks.md"]


def test_versioned_prefix_keeps_only_the_newest_date() -> None:
    links = [
        ("old", "https://m/docs/2025-11-25/learn/a.md"),
        ("new", "https://m/docs/2026-07-28/learn/a.md"),
        ("draft", "https://m/docs/draft/learn/a.md"),
        ("spec-old", "https://m/specification/2025-06-18/basic/b.md"),
        ("spec-new", "https://m/specification/2026-07-28/basic/b.md"),
        ("plain", "https://m/registry/about.md"),
    ]
    cfg = _cfg(versioned_prefixes=("/docs/", "/specification/"))

    assert _urls(loader.select_links(links, cfg)) == [
        "https://m/docs/2026-07-28/learn/a.md",
        "https://m/specification/2026-07-28/basic/b.md",
        "https://m/registry/about.md",
    ]


def test_duplicate_links_are_selected_once() -> None:
    links = [("A", "https://x/docs/a.md"), ("A again", "https://x/docs/a.md")]

    assert len(loader.select_links(links, _cfg())) == 1


def test_vendor_configs_exclude_known_junk() -> None:
    by_product = {c.product: c for c in SOURCES}
    cases = {
        "claude-code": [
            "https://code.claude.com/docs/_llms/fr.md",
            "https://code.claude.com/docs/en/whats-new/2026-w37.md",
            "https://code.claude.com/docs/en/changelog.md",
        ],
        "cursor": [
            "https://cursor.com/help/account-and-billing/refunds.md",
            "https://cursor.com/ja/docs/bugbot.md",
            "https://cursor.com/changelog.md",
        ],
        "codex": ["https://learn.chatgpt.com/docs/codex-manual.md"],
        "mcp": [
            "https://modelcontextprotocol.io/community/working-groups/auth.md",
            "https://modelcontextprotocol.io/seps/990-enable.md",
        ],
    }
    for product, urls in cases.items():
        links = [("t", u) for u in urls]
        assert loader.select_links(links, by_product[product]) == [], product


def test_vendor_configs_keep_real_docs() -> None:
    by_product = {c.product: c for c in SOURCES}
    keep = {
        "claude-code": "https://code.claude.com/docs/en/plugins/create.md",
        "cursor": "https://cursor.com/docs/rules.md",
        "codex": "https://learn.chatgpt.com/docs/hooks.md",
        "mcp": "https://modelcontextprotocol.io/registry/about.md",
    }
    for product, url in keep.items():
        assert _urls(loader.select_links([("t", url)], by_product[product])) == [url]
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `uv run pytest tests/test_source_selection.py -q`
Expected: FAIL — `TypeError: SourceConfig.__init__() got an unexpected keyword argument 'exclude'`.

- [ ] **Step 3: Rewrite `src/ingestion/sources.py`**

```python
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SourceConfig:
    vendor: str
    product: str
    index_url: str
    # Regexes searched in the URL path; a match drops the page. Everything
    # else a vendor lists in llms.txt is indexed, so new pages arrive on
    # their own and junk is kept out here or by the page gate.
    exclude: tuple[str, ...] = ()
    # Prefixes whose pages live under `<prefix>YYYY-MM-DD/`: only the newest
    # dated version is kept; `draft` and older dates are dropped.
    versioned_prefixes: tuple[str, ...] = ()
    # Exact URLs indexed even when the page gate flags them (owner decision).
    allow: tuple[str, ...] = ()


ANTHROPIC = SourceConfig(
    vendor="anthropic",
    product="claude-code",
    index_url="https://code.claude.com/docs/llms.txt",
    exclude=(
        r"^/docs/_llms/",  # localized llms.txt indexes, not documentation
        r"/whats-new/",  # weekly notes restating the main pages
        r"/changelog\.md$",  # huge and rewritten daily
    ),
)


CURSOR = SourceConfig(
    vendor="cursor",
    product="cursor",
    index_url="https://cursor.com/llms.txt",
    exclude=(
        r"^/help/",  # help center: billing and account, out of scope
        r"^/[a-z]{2}(-[a-z]{2,4})?/",  # translations: /es/, /ja/, /cn/ ...
        r"changelog",
    ),
)


OPENAI_CODEX = SourceConfig(
    vendor="openai",
    product="codex",
    index_url="https://developers.openai.com/codex/llms.txt",
    exclude=(
        r"/codex-manual\.md$",  # concatenation of every other page
    ),
)


MCP = SourceConfig(
    vendor="model-context-protocol",
    product="mcp",
    index_url="https://modelcontextprotocol.io/llms.txt",
    versioned_prefixes=("/docs/", "/specification/"),
    exclude=(
        r"^/community/",  # working and interest groups
        r"^/seps/",  # proposals; accepted ones are merged into the spec
    ),
)


SOURCES = (
    ANTHROPIC,
    CURSOR,
    OPENAI_CODEX,
    MCP,
)
```

- [ ] **Step 4: Rewrite `select_links` and drop the allow-list error**

In `src/ingestion/loader.py` replace `newest_version`, `select_links` and the `SourceSelectionError` class with:

```python
from urllib.parse import urlsplit

DATED_SEGMENT = r"(\d{4}-\d{2}-\d{2}|draft)/"


def newest_version(links: list[tuple[str, str]], prefix: str) -> str | None:
    """Newest `<prefix>YYYY-MM-DD/` segment present in the index, if any."""
    dated = re.compile(re.escape(prefix) + r"(\d{4}-\d{2}-\d{2})/")
    versions = {m.group(1) for _, url in links if (m := dated.search(url))}
    return max(versions) if versions else None


def _is_page(url: str) -> bool:
    return urlsplit(url).path.endswith(".md")


def _stale_version(path: str, config: SourceConfig, newest: dict[str, str | None]) -> bool:
    for prefix in config.versioned_prefixes:
        m = re.match(re.escape(prefix) + DATED_SEGMENT, path)
        if m:
            return m.group(1) != newest[prefix]
    return False


def select_links(
    links: list[tuple[str, str]], config: SourceConfig
) -> list[tuple[str, str]]:
    """Every markdown page in llms.txt order, minus excludes and stale versions."""
    newest = {p: newest_version(links, p) for p in config.versioned_prefixes}
    excludes = [re.compile(p) for p in config.exclude]
    selected: dict[str, str] = {}
    for title, url in links:
        if url in selected or not _is_page(url):
            continue
        path = urlsplit(url).path
        if any(p.search(path) for p in excludes):
            continue
        if _stale_version(path, config, newest):
            continue
        selected[url] = title
    return [(title, url) for url, title in selected.items()]
```

Keep `urlsplit` imported once at the top (it already is). Then find leftovers:

Run: `grep -rn "SourceSelectionError\|versioned_prefix\b\|\.include\b" src tests evals`
Expected: no hits except inside this task's files; delete any stale reference.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_source_selection.py -q`
Expected: 7 passed.

- [ ] **Step 6: Check the live selection counts (network, manual)**

```bash
uv run python - <<'EOF'
import httpx
from src.ingestion.sources import SOURCES
from src.ingestion.loader import select_links, _extract_links
for c in SOURCES:
    links = _extract_links(httpx.get(c.index_url, follow_redirects=True).text)
    print(c.product, len(select_links(links, c)))
EOF
```

Expected (±5, vendors change daily): claude-code ~183, cursor ~152, codex ~150, mcp ~76.

- [ ] **Step 7: Run all checks and commit**

```bash
uv run ruff format src evals tests && uv run ruff check src evals tests && uv run mypy && uv run pytest -q
git add src/ingestion/sources.py src/ingestion/loader.py tests/test_source_selection.py
git commit -m "feat(ingestion): select every doc page except excludes

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Concurrent fetch with failure tolerance

**Files:**
- Modify: `src/ingestion/loader.py` (`load_source`, `load_all_sources`)
- Test: `tests/test_loader_fetch.py` (create)

**Interfaces:**
- Consumes: `select_links`, `SourceConfig` (Task 1).
- Produces:
  ```python
  @dataclass(frozen=True, slots=True)
  class LoadResult:
      documents: list[SourceDocument]
      failures: dict[str, str]          # url -> reason
      listed: dict[str, int]            # product -> pages selected from llms.txt
      failed_products: dict[str, str]   # failed url -> product
  def load_all_sources(fetch: Callable[[str], tuple[int, str]] | None = None) -> LoadResult
  ```
  `fetch(url) -> (status_code, text)`; default uses httpx with 6 concurrent requests.

- [ ] **Step 1: Write the failing test**

```python
"""Fetching tolerates single-page failures and reports them."""

from src.ingestion import loader
from src.ingestion.sources import SourceConfig

CFG = SourceConfig(vendor="v", product="p", index_url="https://x/llms.txt")


def test_failed_pages_are_reported_not_fatal() -> None:
    pages = {
        "https://x/llms.txt": (200, "[A](https://x/a.md)\n[B](https://x/b.md)"),
        "https://x/a.md": (200, "# A\nbody"),
        "https://x/b.md": (404, ""),
    }

    result = loader.load_sources((CFG,), fetch=lambda url: pages[url])

    assert [d.url for d in result.documents] == ["https://x/a.md"]
    assert result.failures == {"https://x/b.md": "HTTP 404"}
    assert result.listed == {"p": 2}
    assert result.failed_products == {"https://x/b.md": "p"}


def test_unreachable_index_raises() -> None:
    import pytest

    with pytest.raises(RuntimeError, match="llms.txt"):
        loader.load_sources((CFG,), fetch=lambda url: (503, ""))
```

- [ ] **Step 2: Run and see it fail**

Run: `uv run pytest tests/test_loader_fetch.py -q`
Expected: FAIL — `AttributeError: module 'src.ingestion.loader' has no attribute 'load_sources'`.

- [ ] **Step 3: Implement**

Replace `load_source` and `load_all_sources` in `src/ingestion/loader.py`:

```python
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

FETCH_CONCURRENCY = 6
Fetch = Callable[[str], tuple[int, str]]


@dataclass(frozen=True, slots=True)
class LoadResult:
    documents: list[SourceDocument]
    failures: dict[str, str]
    listed: dict[str, int]
    failed_products: dict[str, str]


def _http_fetch() -> Fetch:
    client = httpx.Client(timeout=30, follow_redirects=True)

    def fetch(url: str) -> tuple[int, str]:
        try:
            response = client.get(url)
        except httpx.HTTPError as error:
            return 0, type(error).__name__
        return response.status_code, response.text

    return fetch


def load_sources(configs: Sequence[SourceConfig], fetch: Fetch) -> LoadResult:
    documents: list[SourceDocument] = []
    failures: dict[str, str] = {}
    failed_products: dict[str, str] = {}
    listed: dict[str, int] = {}
    for config in configs:
        status, index = fetch(config.index_url)
        if status != 200:
            raise RuntimeError(f"{config.index_url}: llms.txt answered {status}")
        links = select_links(_extract_links(index), config)
        listed[config.product] = len(links)
        print(f"{config.vendor}/{config.product}: {len(links)} pages")
        with ThreadPoolExecutor(FETCH_CONCURRENCY) as pool:
            responses = list(pool.map(lambda link: fetch(link[1]), links))
        for (title, url), (status, text) in zip(links, responses, strict=True):
            if status != 200:
                failures[url] = f"HTTP {status}" if status else text
                failed_products[url] = config.product
                continue
            documents.append(
                SourceDocument(
                    title=title,
                    content=text,
                    url=url,
                    vendor=config.vendor,
                    product=config.product,
                )
            )
    return LoadResult(
        documents=documents,
        failures=failures,
        listed=listed,
        failed_products=failed_products,
    )


def load_all_sources(fetch: Fetch | None = None) -> LoadResult:
    return load_sources(SOURCES, fetch or _http_fetch())
```

`reindex.main` still calls `load_all_sources()` and expects a list; Task 7 rewires it. Until then keep the build green by changing the one call site in `src/reindex.py`:

```python
    documents = load_all_sources().documents
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_loader_fetch.py tests/test_reindex.py -q`
Expected: all pass.

- [ ] **Step 5: Checks and commit**

```bash
uv run ruff format src evals tests && uv run ruff check src evals tests && uv run mypy && uv run pytest -q
git add src/ingestion/loader.py src/reindex.py tests/test_loader_fetch.py
git commit -m "feat(ingestion): fetch pages concurrently and report failures

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Manifest v2 and per-collection path

**Files:**
- Modify: `src/reindex.py` (`ManifestEntry`, `load_manifest`, `save_manifest`, `diff`, `MANIFEST_PATH`)
- Move: `data/index-manifest.json` → `data/manifests/agent_docs_hybrid_v1.json`
- Test: `tests/test_reindex.py` (add tests)

**Interfaces:**
- Produces:
  ```python
  @dataclass(frozen=True, slots=True)
  class ManifestEntry:
      sha256: str
      chunks: int
      title: str
      status: Literal["indexed", "quarantined"] = "indexed"
      reason: str = ""
      summary: str = ""
  def manifest_path(collection: str) -> Path   # data/manifests/<collection>.json
  ```
  `diff` rule: a quarantined entry with the same sha is `unchanged`; with a different sha it is `added` (re-gated).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_reindex.py`)

```python
def test_manifest_path_follows_the_collection() -> None:
    assert str(reindex.manifest_path("agent_docs_hybrid_v2")) == (
        "data/manifests/agent_docs_hybrid_v2.json"
    )


def test_old_manifest_entries_load_as_indexed(tmp_path: Any) -> None:
    path = tmp_path / "m.json"
    path.write_text(
        '{"indexed_at": "2026-09-01", "documents": '
        '{"u": {"sha256": "s", "chunks": 1, "title": "T"}}}'
    )

    entry = reindex.load_manifest(path).documents["u"]

    assert entry.status == "indexed" and entry.reason == "" and entry.summary == ""


def test_quarantined_page_is_regated_only_when_content_changes() -> None:
    q = reindex.ManifestEntry(
        sha256=reindex.fingerprint("same"), chunks=0, title="T",
        status="quarantined", reason="size", summary="s",
    )
    manifest = reindex.Manifest(indexed_at=None, documents={"u/q": q})

    same = reindex.diff(manifest, [_doc("u/q", "same")])
    edited = reindex.diff(manifest, [_doc("u/q", "edited")])

    assert same.unchanged == ["u/q"] and not same.added
    assert [d.url for d in edited.added] == ["u/q"]
```

- [ ] **Step 2: Run and see them fail**

Run: `uv run pytest tests/test_reindex.py -q`
Expected: FAIL — `AttributeError: ... 'manifest_path'` and `TypeError` on `status=`.

- [ ] **Step 3: Implement**

In `src/reindex.py`:

```python
from typing import Any, Literal

MANIFEST_DIR = Path("data/manifests")


def manifest_path(collection: str) -> Path:
    return MANIFEST_DIR / f"{collection}.json"


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    sha256: str
    chunks: int
    title: str
    status: Literal["indexed", "quarantined"] = "indexed"
    reason: str = ""
    summary: str = ""
```

Change `load_manifest(path: Path)` and `save_manifest(manifest, path: Path)` to require `path` (remove the `MANIFEST_PATH` default and constant). In `diff`, before the sha comparison:

```python
        elif entry.status == "quarantined" and entry.sha256 == fingerprint(document.content):
            unchanged.append(document.url)
        elif entry.status == "quarantined":
            added.append(document)
```

(ordered after `if entry is None` and before the generic changed/unchanged branches). In `main`, use `path = manifest_path(settings.qdrant_hybrid_collection)` for both load and save. Then move the file:

```bash
mkdir -p data/manifests && git mv data/index-manifest.json data/manifests/agent_docs_hybrid_v1.json
```

Update the existing `test_manifest_round_trips_through_json` call sites to pass `tmp_path / "m.json"` explicitly if they relied on the default.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_reindex.py -q`
Expected: all pass.

- [ ] **Step 5: Checks and commit**

```bash
uv run ruff format src evals tests && uv run ruff check src evals tests && uv run mypy && uv run pytest -q
git add src/reindex.py tests/test_reindex.py data/manifests/agent_docs_hybrid_v1.json data/index-manifest.json
git commit -m "feat(reindex): manifest per collection with quarantine status

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Removal guard and fetch-failure policy

**Files:**
- Modify: `src/reindex.py`
- Test: `tests/test_reindex.py`

**Interfaces:**
- Consumes: `Manifest`, `LoadResult` (Task 2), `SourceDocument.product`.
- Produces:
  ```python
  @dataclass(frozen=True, slots=True)
  class RemovalDecision:
      delete: list[str]               # urls safe to delete
      blocked: dict[str, str]         # product -> reason
  def decide_removals(manifest: Manifest, missing: list[str], load: LoadResult, product_of: dict[str, str]) -> RemovalDecision
  def failing_vendors(load: LoadResult) -> dict[str, str]   # product -> reason, when > 10% failed
  ```
  `product_of` maps manifest URLs to products (built from chunk metadata in Task 7; tests pass it directly). URLs that failed to fetch are never "missing".

- [ ] **Step 1: Write the failing tests**

```python
def _load(listed: dict[str, int], failures: dict[str, str] | None = None) -> Any:
    from src.ingestion.loader import LoadResult

    failures = failures or {}
    return LoadResult(
        documents=[], failures=failures, listed=listed,
        failed_products={u: "p" for u in failures},
    )


def _manifest(n: int, product: str = "p") -> tuple[reindex.Manifest, dict[str, str]]:
    docs = {f"u{i}": reindex.ManifestEntry(sha256="s", chunks=1, title="T") for i in range(n)}
    return reindex.Manifest(indexed_at=None, documents=docs), {u: product for u in docs}


def test_small_removals_are_applied() -> None:
    manifest, product_of = _manifest(20)

    decision = reindex.decide_removals(manifest, ["u0", "u1"], _load({"p": 18}), product_of)

    assert decision.delete == ["u0", "u1"] and decision.blocked == {}


def test_removing_more_than_ten_percent_is_blocked() -> None:
    manifest, product_of = _manifest(20)

    decision = reindex.decide_removals(
        manifest, ["u0", "u1", "u2"], _load({"p": 17}), product_of
    )

    assert decision.delete == []
    assert "3 of 20" in decision.blocked["p"]


def test_shrunken_index_blocks_removals() -> None:
    manifest, product_of = _manifest(20)

    decision = reindex.decide_removals(manifest, ["u0"], _load({"p": 9}), product_of)

    assert decision.delete == [] and "llms.txt" in decision.blocked["p"]


def test_failed_fetches_are_not_missing() -> None:
    manifest, product_of = _manifest(20)

    decision = reindex.decide_removals(
        manifest, ["u0"], _load({"p": 20}, {"u0": "HTTP 500"}), product_of
    )

    assert decision.delete == []


def test_vendor_with_many_fetch_failures_fails_the_run() -> None:
    load = _load({"p": 10}, {f"u{i}": "HTTP 500" for i in range(2)})

    assert "2 of 10" in reindex.failing_vendors(load)["p"]
```

- [ ] **Step 2: Run and see them fail**

Run: `uv run pytest tests/test_reindex.py -q -k "removal or missing or fetch"`
Expected: FAIL — `AttributeError: ... 'decide_removals'`.

- [ ] **Step 3: Implement**

```python
REMOVAL_GUARD = 0.10
SHRINK_GUARD = 0.5
FETCH_FAILURE_GUARD = 0.10


@dataclass(frozen=True, slots=True)
class RemovalDecision:
    delete: list[str]
    blocked: dict[str, str]


def decide_removals(
    manifest: Manifest,
    missing: list[str],
    load: LoadResult,
    product_of: dict[str, str],
) -> RemovalDecision:
    """Delete vanished pages, unless a vendor's index looks broken."""
    gone = [u for u in missing if u not in load.failures]
    indexed: dict[str, int] = {}
    for url, entry in manifest.documents.items():
        if entry.status == "indexed":
            product = product_of.get(url, "")
            indexed[product] = indexed.get(product, 0) + 1
    by_product: dict[str, list[str]] = {}
    for url in gone:
        by_product.setdefault(product_of.get(url, ""), []).append(url)
    delete: list[str] = []
    blocked: dict[str, str] = {}
    for product, urls in by_product.items():
        before = indexed.get(product, 0)
        listed = load.listed.get(product, 0)
        if before and listed < before * SHRINK_GUARD:
            blocked[product] = f"llms.txt lists {listed} pages, was {before}"
        elif before and len(urls) > before * REMOVAL_GUARD:
            blocked[product] = f"{len(urls)} of {before} pages would be removed"
        else:
            delete.extend(urls)
    return RemovalDecision(delete=sorted(delete), blocked=blocked)


def failing_vendors(load: LoadResult) -> dict[str, str]:
    failed: dict[str, int] = {}
    for product in load.failed_products.values():
        failed[product] = failed.get(product, 0) + 1
    return {
        product: f"{n} of {load.listed[product]} pages failed to fetch"
        for product, n in failed.items()
        if n > load.listed.get(product, 0) * FETCH_FAILURE_GUARD
    }
```

Import `LoadResult` from `src.ingestion.loader`.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_reindex.py tests/test_loader_fetch.py -q`
Expected: all pass.

- [ ] **Step 5: Checks and commit**

```bash
uv run ruff format src evals tests && uv run ruff check src evals tests && uv run mypy && uv run pytest -q
git add src/reindex.py src/ingestion/loader.py tests/test_reindex.py tests/test_loader_fetch.py
git commit -m "feat(reindex): guarded automatic removals and fetch-failure limits

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Page gate

**Files:**
- Create: `src/ingestion/gate.py`
- Test: `tests/test_gate.py`

**Interfaces:**
- Consumes: `SourceDocument`, `chunk_document`, `src.rag.llm.chat_model`.
- Produces:
  ```python
  class PageReview(BaseModel):          # structured LLM output
      keep: bool
      category: Literal["documentation", "reference", "changelog", "marketing",
                        "legal", "community", "translation", "duplicate", "other"]
      summary: str                      # one plain sentence: what the page is
  @dataclass(frozen=True, slots=True)
  class GateVerdict:
      keep: bool
      reasons: list[str]                # empty when keep
      summary: str
  def heuristic_flags(document: SourceDocument, chunks: int, vendor_median: float,
                      indexed_texts: dict[str, str]) -> list[str]
  def review_page(document: SourceDocument, review: Callable[[str], PageReview] | None = None) -> PageReview
  def gate_page(document, chunks, vendor_median, indexed_texts, review=None) -> GateVerdict
  ```

- [ ] **Step 1: Write the failing tests**

```python
"""The page gate flags junk before it reaches the index."""

from src.ingestion import gate
from src.models import SourceDocument


def _doc(url: str, content: str = "# Title\nplain english documentation text") -> SourceDocument:
    return SourceDocument(title="T", content=content, url=url, vendor="v", product="p")


def _keep(_: str) -> gate.PageReview:
    return gate.PageReview(keep=True, category="documentation", summary="How to use X.")


def test_clean_page_is_kept_with_a_summary() -> None:
    verdict = gate.gate_page(_doc("https://x/docs/a.md"), 10, 10.0, {}, review=_keep)

    assert verdict.keep and verdict.reasons == [] and verdict.summary == "How to use X."


def test_oversized_page_is_flagged() -> None:
    assert gate.heuristic_flags(_doc("https://x/a.md"), 151, 10.0, {}) == [
        "possible concatenation: 151 chunks"
    ]
    assert gate.heuristic_flags(_doc("https://x/a.md"), 60, 10.0, {}) == [
        "possible concatenation: 60 chunks"
    ]


def test_translation_is_flagged_by_path_or_script() -> None:
    assert "translation" in gate.heuristic_flags(_doc("https://x/ja/docs/a.md"), 1, 10.0, {})[0]
    cyr = _doc("https://x/docs/a.md", "# Заголовок\nтекст документации на русском")
    assert "translation" in gate.heuristic_flags(cyr, 1, 10.0, {})[0]
    assert gate.heuristic_flags(_doc("https://x/docs/en/a.md"), 1, 10.0, {}) == []


def test_duplicate_of_an_indexed_page_is_flagged() -> None:
    text = " ".join(f"word{i}" for i in range(200))
    flags = gate.heuristic_flags(_doc("https://x/b.md", text), 1, 10.0, {"https://x/a.md": text})

    assert flags == ["duplicate of https://x/a.md"]


def test_non_doc_path_keywords_are_flagged() -> None:
    for path in ("release-notes.md", "blog/post.md", "terms.md", "llms-full.md"):
        assert gate.heuristic_flags(_doc(f"https://x/{path}"), 1, 10.0, {}), path


def test_model_quarantine_is_respected_and_reasons_combine() -> None:
    def junk(_: str) -> gate.PageReview:
        return gate.PageReview(keep=False, category="marketing", summary="A launch post.")

    verdict = gate.gate_page(_doc("https://x/blog/launch.md"), 1, 10.0, {}, review=junk)

    assert not verdict.keep
    assert verdict.reasons == ["probably not documentation: blog", "model: marketing"]
    assert verdict.summary == "A launch post."


def test_review_prompt_contains_path_title_and_head_only() -> None:
    seen: list[str] = []

    def capture(prompt: str) -> gate.PageReview:
        seen.append(prompt)
        return gate.PageReview(keep=True, category="documentation", summary="s")

    gate.review_page(_doc("https://x/docs/a.md", "# T\n" + "x" * 5000), review=capture)

    assert "https://x/docs/a.md" in seen[0] and len(seen[0]) < 2500
```

- [ ] **Step 2: Run and see them fail**

Run: `uv run pytest tests/test_gate.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.ingestion.gate'`.

- [ ] **Step 3: Implement `src/ingestion/gate.py`**

```python
"""Decide whether a newly discovered page belongs in the index.

Runs only on pages the manifest has never seen, so it costs one short LLM
call per new page. Any flag, from the free checks or the model, sends the
page to quarantine for the owner to decide.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from src.models import SourceDocument

MAX_CHUNKS = 150
MEDIAN_FACTOR = 5
NON_LATIN_SHARE = 0.30
DUPLICATE_OVERLAP = 0.80
SHINGLE = 5
HEAD_CHARS = 1500
LOCALES = {
    "cn", "de", "es", "fr", "id", "it", "ja", "jp", "ko", "nl", "pl", "pt",
    "pt-br", "ru", "tr", "uk", "vi", "zh", "zh-cn", "zh-tw",
}
NON_DOC = re.compile(
    r"(changelog|release-notes|llms|(?<![a-z])full(?![a-z])|blog|terms|privacy|proposal)"
)

PROMPT = """You review one page found in a software vendor's documentation index.
Decide whether it is product documentation a coding agent would use to answer
how-to, configuration or reference questions. Quarantine changelogs, release
notes, marketing, legal text, community governance, translations and pages
that merely aggregate other pages.

Write `summary` as one short plain sentence saying what the page is, for a
human deciding whether to keep it.

URL: {url}
Title: {title}
Beginning of the page:
{head}"""


class PageReview(BaseModel):
    keep: bool
    category: Literal[
        "documentation", "reference", "changelog", "marketing", "legal",
        "community", "translation", "duplicate", "other",
    ]
    summary: str = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class GateVerdict:
    keep: bool
    reasons: list[str]
    summary: str


def _shingles(text: str) -> set[tuple[str, ...]]:
    words = text.lower().split()
    return {tuple(words[i : i + SHINGLE]) for i in range(len(words) - SHINGLE + 1)}


def heuristic_flags(
    document: SourceDocument,
    chunks: int,
    vendor_median: float,
    indexed_texts: dict[str, str],
) -> list[str]:
    path = urlsplit(document.url).path
    flags: list[str] = []
    if chunks > MAX_CHUNKS or chunks > MEDIAN_FACTOR * vendor_median:
        flags.append(f"possible concatenation: {chunks} chunks")
    segments = [s for s in path.lower().split("/") if s]
    letters = [c for c in document.content if c.isalpha()]
    non_latin = sum(1 for c in letters if not c.isascii())
    if any(s in LOCALES for s in segments) or (
        letters and non_latin / len(letters) > NON_LATIN_SHARE
    ):
        flags.append("translation")
    if m := NON_DOC.search(path.lower()):
        flags.append(f"probably not documentation: {m.group(1)}")
    mine = _shingles(document.content)
    if mine:
        for url, text in indexed_texts.items():
            theirs = _shingles(text)
            if theirs and len(mine & theirs) / len(mine | theirs) >= DUPLICATE_OVERLAP:
                flags.append(f"duplicate of {url}")
                break
    return flags


def _model_review(prompt: str) -> PageReview:
    from src.rag.llm import chat_model

    result = chat_model().with_structured_output(PageReview).invoke(prompt)
    return result if isinstance(result, PageReview) else PageReview.model_validate(result)


def review_page(
    document: SourceDocument, review: Callable[[str], PageReview] | None = None
) -> PageReview:
    prompt = PROMPT.format(
        url=document.url, title=document.title, head=document.content[:HEAD_CHARS]
    )
    return (review or _model_review)(prompt)


def gate_page(
    document: SourceDocument,
    chunks: int,
    vendor_median: float,
    indexed_texts: dict[str, str],
    review: Callable[[str], PageReview] | None = None,
) -> GateVerdict:
    flags = heuristic_flags(document, chunks, vendor_median, indexed_texts)
    verdict = review_page(document, review)
    if not verdict.keep:
        flags.append(f"model: {verdict.category}")
    return GateVerdict(keep=not flags, reasons=flags, summary=verdict.summary)
```

Note `test_oversized_page_is_flagged` second case: 60 > 5 × 10 → flagged.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_gate.py -q`
Expected: 7 passed.

- [ ] **Step 5: Checks and commit**

```bash
uv run ruff format src evals tests && uv run ruff check src evals tests && uv run mypy && uv run pytest -q
git add src/ingestion/gate.py tests/test_gate.py
git commit -m "feat(ingestion): quarantine gate for newly discovered pages

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Snapshot store and change report

**Files:**
- Create: `src/ingestion/snapshots.py`
- Create: `src/ingestion/report.py`
- Test: `tests/test_report.py`, `tests/test_snapshots.py`

**Interfaces:**
- Produces (snapshots):
  ```python
  def snapshot_collection(collection: str) -> str          # f"{collection}_pages"
  class SnapshotStore:
      def __init__(self, client: QdrantClient, collection: str) -> None
      def get(self, url: str) -> str | None
      def put(self, document: SourceDocument, sha256: str) -> None
      def delete(self, url: str) -> None
      def all_texts(self) -> dict[str, str]
  ```
- Produces (report):
  ```python
  @dataclass(frozen=True, slots=True)
  class SectionDiff:
      added: list[str]; removed: list[str]; changed_lines: int; total_lines: int
      @property
      def significant(self) -> bool     # added or removed or changed_lines >= 10% of total
  def section_diff(old: str, new: str) -> SectionDiff
  @dataclass
  class PageLine: url: str; title: str; product: str; summary: str = ""
  @dataclass
  class ChangedLine(PageLine): diff: SectionDiff | None = None
  @dataclass
  class QuarantineLine(PageLine): reasons: list[str] = field(default_factory=list)
  @dataclass
  class ChangeReport:
      day: str; added: list[PageLine]; removed: list[str]; changed: list[ChangedLine]
      quarantined: list[QuarantineLine]; fetch_failures: dict[str, str]
      blocked: dict[str, str]; initial_build: bool = False
      def empty(self) -> bool
  def render_report(report: ChangeReport) -> str
  def render_quarantine_issue(lines: list[QuarantineLine]) -> str
  def summarize_change(title: str, old: str, new: str, summarize: Callable[[str], str] | None = None) -> str
  MAX_CHANGE_SUMMARIES = 20
  ```

- [ ] **Step 1: Write the failing report tests** (`tests/test_report.py`)

```python
"""Readable change reports and section-level diffs."""

from src.ingestion import report


def test_section_diff_finds_added_and_removed_headings() -> None:
    old = "# Hooks\n## Setup\ntext\n## Old part\nx\n"
    new = "# Hooks\n## Setup\ntext\n## PermissionRequest hook\ny\n"

    d = report.section_diff(old, new)

    assert d.added == ["PermissionRequest hook"] and d.removed == ["Old part"]
    assert d.significant


def test_small_edit_is_minor() -> None:
    old = "# A\n" + "\n".join(f"line {i}" for i in range(50))
    new = old.replace("line 7", "line seven")

    d = report.section_diff(old, new)

    assert d.added == [] and d.removed == [] and not d.significant


def test_report_lists_every_kind_of_change() -> None:
    r = report.ChangeReport(
        day="2026-09-28",
        added=[report.PageLine("https://x/new.md", "New", "claude-code", "How to X.")],
        removed=["https://x/gone.md"],
        changed=[
            report.ChangedLine("https://x/big.md", "Big", "cursor", "Adds a hook.",
                               report.SectionDiff(["S"], [], 12, 40)),
            report.ChangedLine("https://x/tiny.md", "Tiny", "cursor", "",
                               report.SectionDiff([], [], 1, 40)),
        ],
        quarantined=[report.QuarantineLine("https://x/blog.md", "Blog", "mcp",
                                           "A launch post.", ["model: marketing"])],
        fetch_failures={"https://x/err.md": "HTTP 500"},
        blocked={},
    )

    text = report.render_report(r)

    assert "Added (1)" in text and "How to X." in text and "https://x/new.md" in text
    assert "Removed (1)" in text and "Changed significantly (1)" in text
    assert "+ S" in text and "Adds a hook." in text
    assert "Minor edits: 1 page" in text
    assert "Quarantined (1)" in text and "A launch post." in text
    assert "HTTP 500" in text


def test_initial_build_reports_totals_only() -> None:
    r = report.ChangeReport(
        day="d", added=[report.PageLine(f"u{i}", "t", "p") for i in range(3)],
        removed=[], changed=[], quarantined=[], fetch_failures={}, blocked={},
        initial_build=True,
    )

    text = report.render_report(r)

    assert "Initial build: 3 pages" in text and "u0" not in text


def test_quarantine_issue_is_short_and_actionable() -> None:
    body = report.render_quarantine_issue(
        [report.QuarantineLine("https://x/blog.md", "Blog", "mcp", "A launch post.",
                               ["model: marketing"])]
    )

    assert "https://x/blog.md" in body and "A launch post." in body
    assert "model: marketing" in body
    assert "exclude" in body and "allow" in body


def test_change_summaries_use_the_injected_model() -> None:
    seen: list[str] = []

    def fake(prompt: str) -> str:
        seen.append(prompt)
        return "Adds a hook."

    assert report.summarize_change("Hooks", "a\n", "b\n", summarize=fake) == "Adds a hook."
    assert "-a" in seen[0] and "+b" in seen[0]
```

- [ ] **Step 2: Write the failing snapshot test** (`tests/test_snapshots.py`)

```python
"""The snapshot store keeps the last fetched markdown per page."""

from qdrant_client import QdrantClient

from src.ingestion.snapshots import SnapshotStore, snapshot_collection
from src.models import SourceDocument


def test_put_get_delete_round_trip() -> None:
    store = SnapshotStore(QdrantClient(":memory:"), "c_pages")
    doc = SourceDocument(title="T", content="# A\nbody", url="https://x/a.md",
                         vendor="v", product="p")

    store.put(doc, "sha")

    assert store.get("https://x/a.md") == "# A\nbody"
    assert store.all_texts() == {"https://x/a.md": "# A\nbody"}
    store.delete("https://x/a.md")
    assert store.get("https://x/a.md") is None


def test_collection_name_follows_the_index() -> None:
    assert snapshot_collection("agent_docs_hybrid_v2") == "agent_docs_hybrid_v2_pages"
```

- [ ] **Step 3: Run and see both fail**

Run: `uv run pytest tests/test_report.py tests/test_snapshots.py -q`
Expected: FAIL — `ModuleNotFoundError` for both modules.

- [ ] **Step 4: Implement `src/ingestion/snapshots.py`**

```python
"""Last fetched markdown per page, kept in Qdrant rather than git.

The repository is public and the documentation belongs to the vendors, so
the previous text needed for a readable diff lives in the private cluster.
"""

import uuid
from datetime import UTC, datetime

from qdrant_client import QdrantClient, models

from src.models import SourceDocument


def snapshot_collection(collection: str) -> str:
    return f"{collection}_pages"


def _point_id(url: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, url))


class SnapshotStore:
    def __init__(self, client: QdrantClient, collection: str) -> None:
        self.client = client
        self.collection = collection
        if not client.collection_exists(collection):
            # Payload-only in spirit; Qdrant still wants a vector per point.
            client.create_collection(
                collection,
                vectors_config=models.VectorParams(size=1, distance=models.Distance.DOT),
            )

    def get(self, url: str) -> str | None:
        points = self.client.retrieve(self.collection, [_point_id(url)], with_payload=True)
        return str(points[0].payload["markdown"]) if points and points[0].payload else None

    def put(self, document: SourceDocument, sha256: str) -> None:
        self.client.upsert(
            self.collection,
            points=[
                models.PointStruct(
                    id=_point_id(document.url),
                    vector=[0.0],
                    payload={
                        "url": document.url,
                        "markdown": document.content,
                        "sha256": sha256,
                        "title": document.title,
                        "product": document.product,
                        "fetched_at": datetime.now(UTC).isoformat(),
                    },
                )
            ],
        )

    def delete(self, url: str) -> None:
        self.client.delete(self.collection, points_selector=models.PointIdsList(points=[_point_id(url)]))

    def all_texts(self) -> dict[str, str]:
        texts: dict[str, str] = {}
        offset = None
        while True:
            points, offset = self.client.scroll(
                self.collection, limit=256, offset=offset, with_payload=["url", "markdown"]
            )
            for p in points:
                if p.payload:
                    texts[str(p.payload["url"])] = str(p.payload["markdown"])
            if offset is None:
                return texts
```

- [ ] **Step 5: Implement `src/ingestion/report.py`**

```python
"""A readable account of what changed in the vendors' documentation."""

import difflib
import re
from collections.abc import Callable
from dataclasses import dataclass, field

SIGNIFICANT_SHARE = 0.10
MAX_CHANGE_SUMMARIES = 20
DIFF_CHARS = 6000
HEADING = re.compile(r"^#{1,3}\s+(.+?)\s*$", re.MULTILINE)

CHANGE_PROMPT = """Here is a diff of one documentation page, "{title}".
In one short plain sentence, say what changed for a reader of this product.

{diff}"""


@dataclass(frozen=True, slots=True)
class SectionDiff:
    added: list[str]
    removed: list[str]
    changed_lines: int
    total_lines: int

    @property
    def significant(self) -> bool:
        return bool(
            self.added
            or self.removed
            or self.changed_lines >= SIGNIFICANT_SHARE * max(self.total_lines, 1)
        )


def section_diff(old: str, new: str) -> SectionDiff:
    before, after = HEADING.findall(old), HEADING.findall(new)
    old_lines, new_lines = old.splitlines(), new.splitlines()
    changed = sum(
        1
        for line in difflib.ndiff(old_lines, new_lines)
        if line.startswith(("+ ", "- "))
    )
    return SectionDiff(
        added=[h for h in after if h not in before],
        removed=[h for h in before if h not in after],
        changed_lines=changed,
        total_lines=max(len(old_lines), len(new_lines)),
    )


def _model_summary(prompt: str) -> str:
    from src.rag.llm import chat_model

    return str(chat_model().invoke(prompt).content).strip()


def summarize_change(
    title: str, old: str, new: str, summarize: Callable[[str], str] | None = None
) -> str:
    diff = "\n".join(
        difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=1)
    )[:DIFF_CHARS]
    return (summarize or _model_summary)(CHANGE_PROMPT.format(title=title, diff=diff))


@dataclass
class PageLine:
    url: str
    title: str
    product: str
    summary: str = ""


@dataclass
class ChangedLine(PageLine):
    diff: SectionDiff | None = None


@dataclass
class QuarantineLine(PageLine):
    reasons: list[str] = field(default_factory=list)


@dataclass
class ChangeReport:
    day: str
    added: list[PageLine]
    removed: list[str]
    changed: list[ChangedLine]
    quarantined: list[QuarantineLine]
    fetch_failures: dict[str, str]
    blocked: dict[str, str]
    initial_build: bool = False

    def empty(self) -> bool:
        return not (
            self.added or self.removed or self.changed or self.quarantined
            or self.fetch_failures or self.blocked
        )


def _page(line: PageLine) -> str:
    text = f"- **{line.product} › {line.title}** — <{line.url}>"
    return f"{text}\n  {line.summary}" if line.summary else text


def render_report(r: ChangeReport) -> str:
    out = [f"# Documentation changes, {r.day}", ""]
    if r.initial_build:
        out += [f"Initial build: {len(r.added)} pages indexed, "
                f"{len(r.quarantined)} quarantined.", ""]
    else:
        if r.added:
            out += [f"## Added ({len(r.added)}) — worth reading", *map(_page, r.added), ""]
        if r.removed:
            out += [f"## Removed ({len(r.removed)})", *(f"- <{u}>" for u in r.removed), ""]
        major = [c for c in r.changed if c.diff and c.diff.significant]
        minor = len(r.changed) - len(major)
        if major:
            out.append(f"## Changed significantly ({len(major)})")
            for c in major:
                assert c.diff is not None
                out.append(_page(c))
                sections = [f"+ {s}" for s in c.diff.added] + [f"− {s}" for s in c.diff.removed]
                detail = ", ".join(sections + [f"{c.diff.changed_lines} lines"])
                out.append(f"  _{detail}_")
            out.append("")
        if minor:
            out += [f"Minor edits: {minor} page{'s' if minor != 1 else ''}.", ""]
    if r.quarantined:
        out.append(f"## Quarantined ({len(r.quarantined)}) — needs a decision")
        for q in r.quarantined:
            out += [_page(q), f"  Flagged: {'; '.join(q.reasons)}"]
        out.append("")
    if r.blocked:
        out += ["## Removals blocked", *(f"- {p}: {why}" for p, why in r.blocked.items()), ""]
    if r.fetch_failures:
        out += ["## Fetch failures (old version kept)",
                *(f"- <{u}>: {why}" for u, why in r.fetch_failures.items()), ""]
    return "\n".join(out).rstrip() + "\n"


def render_quarantine_issue(lines: list[QuarantineLine]) -> str:
    out = [
        "These new pages were not indexed. For each: add a pattern to `exclude` "
        "in `src/ingestion/sources.py` to drop it for good, or add the URL to "
        "`allow` to index it.",
        "",
    ]
    for q in lines:
        out += [f"- <{q.url}>", f"  **What it is:** {q.summary}",
                f"  **Why flagged:** {'; '.join(q.reasons)}"]
    return "\n".join(out) + "\n"
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_report.py tests/test_snapshots.py -q`
Expected: 8 passed.

- [ ] **Step 7: Checks and commit**

```bash
uv run ruff format src evals tests && uv run ruff check src evals tests && uv run mypy && uv run pytest -q
git add src/ingestion/snapshots.py src/ingestion/report.py tests/test_report.py tests/test_snapshots.py
git commit -m "feat(ingestion): snapshot store and readable change report

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Wire the reindex

**Files:**
- Modify: `src/reindex.py` (`main`, new `run`, `_product_of`, `apply`)
- Test: `tests/test_reindex_run.py` (create)

**Interfaces:**
- Consumes: everything above.
- Produces:
  ```python
  @dataclass
  class Deps:                      # everything with side effects, faked in tests
      load: Callable[[], LoadResult]
      snapshots: SnapshotStore-like (get/put/delete/all_texts)
      delete_source: Callable[[str], None]
      add_chunks: Callable[[list[Document]], None]
      product_of: Callable[[], dict[str, str]]
      review: Callable[[str], PageReview] | None
      summarize: Callable[[str], str] | None
  @dataclass(frozen=True)
  class RunResult: manifest: Manifest; report: ChangeReport; exit_code: int
  def run(manifest: Manifest, deps: Deps, *, today: date, dry_run: bool = False,
          gate_report_only: bool = False) -> RunResult
  ```
  Exit codes: 0 ok; 1 smoke failed (unchanged, checked in `main`); 3 removals blocked; 4 fetch failures over limit.
  CLI: `python -m src.reindex [--prune] [--dry-run] [--gate-report-only] [--out DIR]`. Writes `DIR/report.md` (always) and `DIR/quarantine.md` (only if quarantined pages exist); `DIR` defaults to `.`. When the report is not empty and not dry-run, also writes `reports/docs-changes/<day>.md`.

- [ ] **Step 1: Write the failing tests** (`tests/test_reindex_run.py`)

```python
"""End-to-end reindex behaviour with every side effect faked."""

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from src import reindex
from src.ingestion.gate import PageReview
from src.ingestion.loader import LoadResult
from src.models import SourceDocument

DAY = date(2026, 9, 28)


def _doc(url: str, content: str, product: str = "p") -> SourceDocument:
    return SourceDocument(title=url, content=content, url=url, vendor="v", product=product)


@dataclass
class FakeSnapshots:
    texts: dict[str, str] = field(default_factory=dict)

    def get(self, url: str) -> str | None:
        return self.texts.get(url)

    def put(self, document: SourceDocument, sha256: str) -> None:
        self.texts[document.url] = document.content

    def delete(self, url: str) -> None:
        self.texts.pop(url, None)

    def all_texts(self) -> dict[str, str]:
        return dict(self.texts)


def _deps(docs: list[SourceDocument], *, keep: bool = True, listed: int | None = None,
          failures: dict[str, str] | None = None, product_of: dict[str, str] | None = None) -> Any:
    added: list[Any] = []
    deleted: list[str] = []
    deps = reindex.Deps(
        load=lambda: LoadResult(docs, failures or {}, {"p": listed if listed is not None else len(docs)},
                                {u: "p" for u in (failures or {})}),
        snapshots=FakeSnapshots(),
        delete_source=deleted.append,
        add_chunks=added.extend,
        product_of=lambda: product_of or {},
        review=lambda _p: PageReview(keep=keep, category="documentation" if keep else "marketing",
                                     summary="What it is."),
        summarize=lambda _p: "What changed.",
    )
    return deps, added, deleted


def _empty() -> reindex.Manifest:
    return reindex.Manifest(indexed_at=None, documents={})


def test_new_clean_page_is_indexed_and_reported() -> None:
    deps, added, _ = _deps([_doc("https://x/a.md", "# A\ntext")])

    result = reindex.run(_empty(), deps, today=DAY)

    assert result.exit_code == 0
    assert result.manifest.documents["https://x/a.md"].status == "indexed"
    assert added and result.report.added[0].summary == "What it is."


def test_flagged_page_is_quarantined_not_indexed() -> None:
    deps, added, _ = _deps([_doc("https://x/a.md", "# A\ntext")], keep=False)

    result = reindex.run(_empty(), deps, today=DAY)

    entry = result.manifest.documents["https://x/a.md"]
    assert entry.status == "quarantined" and entry.summary == "What it is."
    assert not added and result.report.quarantined[0].reasons == ["model: marketing"]


def test_report_only_gate_indexes_flagged_pages_but_lists_them() -> None:
    deps, added, _ = _deps([_doc("https://x/a.md", "# A\ntext")], keep=False)

    result = reindex.run(_empty(), deps, today=DAY, gate_report_only=True)

    assert added and result.manifest.documents["https://x/a.md"].status == "indexed"
    assert result.report.quarantined


def test_allow_listed_page_skips_the_gate(monkeypatch: Any) -> None:
    monkeypatch.setattr(reindex, "allowed_urls", lambda: {"https://x/a.md"})
    deps, added, _ = _deps([_doc("https://x/a.md", "# A\ntext")], keep=False)

    result = reindex.run(_empty(), deps, today=DAY)

    assert added and not result.report.quarantined


def test_significant_change_gets_a_summary() -> None:
    old, new = "# A\n## One\nx\n", "# A\n## One\nx\n## Two\ny\n"
    manifest = reindex.Manifest(indexed_at="d", documents={
        "https://x/a.md": reindex.ManifestEntry(sha256=reindex.fingerprint(old), chunks=1, title="A")})
    deps, _, _ = _deps([_doc("https://x/a.md", new)])
    deps.snapshots.texts["https://x/a.md"] = old

    result = reindex.run(manifest, deps, today=DAY)

    changed = result.report.changed[0]
    assert changed.diff is not None and changed.diff.added == ["Two"]
    assert changed.summary == "What changed."


def test_vanished_page_is_deleted() -> None:
    entries = {f"https://x/{i}.md": reindex.ManifestEntry(sha256="s", chunks=1, title="t") for i in range(20)}
    docs = [_doc(u, "c") for u in list(entries)[1:]]
    deps, _, deleted = _deps(docs, product_of={u: "p" for u in entries})

    result = reindex.run(reindex.Manifest(indexed_at="d", documents=entries), deps, today=DAY)

    assert deleted == ["https://x/0.md"] and result.report.removed == ["https://x/0.md"]
    assert "https://x/0.md" not in result.manifest.documents


def test_blocked_removal_exits_3_and_deletes_nothing() -> None:
    entries = {f"https://x/{i}.md": reindex.ManifestEntry(sha256="s", chunks=1, title="t") for i in range(20)}
    docs = [_doc(u, "c") for u in list(entries)[5:]]
    deps, _, deleted = _deps(docs, product_of={u: "p" for u in entries})

    result = reindex.run(reindex.Manifest(indexed_at="d", documents=entries), deps, today=DAY)

    assert result.exit_code == 3 and deleted == [] and result.report.blocked


def test_dry_run_writes_nothing() -> None:
    deps, added, deleted = _deps([_doc("https://x/a.md", "# A\ntext")])

    result = reindex.run(_empty(), deps, today=DAY, dry_run=True)

    assert not added and not deleted and not deps.snapshots.texts
    assert result.report.added
```

- [ ] **Step 2: Run and see them fail**

Run: `uv run pytest tests/test_reindex_run.py -q`
Expected: FAIL — `AttributeError: module 'src.reindex' has no attribute 'Deps'`.

- [ ] **Step 3: Implement `run` in `src/reindex.py`**

Add below the existing helpers (keep `fingerprint`, `diff`, `apply` logic but route through `run`):

```python
import statistics
from typing import Protocol

from src.ingestion import report as rep
from src.ingestion.gate import PageReview, gate_page
from src.ingestion.sources import SOURCES


class Snapshots(Protocol):
    def get(self, url: str) -> str | None: ...
    def put(self, document: SourceDocument, sha256: str) -> None: ...
    def delete(self, url: str) -> None: ...
    def all_texts(self) -> dict[str, str]: ...


@dataclass
class Deps:
    load: Callable[[], LoadResult]
    snapshots: Snapshots
    delete_source: Callable[[str], None]
    add_chunks: Callable[[list[Document]], None]
    product_of: Callable[[], dict[str, str]]
    review: Callable[[str], PageReview] | None = None
    summarize: Callable[[str], str] | None = None


@dataclass(frozen=True, slots=True)
class RunResult:
    manifest: Manifest
    report: rep.ChangeReport
    exit_code: int


def allowed_urls() -> set[str]:
    return {url for config in SOURCES for url in config.allow}


def _medians(manifest: Manifest, product_of: dict[str, str]) -> dict[str, float]:
    per: dict[str, list[int]] = {}
    for url, entry in manifest.documents.items():
        if entry.status == "indexed":
            per.setdefault(product_of.get(url, ""), []).append(entry.chunks)
    return {p: float(statistics.median(c)) for p, c in per.items()}


def run(
    manifest: Manifest,
    deps: Deps,
    *,
    today: date,
    dry_run: bool = False,
    gate_report_only: bool = False,
) -> RunResult:
    load = deps.load()
    plan = diff(manifest, load.documents)
    product_of = deps.product_of()
    removals = decide_removals(manifest, plan.missing, load, product_of)
    broken = failing_vendors(load)
    documents = dict(manifest.documents)
    medians = _medians(manifest, product_of)
    indexed_texts = deps.snapshots.all_texts() if plan.added else {}
    allowed = allowed_urls()
    report = rep.ChangeReport(
        day=today.isoformat(), added=[], removed=[], changed=[], quarantined=[],
        fetch_failures=dict(load.failures), blocked={**removals.blocked, **broken},
        initial_build=not manifest.documents,
    )
    summaries = 0

    def index(document: SourceDocument, entry_summary: str) -> None:
        chunks = chunk_document(document)
        sha = fingerprint(document.content)
        if not dry_run:
            deps.delete_source(document.url)
            deps.add_chunks(chunks)
            deps.snapshots.put(document, sha)
        documents[document.url] = ManifestEntry(
            sha256=sha, chunks=len(chunks), title=document.title, summary=entry_summary
        )

    for document in plan.added:
        chunks = chunk_document(document)
        line = rep.PageLine(document.url, document.title, document.product)
        if document.url in allowed:
            index(document, "")
            report.added.append(line)
            continue
        verdict = gate_page(
            document, len(chunks), medians.get(document.product, float(len(chunks))),
            indexed_texts, review=deps.review,
        )
        line.summary = verdict.summary
        if verdict.keep or gate_report_only:
            index(document, verdict.summary)
            report.added.append(line)
        if not verdict.keep:
            report.quarantined.append(
                rep.QuarantineLine(document.url, document.title, document.product,
                                   verdict.summary, verdict.reasons)
            )
            if not gate_report_only:
                documents[document.url] = ManifestEntry(
                    sha256=fingerprint(document.content), chunks=0, title=document.title,
                    status="quarantined", reason="; ".join(verdict.reasons),
                    summary=verdict.summary,
                )

    for document in plan.changed:
        old = deps.snapshots.get(document.url)
        line = rep.ChangedLine(document.url, document.title, document.product)
        if old is not None:
            line.diff = rep.section_diff(old, document.content)
            if line.diff.significant and summaries < rep.MAX_CHANGE_SUMMARIES:
                line.summary = rep.summarize_change(
                    document.title, old, document.content, summarize=deps.summarize
                )
                summaries += 1
        index(document, documents[document.url].summary)
        report.changed.append(line)

    for url in removals.delete:
        if not dry_run:
            deps.delete_source(url)
            deps.snapshots.delete(url)
        documents.pop(url, None)
        report.removed.append(url)

    indexed_at = today.isoformat() if (plan.to_index or removals.delete) else manifest.indexed_at
    code = 4 if broken else 3 if removals.blocked else 0
    return RunResult(Manifest(indexed_at=indexed_at, documents=documents), report, code)
```

Delete the old `apply` function and its two tests in `tests/test_reindex.py` (`test_apply_replaces_only_changed_documents`, `test_apply_keeps_missing_documents_in_manifest`): `run` now owns that behaviour and `test_reindex_run.py` covers it.

- [ ] **Step 4: Rewrite `main`**

```python
def _product_of() -> dict[str, str]:
    """URL -> product for every page in the hybrid collection."""
    client = get_qdrant_client()
    products: dict[str, str] = {}
    try:
        offset = None
        while True:
            points, offset = client.scroll(
                settings.qdrant_hybrid_collection, limit=256, offset=offset,
                with_payload=["metadata.source", "metadata.product"], with_vectors=False,
            )
            for p in points:
                meta = (p.payload or {}).get("metadata", {})
                if meta.get("source"):
                    products[str(meta["source"])] = str(meta.get("product", ""))
            if offset is None:
                return products
    finally:
        client.close()


def main(argv: list[str] | None = None) -> int:
    from evals.seed_query_transform_dataset import INTENTS

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prune", action="store_true",
                        help="Also delete indexed pages no source config selects.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch, select, gate and report without writing anywhere.")
    parser.add_argument("--gate-report-only", action="store_true",
                        help="Index flagged pages anyway but list them (initial build).")
    parser.add_argument("--out", default=".", help="Where report.md and quarantine.md go.")
    args = parser.parse_args(argv)

    collection = settings.qdrant_hybrid_collection
    path = manifest_path(collection)
    manifest = load_manifest(path)
    client = get_qdrant_client()
    try:
        print(f"index points: {touch_index(client, collection)}")
        if not args.dry_run:
            ensure_payload_indexes(client, collection)
        store = SnapshotStore(client, snapshot_collection(collection))
        loaded = load_all_sources()  # fetched once, shared by run and prune
        deps = Deps(
            load=lambda: loaded, snapshots=store, delete_source=_delete_source,
            add_chunks=_add_chunks, product_of=_product_of,
        )
        result = run(manifest, deps, today=datetime.now(UTC).date(),
                     dry_run=args.dry_run, gate_report_only=args.gate_report_only)
        if args.prune and not args.dry_run:
            for url in orphans(_indexed_sources(), loaded.documents):
                print(f"  prune {url}")
                _delete_source(url)
                store.delete(url)
                result.manifest.documents.pop(url, None)
    finally:
        client.close()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    text = rep.render_report(result.report)
    (out / "report.md").write_text(text)
    if result.report.quarantined and not args.gate_report_only:
        (out / "quarantine.md").write_text(rep.render_quarantine_issue(result.report.quarantined))
    print(text)
    if args.dry_run:
        return result.exit_code
    save_manifest(result.manifest, path)
    if not result.report.empty():
        daily = Path("reports/docs-changes") / f"{result.report.day}.md"
        daily.parent.mkdir(parents=True, exist_ok=True)
        daily.write_text(text)
    if result.manifest.indexed_at != manifest.indexed_at:
        write_meta(result.manifest)
        failures = smoke_failures(INTENTS, _search)
        if failures:
            print(f"SMOKE FAILED: expected page missing from top hits for {failures}")
            return 1
    return result.exit_code
```

Import `SnapshotStore`, `snapshot_collection` from `src.ingestion.snapshots`.

- [ ] **Step 5: Run all tests**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 6: Dry run against the live docs and the current v1 collection**

```bash
uv run python -m src.reindex --dry-run --out /tmp/reindex-dry
```

Expected: exit 0 or 3; `report.md` lists ~520 added pages with one-sentence summaries (v1 has only 35), quarantined pages with reasons, no writes (`index points:` unchanged when run twice).

- [ ] **Step 7: Checks and commit**

```bash
uv run ruff format src evals tests && uv run ruff check src evals tests && uv run mypy && uv run pytest -q
git add src/reindex.py tests/test_reindex.py tests/test_reindex_run.py
git commit -m "feat(reindex): gate, guarded removals and change report in one run

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Workflow

**Files:**
- Modify: `.github/workflows/reindex.yml`

**Interfaces:**
- Consumes: CLI from Task 7 (`--out`, `--gate-report-only`, exit codes, `report.md`, `quarantine.md`, `reports/docs-changes/`, `data/manifests/`).

- [ ] **Step 1: Edit the workflow**

Add dispatch inputs and route the collection:

```yaml
  workflow_dispatch:
    inputs:
      prune:
        description: "Drop indexed pages no source config selects any more"
        type: boolean
        default: false
      collection:
        description: "Qdrant collection to build (empty = production default)"
        type: string
        default: ""
      gate_report_only:
        description: "Index flagged pages but list them (initial build)"
        type: boolean
        default: false
```

In `jobs.reindex.env` add:

```yaml
      QDRANT_HYBRID_COLLECTION: ${{ inputs.collection || vars.QDRANT_HYBRID_COLLECTION || 'agent_docs_hybrid_v1' }}
```

Replace the run step:

```yaml
      - name: Reindex changed pages
        id: reindex
        run: |
          set -o pipefail
          uv run python -m src.reindex --out out \
            ${{ inputs.prune && '--prune' || '' }} \
            ${{ inputs.gate_report_only && '--gate-report-only' || '' }} 2>&1 | tee reindex.log
      - name: Job summary
        if: always()
        run: '[ -f out/report.md ] && cat out/report.md >> "$GITHUB_STEP_SUMMARY" || true'
```

In "Commit manifest", replace the path checks with:

```yaml
          if git diff --quiet -- data/manifests reports/docs-changes && [ -z "$(git ls-files --others --exclude-standard data/manifests reports/docs-changes)" ]; then
            echo "nothing to commit"; exit 0
          fi
          ...
          git add data/manifests reports/docs-changes
```

Add after "Commit manifest":

```yaml
      - name: Quarantine issue
        if: always()
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          [ -f out/quarantine.md ] || exit 0
          existing=$(gh issue list --label docs-review --state open --json number --jq '.[0].number')
          if [ -n "$existing" ]; then
            gh issue comment "$existing" --body-file out/quarantine.md
          else
            gh label create docs-review --description "New doc pages waiting for a decision" --force
            gh issue create --title "Pages waiting for review" --label docs-review --body-file out/quarantine.md
          fi
```

Keep "Open an issue on failure" as is (it covers exit codes 1, 3, 4).

- [ ] **Step 2: Validate the YAML**

Run: `uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/reindex.yml'))"`
Expected: no output.

- [ ] **Step 3: Commit, rebase, open the PR for Tasks 1–8**

```bash
git add .github/workflows/reindex.yml
git commit -m "ci(reindex): collection input, change report, quarantine issue

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git stash && git fetch -q && git rebase origin/main && git stash pop
uv run pytest -q
git push -u origin full-docs-index
gh pr create --title "Full documentation index: discovery, gate, report" --body "Implements docs/superpowers/specs/2026-09-27-full-docs-index-design.md §1–4. Production stays on v1 until the eval gate.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

The owner merges before Task 9.

---

### Task 9: Build v2 and review the gate output (operational)

- [ ] **Step 1:** Actions → Reindex → Run workflow with `collection=agent_docs_hybrid_v2`, `gate_report_only=true`. Expected: success; job summary "Initial build: ~560 pages indexed, N quarantined"; `data/manifests/agent_docs_hybrid_v2.json` committed.
- [ ] **Step 2:** Read the quarantine list in the job summary with the owner. For each junk page add an `exclude` pattern; for each false alarm do nothing (it is already indexed in report-only mode, and the manifest marks it `indexed`). Commit `sources.py` changes on a branch, PR, merge, then re-run the workflow with `collection=agent_docs_hybrid_v2`, `prune=true`.
- [ ] **Step 3:** Confirm counts: `uv run python -c "from qdrant_client import QdrantClient; ..."` — or read `index points:` from the run log; expect ~11,800.

---

### Task 10: Eval gate (operational + two small code changes)

**Files:**
- Modify: `evals/run_experiments.py` (`--dataset`)
- Modify: `evals/negative_cases.py`
- Create: `evals/full_corpus_cases.py`, `evals/seed_full_corpus_dataset.py`

- [ ] **Step 1: `--dataset` argument.** In `evals/run_experiments.py` wrap the module-level `DATASET_NAME` use: add `argparse` with `--dataset` (default the existing `DATASET_NAME`) and use `args.dataset` in `langfuse.get_dataset(...)`. Run `uv run python -m evals.run_experiments --help`; expect the flag listed.
- [ ] **Step 2: Re-audit the negative set against v2.** For each case in `evals/negative_cases.py`:
  ```bash
  QDRANT_HYBRID_COLLECTION=agent_docs_hybrid_v2 uv run python -c "from src.service import core; [print(round(p.score,2), p.source) for p in core.search('<question>', limit=3)]"
  ```
  A case whose top passage scores ≥ 0.35 and actually answers it is now answerable: replace it with a question still outside the corpus (e.g. another vendor's product, general programming). Re-seed with `uv run python -m evals.seed_negative_dataset` after deleting replaced items (as done before with `dataset_items.delete`).
- [ ] **Step 3: New-coverage dataset.** Create `evals/full_corpus_cases.py` with 20 cases in the retrieval schema used by `evals/seed_dataset_v3.py` (`question`, `expected_output.relevant: [{vendor, source_contains, heading_contains?}]`), 5 per product, only over pages absent from v1: CLI reference, settings/env vars, SDK, administration, cloud agents, MCP registry and extensions. Write each question from the page text, not from memory. Create `evals/seed_full_corpus_dataset.py` mirroring `evals/seed_dataset_v3.py` with `DATASET_NAME = "rag/full-corpus-v1"`. Seed it.
- [ ] **Step 4: Run both collections.** For each of `agent_docs_hybrid_v1` and `agent_docs_hybrid_v2`:
  ```bash
  export QDRANT_HYBRID_COLLECTION=<collection> GENERATION_TOP_K=8
  uv run python -m evals.run_experiments --dataset rag/retrieval-v3
  uv run python -m evals.run_experiments --dataset rag/retrieval-query-transform-v1
  uv run python -m evals.run_evidence_coverage_experiment
  uv run python -m evals.run_answer_quality_experiment
  uv run python -m evals.run_answer_quality_experiment --negative
  ```
  and on v2 only: `uv run python -m evals.run_experiments --dataset rag/full-corpus-v1`. Leave ≥ 65 s between runs (Cohere trial: 10 calls/min).
- [ ] **Step 5: Decide.** Pass = every regression metric (hit@5, MRR, precision@8, complete evidence coverage, faithfulness, abstention_correct) drops by ≤ 0.03 and `rag/full-corpus-v1` hit@5 ≥ 0.9. Inspect every v2 retrieval miss with `evals/inspect_failures.py`; a miss answered by a newly indexed page is a label gap — extend that case's `relevant` with the evidence, re-seed, re-run. If still failing, apply in order and re-run after each: exclude `/specification/.+/schema\.md$` for MCP; cap chunks per source in the candidate pool; tiered index (new spec). Record the numbers in `reports/full-corpus-eval-2026-09.md`.
- [ ] **Step 6: Commit** the eval code and report on a branch, PR, merge.

---

### Task 11: Switch and document

**Files:**
- Modify: `README.md`, `render.yaml` (comment only)

- [ ] **Step 1:** Render → agent-docs-mcp → Environment: add `QDRANT_HYBRID_COLLECTION=agent_docs_hybrid_v2`; GitHub → Settings → Variables: `QDRANT_HYBRID_COLLECTION=agent_docs_hybrid_v2`. Verify: `/ask` for one new-corpus question returns a v2-only source; Langfuse `production` trace shows it.
- [ ] **Step 2:** README: replace "35 pages" wording with the corpus rules (§1), add "Page gate" and "Change report" sections (where the report and the review issue appear, how to exclude/allow), and the rollback line (set the variable back to `agent_docs_hybrid_v1`).
- [ ] **Step 3:** Commit, PR, merge.
- [ ] **Step 4 (two weeks later):** delete `agent_docs_hybrid_v1`, `agent_docs_hybrid_v1_pages` and `data/manifests/agent_docs_hybrid_v1.json`.
