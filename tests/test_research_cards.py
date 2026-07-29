import json
from datetime import datetime
from zoneinfo import ZoneInfo

from src.research_cards import load_research_cards


def test_loader_keeps_only_public_non_actionable_full_scan_fields(tmp_path):
    report = tmp_path / "report.json"
    report.write_text(json.dumps({
        "status": "完成",
        "generated_at": "2026-07-25T10:00:00+08:00",
        "sources": [{"market": "us", "strategy": "momentum", "requested": 600, "data_complete": 590, "failed": 10, "candidates": 10}],
        "candidates": [{"market": "us", "strategy": "momentum", "rank": 1, "ticker": "NVDA", "name": "NVIDIA", "score": 90, "close": 180.25, "change_percent": -1.5, "reference_stop": 10}],
    }), encoding="utf-8")

    result = load_research_cards(report, now=datetime(2026, 7, 25, 11, 0, tzinfo=ZoneInfo("Asia/Taipei")))

    assert result["sources"][0]["requested"] == 600
    candidate = result["candidates"][0]
    assert candidate["ticker"] == "NVDA"
    assert candidate["score"] == 90
    assert candidate["close"] == 180.25
    assert candidate["change_percent"] == -1.5
    assert "reference_stop" not in candidate
    assert candidate["roe"] is None


def test_loader_hides_candidates_when_the_full_market_scan_is_expired(tmp_path):
    report = tmp_path / "report.json"
    report.write_text(json.dumps({
        "generated_at": "2026-07-25T10:00:00+08:00",
        "sources": [{"market": "us", "strategy": "momentum", "status": "資料完整"}],
        "candidates": [{"market": "us", "strategy": "momentum", "ticker": "NVDA"}],
    }), encoding="utf-8")
    result = load_research_cards(report, now=datetime(2026, 7, 27, 10, 1, tzinfo=ZoneInfo("Asia/Taipei")))
    assert result["availability"] == "expired"
    assert result["candidates"] == []
