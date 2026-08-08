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


def test_loader_keeps_verified_rows_when_incremental_scan_allows_partial_candidates(tmp_path):
    report = tmp_path / "report.json"
    report.write_text(json.dumps({
        "generated_at": "2026-07-25T10:00:00+08:00",
        "sources": [{
            "market": "taiwan",
            "strategy": "value",
            "status": "建檔中",
            "scan_state": "building",
            "failed": 8,
            "partial_candidates_allowed": True,
        }],
        "candidates": [{
            "market": "taiwan",
            "strategy": "value",
            "ticker": "3023",
            "list_type": "formal",
            "condition_count": "6/6",
        }],
    }, ensure_ascii=False), encoding="utf-8")

    result = load_research_cards(report, now=datetime(2026, 7, 25, 11, 0, tzinfo=ZoneInfo("Asia/Taipei")))

    assert [item["ticker"] for item in result["candidates"]] == ["3023"]
    assert result["candidates"][0]["list_type"] == "formal"


def test_loader_preserves_explicit_candidate_counts_for_ui_state(tmp_path):
    report = tmp_path / "report.json"
    report.write_text(json.dumps({
        "generated_at": "2026-07-25T10:00:00+08:00",
        "sources": [{
            "market": "taiwan", "strategy": "value", "scan_state": "building",
            "candidate_state": "available_from_completed_records",
            "candidates": 5, "visible_candidate_count": 5,
            "formal_candidate_count": 5, "observation_candidate_count": 0,
            "history_pending_count": 21,
        }],
        "candidates": [],
    }), encoding="utf-8")

    result = load_research_cards(report, now=datetime(2026, 7, 25, 11, 0, tzinfo=ZoneInfo("Asia/Taipei")))
    source = result["sources"][0]
    assert source["candidate_state"] == "available_from_completed_records"
    assert source["visible_candidate_count"] == 5
    assert source["formal_candidate_count"] == 5
    assert source["history_pending_count"] == 21


def test_loader_preserves_explainability_and_registry_fields(tmp_path):
    report = tmp_path / "report.json"
    report.write_text(json.dumps({
        "generated_at": "2026-07-25T10:00:00+08:00",
        "sources": [{"market": "us", "strategy": "value", "status": "可用", "scan_state": "complete"}],
        "candidates": [{
            "market": "us", "strategy": "value", "ticker": "MSFT",
            "passed_conditions": "roe|cash_flow", "failed_conditions": ["valuation"],
            "risk_factors": ["earnings_gap"], "data_completeness": 96,
            "invalidation_condition": "資料逾時", "strategy_version": "value-v2",
            "data_version": "pit-2026-07-25", "backtest_release": "bt-2026-07",
        }],
    }, ensure_ascii=False), encoding="utf-8")

    result = load_research_cards(report, now=datetime(2026, 7, 25, 11, 0, tzinfo=ZoneInfo("Asia/Taipei")))
    candidate = result["candidates"][0]
    assert candidate["passed_conditions"] == "roe|cash_flow"
    assert candidate["failed_conditions"] == ["valuation"]
    assert candidate["invalidation_condition"] == "資料逾時"
    assert candidate["backtest_release"] == "bt-2026-07"
