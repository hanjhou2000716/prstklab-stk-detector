from __future__ import annotations

import pandas as pd

from src.taiwan_macro_sources import (
    fetch_official_taiwan_components,
    parse_cbc_html_history,
    parse_official_index_history,
)


def test_official_index_parser_accepts_roc_dates_and_chinese_index_field():
    frame = parse_official_index_history({
        "fields": ["日期", "發行量加權股價指數"],
        "data": [["115/09/16", "45,880.95"]],
    })

    assert list(frame.index) == [pd.Timestamp("2026-09-16")]
    assert frame.iloc[0]["Close"] == 45880.95


def test_official_component_fetch_runs_tpex_and_market_history_for_each_month():
    class Response:
        text = "<html></html>"

        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class Session:
        def __init__(self):
            self.calls = []

        def get(self, url, **kwargs):
            self.calls.append(("GET", url, kwargs))
            if "cbc.gov.tw" in url:
                return Response([])
            if "FMTQIK" in url:
                return Response({
                    "fields": ["日期", "成交金額"],
                    "data": [["115/09/16", "1000000"]],
                })
            return Response({
                "fields": ["日期", "發行量加權股價指數"],
                "data": [["115/09/16", "45880.95"]],
            })

        def post(self, url, **kwargs):
            self.calls.append(("POST", url, kwargs))
            return Response({
                "fields": ["日期", "指數"],
                "data": [["115/09/16", "250.0"]],
            })

    session = Session()
    result = fetch_official_taiwan_components(session=session, months=2)

    assert len(result["^TWII"]) == 1
    assert len(result["^TWOII"]) == 1
    assert len(result["TAIEX_VOLUME"]) == 1
    assert sum("indexInfo/inx" in url for method, url, _ in session.calls if method == "POST") == 2
    assert sum("FMTQIK" in url for method, url, _ in session.calls if method == "GET") == 2


def test_official_index_parser_accepts_current_tpex_nested_table_and_close_field():
    frame = parse_official_index_history({
        "date": "20260901",
        "tables": [{
            "fields": ["日期", "開市", "最高", "最低", "收市", "漲/跌"],
            "data": [["2026/09/16", "390.02", "399.80", "390.02", "399.21", "10.48"]],
        }],
    })

    assert list(frame.index) == [pd.Timestamp("2026-09-16")]
    assert frame.iloc[0]["Close"] == 399.21


def test_cbc_annual_html_parser_accepts_date_and_ntd_usd_table():
    frame = parse_cbc_html_history("""
        <table>
          <thead><tr><th>Date</th><th>NTD/USD</th></tr></thead>
          <tbody>
            <tr><td>2025/1/2</td><td>32.868</td></tr>
            <tr><td>2025/1/3</td><td>32.917</td></tr>
          </tbody>
        </table>
    """)

    assert len(frame) == 2
    assert frame.iloc[0]["Close"] == 32.868
