from src.advice_gate import build_explainability_card, evaluate_advice_gate


def test_gate_refuses_stale_or_unverified_context():
    result = evaluate_advice_gate({"data_quality_ok": True, "quote_stale": True, "crosscheck_ok": False, "general_research": True})
    assert result["allowed"] is False
    assert "fresh_quote" in result["blocking_reasons"]


def test_card_contains_conditions_and_disclaimer():
    card = build_explainability_card({"ticker": "2330", "passed_conditions": ["liquidity"], "failed_conditions": ["valuation"]}, evaluate_advice_gate({}))
    assert card["failed_conditions"] == ["valuation"]
    assert "不構成投資建議" in card["disclaimer"]

