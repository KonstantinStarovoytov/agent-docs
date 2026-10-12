"""Recall-in-pool helpers of evals.diagnose_retrieval (no network)."""

from evals.diagnose_retrieval import (
    Case,
    Group,
    case_vendor,
    loss_class,
    recall_table,
)


def _case(*vendors: str | None) -> Case:
    groups = [
        Group(f"g{i}", [{"vendor": v}] if v else [{}]) for i, v in enumerate(vendors)
    ]
    return Case("full-corpus", "id", "q", groups)


def test_case_vendor_is_the_single_vendor_of_all_targets() -> None:
    assert case_vendor(_case("cursor", "cursor")) == "cursor"


def test_case_vendor_is_none_when_mixed_or_unlabelled() -> None:
    assert case_vendor(_case("cursor", "openai")) is None
    assert case_vendor(_case(None)) is None


def test_loss_class() -> None:
    assert loss_class(0, True, None, None, 30) == "NOT_IN_CORPUS"
    assert loss_class(3, True, 5, None, 30) == "IN_POOL"
    assert loss_class(3, False, 12, 80, 30) == "LOST_IN_POOL"
    assert loss_class(3, False, 31, None, 30) == "LOST_BEFORE_FUSION"


def test_recall_table_averages_groups_per_dataset_and_pool() -> None:
    records = [
        {"dataset": "a", "hits": {"10": [True, False], "20": [True, True]}},
        {"dataset": "a", "hits": {"10": [False], "20": [True]}},
    ]

    table = recall_table(records)

    assert table["a"]["10"] == 1 / 3
    assert table["a"]["20"] == 1.0
