from datetime import datetime

import src.taiwan_market_statistics as taiwan_statistics
from src.taiwan_market_statistics import parse_twse_market_statistics


def test_parse_twse_official_statistics_converts_roc_dates_and_keeps_provenance() -> None:
    result = parse_twse_market_statistics(
        turnover_rows=[{
            "Date": "1150907",
            "TradeVolume": "12,345,678",
            "TradeValue": "456,789,000",
            "Transaction": "987,654",
            "TAIEX": "26,500.00",
            "Change": "+123.45",
        }],
        breadth_rows=[{
            "類型": "整體市場",
            "出表日期": "115/09/07",
            "上漲": "500",
            "漲停": "20",
            "下跌": "300",
            "跌停": "10",
            "持平": "100",
            "未成交": "50",
        }],
        institution_payload={
            "stat": "OK",
            "date": "1150907",
            "fields": ["單位名稱", "買賣差額"],
            "data": [
                ["外資及陸資(不含外資自營商)", "1,000"],
                ["投信", "200"],
                ["自營商(自行買賣)", "-50"],
                ["合計", "1,150"],
            ],
        },
    )

    assert result["status"] == "complete"
    assert result["observed_date"] == "2026-09-07"
    assert result["turnover"]["trade_value"] == 456789000
    assert result["breadth"]["advancing"] == 500
    assert result["institutional_flows"]["foreign_net"] == 1000
    assert result["turnover"]["is_proxy"] is False
    assert result["institutional_flows"]["source_url"].endswith("response=json")


def test_parse_twse_statistics_is_explicitly_partial_when_one_endpoint_is_missing() -> None:
    result = parse_twse_market_statistics(
        turnover_rows=[{"Date": "20260907", "TradeValue": "100"}],
        breadth_rows=[],
        institution_payload=None,
    )
    assert result["status"] == "partial"
    assert "breadth_unavailable" in result["errors"]
    assert "institutional_flow_unavailable" in result["errors"]


def test_twse_rejects_malformed_gregorian_year_and_uses_date_not_array_position() -> None:
    result = parse_twse_market_statistics(
        turnover_rows=[
            {"Date": "20260906", "TradeValue": "100"},
            {"Date": "1150907", "TradeValue": "200"},
        ],
        breadth_rows=[], institution_payload=None, target_date="2026-09-07",
    )
    assert result["turnover"]["observed_date"] == "2026-09-07"
    assert result["turnover"]["trade_value"] == 200
    malformed = parse_twse_market_statistics(
        turnover_rows=[{"Date": "1150-09-07", "TradeValue": "200"}],
        breadth_rows=[], institution_payload=None,
    )
    assert malformed["turnover"] is None


def test_twse_does_not_publish_unreasonable_or_unverified_breadth() -> None:
    result = parse_twse_market_statistics(
        turnover_rows=[],
        breadth_rows=[{
            "類型": "整體市場", "出表日期": "20260907",
            "上漲": "3144", "下跌": "9578", "持平": "2",
        }],
        institution_payload=None,
    )
    assert result["breadth"] is None
    assert "breadth_invalid_values" in result["errors"]


def test_fetch_retries_incomplete_official_payload_without_refreshing_data_time(monkeypatch) -> None:
    class Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    complete = {
        "turnover": [{"Date": "20260907", "TradeValue": "100"}],
        "breadth": [{"類型": "整體市場", "出表日期": "20260907", "上漲": "5", "下跌": "3"}],
        "institution": {
            "stat": "OK", "date": "20260907", "fields": ["單位名稱", "買賣差額"],
            "data": [["合計", "100"]],
        },
    }
    incomplete = {**complete, "institution": None}

    class Session:
        def __init__(self):
            self.attempt = 0

        def get(self, url, **_kwargs):
            key = "turnover" if "FMTQIK" in url else "breadth" if "twtazu" in url else "institution"
            payload = incomplete[key] if self.attempt == 0 else complete[key]
            if key == "institution":
                self.attempt += 1
            return Response(payload)

    monkeypatch.setenv("TWSE_STATS_RETRY_ATTEMPTS", "1")
    monkeypatch.setenv("TWSE_STATS_RETRY_WAIT_SECONDS", "0")
    sleeps = []
    monkeypatch.setattr(taiwan_statistics.time, "sleep", sleeps.append)

    result = taiwan_statistics.fetch_twse_market_statistics(
        now=datetime(2026, 9, 7), session=Session(),
    )

    assert result["status"] == "complete"
    assert result["retry_attempt"] == 1
    assert sleeps == [0.0]
