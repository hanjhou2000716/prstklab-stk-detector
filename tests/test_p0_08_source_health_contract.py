from datetime import datetime
from zoneinfo import ZoneInfo

from src.artifact_contract import validate_source_health
from src.source_health import build_source_health

NOW = datetime(2026, 8, 13, 10, 0, tzinfo=ZoneInfo("Asia/Taipei"))


def test_clean_scan_is_no_event_and_has_no_missing_sources():
    health = build_source_health(
        errors=[],
        events={"is_major": False},
        research_report={"sources": []},
        checked_at=NOW,
    )
    assert health["event_scan"]["status"] == "no_event"
    assert health["missing_source_count"] == 0
    assert health["runtime_failure_count"] == 0


def test_failed_required_source_is_scan_failed_and_counted():
    health = build_source_health(
        errors=[{"scope": "official_event", "message": "timeout"}],
        events={"is_major": False},
        research_report={"sources": []},
        checked_at=NOW,
    )
    assert health["event_scan"]["status"] == "scan_failed"
    assert health["event_scan"]["has_events"] is False
    assert health["runtime_failure_count"] >= 1
    assert health["missing_source_count"] >= 1
    assert not validate_source_health(health)


def test_optional_configuration_gap_is_separate_from_runtime_failure():
    health = build_source_health(
        errors=[],
        events={"is_major": False},
        research_report={"sources": []},
        checked_at=NOW,
        additional_sources=[
            {
                "key": "fred",
                "status": "missing_api_key",
                "provider_status": "missing_api_key",
                "role": "optional",
            },
        ],
    )
    assert health["configuration_missing_count"] == 1
    assert health["runtime_failure_count"] == 0
    assert health["event_scan"]["status"] == "no_event"
    assert not validate_source_health(health)


def test_source_health_validator_rejects_counter_mismatch():
    document = {
        "status": "partial",
        "sources": [
            {"key": "quotes", "status": "partial", "semantic_state": "failed"},
        ],
        "event_scan": {"status": "scan_failed", "has_events": False},
        "missing_source_count": 0,
        "runtime_failure_count": 0,
        "configuration_missing_count": 0,
    }
    errors = validate_source_health(document)
    assert any("does not match" in error for error in errors)

