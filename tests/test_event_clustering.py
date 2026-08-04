from datetime import UTC, datetime

from src.event_clustering import cluster_events, cluster_health


NOW = datetime(2026, 8, 4, 3, 0, tzinfo=UTC)


def event(title, url, tier="discovery", official=False, sync=None):
    return {
        "event_type": "conflict",
        "classification": "conflict",
        "title": title,
        "summary": title,
        "source_url": url,
        "source_tier": tier,
        "published_at": "2026-08-04T02:55:00Z",
        "official_confirmed": official,
        "market_sync_confirmed": sync,
    }


def test_same_event_keeps_one_cluster_and_two_sources():
    rows = cluster_events([
        event("Talks between Trump and Iran continue", "https://news.example/a"),
        event("Trump Iran talks continue", "https://reuters.com/story", tier="discovery"),
    ], now=NOW)
    assert len(rows) == 1
    assert rows[0]["evidence_count"] == 2
    assert len(rows[0]["source_domains"]) == 2
    assert rows[0]["cluster_id"]


def test_unconfirmed_conflict_exposes_both_pending_reasons():
    rows = cluster_events([event("Iran war escalation", "https://news.example/a")], now=NOW)
    assert rows[0]["crosscheck_status"] == "waiting_second_source"
    assert set(rows[0]["pending_reasons"]) == {"waiting_second_source", "waiting_market_sync"}


def test_market_sync_clears_only_sync_reason():
    rows = cluster_events([event("Iran war escalation", "https://news.example/a", sync=True)], now=NOW)
    assert rows[0]["pending_reasons"] == ["waiting_second_source"]
    assert cluster_health(rows)["pending"] == 1