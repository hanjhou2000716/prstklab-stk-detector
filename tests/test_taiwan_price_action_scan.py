import pandas as pd

from src.taiwan_price_action_scan import rank_records


class StubScanner:
    def scan_daily(self, bars):
        return bars.attrs.get("result")


def record(ticker, turnover):
    bars = pd.DataFrame({"Open": [1], "High": [1], "Low": [1], "Close": [1], "Volume": [1]})
    bars.attrs["result"] = {"turnover": turnover, "reference_stop": 1, "reference_close": 2}
    return {"ticker": ticker, "name": ticker, "bars": bars}


def test_price_action_candidates_are_liquidity_filtered_ranked_and_limited():
    result = rank_records([record("A", 6_000_000), record("B", 9_000_000), record("C", 4_000_000)], StubScanner())
    assert list(result["ticker"]) == ["B", "A"]


def test_empty_scan_returns_empty_frame():
    assert rank_records([record("A", 1)], StubScanner()).empty
