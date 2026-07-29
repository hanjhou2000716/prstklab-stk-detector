import pandas as pd
from src.taiwan_momentum_scan import rank_records

def bars(step, volume=200000):
    close = [100 + i * step for i in range(70)]
    return pd.DataFrame({"Open": close, "High": [x+1 for x in close], "Low": [x-1 for x in close], "Close": close, "Volume": [volume]*70})

def test_ranking_filters_low_turnover_and_returns_highest_score():
    result = rank_records([{"ticker":"A", "bars":bars(1)}, {"ticker":"B", "bars":bars(2)}, {"ticker":"C", "bars":bars(1, 1)}])
    assert list(result["ticker"])[:1] == ["B"]
    assert "C" not in list(result["ticker"])


def test_ranking_uses_thirty_million_twd_default_liquidity_gate():
    result = rank_records([{"ticker": "LOW", "bars": bars(1, 100_000)}])
    assert result.empty
