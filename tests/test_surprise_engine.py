from src.surprise_engine import calculate_surprise


def test_surprise_is_explicit_and_not_market_direction():
    result = calculate_surprise(expected=2.0, actual=2.5, previous=1.9, historical_std=0.25)
    assert result["status"] == "above_expectation"
    assert result["surprise_z"] == 2.0
    assert result["market_direction"] == "not_determined"

