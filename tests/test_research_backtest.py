import pytest

from src.research_backtest import calculate_hypothetical_return, evaluate_hypothetical_trades


def test_costs_reduce_a_hypothetical_positive_return():
    result = calculate_hypothetical_return(100, 110, "taiwan")
    assert result["gross_return_percent"] == 10
    assert 0 < result["net_return_percent"] < 10
    assert result["cost_drag_percent"] > 0


def test_us_and_taiwan_cost_assumptions_remain_explicit_and_distinct():
    taiwan = calculate_hypothetical_return(100, 100, "taiwan")
    us = calculate_hypothetical_return(100, 100, "us")
    assert taiwan["net_return_percent"] < us["net_return_percent"] < 0


def test_custom_cost_assumptions_can_be_used_for_a_research_scenario():
    result = calculate_hypothetical_return(100, 110, "us", commission_rate=0, slippage_rate=0)
    assert result["net_return_percent"] == 10


def test_invalid_records_are_disclosed_and_not_replaced_with_estimates():
    report = evaluate_hypothetical_trades([
        {"ticker": "ok", "market": "us", "entry_price": 100, "exit_price": 110},
        {"ticker": "bad", "market": "taiwan", "entry_price": 0, "exit_price": 110},
    ])
    assert report["summary"]["count"] == 1
    assert report["skipped"] == ["bad"]


def test_invalid_market_is_rejected():
    with pytest.raises(ValueError):
        calculate_hypothetical_return(100, 110, "crypto")
