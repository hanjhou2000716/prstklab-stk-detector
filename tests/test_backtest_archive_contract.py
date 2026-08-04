from src.backtest_archive_contract import validate_archive_manifest


def test_archive_contract_requires_all_point_in_time_datasets():
    result = validate_archive_manifest({"point_in_time": True, "survivorship_bias_checked": True,
                                        "currency_adjustment_policy": "close_to_close"},
                                       {"bars": [{"as_of": "2026-01-01"}]})
    assert result["status"] == "incomplete"
    assert "missing datasets" in result["reasons"][0]


def test_archive_contract_accepts_complete_snapshot():
    datasets = {name: [{"as_of": "2026-01-01"}] for name in ("bars", "adjustments", "dividends", "membership", "filings", "delisted", "benchmark")}
    result = validate_archive_manifest({"point_in_time": True, "survivorship_bias_checked": True,
                                        "currency_adjustment_policy": "close_to_close"}, datasets)
    assert result["status"] == "ready"
