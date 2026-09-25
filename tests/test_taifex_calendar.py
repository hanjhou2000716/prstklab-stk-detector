from datetime import date, datetime
from pathlib import Path

from src.market_data import get_market_status
from src.scheduled_delivery import _resolve_delivery_obligation
from src.taifex_calendar import get_taifex_index_futures_status


def test_taifex_calendar_confirms_september_holidays_and_next_session():
    sep_25 = get_taifex_index_futures_status(
        date(2026, 9, 25), now=datetime.fromisoformat("2026-09-25T07:00:00+08:00"),
    )
    sep_28 = get_taifex_index_futures_status(
        date(2026, 9, 28), now=datetime.fromisoformat("2026-09-28T07:00:00+08:00"),
    )
    sep_29 = get_taifex_index_futures_status(
        date(2026, 9, 29), now=datetime.fromisoformat("2026-09-29T07:00:00+08:00"),
    )

    assert sep_25["calendar_status"] == "confirmed_closed"
    assert sep_25["closure_reason"] == "中秋節休市"
    assert sep_25["next_trading_date"] == "2026-09-29"
    assert sep_28["calendar_status"] == "confirmed_closed"
    assert sep_28["closure_reason"] == "孔子誕辰紀念日／教師節休市"
    assert sep_28["next_trading_date"] == "2026-09-29"
    assert sep_29["calendar_status"] == "confirmed_open"
    assert sep_29["calendar_provider"] == "TAIFEX"
    assert sep_29["calendar_version"] == "TAIFEX-2026"


def test_taifex_ad_hoc_typhoon_closure_is_not_inferred_from_weekday():
    result = get_taifex_index_futures_status(
        date(2026, 7, 10), now=datetime.fromisoformat("2026-07-10T08:00:00+08:00"),
    )
    assert date(2026, 7, 10).weekday() == 4
    assert result["is_trading_day"] is False
    assert result["closure_reason"] == "巴威颱風公告臨時休市"
    assert any("idx=17137" in url for url in result["calendar_source_urls"])


def test_preopen_holiday_decision_uses_independent_cash_and_taifex_calendars():
    slot_date = date(2026, 9, 28)
    cash = get_market_status("taiwan", slot_date)
    futures = get_taifex_index_futures_status(
        slot_date, now=datetime.fromisoformat("2026-09-28T07:00:00+08:00"),
    )
    obligation, reason, calendar_states = _resolve_delivery_obligation(
        {"markets": {"taiwan_cash": {
            **cash,
            "calendar_provider": "pandas_market_calendars",
            "calendar_basis": "pandas_market_calendars:XTAI",
        }, "taiwan_futures": futures}},
        "pre_open",
        {"slot_date": slot_date.isoformat(), "delivery_intent": "notify_candidate"},
        notification_requested=True,
    )

    assert cash["calendar"] == "XTAI"
    assert cash["is_trading_day"] is False
    assert futures["calendar"] == "TAIFEX"
    assert futures["is_trading_day"] is False
    assert (obligation, reason) == ("holiday_notice_required", "taiwan_exchange_holiday")
    assert [state["calendar_provider"] for state in calendar_states] == [
        "pandas_market_calendars", "TAIFEX",
    ]


def test_taifex_session_boundaries_are_explicit():
    before_open = get_taifex_index_futures_status(
        date(2026, 9, 29), now=datetime.fromisoformat("2026-09-29T08:44:59+08:00"),
    )
    open_at = get_taifex_index_futures_status(
        date(2026, 9, 29), now=datetime.fromisoformat("2026-09-29T08:45:00+08:00"),
    )
    close_at = get_taifex_index_futures_status(
        date(2026, 9, 29), now=datetime.fromisoformat("2026-09-29T13:45:00+08:00"),
    )
    after_close = get_taifex_index_futures_status(
        date(2026, 9, 29), now=datetime.fromisoformat("2026-09-29T13:45:01+08:00"),
    )
    assert before_open["session"] == "開盤前"
    assert open_at["session"] == "交易中"
    assert close_at["session"] == "交易中"
    assert after_close["session"] == "收盤後"


def test_taifex_calendar_fails_closed_outside_verified_year_and_on_bad_file(tmp_path: Path):
    future_year = get_taifex_index_futures_status(
        date(2027, 1, 4), now=datetime.fromisoformat("2027-01-04T08:00:00+08:00"),
    )
    missing_file = get_taifex_index_futures_status(
        date(2026, 9, 29),
        now=datetime.fromisoformat("2026-09-29T08:00:00+08:00"),
        calendar_path=tmp_path / "missing.json",
    )
    assert future_year["calendar_status"] == "unverified"
    assert future_year["is_trading_day"] is None
    assert future_year["calendar_error"] == "taifex_calendar_invalid:calendar_year_not_published"
    assert missing_file["calendar_status"] == "unverified"
    assert missing_file["is_trading_day"] is None
