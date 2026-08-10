import json

import requests

from src.taiwan_universe import (
    TPEX_CLOSE_URL,
    TWSE_OPENAPI_URL,
    fetch_taiwan_universe,
    load_or_fetch_taiwan_universe,
    parse_isin_table,
    parse_tpex_daily_close_records,
    parse_twse_openapi_records,
)


def test_isin_parser_keeps_only_four_digit_ordinary_shares():
    html = """<table><tr><th>名稱</th><th>a</th><th>b</th><th>c</th><th>類別</th></tr>
    <tr><td>2330 台積電</td><td></td><td></td><td></td><td>半導體業</td></tr>
    <tr><td>12345 排除</td><td></td><td></td><td></td><td>其他</td></tr>
    <tr><td>1234 權證</td><td></td><td></td><td></td><td>權證</td></tr></table>"""
    assert parse_isin_table(html, ".TW") == [{"ticker": "2330", "name": "台積電", "symbol": "2330.TW", "category": "半導體業"}]


def test_same_run_universe_snapshot_is_reused(tmp_path, monkeypatch):
    saved = [{"ticker": "2330", "name": "台積電", "symbol": "2330.TW", "category": "半導體業"}]
    path = tmp_path / "universe.json"
    path.write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr("src.taiwan_universe.fetch_taiwan_universe", lambda: (_ for _ in ()).throw(requests.RequestException()))
    assert load_or_fetch_taiwan_universe(path) == saved


def test_official_parsers_keep_ordinary_shares_only():
    listed = parse_twse_openapi_records([
        {"公司代號": "2330", "公司簡稱": "台積電", "產業別": "半導體"},
        {"公司代號": "0050", "公司簡稱": "元大台灣50 ETF", "產業別": "ETF"},
    ])
    otc = parse_tpex_daily_close_records([
        {"SecuritiesCompanyCode": "6488", "CompanyName": "環球晶"},
        {"SecuritiesCompanyCode": "00679B", "CompanyName": "ETF"},
    ])
    assert listed == [{"ticker": "2330", "name": "台積電", "symbol": "2330.TW", "category": "半導體"}]
    assert otc == [{"ticker": "6488", "name": "環球晶", "symbol": "6488.TWO", "category": "TPEx ordinary share"}]


class _Response:
    def __init__(self, text="", payload=None):
        self.text = text
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _OfficialFallbackSession:
    def get(self, url, **_kwargs):
        if "isin.twse.com.tw" in url:
            return _Response("<html>no table</html>")
        if url == TWSE_OPENAPI_URL:
            return _Response(payload=[{"公司代號": "2330", "公司簡稱": "台積電"}])
        if url == TPEX_CLOSE_URL:
            return _Response(payload=[{"SecuritiesCompanyCode": "6488", "CompanyName": "環球晶"}])
        raise AssertionError(url)


def test_universe_falls_back_to_official_openapi_when_isin_shape_changes():
    items = fetch_taiwan_universe(_OfficialFallbackSession())
    assert {item["symbol"] for item in items} == {"2330.TW", "6488.TWO"}
