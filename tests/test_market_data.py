import pandas as pd

from datetime import datetime
from zoneinfo import ZoneInfo

from src.market_data import MARKET_INDICES, WATCHLIST, _daily_quote, _intraday_quote, change_percent, intraday_is_fresh


def test_change_percent_calculates_and_rounds():
    assert change_percent(110, 100) == 10.0
    assert change_percent(99, 100) == -1.0


def test_change_percent_rejects_zero_baseline():
    assert change_percent(10, 0) is None


def test_watchlist_has_expected_market_coverage():
    assert len(WATCHLIST) == 7
    assert {item["market"] for item in WATCHLIST} == {"taiwan", "us"}


def test_market_indices_are_separate_from_research_watchlist():
    assert len(MARKET_INDICES) == 11
    assert {item["ticker"] for item in MARKET_INDICES} == {
        "TAIEX", "TPEx", "S&P 500", "NASDAQ", "DJIA", "SOX", "NIKKEI", "KOSPI", "BRENT", "BTC", "ETH",
    }
    assert not {item["symbol"] for item in MARKET_INDICES} & {item["symbol"] for item in WATCHLIST}


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


def test_daily_quote_is_explicitly_labelled_as_a_daily_close():
    item = {"symbol": "^IXIC", "ticker": "NASDAQ", "name": "那斯達克", "market": "us", "currency": "點"}
    daily = pd.Series([100.0, 105.0], index=pd.to_datetime(["2026-07-23", "2026-07-24"]))
    assert _daily_quote(item, daily)["quote_basis"] == "日線收盤"


def test_intraday_freshness_rejects_an_old_bar_but_accepts_a_recent_one():
    now = datetime(2026, 7, 24, 10, 0, tzinfo=ZoneInfo("America/New_York"))
    assert intraday_is_fresh(pd.Timestamp("2026-07-24 09:55:00", tz="America/New_York"), "us", now)
    assert not intraday_is_fresh(pd.Timestamp("2026-07-24 09:35:00", tz="America/New_York"), "us", now)
    assert not intraday_is_fresh(pd.Timestamp("2026-07-23 16:00:00", tz="America/New_York"), "us", now)
