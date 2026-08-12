from src.advice_gate import build_explainability_card, evaluate_advice_gate


def test_gate_refuses_stale_or_unverified_context():
    result = evaluate_advice_gate({"data_quality_ok": True, "quote_stale": True, "crosscheck_ok": False, "general_research": True})
    assert result["allowed"] is False
    assert "fresh_quote" in result["blocking_reasons"]


def test_card_contains_conditions_and_disclaimer():
    card = build_explainability_card({"ticker": "2330", "passed_conditions": ["liquidity"], "failed_conditions": ["valuation"]}, evaluate_advice_gate({}))
    assert card["failed_conditions"] == ["valuation"]
    assert "不構成投資建議" in card["disclaimer"]


def _valid_context() -> dict:
    return {
        "data_quality_ok": True,
        "quote_stale": False,
        "crosscheck_ok": True,
        "backtest_release_contract": {
            "publication_state": "ready",
            "publish_eligible": True,
            "strategy_registry": [{"strategy_id": "value"}],
        },
        "candidate_data_gap": False,
        "policy_valid": True,
        "general_research": True,
        "evidence": [{"source_url": "https://example.test/evidence"}],
        "invalidation_condition": "crosscheck no longer agrees",
        "alternative_scenario": "market regime reverses",
        "horizon": "20d",
        "confidence": "medium",
    }


def test_structured_backtest_contract_is_required_for_contextual_advice():
    result = evaluate_advice_gate(_valid_context())
    assert result["allowed"] is True
    assert result["checks"]["backtest"] is True
    assert result["decision_support"]["actionable"] is False
    assert result["decision_support"]["horizon"] == "20d"


def test_blocked_backtest_contract_cannot_open_gate():
    context = _valid_context()
    context["backtest_release_contract"] = {
        "publication_state": "blocked",
        "publish_eligible": False,
    }
    result = evaluate_advice_gate(context)
    assert result["allowed"] is False
    assert "invalid_backtest_release" in result["blocking_reasons"]


def test_ready_backtest_contract_requires_registry_membership():
    context = _valid_context()
    context["strategy"] = "value"
    context["backtest_release_contract"]["strategy_registry"] = [{"strategy_id": "momentum"}]
    result = evaluate_advice_gate(context)
    assert result["allowed"] is False
    assert "invalid_strategy_registry" in result["blocking_reasons"]


def test_ready_backtest_contract_without_registry_stays_closed():
    context = _valid_context()
    context["backtest_release_contract"].pop("strategy_registry", None)
    result = evaluate_advice_gate(context)
    assert result["allowed"] is False
    assert "invalid_strategy_registry" in result["blocking_reasons"]


def test_bare_backtest_release_id_cannot_open_gate():
    context = _valid_context()
    context.pop("backtest_release_contract")
    context["backtest_release"] = "backtest-12345678"
    result = evaluate_advice_gate(context)
    assert result["allowed"] is False
    assert "invalid_backtest_release" in result["blocking_reasons"]

