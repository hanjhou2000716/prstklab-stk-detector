import pandas as pd

from datetime import datetime
from zoneinfo import ZoneInfo

from src.market_data import MACRO_REFERENCES, MARKET_INDICES, WATCHLIST, _daily_quote, _intraday_quote, annotate_quote_freshness, apply_taiwan_intraday_crosscheck, change_percent, intraday_is_fresh


def test_change_percent_calculates_and_rounds():
    assert change_percent(110, 100) == 10.0
    assert change_percent(99, 100) == -1.0


def test_change_percent_rejects_zero_baseline():
    assert change_percent(10, 0) is None


def test_watchlist_has_expected_market_coverage():
    assert len(WATCHLIST) == 7
    assert {item["market"] for item in WATCHLIST} == {"taiwan", "us"}


def test_market_indices_are_separate_from_research_watchlist():
    assert len(MARKET_INDICES) == 13
    assert {item["ticker"] for item in MARKET_INDICES} == {
        "TAIEX", "TPEx", "S&P 500", "NASDAQ", "DJIA", "SOX", "NIKKEI", "KOSPI", "BRENT", "WTI", "GOLD", "BTC", "ETH",
    }
    assert not {item["symbol"] for item in MARKET_INDICES} & {item["symbol"] for item in WATCHLIST}
    labels = {item["ticker"]: item["name"] for item in MARKET_INDICES}
    assert labels["TPEx"] == "臺灣上櫃指數"
    assert labels["BTC"] == "比特幣"
    assert labels["ETH"] == "以太坊"


def test_macro_references_are_kept_out_of_main_market_index_list():
    assert {item["ticker"] for item in MACRO_REFERENCES} == {"DXY", "US10Y", "USD/TWD"}
    assert not {item["ticker"] for item in MACRO_REFERENCES} & {item["ticker"] for item in MARKET_INDICES}


def test_intraday_quote_uses_latest_daily_close_when_today_daily_bar_is_not_available():
    item = {"symbol": "^IXIC", "ticker": "NASDAQ", "name": "那斯達克", "market": "us", "currency": "點"}
    daily = pd.Series([100.0, 105.0], index=pd.to_datetime(["2026-07-23", "2026-07-24"]))
    intraday = pd.Series([106.5], index=pd.to_datetime(["2026-07-25 09:35:00+00:00"]))

    quote = _intraday_quote(item, daily, intraday, "盤中 5 分鐘")

    assert quote["price"] == 106.5
    assert quote["change_percent"] == 1.43
    assert quote["quote_basis"] == "盤中 5 分鐘"
    assert quote["quote_time"] is not None


def test_intraday_quote_uses_penultimate_close_when_daily_data_contains_today():
    item = {"symbol": "^TWII", "ticker": "TAIEX", "name": "臺灣加權指數", "market": "taiwan", "currency": "點"}
    daily = pd.Series([100.0, 105.0], index=pd.to_datetime(["2026-07-23", "2026-07-24"]))
    intraday = pd.Series([106.5], index=pd.to_datetime(["2026-07-24 10:00:00+08:00"]))

    quote = _intraday_quote(item, daily, intraday, "盤中 5 分鐘")

    assert quote["change_percent"] == 6.5


def test_intraday_quote_includes_15_minute_move_for_continuous_five_minute_bars():
    item = {"symbol": "^SOX", "ticker": "SOX", "name": "費城半導體", "market": "us", "currency": "點"}
    daily = pd.Series([12000.0, 11800.0], index=pd.to_datetime(["2026-07-23", "2026-07-24"]))
    intraday = pd.Series(
        [11500.0, 11480.0, 11460.0, 11353.26],
        index=pd.date_range("2026-07-27 22:15:00", periods=4, freq="5min", tz="America/New_York"),
    )

    quote = _intraday_quote(item, daily, intraday, "盤中 5 分鐘")

    assert quote["change_15m_percent"] == -1.28


def test_daily_quote_is_explicitly_labelled_as_a_daily_close():
    item = {"symbol": "^IXIC", "ticker": "NASDAQ", "name": "那斯達克", "market": "us", "currency": "點"}
    daily = pd.Series([100.0, 105.0], index=pd.to_datetime(["2026-07-23", "2026-07-24"]))
    assert _daily_quote(item, daily)["quote_basis"] == "日線收盤"


def test_quotes_include_a_public_source_label():
    item = {"symbol": "^IXIC", "ticker": "NASDAQ", "name": "Nasdaq", "market": "us", "currency": "USD"}
    daily = pd.Series([100.0, 105.0], index=pd.to_datetime(["2026-07-23", "2026-07-24"]))
    assert _daily_quote(item, daily)["quote_source"] == "Yahoo Finance public daily quote"


