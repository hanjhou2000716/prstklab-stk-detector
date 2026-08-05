from datetime import UTC, datetime

from src.event_source_catalog import EVENT_SOURCES, EventSource, catalog_health, source_for, validate_catalog


def test_bundled_catalog_has_valid_alert_authority_policy():
    assert validate_catalog(EVENT_SOURCES) == []


def test_discovery_source_cannot_trigger_alone():
    source = source_for("gdelt")
    assert source is not None
    assert source.can_trigger_alone is False


def test_catalog_keeps_unscanned_source_gap_visible():
    rows = catalog_health([{"key": "fed", "status": "healthy"}])
    gdelt = next(row for row in rows if row["key"] == "gdelt")
    assert gdelt["observed_status"] == "not_scanned"
    assert gdelt["data_gap"] == "source_not_scanned"


def test_catalog_distinguishes_no_event_from_failed_and_stale():
    now = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
    rows = catalog_health([
        {"key": "fed", "status": "no_event", "fetched_at": "2026-08-05T11:58:00Z"},
        {"key": "bls", "status": "failed", "fetched_at": "2026-08-05T11:59:00Z"},
        {"key": "eia", "status": "healthy", "fetched_at": "2026-08-05T08:00:00Z"},
    ], now=now)
    by_key = {row["key"]: row for row in rows}
    assert by_key["fed"]["observed_status"] == "no_event"
    assert by_key["fed"]["data_gap"] is None
    assert by_key["bls"]["observed_status"] == "failed"
    assert by_key["bls"]["data_gap"] == "scan_failed"
    assert by_key["eia"]["observed_status"] == "stale"
    assert by_key["eia"]["data_gap"] == "source_stale"


def test_catalog_rejects_discovery_source_that_can_trigger_alone():
    invalid = (EventSource("search", "discovery", "https://example.com", "discovery", 5, 45, True),)
    assert "discovery source cannot trigger alone: search" in validate_catalog(invalid)
