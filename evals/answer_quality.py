"""Strict, traceable answer-quality metrics for the curated RAG dataset.

Ragas' current package requires downgrading this application's OpenAI SDK, so this
module keeps the same core evaluation questions in the application's compatible
LangChain/OpenAI stack. The scores are LLM-as-a-judge signals, not human ground
truth; the structured issue lists make each score auditable in Langfuse.
"""

import json
from dataclasses import dataclass
from typing import Any, Literal

from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI
from langfuse import Evaluation
from pydantic import BaseModel, Field, field_validator

from src.config import settings
from src.observability import model_config, prompt_context, traced
from src.prompts.managed import get_chat_prompt


# Databricks, "Long Context RAG Performance of LLMs", Appendix F: the ways a
# generator fails that the four scores below do not name.
FailureMode = Literal[
    "none",  # a direct answer
    "refusal",  # says the documentation does not cover it
    "empty",  # nothing usable
    "repeated_content",  # loops or restates the same passage
    "fail_follow_inst",  # summarises the context instead of answering
]


class AnswerQualityAssessment(BaseModel):
    faithfulness: float = Field(ge=0.0, le=1.0)
    answer_relevance: float = Field(ge=0.0, le=1.0)
    context_utilization: float = Field(ge=0.0, le=1.0)
    citation_correctness: float = Field(ge=0.0, le=1.0)
    unsupported_claims: list[str]
    missing_aspects: list[str]
    citation_issues: list[str]
    summary: str = Field(min_length=1)
    failure_mode: FailureMode = "none"

    @field_validator(
        "unsupported_claims", "missing_aspects", "citation_issues", mode="before"
    )
    @classmethod
    def _list_sent_as_text(cls, value: object) -> object:
        # Small judges sometimes send a tool call's array as a JSON string.
        if not isinstance(value, str):
            return value
        try:
            parsed = json.loads(value)
        except ValueError:
            return [value] if value.strip() else []
        if isinstance(parsed, list) and all(isinstance(x, str) for x in parsed):
            return parsed
        return [value]


ANTHROPIC_OPENAI_URL = "https://api.anthropic.com/v1/"


def judge_model() -> str:
    return settings.judge_model


def judge_llm(model: str) -> ChatOpenAI:
    """The judge; a Claude model through Anthropic's OpenAI-compatible API."""
    if model.startswith("claude-"):
        if settings.anthropic_api_key is None:
            raise RuntimeError(f"ANTHROPIC_API_KEY must be set to judge with {model}")
        return ChatOpenAI(
            api_key=settings.anthropic_api_key.get_secret_value(),
            base_url=ANTHROPIC_OPENAI_URL,
            model=model,
        )
    # GPT-6 judges reject any temperature, so the generator's setting must not
    # leak here.
    return ChatOpenAI(api_key=settings.openai_api_key.get_secret_value(), model=model)


def structured_judge(model: str) -> Runnable[Any, Any]:
    llm = judge_llm(model)
    if model.startswith("claude-"):
        # Anthropic's OpenAI-compatible API rejects the JSON-schema response
        # format for these scores (no minimum/maximum); a tool call works.
        return llm.with_structured_output(
            AnswerQualityAssessment, method="function_calling"
        )
    return llm.with_structured_output(AnswerQualityAssessment)


def judge_is_independent() -> bool:
    """False when the judge grades its own generations."""
    return judge_model() != settings.openai_chat_model


@dataclass(frozen=True, slots=True)
class AnswerQualityResult:
    assessment: AnswerQualityAssessment
    prompt_metadata: dict[str, str | int | None]


def _assessment_trace_input(
    question: str, answer: str, contexts: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "question": question,
        "answer": answer,
        "contexts": contexts,
    }


