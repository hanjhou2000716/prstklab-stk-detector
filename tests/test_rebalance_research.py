import pytest

from src.rebalance_research import review_rebalance


def target(*pairs):
    return [{"ticker": ticker, "weight_percent": weight} for ticker, weight in pairs]


def test_weight_drift_at_threshold_triggers_manual_review():
    report = review_rebalance({"A": 55, "B": 45}, target(("A", 45), ("B", 55)))
    assert report["should_review"] is True
    assert report["max_weight_drift_percent"] == 10


def test_atr_or_correlation_regime_change_triggers_review_without_drift():
    report = review_rebalance(
        {"A": 50, "B": 50}, target(("A", 50), ("B", 50)),
        regime={"current_atr": 3, "baseline_atr": 2, "current_correlation": 0.8, "baseline_correlation": 0.5},
    )
    assert report["should_review"] is True
    assert len(report["reasons"]) == 2


def test_no_current_weights_never_invents_a_portfolio():
    report = review_rebalance({}, target(("A", 100)))
    assert report["should_review"] is False
    assert report["status"] == "尚未提供現有權重"


def test_invalid_weight_total_is_rejected():
    with pytest.raises(ValueError):
        review_rebalance({"A": 80, "B": 30}, target(("A", 50), ("B", 50)))
