import pytest

from src.transaction_costs import estimate_cost, net_return


def test_taiwan_includes_tax_and_round_trip_costs():
    cost = estimate_cost("taiwan", 100_000)
    assert cost.tax > 0
    assert cost.total > cost.commission
    assert net_return(0.1, cost) < 0.1


def test_us_includes_fx_and_rejects_unknown_market():
    cost = estimate_cost("us", 100_000)
    assert cost.fx > 0
    with pytest.raises(KeyError):
        estimate_cost("crypto", 100)
