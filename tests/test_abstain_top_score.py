"""ask_docs abstains, without the generator, when even the best match is weak."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from langchain_core.documents import Document

from src.rag import generator, pipeline
from src.rag.reranker import RerankResult


def _ranked(*scores: float) -> list[RerankResult]:
    return [
        RerankResult(Document(page_content=f"c{i}", metadata={}), 1.0, score, i, i)
        for i, score in enumerate(scores, start=1)
    ]


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch):
    def setup(*scores: float, threshold: float | None) -> Mock:
        ranked = _ranked(*scores)
        monkeypatch.setattr(pipeline.settings, "min_top_rerank_score", threshold)
        monkeypatch.setattr(pipeline, "search_hybrid", Mock(return_value=["c"]))
        monkeypatch.setattr(
            pipeline,
            "CohereReranker",
            lambda: SimpleNamespace(rerank=Mock(return_value=ranked)),
        )
        generate = Mock(return_value="generated")
        monkeypatch.setattr(pipeline, "generate_answer", generate)
        return generate

    return setup


def test_weak_best_score_abstains_without_generator(wired, monkeypatch) -> None:
    generate = wired(0.55, 0.4, threshold=0.6)
    model = Mock(side_effect=AssertionError("the LLM must not be called"))
    monkeypatch.setattr(generator, "chat_model", model)

    result = pipeline.answer_question("question", strategy="hybrid")

    generate.assert_not_called()
    model.assert_not_called()
    assert result.answer == "I couldn't find relevant documentation for this question."
    assert result.sources == []


@pytest.mark.parametrize("best", [0.6, 0.61, 0.95])
def test_best_score_at_or_above_threshold_answers(wired, best: float) -> None:
    generate = wired(best, 0.2, threshold=0.6)

    assert pipeline.answer_question("question", strategy="hybrid") == "generated"
    generate.assert_called_once()


def test_no_threshold_keeps_previous_behaviour(wired) -> None:
    generate = wired(0.01, threshold=None)

    assert pipeline.answer_question("question", strategy="hybrid") == "generated"
    generate.assert_called_once()


def test_setting_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.config import Settings

    monkeypatch.setenv("MIN_TOP_RERANK_SCORE", "0.5")
    assert Settings().min_top_rerank_score == 0.5
    monkeypatch.setenv("MIN_TOP_RERANK_SCORE", "")
    assert Settings().min_top_rerank_score is None


def test_default_threshold_is_the_measured_one(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.config import Settings

    monkeypatch.delenv("MIN_TOP_RERANK_SCORE", raising=False)
    # reports/dedup-abstain-2026-10.md: lowest answerable top score 0.64.
    assert Settings(_env_file=None).min_top_rerank_score == 0.55  # type: ignore[call-arg]
