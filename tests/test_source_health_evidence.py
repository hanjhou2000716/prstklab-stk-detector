from datetime import UTC, datetime

from src.source_health import build_source_health


def test_source_health_exposes_quote_evidence_and_stale_count() -> None:
    result = build_source_health(
        errors=[],
        events={"is_major": False},
        research_report={"sources": []},
        checked_at=datetime(2026, 8, 5, tzinfo=UTC),
        quote_evidence={
            "quotes": {"count": 1, "stale_count": 1, "alert_eligible_count": 0},
            "indices": {"count": 1, "stale_count": 0, "alert_eligible_count": 1},
        },
    )
    market = next(item for item in result["sources"] if item["key"] == "market_quotes")
    assert market["status"] == "partial"
    assert market["evidence"]["quotes"]["stale_count"] == 1
    assert result["missing_source_count"] == 1
