from src.cross_asset_risk import detect_contagion, rolling_correlation
from src.market_regime import classify_regime


def test_regime_exposes_factor_contributions():
    result = classify_regime({"trend": 1.0, "volatility": -2.0, "credit": -1.0})
    assert result["regime"] == "Stress"
    assert result["factor_contributions"]["volatility"] == -2.0


def test_contagion_requires_two_confirmations():
    assert detect_contagion({"equities": {"change_percent": -4}, "vix": {"change_percent": 12}})["contagion"] is True
    assert detect_contagion({"equities": {"change_percent": -4}})["contagion"] is False


def test_rolling_correlation_requires_full_window():
    assert rolling_correlation([1, 2], [1, 2], 3) is None
    assert rolling_correlation([1, 2, 3], [1, 2, 3], 3) == 1.0

