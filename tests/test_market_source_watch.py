from datetime import datetime, timedelta

import pytest

from src.market_source_watch import (
    TAIPEI,
    run_watch,
    watch_quote_updates,
    watch_until,
)


def test_prequeue_watch_returns_at_twelve_minute_preparation_boundary():
    current = [datetime(2026, 10, 5, 14, 20, tzinfo=TAIPEI)]
    probes = []

    def probe():
        probes.append(current[0])
        return {"cash_target_available": False, "futures_target_available": False}

    def sleep(seconds):
        current[0] += timedelta(seconds=seconds)

    result = watch_until(
        deadline=current[0] + timedelta(minutes=12),
        probe=probe,
        now=lambda: current[0],
        sleep=sleep,
    )
    assert result["status"] == "source_watch_cutoff_reached"
    assert result["attempts"] == 7
    assert probes[-1] == datetime(2026, 10, 5, 14, 32, tzinfo=TAIPEI)


def test_final_source_watch_overlaps_preparation_and_reaches_anchor_plus_twenty():
    current = [datetime(2026, 10, 5, 14, 32, tzinfo=TAIPEI)]
    probes = []

    def probe():
        probes.append(current[0])
        return {"cash_target_available": True, "futures_target_available": True}

    def sleep(seconds):
        current[0] += timedelta(seconds=seconds)

    result = watch_until(
        deadline=datetime(2026, 10, 5, 14, 40, tzinfo=TAIPEI),
        probe=probe,
        now=lambda: current[0],
        sleep=sleep,
        stop_when_complete=False,
    )
    assert result["status"] == "source_watch_cutoff_reached"
    assert result["attempts"] == 5
    assert probes[-1] == datetime(2026, 10, 5, 14, 40, tzinfo=TAIPEI)


def test_final_source_watch_does_not_start_a_probe_after_cutoff():
    current = [datetime(2026, 10, 5, 14, 40, 1, tzinfo=TAIPEI)]
    probes = []

    result = watch_until(
        deadline=datetime(2026, 10, 5, 14, 40, tzinfo=TAIPEI),
        probe=lambda: probes.append(current[0]) or {},
        now=lambda: current[0],
        stop_when_complete=False,
    )

    assert result["status"] == "source_watch_cutoff_reached"
    assert result["attempts"] == 0
    assert probes == []


def test_watch_until_stops_when_both_same_day_official_quotes_arrive():
    current = [datetime(2026, 10, 5, 14, 20, tzinfo=TAIPEI)]
    calls = []

    def probe():
        calls.append(current[0])
        return {"cash_target_available": True, "futures_target_available": True}

    result = watch_until(
        deadline=current[0] + timedelta(minutes=20),
        probe=probe,
        now=lambda: current[0],
        sleep=lambda _seconds: None,
    )
    assert result["status"] == "both_official_closes_available"
    assert result["attempts"] == 1
    assert len(calls) == 1


def test_run_watch_uses_independent_calendars_and_fixed_anchor(monkeypatch):
    from src import market_data, market_source_watch, taifex_calendar

    monkeypatch.setattr(market_data, "get_market_status", lambda _market, today: {
        "calendar_status": "confirmed_open" if today.isoformat() == "2026-10-05" else "confirmed_closed",
    })
    monkeypatch.setattr(taifex_calendar, "get_taifex_index_futures_status", lambda *, today, now: {
        "calendar_status": "confirmed_open" if today.isoformat() == "2026-10-05" else "confirmed_closed",
    })
    seen = []

    def probe(cash_target, futures_target):
        seen.append((cash_target, futures_target))
        return {"cash_target_available": True, "futures_target_available": True}

    def run_immediate_watch(*, deadline, probe, **_kwargs):
        assert deadline == datetime(2026, 10, 5, 14, 32, tzinfo=TAIPEI)
        result = probe()
        return {
            "status": "both_official_closes_available",
            "attempts": 1,
            "last_probe": result,
        }

    monkeypatch.setattr(market_source_watch, "watch_until", run_immediate_watch)

    result = run_watch("2026-10-05T14:20:00+08:00", probe=probe)
    assert result["status"] == "both_official_closes_available"
    assert seen == [("2026-10-05", "2026-10-05")]
    assert result["cutoff_at"] == "2026-10-05T14:32:00+08:00"


