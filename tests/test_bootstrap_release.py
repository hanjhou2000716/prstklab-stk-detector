import json

from src.bootstrap_release import BOOTSTRAP_MAX_BYTES, build_bootstrap_snapshot


def test_bootstrap_keeps_first_paint_fields_and_drops_large_history() -> None:
    market = {
        "snapshot_id": "market-12345678",
        "generated_at": "2026-09-20T01:00:00+00:00",
        "data_status": "資料可用",
        "markets": {"taiwan": {"session": "收盤"}},
        "indices": [{"ticker": "TAIEX", "price": 100, "change_percent": 1.2, "history": list(range(10000))}],
        "quotes": [{"ticker": "2330", "price": 1000, "change_percent": -0.5}],
        "macro_quotes": [{"ticker": "US10Y", "price": 4.1, "change_percent": 0.2}],
        "events": {"items": [{"notification_id": "alert-1", "title": "事件", "event": "完整事件內容"}]},
        "briefing": {"slot": "live", "public_short_message": "即時市場速報", "observations": [{"title": "觀察"}]},
        "risk": {"summary": "中性"},
        "source_health": {"status": "healthy", "sources": [{"key": "large", "payload": "不要進首屏"}]},
    }
    result = build_bootstrap_snapshot(market, release_id="release-12345678", created_at="2026-09-20T01:00:01+00:00")
    encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    assert len(encoded) < BOOTSTRAP_MAX_BYTES
    assert result["release_id"] == "release-12345678"
    assert result["snapshot_id"] == "market-12345678"
    assert result["indices"][0]["ticker"] == "TAIEX"
    assert "history" not in result["indices"][0]
    assert "sources" not in result["source_health"]


def test_bootstrap_contains_only_current_release_deep_link_rows() -> None:
    market = {"snapshot_id": "market-12345678", "events": {"items": []}}
    rows = [
        {"notification_id": "current", "release_id": "release-12345678", "path": "alerts/current.json"},
        {"notification_id": "old", "release_id": "release-old", "path": "alerts/old.json"},
    ]
    result = build_bootstrap_snapshot(
        market,
        release_id="release-12345678",
        created_at="2026-09-20T01:00:00+00:00",
        alert_index_rows=rows[:1],
    )

    assert [row["notification_id"] for row in result["alert_index"]["alerts"]] == ["current"]
