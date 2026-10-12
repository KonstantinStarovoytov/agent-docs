from evals.evidence_coverage import CASES, coverage, matches_target


def test_cases_are_unique_and_multi_aspect():
    ids = [case["id"] for case in CASES]
    assert len(ids) == len(set(ids))
    for case in CASES:
        groups = case["evidence_groups"]
        assert len(groups) >= 2, case["id"]
        assert len({group["id"] for group in groups}) == len(groups), case["id"]
        for group in groups:
            assert group["target"].get("source_contains"), group["id"]


def test_matches_target_requires_every_specified_field():
    result = {
        "vendor": "cursor",
        "source": "https://cursor.com/docs/rules.md",
        "heading": "Rules > Project rules > Glob pattern examples",
    }
    assert matches_target(
        result,
        {
            "vendor": "cursor",
            "source_contains": "rules.md",
            "heading_contains": "glob pattern",
        },
    )
    assert not matches_target(result, {"heading_contains": "MCP"})


def test_coverage_requires_each_independent_evidence_group():
    expected = {
        "evidence_groups": [
            {"id": "rules", "target": {"source_contains": "rules.md"}},
            {"id": "mcp", "target": {"source_contains": "mcp.md"}},
        ]
    }
    measured = coverage(
        {"results": [{"source": "https://cursor.com/docs/rules.md"}]}, expected
    )
    assert measured == {
        "covered": ["rules"],
        "missing": ["mcp"],
        "value": 0.5,
        "complete": 0.0,
    }


def test_coverage_accepts_recorded_alternative_sources():
    expected = {
        "evidence_groups": [
            {
                "id": "server",
                "target": {"source_contains": "learn/server-concepts.md"},
                "alternatives": [{"source_contains": "/server/index.md"}],
            },
        ]
    }
    spec_page = {
        "source": "https://modelcontextprotocol.io/specification/x/server/index.md"
    }
    assert coverage({"results": [spec_page]}, expected)["complete"] == 1.0
    assert coverage({"results": [{"source": "other.md"}]}, expected)["complete"] == 0.0
