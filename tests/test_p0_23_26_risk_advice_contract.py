"""P0-23/P0-24/P0-26 risk and advice fail-closed contracts."""

from src.advice_gate import evaluate_advice_gate
from src.cross_asset_risk import detect_contagion
from src.market_regime import classify_regime
from src.stress_scenarios import run_stress_scenario


def test_p0_23_regime_exposes_missing_factors_and_is_non_predictive() -> None:
    result = classify_regime({"trend": 1.0, "volatility": -2.0})
    assert result["evidence_status"] == "sufficient"
    assert "breadth" in result["missing_factors"]
    assert result["non_predictive"] is True


def test_p0_23_stale_cross_asset_input_cannot_confirm_contagion() -> None:
    result = detect_contagion({
        "equities": {"change_percent": -4, "freshness": "stale"},
        "vix": {"change_percent": 12, "freshness": "live"},
    })
    assert result["contagion"] is False
    assert result["evidence_sufficient"] is False
    assert result["unusable_inputs"] == ["equities"]


def test_p0_24_stress_scenario_is_shock_observation_not_forecast() -> None:
    result = run_stress_scenario("semiconductor_shock", {"SOX": 0.5, "TSM": 0.25})
    assert result["non_predictive"] is True
    assert result["contributions"][0]["shock_percent"] == -15.0


def test_p0_26_advice_gate_refuses_missing_backtest_and_evidence() -> None:
    result = evaluate_advice_gate({"data_quality_ok": True, "general_research": True})
    assert result["allowed"] is False
    assert "no_backtest_release" in result["blocking_reasons"]
    assert result["decision_support"]["actionable"] is False
