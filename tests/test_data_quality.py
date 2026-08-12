from datetime import UTC, datetime, timedelta

from src.data_quality import QualityThresholds, freshness_state, score_source


def test_quality_marks_old_source_stale_and_not_alert_eligible() -> None:
    now = datetime(2026, 8, 5, 1, 0, tzinfo=UTC)
    result = score_source(
        {"provider": "yahoo", "status": "healthy", "fetched_at": (now - timedelta(hours=3)).isoformat(), "cross_checked": True, "completeness": 100, "parsing_confidence": 100},
        now=now,
    )
    assert result["freshness"] == "stale"
    assert result["alert_eligible"] is False
    assert "quote_stale_or_missing" in result["quality_reasons"]
    assert "quote_stale_or_missing" in result["reasons"]


def test_fresh_cross_checked_complete_source_is_alert_eligible() -> None:
    now = datetime(2026, 8, 5, 1, 0, tzinfo=UTC)
    result = score_source(
        {"provider": "twse", "status": "healthy", "fetched_at": (now - timedelta(minutes=2)).isoformat(), "cross_checked": True, "completeness": 100, "parsing_confidence": 100},
        now=now,
    )
    assert result["data_quality_score"] == 100
    assert result["alert_eligible"] is True
    assert result["quality_reasons"] == []


def test_missing_timestamp_is_unavailable_even_if_provider_says_healthy() -> None:
    freshness, age = freshness_state("", thresholds=QualityThresholds())
    assert freshness == "unavailable"
    assert age is None


def test_consecutive_source_failures_are_exposed_and_fail_closed() -> None:
    now = datetime(2026, 8, 5, 1, 0, tzinfo=UTC)
    result = score_source(
        {
            "provider": "twse",
            "status": "healthy",
            "fetched_at": (now - timedelta(minutes=2)).isoformat(),
            "last_success_at": (now - timedelta(minutes=2)).isoformat(),
            "consecutive_failures": 2,
            "cross_checked": True,
            "completeness": 100,
            "parsing_confidence": 100,
        },
        now=now,
    )
    assert result["consecutive_failures"] == 2
    assert result["last_success_at"] is not None
    assert result["alert_eligible"] is False
    assert "consecutive_failures" in result["reasons"]
