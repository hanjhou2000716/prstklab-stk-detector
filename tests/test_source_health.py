from datetime import datetime
from zoneinfo import ZoneInfo

from src.source_health import build_source_health


NOW = datetime(2026, 7, 29, 10, 0, tzinfo=ZoneInfo("Asia/Taipei"))


def test_clean_event_scan_explicitly_says_no_event_not_a_source_failure():
    health = build_source_health(
        errors=[], events={"is_major": False}, research_report={"sources": []}, checked_at=NOW
    )
    assert health["status"] == "healthy"
    assert health["event_scan"]["status"] == "no_event"
    assert "未發現" in health["event_scan"]["detail"]


def test_failed_event_source_never_claims_no_event():
    health = build_source_health(
        errors=[{"ticker": "官方重大事件", "scope": "official_event", "message": "FED 官方來源暫時無法取得"}],
        events={"is_major": False}, research_report={"sources": []}, checked_at=NOW,
    )
    official = next(item for item in health["sources"] if item["key"] == "official_events")
    assert official["status"] == "partial"
    assert health["event_scan"]["status"] == "incomplete"
    assert "不能將本輪解讀為沒有事件" in health["event_scan"]["detail"]


def test_news_error_is_classified_as_news_not_market_quote():
    health = build_source_health(
        errors=[{"ticker": "新聞", "message": "台股新聞資料暫時無法取得"}],
        events={"is_major": False}, research_report={"sources": []}, checked_at=NOW,
    )
    news = next(item for item in health["sources"] if item["key"] == "market_news")
    quotes = next(item for item in health["sources"] if item["key"] == "market_quotes")
    assert news["status"] == "partial"
    assert quotes["status"] == "healthy"
