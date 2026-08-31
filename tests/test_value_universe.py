import json

import pandas as pd
import requests

from src.value_fundamentals import sec_fundamentals, sec_value_metrics
from src.value_review import review_public_pool, score_public_fundamentals
from src.value_universe import (
    _yuanta_pcf_rows,
    fetch_taiwan_official_share_records,
    fetch_us_value_universe,
    parse_sp500_constituents,
    parse_vanguard_holdings,
    parse_yuanta_holdings,
)


def test_taiwan_official_share_records_use_one_issued_common_basis(tmp_path):
    class Response:
        def __init__(self, payload): self.payload = payload
        def raise_for_status(self): return None
        def json(self): return self.payload

    class Client:
        headers = {}
        def get(self, url, **_):
            if "tpex" in url:
                return Response([{"SecuritiesCompanyCode": "6488", "IssueShares": "1,234,000", "Date": "1150830"}])
            return Response([{"公司代號": "2330", "已發行普通股數或TDR原股發行股數": "7,523,181,742", "出表日期": "1150829"}])

    rows, errors = fetch_taiwan_official_share_records(
        [{"ticker": "2330", "symbol": "2330.TW"}, {"ticker": "6488", "symbol": "6488.TWO"}],
        session=Client(), cache_path=tmp_path / "shares.json",
    )
    assert errors == []
    assert {item["shares_basis"] for item in rows.values()} == {"issued_common_shares"}
    assert rows["2330.TW"]["shares_as_of"] == "2026-08-29"
    assert rows["6488.TWO"]["shares_source"].startswith("TPEx")


def test_taiwan_official_share_records_do_not_use_incompatible_cache(tmp_path):
    cache = tmp_path / "shares.json"
    cache.write_text('{"2330.TW":{"value":10,"shares_basis":"float_shares","fetched_at":"2026-08-30T00:00:00+00:00"}}', encoding="utf-8")
    class Client:
        headers = {}
        def get(self, *_, **__): raise requests.RequestException("offline")
    rows, errors = fetch_taiwan_official_share_records([{"ticker":"2330","symbol":"2330.TW"}], session=Client(), cache_path=cache)
    assert rows == {}
    assert any("missing" in item for item in errors)


def test_yuanta_parser_keeps_only_taiwan_common_stock_rows():
    rows = parse_yuanta_holdings([
        pd.DataFrame([["2330", "台積電"], ["TXF", "台指期貨"], ["0050", "基金"]])
    ], "0050")
    assert rows == [{"ticker": "2330", "symbol": "2330.TW", "name": "台積電", "pool": "0050", "source": "Yuanta 0050 PCF"}]


def test_vanguard_parser_reads_ticker_and_holding_columns():
    rows = parse_vanguard_holdings([pd.DataFrame({"Ticker": ["NVDA", "CASH"], "Holdings": ["NVIDIA Corp.", "Cash"]})])
    assert rows == [{"ticker": "NVDA", "symbol": "NVDA", "name": "NVIDIA Corp.", "pool": "VOO", "source": "Vanguard VOO holdings"}]


def test_sp500_proxy_parser_normalizes_class_share_symbols():
    rows = parse_sp500_constituents([
        pd.DataFrame({"Symbol": ["NVDA", "BRK.B"], "Security": ["NVIDIA", "Berkshire Hathaway"], "CIK": [1045810, 1067983]})
    ])

    assert [row["ticker"] for row in rows] == ["NVDA", "BRK-B"]
    assert all(row["pool"] == "VOO-proxy" for row in rows)
    assert rows[0]["cik"] == "1045810"


def test_yuanta_pcf_reader_uses_issuer_api_payload():
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"InKind": {"FundComposition": [
                {"stkcd": "2330", "name": "TSMC"},
                {"stkcd": "TXF", "name": "Future"},
            ]}}

    class Client:
        def get(self, *args, **kwargs):
            return Response()

    assert _yuanta_pcf_rows(Client(), "0050") == [{
        "ticker": "2330", "symbol": "2330.TW", "name": "TSMC",
        "pool": "0050", "source": "Yuanta 0050 PCF API",
    }]


def test_yuanta_pcf_reader_uses_english_name_when_provider_chinese_is_corrupt():
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"InKind": {"FundComposition": [
                {"stkcd": "2330", "name": "�Τ@", "ename": "TSMC"},
            ]}}

    class Client:
        def get(self, *args, **kwargs):
            return Response()

    assert _yuanta_pcf_rows(Client(), "0050")[0]["name"] == "TSMC"


def test_us_value_universe_is_bounded_to_nasdaq100_and_semiconductor_core():
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"aaData": [{"Symbol": "AAPL", "Name": "Apple"}, {"Symbol": "NVDA", "Name": "NVIDIA"}]}

    class Client:
        headers = {}

        def post(self, *args, **kwargs):
            return Response()

    rows, errors = fetch_us_value_universe(Client())
    assert errors == []
    assert {row["ticker"] for row in rows} >= {"AAPL", "NVDA", "AMD", "ASML"}
    assert len(rows) < 150


