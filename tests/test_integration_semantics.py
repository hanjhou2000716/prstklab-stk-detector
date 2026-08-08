from datetime import datetime

import pandas as pd

from src.artifact_contract import validate_research
from src.market_data import summarize_market_freshness
from src.research_report import build_research_report


def test_market_freshness_is_mixed_when_live_and_recent_close_coexist():
    result = summarize_market_freshness([
        {"ticker": "TAIEX", "freshness": "live"},
        {"ticker": "SOX", "freshness": "recent_close"},
    ])
    assert result == {
        "overall_state": "mixed",
        "live_count": 1,
        "recent_close_count": 1,
        "stale_count": 0,
        "unavailable_count": 0,
    }


def test_research_building_with_rows_is_available_from_completed_records(tmp_path):
    csv_path = tmp_path / "scan.csv"
    pd.DataFrame([{"ticker": "2330", "name": "TSM", "score": 90}]).to_csv(csv_path, index=False)
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(
        '{"requested": 150, "data_complete": 129, "failed": 0, '
        '"scan_state": "building", "history_pending": 21, '
        '"partial_candidates_allowed": true}',
        encoding="utf-8",
    )
    report = build_research_report([{
        "path": str(csv_path),
        "summary_path": str(summary_path),
        "market": "taiwan",
        "strategy": "value",
    }])
    source = report["sources"][0]
    assert source["candidate_state"] == "available_from_completed_records"
    assert source["visible_candidate_count"] == 1
    assert source["history_pending_count"] == 21
    assert source["incomplete_record_count"] == 21
    assert not validate_research({**report, "generated_at": datetime.now().isoformat(), "health": {}})