def test_intraday_freshness_rejects_an_old_bar_but_accepts_a_recent_one():
    now = datetime(2026, 7, 24, 10, 0, tzinfo=ZoneInfo("America/New_York"))
    assert intraday_is_fresh(pd.Timestamp("2026-07-24 09:55:00", tz="America/New_York"), "us", now)
    assert not intraday_is_fresh(pd.Timestamp("2026-07-24 09:35:00", tz="America/New_York"), "us", now)
    assert not intraday_is_fresh(pd.Timestamp("2026-07-23 16:00:00", tz="America/New_York"), "us", now)


def test_taiwan_intraday_crosscheck_replaces_taiex_only_with_official_observation():
    indices, errors = apply_taiwan_intraday_crosscheck(
        [
            {"ticker": "TAIEX", "price": 41590, "change_percent": -1.0, "quote_basis": "盤中 5 分鐘"},
            {"ticker": "NASDAQ", "price": 25000},
        ],
        "交易中",
        twse_fetcher=lambda: {"price": 41600, "change": -400, "change_percent": -0.95, "quote_date": "2026-07-29", "quote_time": "2026-07-29T10:00:00+08:00"},
        taifex_fetcher=lambda: {"price": 41550, "change": -350, "change_percent": -0.84, "quote_date": "2026-07-29", "quote_time": "2026-07-29T10:00:00+08:00"},
    )
    assert errors == []
    assert indices[0]["price"] == 41600
    assert indices[0]["crosscheck_status"] == "已交叉核對"
    assert indices[1]["price"] == 25000


def test_taiwan_intraday_crosscheck_marks_partial_official_source_as_non_actionable():
    indices, errors = apply_taiwan_intraday_crosscheck(
        [{"ticker": "TAIEX", "price": 41590, "change_percent": -1.0}],
        "交易中",
        twse_fetcher=lambda: {"price": 41600, "change": -400, "change_percent": -0.95, "quote_date": "2026-07-29", "quote_time": "2026-07-29T10:00:00+08:00"},
        taifex_fetcher=lambda: None,
    )
    assert errors == []
    assert indices[0]["crosscheck_status"] == "官方來源部分缺漏"
    assert indices[0]["quote_delayed"] is True


def test_tpex_official_close_replaces_stale_yahoo_quote_even_outside_session():
    indices, errors = apply_taiwan_intraday_crosscheck(
        [{"ticker": "TPEx", "price": 378.44, "quote_date": "2026-07-17"}],
        "盤後收盤",
        tpex_fetcher=lambda: {"ticker": "TPEx", "price": 334.24, "quote_date": "2026-07-29", "quote_source": "TPEx OpenAPI official close"},
    )
    assert errors == []
    assert indices[0]["price"] == 334.24
    assert indices[0]["quote_date"] == "2026-07-29"


def test_tpex_official_close_restores_a_missing_yahoo_index_row():
    indices, errors = apply_taiwan_intraday_crosscheck(
        [{"ticker": "TAIEX", "price": 41590}],
        "收盤後",
        tpex_fetcher=lambda: {"ticker": "TPEx", "price": 334.24, "quote_date": "2026-07-29", "quote_source": "TPEx OpenAPI official close"},
    )

    assert errors == []
    assert indices[-1]["ticker"] == "TPEx"
    assert indices[-1]["price"] == 334.24


def test_tpex_unavailable_keeps_a_visible_non_actionable_row():
    indices, errors = apply_taiwan_intraday_crosscheck(
        [{"ticker": "TAIEX", "price": 41590}],
        "收盤後",
        tpex_fetcher=lambda: None,
    )

    tpex = next(item for item in indices if item["ticker"] == "TPEx")
    assert tpex["price"] is None
    assert tpex["data_status"] == "unavailable"
    assert any(error["ticker"] == "TPEx" for error in errors)


def test_unavailable_quote_is_not_classified_as_recent_close():
    quotes = annotate_quote_freshness([{"ticker": "TPEx", "price": None}])
    assert quotes[0]["freshness"] == "unavailable"


def test_stale_daily_quote_is_explicitly_marked_for_the_ui():
    quotes = annotate_quote_freshness(
        [{"ticker": "TPEx", "quote_date": "2026-07-17"}],
        now=datetime(2026, 7, 30, tzinfo=ZoneInfo("Asia/Taipei")),
    )
    assert quotes[0]["freshness"] == "stale"


def test_daily_close_becomes_stale_after_the_next_completed_taiwan_session():
    quote = {"ticker": "2330", "market": "taiwan", "price": 1000, "quote_date": "2026-07-30"}

    # Friday is a completed Taiwan session; on Saturday the Thursday close is
    # no longer the latest completed public close and must be disclosed.
    annotated = annotate_quote_freshness(
        [quote], now=datetime(2026, 8, 1, 10, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    )

    assert annotated[0]["freshness"] == "stale"


def test_daily_close_remains_recent_while_the_following_session_is_open():
    quote = {"ticker": "2330", "market": "taiwan", "price": 1000, "quote_date": "2026-07-30"}

    annotated = annotate_quote_freshness(
        [quote], now=datetime(2026, 7, 31, 10, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    )

    assert annotated[0]["freshness"] == "recent_close"
