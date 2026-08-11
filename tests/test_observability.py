from src.event_timeline import build_timeline
from src.health_observability import aggregate_source_health, source_state


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

