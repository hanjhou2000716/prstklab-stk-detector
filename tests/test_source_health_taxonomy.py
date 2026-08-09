from datetime import datetime, timezone

from src.source_health import build_source_health


def _health(additional_sources=None, errors=None):
    return build_source_health(
        errors=errors or [],
        events={"is_major": False},
        research_report={"sources": []},
        checked_at=datetime.now(timezone.utc),
        additional_sources=additional_sources,
    )


def test_missing_key_is_configuration_required_not_core_failure():
    health = _health([{"key": "fred", "label": "FRED", "status": "missing_api_key"}])
    item = next(item for item in health["sources"] if item["key"] == "fred")
    assert item["state"] == "configuration_required"
    assert health["state_counts"]["configuration_required"] == 1


def test_no_event_and_failed_scan_are_distinct():
    health = _health(errors=[{"scope": "news", "ticker": "新聞", "message": "timeout"}])
    market_news = next(item for item in health["sources"] if item["key"] == "market_news")
    assert market_news["state"] == "failed"
    assert health["event_scan"]["status"] == "incomplete"


def test_fallback_is_degraded_with_fallback():
    health = _health([{"key": "stooq", "label": "Stooq", "status": "partial", "fallback_used": True}])
    item = next(item for item in health["sources"] if item["key"] == "stooq")
    assert item["state"] == "degraded_with_fallback"
