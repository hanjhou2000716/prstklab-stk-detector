"""P0-28 source-health and release observability contracts."""

from src.health_observability import aggregate_source_health, source_state
from src.production_integration import summarize_observations


def test_p0_28_health_separates_no_event_from_scan_failure() -> None:
    assert source_state(scanned=True, has_events=False)["state"] == "no_events"
    assert source_state(scanned=True, has_events=False, error="timeout")["state"] == "scan_failed"


def test_p0_28_health_aggregate_counts_stale_and_configuration_gaps() -> None:
    result = aggregate_source_health([
        {"status": "no_event"},
        {"status": "healthy", "freshness": "stale"},
        {"status": "configuration_missing"},
        {"status": "failed"},
    ])
    assert result["no_event_count"] == 1
    assert result["configuration_missing_count"] == 1
    assert result["stale_count"] == 1
    assert result["failure_count"] == 1


def test_p0_28_mixed_data_quality_is_explicit() -> None:
    result = summarize_observations([
        {"freshness": "live"},
        {"freshness": "recent_close"},
        {"freshness": "stale"},
    ])
    assert result["overall_state"] == "degraded"
    assert result["counts"]["stale"] == 1
    assert result["data_quality_score"] < 100
