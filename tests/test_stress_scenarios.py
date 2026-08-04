import pytest

from src.stress_scenarios import available_scenarios, evaluate_scenario


def test_scenarios_are_non_predictive_and_have_confirmations():
    result = evaluate_scenario("technology_selloff")
    assert result.non_predictive
    assert result.confirmations
    assert "semiconductors" in result.affected_markets


def test_observed_shock_can_be_labelled_stress():
    result = evaluate_scenario("inflation_shock", observed={"oil": 0.25})
    assert result.risk_level == "stress"


def test_unknown_scenario_fails_closed():
    with pytest.raises(KeyError):
        evaluate_scenario("buy_the_dip")
    assert len(available_scenarios()) == 3
