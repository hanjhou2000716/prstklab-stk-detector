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


def test_news_no_event_is_not_counted_as_a_missing_source():
    health = build_source_health(
        errors=[], events={"is_major": False}, research_report={"sources": []}, checked_at=NOW,
        news_sources=[
            {"key": "news_taiwan", "status": "no_event", "item_count": 0},
            {"key": "news_us", "status": "healthy", "item_count": 3},
        ],
    )
    news = next(item for item in health["sources"] if item["key"] == "market_news")
    assert news["data_gaps"] == []
    assert health["status"] == "healthy"


def test_pristine_history_warming_is_not_reported_as_a_missing_source():
    health = build_source_health(
        errors=[], events={"is_major": False}, research_report={"sources": [{"market": "taiwan", "strategy": "value", "status": "建檔中", "history_cached": 20, "history_expected": 100}]}, checked_at=NOW,
    )
    research = next(item for item in health["sources"] if item["key"] == "research")
    assert research["status"] == "warming"
    assert "20／100" in research["issues"][0]
    assert health["status"] == "warming"
    assert health["summary"] == "璞玉價值歷史資料建檔中"
def test_completed_empty_research_is_healthy_but_explicitly_reports_no_candidates():
    health = build_source_health(
        errors=[], events={"is_major": False}, research_report={"sources": [{
            "market": "us", "strategy": "value", "status": "可用",
            "scan_state": "complete", "candidates": 0,
            "formal_candidates": 0, "observation_candidates": 0,
            "selection_diagnostics": {"records": 12, "complete_records": 12},
        }]}, checked_at=NOW,
    )
    research = next(item for item in health["sources"] if item["key"] == "research")
    assert research["status"] == "healthy"
    assert research["candidate_state"] == "no_candidates"
    assert research["candidate_count"] == 0


def test_per_source_health_is_exposed_as_a_gap_without_hiding_other_sources():
    health = build_source_health(
        errors=[], events={"is_major": False}, research_report={"sources": []}, checked_at=NOW,
        official_sources=[
            {"key": "fed", "status": "healthy", "item_count": 0},
            {"key": "bls", "status": "failed", "data_gap": "Timeout"},
        ],
    )
    official = next(item for item in health["sources"] if item["key"] == "official_events")
    assert official["status"] == "partial"
    assert len(official["data_gaps"]) == 1
    assert health["missing_source_count"] >= 1


def test_detail_sources_expose_freshness_summary_without_fabricating_failed_success():
    health = build_source_health(
        errors=[], events={"is_major": False}, research_report={"sources": []}, checked_at=NOW,
        official_sources=[
            {
                "key": "fed", "status": "healthy", "checked_at": "2026-07-29T02:00:00+00:00",
                "source_url": "https://example.test/fed", "item_count": 2,
                "latency_ms": 120,
            },
            {
                "key": "bls", "status": "failed", "checked_at": "2026-07-29T02:01:00+00:00",
                "source_url": "https://example.test/bls", "item_count": 0,
                "data_gap": "Timeout",
            },
        ],
    )
    official = next(item for item in health["sources"] if item["key"] == "official_events")
    assert official["item_count"] == 2
    assert official["last_success_at"] == "2026-07-29T02:00:00+00:00"
    assert official["latency_ms"] == 120
    assert len(official["source_urls"]) == 2
    assert "bls" not in official.get("last_success_at", "")


def test_monitor_health_pending_reason_survives_normal_market_refresh():
    health = build_source_health(
        errors=[], events={"is_major": False}, research_report={"sources": []}, checked_at=NOW,
        monitor_health={
            "component": "gdelt",
            "checked_at": NOW.isoformat(),
            "status": "pending",
            "pending_count": 2,
            "pending_reasons": {"waiting_second_trusted_source": 2},
            "market_sync_status": "not_confirmed",
        },
    )
    gdelt = next(item for item in health["sources"] if item["key"] == "gdelt_crosscheck")
    assert gdelt["status"] == "pending"
    assert gdelt["pending_count"] == 2
    assert health["missing_source_count"] == 0


def test_research_machine_failed_state_is_not_reported_as_healthy():
    health = build_source_health(
        errors=[], events={"is_major": False}, research_report={"sources": [{
            "market": "us", "strategy": "value", "status": "failed",
            "scan_state": "failed", "candidates": 0,
            "failed_records": 3,
        }]}, checked_at=NOW,
    )
    research = next(item for item in health["sources"] if item["key"] == "research")
    assert research["semantic_state"] == "failed"
    assert research["status"] == "partial"
    assert health["missing_source_count"] >= 1


def test_research_machine_building_state_preserves_partial_progress():
    health = build_source_health(
        errors=[], events={"is_major": False}, research_report={"sources": [{
            "market": "taiwan", "strategy": "value", "status": "building",
            "scan_state": "building", "candidates": 2,
            "history_cached": 20, "history_expected": 150,
        }]}, checked_at=NOW,
    )
    research = next(item for item in health["sources"] if item["key"] == "research")
    assert research["status"] == "warming"
    assert research["semantic_state"] == "warming"
    assert "20／150" in research["issues"][0]


def test_source_health_publishes_observability_counts_for_mini_app():
    health = build_source_health(
        errors=[], events={"is_major": False}, research_report={"sources": []}, checked_at=NOW,
        additional_sources=[
            {"key": "clean", "label": "Clean", "status": "healthy", "cross_checked": True},
            {"key": "quiet", "label": "Quiet", "status": "no_event"},
            {"key": "stale", "label": "Stale", "status": "healthy", "freshness": "stale"},
        ],
    )
    metrics = health["observability"]
    assert metrics["observations"] >= 3
    assert metrics["no_event_count"] == 1
    assert metrics["stale_count"] == 1
    assert metrics["crosscheck_rate"] > 0
    assert metrics["state"] == "partial"
