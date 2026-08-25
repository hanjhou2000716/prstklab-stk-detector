from datetime import UTC, datetime, timedelta

from src.event_timeline import build_timeline
from src.health_observability import aggregate_source_health, source_state, summarize_health_history


def test_health_aggregate_exposes_stale_and_crosscheck_rates():
    result = aggregate_source_health([{"status": "healthy", "cross_checked": True}, {"status": "failed", "freshness": "stale", "cross_checked": False}])
    assert result["failure_count"] == 1
    assert result["stale_count"] == 1
    assert result["crosscheck_rate"] == 50.0


def test_no_event_is_successful_observation_but_failure_and_stale_are_degraded():
    result = aggregate_source_health([
        {"status": "no_event"},
        {"status": "healthy", "freshness": "stale"},
        {"status": "failed"},
    ])
    assert result["no_event_count"] == 1
    assert result["failure_count"] == 1
    assert result["stale_count"] == 1
    assert result["degraded_count"] == 2
    assert result["state"] == "partial"


def test_source_state_distinguishes_empty_from_failure():
    assert source_state(scanned=True, has_events=False)["state"] == "no_events"
    assert source_state(scanned=True, has_events=False, error="timeout")["state"] == "scan_failed"


def test_timeline_filters_and_sorts():
    rows = build_timeline([{"market": "us", "published_at": "2026-08-01"}, {"market": "tw", "published_at": "2026-08-02"}], market="tw")
    assert len(rows) == 1


def test_health_history_exposes_bounded_24h_and_7d_windows():
    now = datetime(2026, 8, 25, 12, tzinfo=UTC)
    result = summarize_health_history([
        {"checked_at": (now - timedelta(hours=2)).isoformat(), "observations": 2, "success_rate": 100, "failure_count": 0, "no_event_count": 2, "stale_count": 0, "crosscheck_rate": 50, "parser_error_count": 0},
        {"checked_at": (now - timedelta(hours=26)).isoformat(), "observations": 1, "success_rate": 0, "failure_count": 1, "no_event_count": 0, "stale_count": 1, "crosscheck_rate": 0, "parser_error_count": 1},
        {"checked_at": (now - timedelta(days=8)).isoformat(), "observations": 1, "success_rate": 0, "failure_count": 1},
        {"checked_at": "not-a-time", "observations": 1},
    ], now=now)
    assert result["sample_count"] == 2
    assert result["invalid_sample_count"] == 1
    assert result["windows"]["24h"]["failure_count"] == 0
    assert result["windows"]["7d"]["failure_count"] == 1
    assert result["windows"]["7d"]["stale_count"] == 1


def test_health_history_clamps_retention_and_sample_count():
    now = datetime(2026, 8, 25, 12, tzinfo=UTC)
    result = summarize_health_history(
        [{"checked_at": (now - timedelta(minutes=index)).isoformat(), "observations": 1, "success_rate": 100} for index in range(200)],
        now=now,
        retention_hours=999,
        max_samples=999,
    )
    assert result["retention_hours"] == 168
    assert result["max_samples"] == 168
    assert result["sample_count"] == 168

