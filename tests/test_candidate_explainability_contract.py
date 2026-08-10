from src.advice_gate import build_explainability_card
from src.artifact_contract import validate_research


def _report(candidate):
    return {
        "schema_version": "2.0",
        "generated_at": "2026-08-10T08:00:00+00:00",
        "sources": [],
        "candidates": [candidate],
        "health": {},
    }


def test_explainability_contract_accepts_complete_candidate():
    candidate = {
        "ticker": "2330",
        "explainability": {
            "passed_conditions": ["quality"],
            "failed_conditions": [],
            "data_completeness": 1.0,
            "risk_factors": ["valuation"],
            "evidence": [{"source_url": "https://example.test/evidence"}],
            "signal_date": "2026-08-10",
            "invalidation": "quality data becomes stale",
        },
    }
    assert validate_research(_report(candidate)) == []


def test_explainability_contract_rejects_missing_fields_and_wrong_types():
    candidate = {"explainability": {"passed_conditions": "quality", "evidence": []}}
    errors = validate_research(_report(candidate))
    assert any("missing required fields" in error for error in errors)
    assert any("passed_conditions must be an array" in error for error in errors)


def test_advice_card_exposes_nested_explainability_contract():
    card = build_explainability_card(
        {"ticker": "2330", "passed_conditions": ["quality"]},
        {"allowed": False},
    )
    assert card["explainability"]["passed_conditions"] == ["quality"]