def test_value_score_does_not_label_one_roe_observation_as_three_year_stability():
    score, checks = score_public_fundamentals({"net_income": 6_000_000_000, "roe": .2, "roe_stable": None, "payout_ratio": .3, "pe": 15, "financial_source": "TWSE"}, "taiwan")
    assert score == 85
    assert "最新 ROE 達標" in checks
    assert "三年 ROE 穩定" not in checks


def test_sec_value_metrics_requires_three_annual_roe_observations_for_stable_label():
    def fact(values):
        return {"units": {"USD": values}}
    def annual(year, value):
        return {"fy": year, "end": f"{year}-12-31", "filed": f"{year + 1}-02-01", "fp": "FY", "form": "10-K", "val": value}
    facts = {"facts": {"us-gaap": {
        "NetIncomeLoss": fact([annual(2025, 30), annual(2024, 28), annual(2023, 25)]),
        "StockholdersEquity": fact([annual(2025, 150), annual(2024, 140), annual(2023, 130), annual(2022, 120)]),
        "PaymentsOfDividendsCommonStock": fact([annual(2025, 8)]),
    }}}
    metrics = sec_value_metrics(facts)
    assert metrics["years_available"] == 3
    assert metrics["roe_stable"] is True


def test_sec_value_metrics_uses_dei_share_count_as_turnover_fallback():
    def annual(year, value):
        return {"fy": year, "end": f"{year}-12-31", "filed": f"{year + 1}-02-01", "fp": "FY", "form": "10-K", "val": value}
    facts = {"facts": {
        "us-gaap": {"NetIncomeLoss": {"units": {"USD": [annual(2025, 30), annual(2024, 28), annual(2023, 25)]}}},
        "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [{"end": "2026-07-31", "filed": "2026-08-01", "val": 1_000_000}]}}},
    }}
    metrics = sec_value_metrics(facts)
    assert metrics["shares_outstanding"] == 1_000_000


def test_sec_fundamentals_uses_recent_cache_when_sec_is_temporarily_unavailable(tmp_path, monkeypatch):
    class Response:
        def json(self):
            return {"facts": {"us-gaap": {}}}

    class Client:
        headers = {}

    monkeypatch.setattr("src.value_fundamentals._sec_get", lambda *args, **kwargs: Response())
    cache = tmp_path / "sec-cache.json"
    first, first_errors = sec_fundamentals(["AAPL"], Client(), cik_overrides={"AAPL": "320193"}, cache_path=cache)
    assert first_errors == []
    assert first["AAPL"]["sec_cache_used"] is False

    def unavailable(*args, **kwargs):
        raise requests.HTTPError("temporary SEC outage")

    monkeypatch.setattr("src.value_fundamentals._sec_get", unavailable)
    second, second_errors = sec_fundamentals(["AAPL"], Client(), cik_overrides={"AAPL": "320193"}, cache_path=cache)
    assert second_errors == []
    assert second["AAPL"]["sec_cache_used"] is True


def test_sec_fundamentals_uses_cached_cik_when_ticker_mapping_is_unavailable(tmp_path, monkeypatch):
    class Client:
        headers = {}

    cache = tmp_path / "sec-cache.json"
    cache.write_text(
        json.dumps({
            "AEP": {
                "cik": 4904,
                "fetched_at": "2026-08-08T12:00:00+00:00",
                "metrics": {"years_available": 3},
            }
        }),
        encoding="utf-8",
    )

    def unavailable_mapping(*args, **kwargs):
        raise requests.HTTPError("SEC ticker mapping unavailable")

    monkeypatch.setattr("src.value_fundamentals.sec_ticker_ciks", unavailable_mapping)

    def unavailable_facts(*args, **kwargs):
        raise requests.HTTPError("SEC facts unavailable")

    monkeypatch.setattr("src.value_fundamentals._sec_get", unavailable_facts)
    result, errors = sec_fundamentals(["AEP"], Client(), cache_path=cache)

    assert errors == []
    assert result["AEP"]["sec_cache_used"] is True


def test_independent_pool_does_not_require_an_upstream_technical_candidate():
    rows = review_public_pool(
        [{"ticker": "2330", "name": "台積電", "symbol": "2330.TW", "pool": "0050"}],
        {"2330": {"net_income": 6_000_000_000, "roe": .2, "payout_ratio": .3, "pe": 18, "financial_source": "TWSE"}},
        {"2330.TW": {"close": 1000, "change_percent": 1.2, "as_of": "2026-07-29"}},
        "taiwan",
    )
    assert rows[0]["ticker"] == "2330"
    assert rows[0]["pool"] == "0050"


def test_taiwan_pristine_can_keep_complete_public_history_without_twse_supplemental():
    rows = review_public_pool(
        [{"ticker": "2330", "name": "TSMC", "symbol": "2330.TW", "pool": "0050"}],
        {},
        {"2330.TW": {"close": 1000, "change_percent": 1.2, "as_of": "2026-07-29"}},
        "taiwan",
        allow_missing_supplemental=True,
    )
    assert rows[0]["ticker"] == "2330"
