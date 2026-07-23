import pandas as pd

from src.price_action import PriceActionResearchScanner


def bars(rows):
    return pd.DataFrame(rows, index=pd.date_range("2026-01-01", periods=len(rows), freq="D"))


def test_prepare_indicators_marks_lower_shadow_reversal():
    scanner = PriceActionResearchScanner(atr_window=2, swing_window=1)
    frame = bars([
        {"Open": 10, "High": 11, "Low": 9, "Close": 10, "Volume": 100},
        {"Open": 10, "High": 11, "Low": 8, "Close": 10.5, "Volume": 100},
        {"Open": 10.5, "High": 12, "Low": 10, "Close": 11, "Volume": 100},
    ])
    indicators = scanner.prepare_indicators(frame)
    assert indicators.iloc[1]["ATR"] == 2.5
    assert bool(indicators.iloc[1]["Is_Reversal"]) is True


def test_fake_breakdown_that_recovers_matches_funnel_three():
    scanner = PriceActionResearchScanner(atr_window=2, swing_window=1)
    frame = bars([
        {"Open": 9, "High": 10, "Low": 8, "Close": 9, "Volume": 100},
        {"Open": 9, "High": 10, "Low": 7, "Close": 8.5, "Volume": 120},
        {"Open": 10, "High": 12, "Low": 8, "Close": 11, "Volume": 140},
        {"Open": 8, "High": 11, "Low": 6.5, "Close": 10, "Volume": 200},
    ])
    result = scanner.scan_daily(frame)
    assert result is not None
    assert "Funnel_3" in result["matched_funnels"]
    assert result["reference_stop"] < result["support_edge"]


def test_screen_returns_only_candidates_ranked_by_turnover(monkeypatch):
    scanner = PriceActionResearchScanner()
    result_by_volume = {
        100: {"turnover": 1000, "reference_close": 10},
        200: {"turnover": 3000, "reference_close": 15},
    }
    monkeypatch.setattr(scanner, "scan_daily", lambda frame: result_by_volume[int(frame.iloc[0]["Volume"])])
    low = bars([{"Open": 1, "High": 1, "Low": 1, "Close": 1, "Volume": 100}])
    high = bars([{"Open": 1, "High": 1, "Low": 1, "Close": 1, "Volume": 200}])
    screened = scanner.screen({"LOW": low, "HIGH": high})
    assert list(screened["ticker"]) == ["HIGH", "LOW"]
