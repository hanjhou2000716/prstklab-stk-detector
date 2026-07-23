from src.market_data import WATCHLIST, change_percent


def test_change_percent_calculates_and_rounds():
    assert change_percent(110, 100) == 10.0
    assert change_percent(99, 100) == -1.0


def test_change_percent_rejects_zero_baseline():
    assert change_percent(10, 0) is None


def test_watchlist_has_expected_market_coverage():
    assert len(WATCHLIST) == 7
    assert {item["market"] for item in WATCHLIST} == {"taiwan", "us"}
