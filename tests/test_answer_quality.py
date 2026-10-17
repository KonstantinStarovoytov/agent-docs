from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from evals import answer_quality
from src.config import Settings


def test_quality_metrics_fan_out_one_judge_assessment(monkeypatch):
    assessment = answer_quality.AnswerQualityAssessment(
        faithfulness=0.75,
        answer_relevance=0.5,
        context_utilization=1.0,
        citation_correctness=0.25,
        unsupported_claims=["Unsupported detail"],
        missing_aspects=["Authorization"],
        citation_issues=["[2] does not support the claim"],
        summary="One claim is unsupported.",
    )
    monkeypatch.setattr(
        answer_quality,
        "assess_answer_quality",
        lambda *_args: answer_quality.AnswerQualityResult(
            assessment=assessment,
            prompt_metadata={"prompt_name": "agent-docs/answer-evaluator"},
        ),
    )
    monkeypatch.setattr(
        answer_quality,
        "settings",
        SimpleNamespace(openai_chat_model="judge-model", judge_model="judge-model"),
    )

    scores = answer_quality.answer_quality_metrics(
        input={"question": "How are tools authorized?"},
        output={
            "answer": "An answer [1].",
            "contexts": [{"citation": 1, "content": "Context"}],
        },
    )

    assert [(score.name, score.value) for score in scores] == [
        ("answer_faithfulness", 0.75),
        ("answer_relevance", 0.5),
        ("context_utilization", 1.0),
        ("citation_correctness", 0.25),
        ("answer_failure_mode", "none"),
    ]
    assert scores[0].metadata["unsupported_claims"] == ["Unsupported detail"]
    assert scores[0].metadata["evaluator_independent"] is False


def test_missing_answer_or_context_scores_zero_without_calling_judge(monkeypatch):
    judge = SimpleNamespace()
    monkeypatch.setattr(answer_quality, "assess_answer_quality", judge)

    scores = answer_quality.answer_quality_metrics(
        input={"question": "Question"}, output={"answer": "", "contexts": []}
    )

    assert [score.value for score in scores] == [0.0, 0.0, 0.0, 0.0]


def _assessment(**overrides):
    base = dict(
        faithfulness=1.0,
        answer_relevance=1.0,
        context_utilization=1.0,
        citation_correctness=1.0,
        unsupported_claims=[],
        missing_aspects=[],
        citation_issues=[],
        summary="ok",
    )
    base.update(overrides)
    return answer_quality.AnswerQualityAssessment(**base)


def _judge_returning(monkeypatch, assessment):
    monkeypatch.setattr(
        answer_quality,
        "assess_answer_quality",
        lambda *_args: answer_quality.AnswerQualityResult(
            assessment=assessment, prompt_metadata={}
        ),
    )
    monkeypatch.setattr(
        answer_quality,
        "settings",
        SimpleNamespace(openai_chat_model="gen", judge_model="judge"),
    )


def test_failure_mode_is_reported_as_its_own_score(monkeypatch):
    """Databricks' failure taxonomy: a refusal is not a faithful answer to hide."""
    _judge_returning(monkeypatch, _assessment(failure_mode="refusal"))

    scores = answer_quality.answer_quality_metrics(
        input={"question": "q"},
        output={"answer": "The docs do not cover this.", "contexts": [{"c": 1}]},
    )

    failure = next(score for score in scores if score.name == "answer_failure_mode")
    assert failure.value == "refusal"
    assert scores[0].metadata["evaluator_model"] == "judge"
    assert scores[0].metadata["evaluator_independent"] is True


def test_failure_mode_defaults_to_none_for_older_judge_outputs():
    assert _assessment().failure_mode == "none"


def test_abstention_is_correct_only_when_expected(monkeypatch):
    _judge_returning(monkeypatch, _assessment(failure_mode="refusal"))
    output = {"answer": "Not in the docs.", "contexts": [{"c": 1}]}

    expected_abstain = answer_quality.abstention_correct(
        input={"question": "q"},
        output=output,
        expected_output={"expect_abstention": True},
    )
    expected_answer = answer_quality.abstention_correct(
        input={"question": "q"},
        output=output,
        expected_output={"expect_abstention": False},
    )

    assert expected_abstain.value == 1.0
    assert expected_answer.value == 0.0


