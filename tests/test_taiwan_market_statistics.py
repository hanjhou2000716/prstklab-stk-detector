from datetime import datetime

import src.taiwan_market_statistics as taiwan_statistics
from src.taiwan_market_statistics import parse_twse_market_statistics, parse_twse_mi_index_breadth


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
    assert result["turnover"]["unit"] == "元"
    assert result["turnover"]["currency"] == "TWD"
    assert result["breadth"]["advancing"] == 500
    assert result["institutional_flows"]["foreign_net"] == 1000
    assert result["institutional_flows"]["unit"] == "元"
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


def test_parse_twse_mi_index_breadth_uses_stock_column_and_preserves_source():
    payload = {
        "date": "20260916",
        "tables": [{
            "title": "\u6f32\u8dcc\u8b49\u5238\u6578\u5408\u8a08",
            "fields": ["\u985e\u578b", "\u6574\u9ad4\u5e02\u5834", "\u80a1\u7968"],
            "data": [
                ["\u4e0a\u6f32(\u6f32\u505c)", "7,321(98)", "733(24)"],
                ["\u4e0b\u8dcc(\u8dcc\u505c)", "4,558(75)", "213(0)"],
                ["\u6301\u5e73", "1,157", "120"],
                ["\u672a\u6210\u4ea4", "17,769", "8"],
            ],
        }],
    }

    rows = parse_twse_mi_index_breadth(payload)

    assert rows == [{
        "\u985e\u578b": "\u6574\u9ad4\u5e02\u5834",
        "\u51fa\u8868\u65e5\u671f": "2026-09-16",
        "\u4e0a\u6f32": 733,
        "\u6f32\u505c": 24,
        "\u4e0b\u8dcc": 213,
        "\u8dcc\u505c": 0,
        "\u6301\u5e73": 120,
        "\u672a\u6210\u4ea4": 8,
        "_source_url": taiwan_statistics.TWSE_MI_INDEX_URL,
    }]


def test_fetch_resolves_latest_completed_date_and_uses_mi_index_breadth(monkeypatch):
    class Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    turnover = [{"Date": "1150916", "TradeVolume": "100", "TradeValue": "200"}]
    mi_index = {
        "date": "20260916",
        "tables": [{
            "title": "\u6f32\u8dcc\u8b49\u5238\u6578\u5408\u8a08",
            "fields": ["\u985e\u578b", "\u6574\u9ad4\u5e02\u5834", "\u80a1\u7968"],
            "data": [
                ["\u4e0a\u6f32(\u6f32\u505c)", "7,321(98)", "733(24)"],
                ["\u4e0b\u8dcc(\u8dcc\u505c)", "4,558(75)", "213(0)"],
            ],
        }],
    }
    institution = {
        "stat": "OK",
        "date": "20260916",
        "fields": ["\u55ae\u4f4d\u540d\u7a31", "\u8cb7\u8ce3\u5dee\u984d"],
        "data": [["\u5408\u8a08", "100"]],
    }

    class Session:
        def get(self, url, **kwargs):
            if url == taiwan_statistics.TWSE_FMTQIK_URL:
                return Response(turnover)
            if url == taiwan_statistics.TWSE_BREADTH_URL:
                return Response([])
            if url == taiwan_statistics.TWSE_INSTITUTION_URL:
                assert kwargs["params"]["dayDate"] == "20260916"
                return Response(institution)
            if url == taiwan_statistics.TWSE_MI_INDEX_URL:
                assert kwargs["params"]["date"] == "20260916"
                return Response(mi_index)
            raise AssertionError(url)

    monkeypatch.setenv("TWSE_STATS_RETRY_ATTEMPTS", "0")
    result = taiwan_statistics.fetch_twse_market_statistics(
        now=datetime(2026, 9, 17, 12, 0),
        session=Session(),
    )

    assert result["status"] == "complete"
    assert result["resolved_target_date"] == "2026-09-16"
    assert result["breadth"]["advancing"] == 733
    assert result["breadth"]["scope_verified"] is True
    assert result["breadth"]["source_url"] == taiwan_statistics.TWSE_MI_INDEX_URL


def test_fetch_does_not_retry_supplementary_statistics_or_delay_the_slot(monkeypatch) -> None:
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

    result = taiwan_statistics.fetch_twse_market_statistics(
        now=datetime(2026, 9, 7), session=Session(),
    )

    assert result["status"] != "complete"
    assert result["retry_attempt"] == 0
    assert result["retry_attempts_configured"] == 0
