from datetime import datetime

from src.market_data import annotate_quote_freshness


def test_recent_close_is_visible_but_not_alert_eligible():
    rows = annotate_quote_freshness([{"ticker": "NASDAQ", "price": 1, "quote_date": datetime.now().date().isoformat()}])
    assert rows[0]["data_status"] in {"最近收盤", "盤中"}
    if rows[0]["freshness"] != "live":
        assert rows[0]["alert_eligible"] is False


def test_unavailable_status_is_explicit():
    row = annotate_quote_freshness([{"ticker": "TPEx", "price": None}])[0]
    assert row["data_status"] == "暫無資料"
    assert row["alert_eligible"] is False
