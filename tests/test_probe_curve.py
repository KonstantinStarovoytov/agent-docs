"""Retrieval-only coverage curve over the candidate pool size."""

from typing import Any

from evals.experiments.probe_context_assembly import coverage_curve

CASE = {
    "id": "c",
    "question": "q",
    "evidence_groups": [
        {"id": "g1", "target": {"vendor": "cursor", "source_contains": "rules"}},
        {"id": "g2", "target": {"vendor": "cursor", "source_contains": "hooks"}},
    ],
}


class _Doc:
    def __init__(self, source: str) -> None:
        self.metadata = {"vendor": "cursor", "source": source, "title": "t"}
        self.page_content = ""


class _Ranked:
    def __init__(self, source: str) -> None:
        self.document = _Doc(source)


def test_curve_reports_complete_coverage_per_pool_size() -> None:
    # The second required source only appears at rank 6.
    ranked = [_Ranked("rules"), *[_Ranked("other")] * 4, _Ranked("hooks")]

    def retrieve_and_rank(question: str, pool: int) -> list[Any]:
        return ranked[:pool]

    curve = coverage_curve([CASE], [5, 10], retrieve_and_rank)

    assert curve == {5: 0.0, 10: 1.0}


def test_curve_reports_progress_as_each_pool_completes() -> None:
    """A crash on pool 30 must not lose the results already computed for pool 5."""
    from evals.experiments.probe_context_assembly import coverage_curve

    seen: list[tuple[int, float]] = []

    def retrieve_and_rank(question: str, pool: int) -> list[Any]:
        return [_Ranked("rules"), _Ranked("hooks")]

    coverage_curve(
        [CASE],
        [5, 10],
        retrieve_and_rank,
        on_pool_done=lambda p, v: seen.append((p, v)),
    )

    assert seen == [(5, 1.0), (10, 1.0)]


def test_retry_on_rate_limit_backs_off_and_retries() -> None:
    from cohere.errors.too_many_requests_error import TooManyRequestsError

    from evals.experiments.probe_context_assembly import with_cohere_retry

    calls = 0
    slept: list[float] = []

    def flaky() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise TooManyRequestsError(headers={}, body={"message": "rate limited"})
        return "ok"

    result = with_cohere_retry(flaky, sleep=slept.append)

    assert result == "ok"
    assert calls == 3
    assert slept == [10.0, 20.0]


def test_retry_gives_up_after_max_attempts() -> None:
    import pytest as _pytest
    from cohere.errors.too_many_requests_error import TooManyRequestsError

    from evals.experiments.probe_context_assembly import with_cohere_retry

    def always_fails() -> str:
        raise TooManyRequestsError(headers={}, body={"message": "rate limited"})

    with _pytest.raises(TooManyRequestsError):
        with_cohere_retry(always_fails, sleep=lambda _s: None, max_attempts=2)
