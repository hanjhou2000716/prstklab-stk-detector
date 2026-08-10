from src.cross_asset_risk import detect_contagion, rolling_correlation
from src.market_regime import classify_regime


def test_regime_exposes_factor_contributions():
    result = classify_regime({"trend": 1.0, "volatility": -2.0, "credit": -1.0})
    assert result["regime"] == "Stress"
    assert result["factor_contributions"]["volatility"] == -2.0
    assert "breadth" in result["missing_factors"]
    assert result["evidence_status"] == "sufficient"
    assert result["non_predictive"] is True


def test_contagion_requires_two_confirmations():
    confirmed = detect_contagion({"equities": {"change_percent": -4}, "vix": {"change_percent": 12}})
    assert confirmed["contagion"] is True
    assert confirmed["evidence_sufficient"] is True
    partial = detect_contagion({"equities": {"change_percent": -4}})
    assert partial["contagion"] is False
    assert "vix" in partial["missing_inputs"]


def test_rolling_correlation_requires_full_window():
    assert rolling_correlation([1, 2], [1, 2], 3) is None
    assert rolling_correlation([1, 2, 3], [1, 2, 3], 3) == 1.0

