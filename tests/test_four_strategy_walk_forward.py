import pandas as pd

from src.four_strategy_walk_forward import fixed_windows, run_walk_forward, survivorship_audit


def bars(periods=260):
    index = pd.bdate_range("2021-01-01", periods=periods)
    close = pd.Series(range(100, 100 + periods), index=index, dtype=float)
    return pd.DataFrame({"Open": close, "High": close + 2, "Low": close - 2, "Close": close, "Volume": 1_000_000}, index=index)


def config():
    return {
        "fixed_windows": {
            "training": ["2021-01-01", "2021-04-30"],
            "validation": ["2021-05-01", "2021-07-31"],
            "test": ["2021-08-01", "2021-10-31"],
        },
        "top_n": 1,
        "holding_days": 5,
        "minimum_history_days": 20,
        "costs": {"us": {"commission_rate": 0.00005, "slippage_rate": 0.005}},
        "survivorship_policy": {"require_point_in_time_universe": True},
    }


def universes(point_in_time=True):
    return [{"as_of": "2020-12-31", "market": "us", "tickers": ["AAA"], "source": "archived VOO membership", "point_in_time": point_in_time}]


def test_current_constituent_universe_is_rejected_by_survivorship_audit():
    report = survivorship_audit([{"as_of": "2025-01-01", "market": "us", "tickers": ["AAA"], "source": "current VOO members", "point_in_time": False}], market="us")
    assert report["status"] == "failed"
    assert any("current-constituent" in reason for reason in report["reasons"])


def test_fixed_windows_must_not_overlap():
    broken = config()
    broken["fixed_windows"]["validation"][0] = "2021-04-30"
    try:
        fixed_windows(broken)
    except ValueError as error:
        assert "overlap" in str(error)
    else:
        raise AssertionError("overlapping windows must fail")


def test_value_walk_forward_uses_prior_fundamental_snapshot_and_next_open_costs():
    fundamentals = [{"as_of": "2020-12-31", "market": "us", "ticker": "AAA", "point_in_time": True, "net_income": 600_000_000, "roe": 0.20, "payout_ratio": 0.30, "pe": 20, "financial_source": "SEC EDGAR archived filing"}]
    report = run_walk_forward({"AAA": bars()}, universes(), market="us", config=config(), fundamental_snapshots=fundamentals, strategies=("value",))
    assert report["status"] == "complete"
    trades = report["strategies"]["value"]["windows"]["training"]
    assert trades
    assert trades[0]["entry_date"] > trades[0]["signal_date"]
    assert trades[0]["net_return_percent"] < trades[0]["gross_return_percent"]


def test_future_published_fundamentals_are_rejected_as_data_gap():
    future = [{"as_of": "2020-12-31", "published_at": "2022-01-01T00:00:00Z", "market": "us", "ticker": "AAA", "point_in_time": True, "net_income": 600_000_000, "roe": 0.20, "payout_ratio": 0.30, "pe": 20}]
    report = run_walk_forward({"AAA": bars()}, universes(), market="us", config=config(), fundamental_snapshots=future, strategies=("value",))
    assert report["strategies"]["value"]["windows"]["training"] == []
    assert any("fundamentals unavailable" in gap["reason"] for gap in report["strategies"]["value"]["data_gaps"])


def test_value_strategy_reports_gap_instead_of_using_today_fundamentals_for_history():
    report = run_walk_forward({"AAA": bars()}, universes(), market="us", config=config(), strategies=("value",))
    assert report["strategies"]["value"]["windows"]["training"] == []
    assert any("fundamentals unavailable" in gap["reason"] for gap in report["strategies"]["value"]["data_gaps"])
