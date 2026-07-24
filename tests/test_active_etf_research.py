import pytest

from src.active_etf_research import build_research_allocation


def candidate(ticker, price, stop):
    return {"ticker": ticker, "Entry_Price": price, "Dynamic_Stop_Loss": stop}


def test_inverse_risk_weights_are_capped_and_use_all_research_capital():
    plan = build_research_allocation([
        candidate("A", 100, 99), candidate("B", 100, 90), candidate("C", 100, 80),
    ])
    weights = [item["weight_percent"] for item in plan["allocations"]]
    assert plan["status"] == "研究配置草案"
    assert max(weights) <= 45
    assert sum(weights) == pytest.approx(100, abs=0.01)
    assert plan["allocations"][0]["ticker"] == "A"


def test_one_or_two_candidates_relax_the_cap_without_idle_amount():
    one = build_research_allocation([candidate("A", 100, 90)])
    two = build_research_allocation([candidate("A", 100, 90), candidate("B", 100, 80)])
    assert one["max_weight_percent"] == 100
    assert one["allocations"][0]["weight_percent"] == 100
    assert two["max_weight_percent"] == 50
    assert sum(item["weight_percent"] for item in two["allocations"]) == pytest.approx(100, abs=0.01)


def test_invalid_structural_risk_is_excluded_instead_of_guessed():
    plan = build_research_allocation([candidate("bad", 100, 101), candidate("ok", 100, 90)])
    assert plan["skipped"] == ["bad"]
    assert [item["ticker"] for item in plan["allocations"]] == ["ok"]


def test_invalid_configurations_are_rejected():
    with pytest.raises(ValueError):
        build_research_allocation([], capital=0)
    with pytest.raises(ValueError):
        build_research_allocation([], max_weight_per_stock=0)
