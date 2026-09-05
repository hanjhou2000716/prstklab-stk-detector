import pandas as pd

from src.research_report import build_research_report, normalize_frame


def test_normalize_preserves_missing_strategy_fields_as_none():
    frame = pd.DataFrame([{"ticker": "NVDA", "name": "NVIDIA", "score": 88.5}])
    candidate = normalize_frame(frame, "us", "momentum")[0]
    assert candidate["market"] == "us"
    assert candidate["score"] == 88.5
    assert "structural_stop" not in candidate


def test_normalize_binds_known_instrument_and_marks_unknown_without_guessing():
    frame = pd.DataFrame([{"ticker": "2330"}, {"ticker": "3037"}])
    rows = normalize_frame(frame, "taiwan", "momentum")
    assert rows[0]["instrument_resolution"] == "resolved"
    assert rows[0]["instrument_id"] == "twse:2330"
    assert rows[0]["currency"] == "TWD"
    assert rows[1]["instrument_resolution"] == "unknown"
    assert rows[1]["instrument_id"] is None


def test_normalize_keeps_public_quote_fields_for_research_cards():
    frame = pd.DataFrame([{"ticker": "NVDA", "name": "NVIDIA", "close": 180.25, "change_percent": -1.5, "score": 88.5}])
    candidate = normalize_frame(frame, "us", "momentum")[0]
    assert candidate["close"] == 180.25
    assert candidate["change_percent"] == -1.5


def test_research_producer_stamps_explainability_and_fail_closed_advice_gate(tmp_path):
    available = tmp_path / "scan.csv"
    pd.DataFrame([{
        "ticker": "2330", "name": "TSM", "turnover": 9_000_000,
        "close": 100, "change_percent": 1.2, "roe": 18.0,
    }]).to_csv(available, index=False)
    report = build_research_report([{
        "path": str(available), "market": "taiwan", "strategy": "momentum",
    }])
    candidate = report["candidates"][0]
    assert candidate["strategy_binding"]["state"] == "observation_only"
    assert candidate["advice_gate"] == "observation_only"
    assert candidate["advice_gate_detail"]["allowed"] is False
    assert candidate["explainability"]["liquidity"] == 9_000_000
    assert candidate["explainability"]["quality_position"] == 18.0


def test_report_combines_available_sources_and_discloses_missing_ones(tmp_path):
    available = tmp_path / "taiwan.csv"
    pd.DataFrame([{"ticker": "2330", "name": "台積電", "turnover": 9_000_000, "reference_close": 100, "reference_stop": 90}]).to_csv(available, index=False)
    report = build_research_report([
        {"path": str(available), "market": "taiwan", "strategy": "price_action"},
        {"path": str(tmp_path / "missing.csv"), "market": "us", "strategy": "momentum"},
    ])
    assert report["summary"]["total_candidates"] == 1
    assert report["sources"][1]["status"] == "資料暫時無法取得"
    assert "reference_price" not in report["candidates"][0]
    assert "structural_stop" not in report["candidates"][0]


def test_empty_source_is_not_replaced_with_old_candidates(tmp_path):
    empty = tmp_path / "empty.csv"
    empty.write_text("ticker,name\n", encoding="utf-8")
    report = build_research_report([{"path": str(empty), "market": "taiwan", "strategy": "momentum"}])
    assert report["status"] == "目前沒有可整合的研究候選"
    assert report["sources"][0]["status"] == "本次無研究候選"


def test_report_preserves_full_pool_contract_fields(tmp_path):
    scan = tmp_path / "taiwan-value-scan.csv"
    pd.DataFrame([{"ticker": "2330", "name": "台積電"}]).to_csv(scan, index=False)
    summary = tmp_path / "taiwan-value-summary.json"
    summary.write_text(
        "{\"requested\":150,\"data_complete\":150,\"full_pool_expected\":150,"
        "\"scan_state\":\"complete\",\"rule_version\":\"tw_value_total_equity_quality_v3\"}",
        encoding="utf-8",
    )

    report = build_research_report([{
        "path": str(scan),
        "summary_path": str(summary),
        "market": "taiwan",
        "strategy": "value",
    }])

    assert report["sources"][0]["full_pool_expected"] == 150


def test_price_action_report_backfills_structure_match_score_from_existing_labels():
    frame = pd.DataFrame([{
        "ticker": "3037", "name": "欣興", "score": None,
        "funnel_labels": "['雙底右腳確認', '訂單塊回踩']",
    }])
    candidate = normalize_frame(frame, "taiwan", "price_action")[0]
    assert candidate["score"] == 85
