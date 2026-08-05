import pytest

from src.stress_scenarios import run_stress_scenario


def test_stress_scenario_is_transparent_and_non_predictive():
    result = run_stress_scenario("semiconductor_shock", {"SOX": 0.5, "TSM": 0.25, "CASH": 0.25})
    assert result["estimated_weighted_effect"] == -0.105
    assert result["non_predictive"] is True
    assert result["risk_level"] == "normal"
    assert result["contributions"][0]["shock_percent"] == -15.0


def test_unknown_scenario_fails_closed():
    with pytest.raises(ValueError):
        run_stress_scenario("forecast", {"NASDAQ": 1})
