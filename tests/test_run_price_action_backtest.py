import pandas as pd

from src.run_price_action_backtest import write_report


def test_write_report_creates_json_and_csv_artifacts(tmp_path):
    report = {"trades": [{"ticker": "TEST", "net_return_percent": 1.25}], "summary": {"count": 1}}
    json_path, csv_path = write_report(report, tmp_path)
    assert json_path.exists()
    assert csv_path.exists()
    assert pd.read_csv(csv_path).iloc[0]["ticker"] == "TEST"
