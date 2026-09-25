from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import requests

from src.taifex_daily import (
    TAIFEX_DAILY_API,
    _contract_is_unexpired,
    _monthly_expiry,
    fetch_latest_verified_txf,
    parse_daily_api,
    parse_daily_html,
    validated_txf_backup,
)

NOW = datetime.fromisoformat("2026-09-25T09:35:00+08:00")


def _api_row(month="202610", *, session="一般交易時段", contract="TX", day="20260924", last="48123", change="-189", percent="-0.39%"):
    return {
        "Date": day,
        "Contract": contract,
        "ContractMonth(Week)": month,
        "TradingSession": session,
        "Last": last,
        "Change": change,
        "Change%": percent,
    }


def test_openapi_selects_nearest_active_monthly_regular_day_row_only():
    payload = [
        _api_row("202611", last="48200", change="-100", percent="-0.21%"),
        _api_row("202610"),
        _api_row("202610W4", last="99999"),
        _api_row("202610", session="盤後交易時段", last="50000"),
        _api_row("202610", contract="TXO", last="50000"),
        _api_row("202610/202611", last="50000"),
    ]
    with (
        patch("src.taifex_daily._calendar_open", return_value=True),
        patch("src.taifex_daily._session_gap", return_value=1),
        patch("src.taifex_daily._contract_is_unexpired", return_value=True),
    ):
        quote = parse_daily_api(payload, now=NOW)
    assert quote is not None
    assert quote["contract_month"] == "202610"
    assert quote["price"] == 48123
    assert quote["change"] == -189
    assert quote["change_percent"] == -0.39
    assert quote["session"] == "regular"
    assert quote["quote_date"] == "2026-09-24"
    assert quote["source_url"] == TAIFEX_DAILY_API


def test_openapi_never_publishes_current_session_before_close_or_stale_rows():
    row_today = _api_row(day="20260925")
    with (
        patch("src.taifex_daily._calendar_open", return_value=True),
        patch("src.taifex_daily._session_gap", return_value=1),
        patch("src.taifex_daily._contract_is_unexpired", return_value=True),
    ):
        assert parse_daily_api([row_today], now=datetime.fromisoformat("2026-09-25T13:44:00+08:00")) is None
        assert parse_daily_api([_api_row()], now=NOW) is not None
        with patch("src.taifex_daily._session_gap", return_value=4):
            assert parse_daily_api([_api_row()], now=NOW) is None


def test_expiring_month_rolls_after_settlement_time():
    expiry = datetime.fromisoformat("2026-09-16T00:00:00+08:00").date()
    with patch("src.taifex_daily._monthly_expiry", return_value=expiry):
        assert _contract_is_unexpired(
            "202609", datetime.fromisoformat("2026-09-16T13:29:00+08:00")
        )
        assert not _contract_is_unexpired(
            "202609", datetime.fromisoformat("2026-09-16T13:30:00+08:00")
        )


def test_taifex_holiday_on_third_wednesday_rolls_expiry_forward():
    _monthly_expiry.cache_clear()

    def calendar_status(*, today, now):
        return {"calendar_status": "confirmed_closed" if today.isoformat() == "2026-09-16" else "confirmed_open"}

    with patch("src.taifex_daily.get_taifex_index_futures_status", side_effect=calendar_status):
        assert _monthly_expiry("202609").isoformat() == "2026-09-17"
    _monthly_expiry.cache_clear()


def test_official_html_parser_reads_only_the_explicit_regular_session_table():
    html = """
    <p>日期：2026/09/24</p>
    <h3>一般交易時段行情表</h3>
    <table><thead><tr><th>商品代號</th><th>到期月份(週別)</th><th>開盤價</th><th>最高價</th><th>最低價</th><th>最後成交價</th><th>漲跌價</th><th>漲跌%</th></tr></thead>
    <tbody><tr><td>TX</td><td>202610</td><td>48000</td><td>48300</td><td>47900</td><td>48123</td><td>▼189</td><td>▼0.39%</td></tr></tbody></table>
    <h3>盤後交易時段行情表</h3>
    <table><tr><th>商品代號</th><th>到期月份(週別)</th><th>開盤價</th><th>最高價</th><th>最低價</th><th>最後成交價</th><th>漲跌價</th><th>漲跌%</th></tr>
    <tr><td>TX</td><td>202610</td><td>50000</td><td>51000</td><td>49000</td><td>50500</td><td>1000</td><td>2.00%</td></tr></table>
    """
    with (
        patch("src.taifex_daily._calendar_open", return_value=True),
        patch("src.taifex_daily._session_gap", return_value=1),
        patch("src.taifex_daily._contract_is_unexpired", return_value=True),
    ):
        quote = parse_daily_html(html, now=NOW)
    assert quote is not None
    assert quote["price"] == 48123
    assert quote["change"] == -189
    assert quote["change_percent"] == -0.39
    assert quote["source_label"] == "TAIFEX日盤"


