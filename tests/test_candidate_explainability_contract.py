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


def test_advice_card_preserves_investor_facing_evidence_dimensions():
    card = build_explainability_card(
        {
            "ticker": "2330",
            "turnover": 1234567,
            "recent_events": [{"title": "earnings", "source_url": "https://example.test/event"}],
            "pe": 18.2,
            "change_percent": 2.1,
            "roe": 21.0,
        },
        {"allowed": False},
    )
    explainability = card["explainability"]
    assert explainability["liquidity"] == 1234567
    assert explainability["recent_events"][0]["title"] == "earnings"
    assert explainability["valuation_position"] == 18.2
    assert explainability["momentum_position"] == 2.1
    assert explainability["quality_position"] == 21.0


def test_advice_card_exposes_strategy_registry_binding_when_present():
    card = build_explainability_card(
        {
            "ticker": "2330", "strategy": "momentum", "strategy_version": "2", "data_version": "d1",
            "backtest_release": "bt1",
            "strategy_registry": {
                "strategy_id": "momentum", "strategy_version": "2", "data_version": "d1", "backtest_release": "bt1",
                "parameter_hash": "abc", "universe_version": "u1", "code_commit": "deadbeef",
            },
        },
        {"allowed": False},
    )
    assert card["explainability"]["strategy_binding"]["registry_state"] == "verified"
