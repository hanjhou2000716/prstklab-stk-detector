from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pandas_market_calendars as mcal

from src.news_freshness import qualify_market_news_date
from src.news_intelligence import build_news_intelligence


def test_publication_date_gate_rejects_missing_invalid_future_and_over_ten_days():
    reference = datetime(2026, 10, 13, 12, tzinfo=UTC)

    assert qualify_market_news_date(None, "us", reference)["reason"] == "missing_published_at"
    assert qualify_market_news_date("not-a-date", "us", reference)["reason"] == "invalid_published_at"
    assert qualify_market_news_date("2026-10-13T13:00:00+00:00", "us", reference)["reason"] == "future_published_at"
    assert qualify_market_news_date("2026-10-02T12:00:00+00:00", "us", reference)["reason"] == "outside_calendar_window"


def test_exchange_calendar_keeps_weekend_reference_and_excludes_sixth_session():
    market_zone = ZoneInfo("Asia/Taipei")
    reference = datetime(2026, 10, 10, 12, tzinfo=market_zone)
    calendar = mcal.get_calendar("XTAI")
    sessions = [
        item.date() for item in calendar.schedule(start_date="2026-09-20", end_date="2026-10-09").index
    ]
    fifth_session = datetime.combine(sessions[-5], datetime.min.time(), tzinfo=market_zone).replace(hour=12)
    sixth_session = datetime.combine(sessions[-6], datetime.min.time(), tzinfo=market_zone).replace(hour=12)
    weekend_result = qualify_market_news_date(fifth_session.isoformat(), "taiwan", reference)
    beyond_window = qualify_market_news_date(sixth_session.isoformat(), "taiwan", reference)

    assert weekend_result["eligible"] is True
    assert weekend_result["status"] == "recent_reference"
    assert weekend_result["trading_sessions"] == 5
    assert beyond_window["eligible"] is False
    assert beyond_window["reason"] == "outside_trading_session_window"


def test_news_aggregator_applies_one_date_gate_to_current_and_inventory_stories():
    reference = datetime(2026, 10, 13, 12, tzinfo=UTC)
    current = {
        "title": "Fed raises rates after new inflation report",
        "url": "https://www.federalreserve.gov/newsevents/pressreleases/a.htm",
        "published_at": "2026-10-13T11:00:00+00:00",
    }
    recent = {
        "title": "Nasdaq outlook changes after Fed meeting",
        "url": "https://news.google.com/rss/articles/recent",
        "published_at": "2026-10-09T14:00:00+00:00",
    }
    old_inventory = {
        "title": "Fed signals rates outlook after policy review",
        "url": "https://news.google.com/rss/articles/old",
        "published_at": "2026-09-13T14:00:00+00:00",
    }
    missing_inventory = {
        "title": "Fed policy decision update",
        "url": "https://www.federalreserve.gov/newsevents/pressreleases/missing.htm",
    }

    result = build_news_intelligence(
        [current], market="us", reference_time=reference,
        inventory_stories=[recent, old_inventory, missing_inventory],
    )

    assert [(item["title"], item["date_eligibility_status"]) for item in result["stories"]] == [
        (current["title"], "current"),
        (recent["title"], "recent_reference"),
    ]
    assert result["scan_summary"]["reference_time"] == reference.isoformat()
    assert result["scan_summary"]["date_eligible_current"] == 1
    assert result["scan_summary"]["date_eligible_inventory"] == 1
    assert result["scan_summary"]["date_exclusion_reasons_inventory"] == {
        "missing_published_at": 1,
        "outside_calendar_window": 1,
    }