def test_html_fallback_rejects_unverified_or_expired_contract_rows():
    html = """<p>日期：2026/09/24</p><h3>一般交易時段行情表</h3><table>
    <tr><th>商品代號</th><th>到期月份</th><th>開盤價</th><th>最高價</th><th>最低價</th><th>最後成交價</th><th>漲跌價</th><th>漲跌%</th></tr>
    <tr><td>TX</td><td>202610</td><td>1</td><td>2</td><td>1</td><td>48123</td><td>-189</td><td>-0.39%</td></tr></table>"""
    with (
        patch("src.taifex_daily._calendar_open", return_value=True),
        patch("src.taifex_daily._session_gap", return_value=1),
        patch("src.taifex_daily._contract_is_unexpired", return_value=False),
    ):
        assert parse_daily_html(html, now=NOW) is None
    assert parse_daily_html("<html>unrelated page</html>", now=NOW) is None


def test_fetch_uses_official_html_only_when_openapi_has_no_verified_day_row():
    response = SimpleNamespace(
        status_code=200,
        raise_for_status=lambda: None,
        json=lambda: [_api_row()],
    )

    class Session:
        def __init__(self):
            self.calls = []

        def get(self, url, **kwargs):
            self.calls.append(url)
            return response

    session = Session()
    with (
        patch("src.taifex_daily._calendar_open", return_value=True),
        patch("src.taifex_daily._session_gap", return_value=1),
        patch("src.taifex_daily._contract_is_unexpired", return_value=True),
    ):
        quote = fetch_latest_verified_txf(session=session, now=NOW)
    assert quote is not None
    assert quote["source_url"] == TAIFEX_DAILY_API
    assert len(session.calls) == 1


def test_fetch_uses_table_fallback_after_invalid_api_and_fails_closed_if_both_fail():
    html = """<p>日期：2026/09/24</p><h3>一般交易時段行情表</h3><table>
    <tr><th>商品代號</th><th>到期月份</th><th>開盤價</th><th>最高價</th><th>最低價</th><th>最後成交價</th><th>漲跌價</th><th>漲跌%</th></tr>
    <tr><td>TX</td><td>202610</td><td>48000</td><td>48300</td><td>47900</td><td>48123</td><td>-189</td><td>-0.39%</td></tr></table>"""

    class Response:
        def __init__(self, *, body=None, text=""):
            self.body = body
            self.text = text

        def raise_for_status(self):
            return None

        def json(self):
            return self.body

    class Session:
        def __init__(self, fail=False):
            self.calls = []
            self.fail = fail

        def get(self, url, **kwargs):
            self.calls.append(url)
            if self.fail:
                raise requests.RequestException("unavailable")
            if url == TAIFEX_DAILY_API:
                return Response(body=[_api_row(session="夜盤")])
            return Response(text=html)

    with (
        patch("src.taifex_daily._calendar_open", return_value=True),
        patch("src.taifex_daily._session_gap", return_value=1),
        patch("src.taifex_daily._contract_is_unexpired", return_value=True),
    ):
        fallback_session = Session()
        quote = fetch_latest_verified_txf(session=fallback_session, now=NOW)
        failed_session = Session(fail=True)
        missing = fetch_latest_verified_txf(session=failed_session, now=NOW)
    assert quote is not None and quote["source_label"] == "TAIFEX日盤"
    assert quote["source_url"].startswith("https://www.taifex.com.tw/cht/3/futDailyMarketExcel")
    assert len(fallback_session.calls) == 2
    assert missing is None
    assert len(failed_session.calls) == 2


def test_last_known_good_requires_complete_official_contract_and_session_evidence():
    good = {
        "market_date": "2026-09-24", "observed_at": "2026-09-24T13:45:00+08:00",
        "price": 48123, "previous_close": 48312, "change": -189, "change_percent": -0.39,
        "quote_basis": "TAIFEX_TXF_DAY|contract=202610|session=regular",
        "instrument_id": "market:txf:taifex:202610:regular",
        "source_url": TAIFEX_DAILY_API,
    }

    class Store:
        def __init__(self, row):
            self.row = row

        def latest_quote(self, ticker, **kwargs):
            assert ticker == "TXF"
            assert kwargs["provider"] == "TAIFEX日盤"
            return self.row

    with (
        patch("src.taifex_daily._session_gap", return_value=1),
        patch("src.taifex_daily._calendar_open", return_value=True),
        patch("src.taifex_daily._contract_is_unexpired", return_value=True),
    ):
        backup = validated_txf_backup(Store(good), now=NOW)
        assert backup is not None and backup["backup_used"] is True
        assert validated_txf_backup(Store({**good, "quote_basis": "legacy generic quote"}), now=NOW) is None
        assert validated_txf_backup(Store({**good, "source_url": "https://openapi.taifex.com.tw.evil/v1/DailyMarketReportFut"}), now=NOW) is None
