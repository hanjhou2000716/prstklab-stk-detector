import pandas as pd

from src.momentum_research import build_momentum_snapshot, features


def frame(multiplier=1):
    closes = [100 + multiplier * index for index in range(70)]
    return pd.DataFrame({"Open": closes, "High": [v + 2 for v in closes], "Low": [v - 2 for v in closes], "Close": closes, "Volume": [100] * 70})


def test_features_requires_sixty_one_bars():
    assert features(frame().iloc[:60]) is None
    assert features(frame()) is not None


def test_momentum_snapshot_ranks_available_watchlist():
    items = (
        {"symbol": "A", "ticker": "A", "name": "A", "market": "us"},
        {"symbol": "B", "ticker": "B", "name": "B", "market": "us"},
    )
    snapshot = build_momentum_snapshot(items, downloader=lambda symbol: frame(2 if symbol == "B" else 1))
    assert snapshot["status"] == "動能研究排序"
    assert snapshot["candidates"][0]["ticker"] == "B"
