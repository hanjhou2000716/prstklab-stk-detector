import json
from pathlib import Path

import pandas as pd
from jsonschema import Draft202012Validator

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


def test_research_schema_rejects_no_candidates_with_visible_rows():
    schema = json.loads(Path("schemas/research-report.schema.json").read_text(encoding="utf-8"))
    payload = {
        "schema_version": "2.0", "generated_at": "2026-08-04T10:00:00+00:00",
        "sources": [{"scan_state": "complete", "candidate_state": "no_candidates", "visible_candidates": 1}],
        "candidates": [], "health": {},
    }
    assert list(Draft202012Validator(schema).iter_errors(payload))


def test_research_schema_accepts_partial_candidates_with_history_pending():
    schema = json.loads(Path("schemas/research-report.schema.json").read_text(encoding="utf-8"))
    payload = {
        "schema_version": "2.0", "generated_at": "2026-08-04T10:00:00+00:00",
        "sources": [{"scan_state": "building", "candidate_state": "available_from_completed_records", "visible_candidates": 1, "history_pending_count": 21}],
        "candidates": [], "health": {},
    }
    assert list(Draft202012Validator(schema).iter_errors(payload)) == []
