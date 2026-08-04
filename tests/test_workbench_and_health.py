from src.event_timeline import filter_events, group_versions
from src.source_health_history import summarize_source_history
from src.workbench_sections import HOME_SECTIONS, build_home_sections


def test_home_order_and_event_filters():
    assert build_home_sections({})[0]["id"] == "system_health"
    events = [{"cluster_id": "a", "market": "us", "importance": "high", "official_confirmed": True, "last_updated": "2026-01-02"}, {"cluster_id": "a", "market": "tw", "importance": "normal", "last_updated": "2026-01-01"}]
    assert filter_events(events, market="us")[0]["cluster_id"] == "a"
    assert len(group_versions(events)["a"]) == 2
    assert len(HOME_SECTIONS) == 8


def test_source_health_summary_counts_failures_and_stale_uses():
    result = summarize_source_history([{"source": "twse", "status": "ok", "latency_ms": 10, "fetched_at": "2026-01-02", "cross_checked": True}, {"source": "twse", "status": "failed", "latency_ms": 30, "stale_used": True, "error_type": "parser"}])
    assert result["twse"]["success_rate"] == 0.5
    assert result["twse"]["stale_cache_uses"] == 1