def _settings(monkeypatch, **env):
    for name in ("JUDGE_MODEL", "OPENAI_JUDGE_MODEL"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return Settings(openai_api_key="k", cohere_api_key="k", _env_file=None)


def test_the_default_judge_is_not_the_generator(monkeypatch):
    settings = _settings(monkeypatch)

    assert settings.judge_model == "gpt-6-sol" != settings.openai_chat_model


def test_the_old_judge_variable_still_sets_the_judge(monkeypatch):
    settings = _settings(monkeypatch, OPENAI_JUDGE_MODEL="claude-haiku-5-5")

    assert settings.judge_model == "claude-haiku-5-5"


def test_a_judge_set_to_the_generator_says_so(monkeypatch):
    monkeypatch.setattr(
        answer_quality,
        "settings",
        SimpleNamespace(openai_chat_model="gen", judge_model="gen"),
    )

    assert answer_quality.judge_is_independent() is False


def test_a_claude_judge_goes_through_anthropic(monkeypatch):
    monkeypatch.setattr(
        answer_quality,
        "settings",
        SimpleNamespace(
            openai_api_key=SecretStr("openai-key"),
            anthropic_api_key=SecretStr("anthropic-key"),
        ),
    )

    claude = answer_quality.judge_llm("claude-haiku-5-5")
    gpt = answer_quality.judge_llm("gpt-6-sol")

    assert claude.openai_api_base == answer_quality.ANTHROPIC_OPENAI_URL
    assert claude.openai_api_key.get_secret_value() == "anthropic-key"
    assert gpt.openai_api_base is None
    assert gpt.openai_api_key.get_secret_value() == "openai-key"


def test_a_claude_judge_answers_with_a_tool_call(monkeypatch):
    """Anthropic's OpenAI-compatible API rejects the JSON-schema response
    format for these scores (it does not support minimum/maximum)."""
    monkeypatch.setattr(
        answer_quality,
        "settings",
        SimpleNamespace(
            openai_api_key=SecretStr("o"), anthropic_api_key=SecretStr("a")
        ),
    )

    claude = answer_quality.structured_judge("claude-haiku-5-5").first.kwargs
    gpt = answer_quality.structured_judge("gpt-6-sol").first.kwargs

    assert "tools" in claude and "response_format" not in claude
    assert "response_format" in gpt


def test_a_claude_judge_needs_the_anthropic_key(monkeypatch):
    monkeypatch.setattr(
        answer_quality,
        "settings",
        SimpleNamespace(openai_api_key=SecretStr("k"), anthropic_api_key=None),
    )

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        answer_quality.judge_llm("claude-haiku-5-5")


def test_both_evaluators_share_one_judge_call(monkeypatch):
    calls = 0

    def judge(question, answer, contexts):
        nonlocal calls
        calls += 1
        return answer_quality.AnswerQualityResult(
            assessment=_assessment(failure_mode="refusal"), prompt_metadata={}
        )

    monkeypatch.setattr(answer_quality, "assess_answer_quality", judge)
    monkeypatch.setattr(
        answer_quality,
        "settings",
        SimpleNamespace(openai_chat_model="gen", judge_model="judge"),
    )
    answer_quality.forget_assessments()
    output = {"answer": "Not covered.", "contexts": [{"citation": 1, "content": "c"}]}

    answer_quality.answer_quality_metrics(input={"question": "q"}, output=output)
    answer_quality.abstention_correct(
        input={"question": "q"},
        output=output,
        expected_output={"expect_abstention": True},
    )

    assert calls == 1


def test_clean_abstention_with_empty_context_is_judged_not_zeroed(monkeypatch):
    """min_rerank_score can legitimately filter every candidate out; the
    canned "I couldn't find..." answer is then a correct abstention, not a
    generation failure, and must still be scored (not force-zeroed)."""
    _judge_returning(monkeypatch, _assessment(faithfulness=1.0, failure_mode="refusal"))

    scores = answer_quality.answer_quality_metrics(
        input={"question": "q"},
        output={
            "answer": "I couldn't find relevant documentation for this question.",
            "contexts": [],
        },
    )

    assert scores[0].value == 1.0  # judged, not the empty-input zero path


def test_a_list_sent_as_a_json_string_is_read_as_a_list():
    """Small judges sometimes send a tool call's array as a JSON string."""
    assessment = answer_quality.AnswerQualityAssessment(
        faithfulness=1.0,
        answer_relevance=1.0,
        context_utilization=1.0,
        citation_correctness=1.0,
        unsupported_claims="[]",
        missing_aspects='["Authorization"]',
        citation_issues="[1] does not support the claim",
        summary="Fine.",
    )

    assert assessment.unsupported_claims == []
    assert assessment.missing_aspects == ["Authorization"]
    assert assessment.citation_issues == ["[1] does not support the claim"]
