from datetime import UTC, datetime, timedelta

from src.data_quality import QualityThresholds, score_source

NOW = datetime(2026, 8, 4, 2, 0, tzinfo=UTC)


def record(**updates):
    value = {
        "provider": "twse", "status": "healthy", "checked_at": (NOW - timedelta(minutes=5)).isoformat(),
        "latency_ms": 200, "item_count": 10, "expected_count": 10,
        "cross_checked": True, "parsing_confidence": 1.0, "consecutive_failures": 0,
    }
    value.update(updates)
    return value


def test_healthy_fresh_cross_checked_source_passes_all_gates():
    report = score_source(record(), now=NOW)
    assert report.score >= 80
    assert report.allow_display is True
    assert report.allow_alert is True
    assert report.allow_research is True
    assert report.status == "healthy"


def test_stale_source_can_display_but_cannot_alert_or_research():
    report = score_source(record(checked_at=(NOW - timedelta(hours=2)).isoformat(), cross_checked=True), now=NOW)
    assert report.allow_display is True
    assert report.allow_alert is False
    assert report.allow_research is False
    assert "stale_or_unknown_freshness" in report.reasons


def test_missing_crosscheck_blocks_alert_but_not_necessarily_research():
    report = score_source(record(cross_checked=False, cross_source_agreement=0.0), now=NOW)
    assert report.allow_alert is False
    assert report.allow_research is True
    assert "cross_source_not_confirmed" in report.reasons


def test_failed_source_is_visible_but_fail_closed():
    report = score_source(record(status="failed", item_count=0, expected_count=10, consecutive_failures=4, cross_checked=False), now=NOW)
    assert report.allow_display is True
    assert report.allow_alert is False
    assert report.allow_research is False
    assert report.status == "failed"


def test_custom_thresholds_are_applied():
    report = score_source(record(), now=NOW, thresholds=QualityThresholds(research_min_score=99))
    assert report.allow_research is False