from datetime import UTC, datetime

from src.source_health import build_source_health


def test_market_quote_health_keeps_all_unique_gap_reasons():
    health = build_source_health(
        errors=[
            {"ticker": "006208", "message": "stale", "scope": "index"},
            {"ticker": "00685L", "message": "stale", "scope": "index"},
            {"ticker": "Macro FGI", "message": "insufficient_history", "scope": "risk"},
            {"ticker": "006208", "message": "stale", "scope": "index"},
        ],
        events={},
        research_report={"sources": []},
        checked_at=datetime(2026, 9, 17, tzinfo=UTC),
    )
    market = next(item for item in health["sources"] if item["key"] == "market_quotes")
    risk = next(item for item in health["sources"] if item["key"] == "risk")
    assert market["issues"] == ["stale"]
    assert market["issue_count"] == 1
    assert risk["issues"] == ["insufficient_history"]
