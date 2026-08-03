import pandas as pd

from src.price_action import PriceActionResearchScanner, structure_match_score


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
    assert result["score"] >= 85


def test_screen_returns_candidates_ranked_by_turnover_then_volume(monkeypatch):
    scanner = PriceActionResearchScanner()
    result_by_volume = {
        100: {"turnover": 1000, "reference_close": 10, "score": 80},
        200: {"turnover": 3000, "reference_close": 15, "score": 70},
    }
    monkeypatch.setattr(scanner, "scan_daily", lambda frame: result_by_volume[int(frame.iloc[0]["Volume"])])
    low = bars([{"Open": 1, "High": 1, "Low": 1, "Close": 1, "Volume": 100}])
    high = bars([{"Open": 1, "High": 1, "Low": 1, "Close": 1, "Volume": 200}])
    screened = scanner.screen({"LOW": low, "HIGH": high})
    assert list(screened["ticker"]) == ["HIGH", "LOW"]
    assert list(screened["structure_count"]) == [0, 0]


def test_screen_uses_confirmed_structure_count_after_turnover(monkeypatch):
    scanner = PriceActionResearchScanner()
    result_by_volume = {
        100: {"turnover": 3000, "volume": 100, "matched_funnels": ["Funnel_1"], "reference_close": 10, "score": 70},
        200: {"turnover": 3000, "volume": 100, "matched_funnels": ["Funnel_1", "Funnel_3"], "reference_close": 15, "score": 90},
    }
    monkeypatch.setattr(scanner, "scan_daily", lambda frame: result_by_volume[int(frame.iloc[0]["Volume"])])
    low = bars([{"Open": 1, "High": 1, "Low": 1, "Close": 1, "Volume": 100}])
    high = bars([{"Open": 1, "High": 1, "Low": 1, "Close": 1, "Volume": 200}])
    screened = scanner.screen({"ONE": low, "TWO": high})
    assert list(screened["ticker"]) == ["TWO", "ONE"]


def test_structure_match_score_rewards_confirming_funnels_without_becoming_a_forecast():
    assert structure_match_score([]) == 0
    assert structure_match_score(["Funnel_3"]) == 85
    assert structure_match_score(["Funnel_2", "Funnel_4"]) == 85


def test_strict_order_block_requires_high_volume_origin_and_impulse_before_first_revisit():
    scanner = PriceActionResearchScanner(atr_window=14, swing_window=2)
    rows = [{"Open": 100, "High": 101, "Low": 99, "Close": 100, "Volume": 100} for _ in range(35)]
    rows[20] = {"Open": 102, "High": 103, "Low": 99, "Close": 100, "Volume": 200}
    rows[21] = {"Open": 100, "High": 108, "Low": 100, "Close": 107, "Volume": 200}
    for index in range(22, 34):
        rows[index] = {"Open": 110, "High": 111, "Low": 109, "Close": 110, "Volume": 100}
    rows[34] = {"Open": 105, "High": 110, "Low": 102, "Close": 104, "Volume": 100}

    result = scanner.scan_daily(bars(rows))

    assert result is not None
    assert "Funnel_4" in result["matched_funnels"]
    assert result["score"] >= 80
