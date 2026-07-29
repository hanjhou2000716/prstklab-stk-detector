import json

from src.backtest_archive import audit_backtest_archive


def test_archive_audit_blocks_missing_historical_inputs(tmp_path):
    report = audit_backtest_archive(tmp_path, "taiwan")
    assert report["status"] == "incomplete"
    assert report["bar_file_count"] == 0


def test_archive_audit_accepts_point_in_time_data_with_delisted_coverage(tmp_path):
    root = tmp_path / "us"
    bars = root / "bars"
    bars.mkdir(parents=True)
    (bars / "AAA.csv").write_text("Date,Open,High,Low,Close,Volume\n2024-01-02,1,2,1,2,100\n", encoding="utf-8")
    (root / "universe.json").write_text(json.dumps([
        {"market": "us", "as_of": "2023-12-31", "tickers": ["AAA", "GONE"], "source": "archived VOO membership", "point_in_time": True}
    ]), encoding="utf-8")
    (root / "fundamentals.json").write_text(json.dumps([
        {"market": "us", "ticker": "AAA", "as_of": "2023-12-31", "point_in_time": True}
    ]), encoding="utf-8")
    (root / "manifest.json").write_text(json.dumps({
        "schema_version": "1.0", "market": "us", "bars_directory": "bars",
        "universe_snapshots": "universe.json", "fundamental_snapshots": "fundamentals.json",
        "delisted_symbols_included": True,
    }), encoding="utf-8")

    report = audit_backtest_archive(tmp_path, "us")
    assert report["status"] == "ready"
    assert report["survivorship_audit"]["status"] == "pass"
