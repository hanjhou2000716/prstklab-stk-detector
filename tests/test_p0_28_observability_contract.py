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


def test_p0_28_history_contract_accepts_bounded_windows() -> None:
    from src.artifact_contract import validate_source_health

    health = {
        "status": "healthy",
        "sources": [{"key": "market_quotes", "status": "healthy"}],
        "event_scan": {"status": "no_event", "has_events": False},
        "observability": {
            "observations": 1,
            "success_rate": 100,
            "failure_count": 0,
            "no_event_count": 1,
            "stale_count": 0,
            "degraded_count": 0,
            "crosscheck_rate": 100,
            "parser_error_count": 0,
            "state": "healthy",
            "history": {
                "retention_hours": 168,
                "max_samples": 168,
                "sample_count": 1,
                "invalid_sample_count": 0,
                "last_checked_at": "2026-08-25T12:00:00+00:00",
                "windows": {
                    "24h": {"sample_count": 1, "success_rate": 100, "failure_count": 0, "no_event_count": 1, "stale_count": 0, "crosscheck_rate": 100, "parser_error_count": 0, "state": "healthy"},
                    "7d": {"sample_count": 1, "success_rate": 100, "failure_count": 0, "no_event_count": 1, "stale_count": 0, "crosscheck_rate": 100, "parser_error_count": 0, "state": "healthy"},
                },
                "samples": [{"checked_at": "2026-08-25T12:00:00+00:00", "sample_count": 1, "success_rate": 100, "failure_count": 0, "no_event_count": 1, "stale_count": 0, "crosscheck_rate": 100, "parser_error_count": 0, "state": "healthy"}],
            },
        },
    }
    assert validate_source_health(health) == []
