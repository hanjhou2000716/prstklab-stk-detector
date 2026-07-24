from datetime import datetime
from zoneinfo import ZoneInfo

from src.research_health import assess_research_health


def test_health_is_green_for_fresh_available_sources():
    report = {"generated_at": "2026-07-24T09:00:00+08:00", "sources": [{"market": "taiwan", "strategy": "momentum", "status": "可用"}]}
    health = assess_research_health(report, now=datetime(2026, 7, 24, 9, 30, tzinfo=ZoneInfo("Asia/Taipei")))
    assert health["status"] == "健康"
    assert health["age_minutes"] == 30


def test_health_discloses_unavailable_and_stale_sources():
    report = {"generated_at": "2026-07-24T06:00:00+08:00", "sources": [{"market": "us", "strategy": "price_action", "status": "資料暫時無法取得"}]}
    health = assess_research_health(report, now=datetime(2026, 7, 24, 10, 0, tzinfo=ZoneInfo("Asia/Taipei")))
    assert health["status"] == "需留意"
    assert health["unavailable_sources"] == 1
    assert len(health["reasons"]) == 2
