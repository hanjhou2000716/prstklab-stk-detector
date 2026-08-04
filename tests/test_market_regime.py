import pytest

from src.market_regime import classify_regime, evaluate_regime


def test_regime_levels_are_ordered():
    assert classify_regime(-0.9) == "Crisis"
    assert classify_regime(-0.6) == "Stress"
    assert classify_regime(-0.3) == "Risk-off"
    assert classify_regime(0) == "Neutral"
    assert classify_regime(0.6) == "Risk-on"


def test_contributions_and_partial_quality_are_visible():
    result = evaluate_regime({"index_trend": -0.8, "breadth": -0.6, "volatility": 0.8})
    assert result.regime in {"Risk-off", "Stress"}
    assert result.contributions["index_trend"] < 0
    assert "credit" in result.missing_factors
    assert result.data_quality == "partial"


def test_factor_outside_normalized_range_fails():
    with pytest.raises(ValueError):
        evaluate_regime({"index_trend": 2})