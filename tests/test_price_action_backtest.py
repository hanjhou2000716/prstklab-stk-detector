import pandas as pd

from src.price_action_backtest import walk_forward_price_action


def bars(rows):
    return pd.DataFrame(rows, index=pd.date_range("2025-01-01", periods=len(rows), freq="D"))


class SignalAtLength:
    def __init__(self, length, stop=90):
        self.length, self.stop = length, stop

    def scan_daily(self, data):
        return {"reference_stop": self.stop} if len(data) == self.length else None


def row(open_=100, high=105, low=95, close=100):
    return {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": 1_000}


def test_walk_forward_uses_next_open_and_reaches_10r_without_future_signal_data():
    data = bars([row(), row(), row(), row(100, 205, 95, 200), row()])
    report = walk_forward_price_action(data, "TEST", "us", scanner=SignalAtLength(3), min_history=3)
    trade = report["trades"][0]
    assert trade["signal_date"] == "2025-01-03"
    assert trade["entry_date"] == "2025-01-04"
    assert trade["outcome"] == "達到10R研究目標"
    assert trade["target_10r"] == 200
    assert trade["net_return_percent"] < 100


def test_same_day_stop_and_target_is_flagged_as_ambiguous_not_assumed_profitable():
    data = bars([row(), row(), row(), row(100, 205, 85, 150), row()])
    report = walk_forward_price_action(data, "TEST", "taiwan", scanner=SignalAtLength(3), min_history=3)
    trade = report["trades"][0]
    assert trade["outcome"] == "同日停損／10R順序不明"
    assert trade["ambiguous"] is True
    assert trade["net_return_percent"] < 0


def test_signal_invalidated_before_entry_is_disclosed():
    data = bars([row(), row(), row(), row(85, 90, 80, 85), row()])
    report = walk_forward_price_action(data, "TEST", "us", scanner=SignalAtLength(3), min_history=3)
    assert report["trades"] == []
    assert report["skipped_signals"][0]["reason"] == "下一根開盤已低於結構風險邊界"


def test_free_roll_locks_half_at_5r_then_marks_remaining_half_at_cost_boundary():
    data = bars([row(), row(), row(), row(100, 151, 101, 150), row(100, 120, 95, 100), row()])
    report = walk_forward_price_action(data, "TEST", "us", scanner=SignalAtLength(3), min_history=3, free_roll_enabled=True)
    trade = report["trades"][0]
    assert trade["outcome"] == "5R後保本研究邊界"
    assert trade["target_5r"] == 150
    assert trade["free_roll_enabled"] is True
    assert 20 < trade["gross_return_percent"] < 30


def test_free_roll_same_day_cost_boundary_and_10r_is_disclosed_as_ambiguous():
    data = bars([row(), row(), row(), row(100, 151, 101, 150), row(100, 205, 95, 120), row()])
    report = walk_forward_price_action(data, "TEST", "taiwan", scanner=SignalAtLength(3), min_history=3, free_roll_enabled=True)
    trade = report["trades"][0]
    assert trade["outcome"] == "5R後保本／10R順序不明"
    assert trade["ambiguous"] is True