@traced(
    "evaluate-answer-quality",
    "evaluator",
    input_factory=_assessment_trace_input,
)
def assess_answer_quality(
    question: str,
    answer: str,
    contexts: list[dict[str, Any]],
    judge: str | None = None,
) -> AnswerQualityResult:
    """Judge one answer once, then fan its structured scores into Langfuse.

    `judge` overrides the configured judge model (to compare two judges).
    """
    prompt = get_chat_prompt(
        "answer-evaluator",
        version=settings.answer_evaluator_prompt_version,
        # An experiment must never silently compare a remote production prompt
        # against a local fallback.
        strict=True,
        question=question,
        answer=answer,
        contexts=json.dumps(contexts, ensure_ascii=False),
    )
    model = structured_judge(judge or judge_model())
    with prompt_context(prompt):
        assessment = model.invoke(
            prompt.messages,
            config=model_config("evaluate-answer-quality"),
        )
    if not isinstance(assessment, AnswerQualityAssessment):
        assessment = AnswerQualityAssessment.model_validate(assessment)
    return AnswerQualityResult(
        assessment=assessment,
        prompt_metadata=prompt.metadata,
    )


# Several evaluators read the same judgement; one paid call per answer.
_assessments: dict[str, AnswerQualityResult] = {}


def _judged(
    question: str, answer: str, contexts: list[dict[str, Any]]
) -> AnswerQualityResult:
    key = json.dumps([question, answer, contexts], ensure_ascii=False, sort_keys=True)
    if key not in _assessments:
        _assessments[key] = assess_answer_quality(question, answer, contexts)
    return _assessments[key]


def forget_assessments() -> None:
    _assessments.clear()


def answer_quality_metrics(*, input, output, **_kwargs) -> list[Evaluation]:
    """Return all quality dimensions from one judge invocation.

    Only a missing answer short-circuits to zero: that is a real generation
    failure. Empty contexts with a real answer is generate_from_selected's
    canned "I couldn\'t find..." reply (e.g. min_rerank_score filtered every
    candidate out) — a correct abstention the judge should still score, not a
    failure to force-zero.
    """
    answer = output.get("answer", "")
    contexts = output.get("contexts", [])
    if not answer:
        return [
            Evaluation(
                name=name,
                value=0.0,
                comment="No generated answer was available.",
            )
            for name in (
                "answer_faithfulness",
                "answer_relevance",
                "context_utilization",
                "citation_correctness",
            )
        ]

    quality = _judged(input["question"], answer, contexts)
    assessment = quality.assessment
    issues = {
        "unsupported_claims": assessment.unsupported_claims,
        "missing_aspects": assessment.missing_aspects,
        "citation_issues": assessment.citation_issues,
        "summary": assessment.summary,
        "failure_mode": assessment.failure_mode,
        "evaluator_model": judge_model(),
        "evaluator_independent": judge_is_independent(),
        **quality.prompt_metadata,
    }
    return [
        Evaluation(
            name="answer_faithfulness",
            value=assessment.faithfulness,
            comment=assessment.summary,
            metadata=issues,
        ),
        Evaluation(
            name="answer_relevance",
            value=assessment.answer_relevance,
            comment=f"missing_aspects={assessment.missing_aspects}",
            metadata=issues,
        ),
        Evaluation(
            name="context_utilization",
            value=assessment.context_utilization,
            comment="Selected contexts were judged against the generated answer.",
            metadata=issues,
        ),
        Evaluation(
            name="citation_correctness",
            value=assessment.citation_correctness,
            comment=f"citation_issues={assessment.citation_issues}",
            metadata=issues,
        ),
        # Categorical: which way the generator failed, if it did.
        Evaluation(
            name="answer_failure_mode",
            value=assessment.failure_mode,
            comment=assessment.summary,
            metadata=issues,
        ),
    ]


def abstention_correct(*, input, output, expected_output, **_kwargs) -> Evaluation:
    """Did the system abstain exactly when the corpus has no answer?

    Negative cases set expect_abstention; on positive cases an abstention is
    a miss that faithfulness alone would score as correct.
    """
    expected = bool(expected_output.get("expect_abstention", False))
    answer = output.get("answer", "")
    contexts = output.get("contexts", [])
    if not answer:
        abstained = True
    else:
        judged = _judged(input["question"], answer, contexts)
        abstained = judged.assessment.failure_mode == "refusal"
    return Evaluation(
        name="abstention_correct",
        value=float(abstained == expected),
        comment=f"expected_abstention={expected} abstained={abstained}",
    )
