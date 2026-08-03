from src.monitor_health import apply_monitor_health


def test_pending_reasons_are_published_without_becoming_a_data_gap():
    snapshot = {"source_health": {
        "status": "healthy",
        "summary": "所有資料來源目前可用",
        "missing_source_count": 0,
        "sources": [{"key": "market_quotes", "status": "healthy"}],
    }}
    updated = apply_monitor_health(snapshot, {
        "component": "gdelt",
        "status": "healthy",
        "checked_at": "2026-08-03T02:00:00+00:00",
        "pending_count": 2,
        "pending_reasons": {
            "waiting_second_trusted_source": 1,
            "waiting_market_sync_for_warning": 1,
        },
        "market_sync_status": "not_confirmed",
    })
    health = updated["source_health"]
    gdelt = next(item for item in health["sources"] if item["key"] == "gdelt_crosscheck")
    assert gdelt["status"] == "pending"
    assert "等待第二來源" in gdelt["issues"][0]
    assert "等待市場同步" in gdelt["issues"][1]
    assert health["missing_source_count"] == 0
    assert health["pending_event_count"] == 2


def test_failed_monitor_is_visible_as_a_partial_source():
    snapshot = {"source_health": {"sources": []}}
    updated = apply_monitor_health(snapshot, {
        "component": "gdelt",
        "status": "failed",
        "checked_at": "2026-08-03T02:00:00+00:00",
        "pending_count": 0,
        "pending_reasons": {},
        "error": "Timeout",
    })
    health = updated["source_health"]
    gdelt = next(item for item in health["sources"] if item["key"] == "gdelt_crosscheck")
    assert gdelt["status"] == "partial"
    assert "Timeout" in gdelt["issues"][0]
    assert health["missing_source_count"] == 1
