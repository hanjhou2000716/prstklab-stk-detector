import json
from datetime import datetime

from src.research_cards import load_research_cards


def test_research_candidate_without_backtest_is_observation_only(tmp_path):
    path = tmp_path / "research.json"
    path.write_text(json.dumps({
        "generated_at": "2026-08-09T09:00:00+08:00",
        "sources": [{"market": "taiwan", "strategy": "momentum", "scan_state": "complete"}],
        "candidates": [{
            "market": "taiwan", "strategy": "momentum", "ticker": "2330",
            "strategy_version": "1", "data_version": "d1",
        }],
    }), encoding="utf-8")

    result = load_research_cards(path, now=datetime.fromisoformat("2026-08-09T10:00:00+08:00"))
    candidate = result["candidates"][0]
    assert candidate["strategy_binding"]["state"] == "observation_only"
    assert candidate["advice_gate"] == "observation_only"
    assert candidate["explainability"]["advice_gate"]["allowed"] is False
    assert "backtest" in candidate["explainability"]["advice_gate"]["blocking_reasons"]


def test_research_candidate_with_backtest_can_be_bound(tmp_path):
    path = tmp_path / "research.json"
    path.write_text(json.dumps({
        "generated_at": "2026-08-09T09:00:00+08:00",
        "sources": [{"market": "taiwan", "strategy": "momentum", "scan_state": "complete"}],
        "candidates": [{
            "market": "taiwan", "strategy": "momentum", "ticker": "2330",
            "strategy_version": "1", "data_version": "d1", "backtest_release": "bt1",
        }],
    }), encoding="utf-8")

    candidate = load_research_cards(
        path, now=datetime.fromisoformat("2026-08-09T10:00:00+08:00")
    )["candidates"][0]
    assert candidate["strategy_binding"]["state"] == "production"
    assert candidate["explainability"]["advice_gate"]["allowed"] is False
