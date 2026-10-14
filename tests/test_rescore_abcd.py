from evals.experiments.rescore_query_transform_results import (
    EXPERIMENT_IDS,
    calculate_scores,
    summarize_runs,
)
from evals.seed_query_transform_dataset import INTENTS


def test_golden_set_is_balanced_and_has_unique_intent_variants():
    expected_types = {"clean_en", "natural_en", "short_en", "ru", "pl", "mixed"}
    keys = []

    for intent in INTENTS:
        assert set(intent["variants"]) == expected_types
        assert intent["relevant"]
        keys.extend((intent["id"], query_type) for query_type in intent["variants"])

    assert len(INTENTS) == 8
    assert len(keys) == 48
    assert len(keys) == len(set(keys))


def test_old_abcd_experiment_ids_are_pinned():
    assert EXPERIMENT_IDS == {
        "A_original": "a63da7fc-fdd3-4f9d-8dba-e0e210b8aa6f",
        "B_english": "0cd4edc5-f784-49ed-a090-a840a146d1ca",
        "C_semantic": "b6dd2080-057c-420b-813e-1f5b373fccc7",
        "D_english_semantic": "7b1c55b4-fbd1-478f-b5a1-16052dbf7746",
    }


def test_calculate_scores_uses_first_relevant_rank():
    expected = {"relevant": [{"vendor": "cursor"}]}
    scores = calculate_scores(
        [
            {"rank": 1, "vendor": "openai"},
            {"rank": 2, "vendor": "cursor"},
        ],
        expected,
    )

    assert scores == {
        "hit_at_1": 0.0,
        "hit_at_5": 1.0,
        "hit_at_10": 1.0,
        "reciprocal_rank": 0.5,
    }


def test_summarize_runs_compares_all_strategies_on_shared_cases():
    runs = {
        "A_original": {
            "intent:ru": {
                "query_type": "ru",
                "hit_at_1": 0.0,
                "hit_at_5": 1.0,
                "hit_at_10": 1.0,
                "reciprocal_rank": 0.5,
            }
        },
        "B_english": {
            "intent:ru": {
                "query_type": "ru",
                "hit_at_1": 1.0,
                "hit_at_5": 1.0,
                "hit_at_10": 1.0,
                "reciprocal_rank": 1.0,
            }
        },
        "C_semantic": {
            "intent:ru": {
                "query_type": "ru",
                "hit_at_1": 0.0,
                "hit_at_5": 0.0,
                "hit_at_10": 1.0,
                "reciprocal_rank": 0.1,
            }
        },
        "D_english_semantic": {
            "intent:ru": {
                "query_type": "ru",
                "hit_at_1": 0.0,
                "hit_at_5": 1.0,
                "hit_at_10": 1.0,
                "reciprocal_rank": 0.25,
            }
        },
    }

    summary = summarize_runs(runs)

    assert summary["shared_cases"] == 1
    assert summary["overall"]["B_english"]["reciprocal_rank"] == 1.0
    assert summary["by_query_type"]["ru"]["C_semantic"]["hit_at_5"] == 0.0
