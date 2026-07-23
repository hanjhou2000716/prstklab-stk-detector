import pandas as pd

from src.resonance_research import label, percentile, score_bars


def bars(count=160):
    prices = [100 + i * .4 for i in range(count)]
    return pd.DataFrame({"High": [p + 1 for p in prices], "Low": [p - 1 for p in prices], "Close": prices, "Volume": [1000 + i for i in range(count)]})


def test_percentile_and_labels_use_fixed_bands():
    assert percentile(pd.Series(range(120))) == 100.0
    assert label(25.9) == "極度恐慌"
    assert label(45) == "中立"
    assert label(75) == "極度貪婪"


def test_score_requires_sufficient_ohlcv_history():
    assert score_bars(bars(149)) is None
    assert score_bars(bars()) is not None
