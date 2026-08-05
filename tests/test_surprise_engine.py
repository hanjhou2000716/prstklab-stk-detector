from src.surprise_engine import calculate_surprise


def test_surprise_is_explicit_and_not_market_direction():
    result = calculate_surprise(
        expected=2.0, actual=2.5, previous=1.9, historical_std=0.25,
        revision=0.1, release_time="2026-08-05T08:30:00Z",
        source_url="https://www.bls.gov/",
    )
    assert result["status"] == "above_expectation"
    assert result["surprise_z"] == 2.0
    assert result["market_direction"] == "not_determined"
    assert result["revision"] == 0.1
    assert result["release_time"].endswith("Z")


def test_missing_observation_and_invalid_std_fail_closed():
    missing = calculate_surprise(expected=2.0, actual=None, historical_std=0)
    assert missing["status"] == "insufficient_evidence"
    assert missing["market_direction"] == "not_determined"
    complete = calculate_surprise(expected=2.0, actual=2.5, historical_std=0)
    assert complete["surprise_z"] is None