@pytest.mark.parametrize(
    ("previous_fields", "expected_changes"),
    [
        ({"quote_date": "2026-11-25", "price": 38195.43}, {"quote_date", "price"}),
        ({"quote_date": "2026-11-26", "price": 39150}, {"price"}),
        ({"quote_date": "2026-11-25", "price": 39151.81, "change": 956.38, "change_percent": 2.50}, {"quote_date"}),
        ({"price": 39151.81, "quote_time": "2026-11-26T13:30:00+08:00"}, set()),
        ({"price": "39151.811", "quote_date": "2026-11-26", "source": "TWSE FMTQIK"}, set()),
        ({"price": 39151.81}, {"quote_date"}),
        ({"quote_date": "2026-11-26", "price": None}, {"price"}),
        ({"quote_date": "2026-11-26", "price": 39151.81, "change_percent": 2.49}, {"change_percent"}),
    ],
)
def test_final_watch_compares_normalized_close_and_uses_quote_time_for_missing_date(
    previous_fields, expected_changes,
):
    now = datetime(2026, 11, 26, 14, 39, tzinfo=TAIPEI)
    snapshot = {"TAIEX": {"ticker": "TAIEX", **previous_fields}}
    candidate = {
        "ticker": "TAIEX", "quote_date": "2026-11-26", "quote_time": "2026-11-26T13:30:00+08:00",
        "instrument_id": "twse:taiex", "quote_basis": "TWSE_TAIEX_DAILY_CLOSE", "source_tier": "official",
        "price": 39151.81, "change": 956.38, "change_percent": 2.50,
        "source_url": "https://www.twse.com.tw/exchangeReport/MI_INDEX",
        "source_attempts": [{"source": "twse_mi_index_json", "outcome": "verified",
                             "target_date": "2026-11-26", "observed_date": "2026-11-26"}],
    }
    overrides, updates = watch_quote_updates({"cash_quote": candidate}, snapshot, now=now)
    assert bool(overrides) is bool(expected_changes)
    assert set(updates.get("TAIEX", {}).get("changed_fields", {})) == expected_changes


@pytest.mark.parametrize(
    ("field", "old_value"),
    [("quote_date", "2026-11-25"), ("contract_month", "202701"), ("session", "night"), ("change", 1137)],
)
def test_equal_price_txf_changes_still_require_the_verified_observation(field, old_value):
    now = datetime(2026, 11, 26, 14, 39, tzinfo=TAIPEI)
    today = now.date().isoformat()
    candidate = {
        "ticker": "TXF", "quote_date": today, "quote_time": f"{today}T13:45:00+08:00",
        "price": 39200, "change": 1138, "change_percent": 2.99, "freshness": "recent_close",
        "contract_month": "202612", "session": "regular", "source_tier": "official",
        "instrument_id": "market:txf:taifex:202612:regular",
        "quote_basis": "TAIFEX_TXF_DAY|contract=202612|session=regular",
        "source_url": "https://openapi.taifex.com.tw/v1/DailyMarketReportFut",
        "source_attempts": [
            {"source": source, "outcome": outcome, "target_date": today, "observed_date": today}
            for source, outcome in (
                ("taifex_openapi", "verified"), ("taifex_daily_table", "verified"),
                ("taifex_selection", "selected:taifex_openapi"),
            )
        ],
    }
    previous = {**candidate, field: old_value}
    if field == "quote_date":
        previous["quote_time"] = f"{old_value}T13:45:00+08:00"
    if field in {"contract_month", "session"}:
        previous["instrument_id"] = f"market:txf:taifex:{previous['contract_month']}:{previous['session']}"
        previous["quote_basis"] = f"TAIFEX_TXF_DAY|contract={previous['contract_month']}|session={previous['session']}"
    overrides, updates = watch_quote_updates({"futures_quote": candidate}, {"TXF": previous}, now=now)
    assert overrides == {"futures_quote": candidate}
    assert updates["TXF"]["changed_fields"] == {field: {"before": old_value, "after": candidate[field]}}
    assert watch_quote_updates(overrides, {"TXF": candidate}, now=now, require_complete=True) == ({}, {})
