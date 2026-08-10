import pandas as pd

from src.run_value_quality_scan import candidate_state_for, load_upstream_candidates


def test_partial_scan_keeps_completed_candidates_visible():
    assert candidate_state_for([{"ticker": "2330"}], "building") == "available_from_completed_records"
    assert candidate_state_for([{"ticker": "2330"}], "partial") == "available_from_completed_records"


def test_empty_partial_scan_remains_a_data_gap():
    assert candidate_state_for([], "building") == "data_gap"
    assert candidate_state_for([], "failed") == "data_gap"
    assert candidate_state_for([], "complete") == "no_candidates"


def test_value_scan_collects_unique_upstream_candidates_and_taiwan_symbols(tmp_path):
    pd.DataFrame([{"ticker": "2330", "name": "台積電"}, {"ticker": "2317", "name": "鴻海"}]).to_csv(tmp_path / "taiwan-momentum-scan-0.csv", index=False)
    pd.DataFrame([{"ticker": "2330", "name": "台積電"}]).to_csv(tmp_path / "taiwan-price-action-scan-0.csv", index=False)
    (tmp_path / "universe.json").write_text('[{"ticker":"2330","symbol":"2330.TW"},{"ticker":"2317","symbol":"2317.TW"}]', encoding="utf-8")

    result = load_upstream_candidates("taiwan", tmp_path, str(tmp_path / "universe.json"))

    assert result == [
        {"ticker": "2330", "name": "台積電", "symbol": "2330.TW"},
        {"ticker": "2317", "name": "鴻海", "symbol": "2317.TW"},
    ]
