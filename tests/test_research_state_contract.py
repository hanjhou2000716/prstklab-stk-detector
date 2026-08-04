import json

import pandas as pd

from src.research_report import build_research_report


def test_complete_empty_scan_is_no_candidates_not_data_gap(tmp_path):
    scan = tmp_path / "empty.csv"
    pd.DataFrame(columns=["ticker", "name"]).to_csv(scan, index=False)
    summary = tmp_path / "summary.json"
    summary.write_text(json.dumps({
        "requested": 10, "data_complete": 10, "failed": 0, "scan_state": "complete",
    }), encoding="utf-8")

    report = build_research_report([{
        "path": str(scan), "summary_path": str(summary),
        "market": "us", "strategy": "value",
    }])
    source = report["sources"][0]
    assert source["scan_state"] == "complete"
    assert source["candidate_state"] == "no_candidates"
    assert source["visible_candidates"] == 0
    assert source["candidates"] == source["visible_candidates"]


def test_failed_scan_is_data_gap_and_not_no_candidates(tmp_path):
    summary = tmp_path / "summary.json"
    summary.write_text(json.dumps({
        "requested": 10, "data_complete": 0, "failed": 10, "scan_state": "failed",
    }), encoding="utf-8")

    report = build_research_report([{
        "path": str(tmp_path / "missing.csv"), "summary_path": str(summary),
        "market": "us", "strategy": "value",
    }])
    source = report["sources"][0]
    assert source["scan_state"] == "failed"
    assert source["candidate_state"] == "data_gap"
    assert source["visible_candidates"] == 0
