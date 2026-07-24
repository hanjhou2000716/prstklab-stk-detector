import pandas as pd

from src.research_report import build_research_report, normalize_frame


def test_normalize_preserves_missing_strategy_fields_as_none():
    frame = pd.DataFrame([{"ticker": "NVDA", "name": "NVIDIA", "score": 88.5}])
    candidate = normalize_frame(frame, "us", "momentum")[0]
    assert candidate["market"] == "us"
    assert candidate["score"] == 88.5
    assert "structural_stop" not in candidate


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
