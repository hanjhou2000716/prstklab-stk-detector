import pandas as pd

from src.resonance_universe import rank_records


def bars(seed: float, volume: int = 1_000_000) -> pd.DataFrame:
    close = [100 + seed + index * .1 for index in range(180)]
    return pd.DataFrame({"Open": close, "High": [item + 1 for item in close], "Low": [item - 1 for item in close], "Close": close, "Volume": [volume] * len(close)})


def test_full_universe_resonance_filters_hot_and_illiquid_records(monkeypatch):
    monkeypatch.setattr("src.resonance_universe.score_bars", lambda frame: frame.attrs["score"])
    first, second, illiquid = bars(1), bars(2), bars(3, volume=1)
    first.attrs["score"], second.attrs["score"], illiquid.attrs["score"] = 45, 20, 10

    result = rank_records([
        {"ticker": "A", "bars": first}, {"ticker": "B", "bars": second}, {"ticker": "C", "bars": illiquid},
    ], min_turnover=1_000)

    assert list(result["ticker"]) == ["B", "A"]
