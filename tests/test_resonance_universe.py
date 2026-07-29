import pandas as pd

from src.resonance_universe import rank_records


def bars(*, absorption: bool = True) -> pd.DataFrame:
    close = [100 + index * 0.05 for index in range(180)]
    frame = pd.DataFrame({
        "Open": close,
        "High": [item + 1 for item in close],
        "Low": [item - 1 for item in close],
        "Close": close,
        "Volume": [1_000_000] * len(close),
    })
    previous = len(frame) - 2
    current = len(frame) - 1
    frame.loc[previous, ["Open", "High", "Low", "Close"]] = [100, 101, 98, 100]
    frame.loc[current, ["Open", "High", "Low", "Close"]] = [100, 105, 97 if absorption else 97.1, 102]
    if absorption:
        frame.loc[current, "Volume"] = 1_300_000
    return frame


def benchmark() -> pd.DataFrame:
    return pd.DataFrame({"Close": [100.0] * 180})


def test_full_universe_prioritizes_four_conditions_then_three_condition_fallback(monkeypatch):
    monkeypatch.setattr("src.resonance_universe.score_bars", lambda _: 30.0)
    all_four, three = bars(absorption=True), bars(absorption=False)

    result = rank_records(
        [{"ticker": "FOUR", "bars": all_four}, {"ticker": "THREE", "bars": three}],
        min_turnover=1_000,
        benchmark_bars=benchmark(),
    )

    assert list(result["ticker"]) == ["FOUR", "THREE"]
    assert list(result["condition_count"]) == [4, 3]
    assert list(result["score"]) == [100, 65]
    assert result.iloc[0]["conditions_matched"][0] == "爆量吸收／長下影"


def test_full_universe_discloses_three_condition_fallback_when_alpha_is_unverified(monkeypatch):
    monkeypatch.setattr("src.resonance_universe.score_bars", lambda _: 30.0)

    result = rank_records([{"ticker": "A", "bars": bars()}], min_turnover=1_000, benchmark_bars=None)

    assert result.iloc[0]["condition_count"] == 3
    assert "相對大盤 Alpha > 0" not in result.iloc[0]["conditions_matched"]
