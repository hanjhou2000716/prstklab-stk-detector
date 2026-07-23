import pandas as pd

import src.resonance_scan as scan


def test_resonance_snapshot_filters_hot_scores_and_orders_low_to_high(monkeypatch):
    scores = {"A": 50.0, "B": 20.0, "C": 70.0}
    monkeypatch.setattr(scan, "download_daily_bars", lambda symbol: pd.DataFrame({"symbol": [symbol]}))
    monkeypatch.setattr(scan, "score_bars", lambda frame: scores[frame.iloc[0]["symbol"]])
    watchlist = tuple({"symbol": symbol, "ticker": symbol, "name": symbol, "market": "us"} for symbol in scores)
    result = scan.build_resonance_snapshot(watchlist)
    assert [item["ticker"] for item in result["candidates"]] == ["B", "A"]
