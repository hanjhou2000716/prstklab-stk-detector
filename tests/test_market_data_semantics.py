from datetime import datetime

from src.market_data import annotate_quote_freshness, market_data_status


def test_aggregate_close_only_is_not_labelled_live():
    assert market_data_status({"overall_state": "close_only"}) == "最近收盤"
    assert market_data_status({"overall_state": "mixed"}) == "混合資料"


def test_recent_close_is_visible_but_not_alert_eligible():
    rows = annotate_quote_freshness([{"ticker": "NASDAQ", "price": 1, "quote_date": datetime.now().date().isoformat()}])
    assert rows[0]["data_status"] in {"最近收盤", "盤中", "資料過期"}
    if rows[0]["freshness"] != "live":
        assert rows[0]["alert_eligible"] is False


def test_unavailable_status_is_explicit():
    row = annotate_quote_freshness([{"ticker": "TPEx", "price": None}])[0]
    assert row["data_status"] == "暫無資料"
    assert row["alert_eligible"] is False
