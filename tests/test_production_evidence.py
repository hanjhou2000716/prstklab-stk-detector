from datetime import UTC, datetime

from src.production_evidence import bind_market_evidence, quality_summary


def test_stale_quote_remains_visible_but_is_not_alert_eligible() -> None:
    items = bind_market_evidence(
        [
            {
                "ticker": "TAIEX",
                "price": 43119,
                "previous_close": 40000,
                "change_percent": 7.8,
                "quote_date": "2026-07-31",
                "freshness": "stale",
                "cross_checked": True,
                "quote_source": "TWSE official close",
            }
        ],
        now=datetime(2026, 8, 5, tzinfo=UTC),
    )
    assert len(items) == 1
    assert items[0]["price"] == 43119
    assert items[0]["alert_eligible"] is False
    assert items[0]["data_quality_score"] == 0.0


def test_fresh_cross_checked_quote_is_alert_eligible() -> None:
    items = bind_market_evidence(
        [
            {
                "ticker": "TAIEX",
                "price": 43119,
                "previous_close": 40000,
                "change_percent": 7.8,
                "quote_time": "2026-08-05T09:05:00+08:00",
                "freshness": "live",
                "cross_checked": True,
                "quote_source": "TWSE official MIS",
            }
        ],
        now=datetime(2026, 8, 5, 1, 10, tzinfo=UTC),
    )
    assert items[0]["alert_eligible"] is True
    assert items[0]["data_quality_score"] == 100


def test_quality_summary_counts_stale_and_verified_quotes() -> None:
    summary = quality_summary(
        [
            {"data_quality_score": 100, "alert_eligible": True, "quality_freshness": "live", "cross_checked": True},
            {"data_quality_score": 0, "alert_eligible": False, "quality_freshness": "stale", "cross_checked": False},
        ]
    )
    assert summary == {
        "count": 2,
        "alert_eligible_count": 1,
        "stale_count": 1,
        "cross_checked_count": 1,
        "data_quality_score": 50.0,
    }
