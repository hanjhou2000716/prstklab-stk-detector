from src.surprise_engine import build_macro_evidence, calculate_surprise, first_market_reaction


def test_above_expected_has_explicit_evidence():
    result = calculate_surprise(actual=105, expected=100, previous=98, prior_revision=97, historical_std=2.5)
    assert result.direction == "above_expected"
    assert result.surprise == 5
    assert result.revision == 1
    assert result.surprise_z == 2


def test_missing_expected_does_not_invent_surprise():
    result = calculate_surprise(actual=105)
    assert result.surprise is None
    assert result.direction == "unknown"
    assert result.evidence == "expected_value_unavailable"


def test_reaction_reports_relative_move_without_prediction():
    reaction = first_market_reaction(before=100, after=102, benchmark_before=100, benchmark_after=101)
    assert reaction["move_percent"] == 2
    assert reaction["relative_move_percent"] == 1
    assert reaction["observed_only"] is True


def test_macro_evidence_keeps_release_and_reaction_separate():
    result = build_macro_evidence({"actual": 3.2, "expected": 3.0, "market_before": 100, "market_after": 99})
    assert result["release"]["direction"] == "above_expected"
    assert result["market_reaction"]["direction"] == "down"
    assert result["prediction"] is False