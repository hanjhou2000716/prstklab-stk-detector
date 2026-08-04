from src.strategy_explainability import build_explainability_card, explainability_complete


def test_card_contains_pass_fail_and_risk_context():
    card = build_explainability_card({"ticker": "2330", "checks": ["above_ma5"], "failed_checks": ["volume"]}, strategy="momentum", as_of="2026-01-01", data_quality="complete", risk_factors=["volatility"], invalidation=["close below MA5"])
    assert explainability_complete(card)
    assert card["failed_conditions"] == ["volume"]
    assert card["not_a_buy_signal"]


def test_missing_identity_is_incomplete():
    assert not explainability_complete({"strategy": "value"})
