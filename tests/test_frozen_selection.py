import pytest
from langchain_core.documents import Document

from evals.experiments.frozen_selection import Aspect, Assignment, pick_ids, select_set
from src.rag.reranker import RerankResult
from src.rag.retriever import document_key


def result(text):
    return RerankResult(Document(page_content=text), 1, 1, 1, 1)


def test_one_chunk_can_cover_multiple_aspects_without_document_caps():
    ranked = [result("irrelevant"), result("both requirements"), result("third")]
    both, third = [document_key(r.document) for r in ranked[1:]]
    assignment = Assignment(
        aspects=[
            Aspect(requirement="first", chunk_ids=[both]),
            Aspect(requirement="second", chunk_ids=[both]),
            Aspect(requirement="third", chunk_ids=[third]),
        ]
    )
    assert select_set(ranked, assignment, 2) == ranked[1:]


def test_unknown_ids_fail_instead_of_silently_improving_coverage():
    assignment = Assignment(aspects=[Aspect(requirement="x", chunk_ids=["fake"])])
    with pytest.raises(ValueError, match="unknown"):
        select_set([result("real")], assignment, 1)


def test_unsupported_aspects_backfill_in_original_order():
    ranked = [result("first"), result("second")]
    assignment = Assignment(aspects=[Aspect(requirement="absent", chunk_ids=[])])
    assert select_set(ranked, assignment, 2) == ranked


def test_pick_ids_preserves_stored_order_and_rejects_unknown():
    ranked = [result("first"), result("second"), result("third")]
    first, second = [document_key(r.document) for r in ranked[:2]]
    assert pick_ids(ranked, [second, first]) == [ranked[1], ranked[0]]
    with pytest.raises(ValueError, match="missing"):
        pick_ids(ranked, ["nope"])
