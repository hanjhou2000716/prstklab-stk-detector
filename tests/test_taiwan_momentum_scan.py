import pandas as pd
from src.taiwan_momentum_scan import rank_records

def bars(step, volume=100000):
    close = [100 + i * step for i in range(70)]
    return pd.DataFrame({"Open": close, "High": [x+1 for x in close], "Low": [x-1 for x in close], "Close": close, "Volume": [volume]*70})

def test_ranking_filters_low_turnover_and_returns_highest_score():
    result = rank_records([{"ticker":"A", "bars":bars(1)}, {"ticker":"B", "bars":bars(2)}, {"ticker":"C", "bars":bars(1, 1)}])
    assert list(result["ticker"])[:1] == ["B"]
    assert "C" not in list(result["ticker"])
