import json
from datetime import datetime, timedelta

from src.market_source_watch import (
    TAIPEI,
    run_watch,
    watch_quotes_supersede_snapshot,
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


def test_final_watch_rebuilds_only_when_official_values_supersede_snapshot(tmp_path):
    snapshot = tmp_path / "market.json"
    snapshot.write_text(json.dumps({"indices": [
        {"ticker": "TAIEX", "quote_date": "2026-10-02", "price": 48475.74, "change": 123.0, "change_percent": 0.25},
        {"ticker": "TXF", "quote_date": "2026-10-02", "price": 48671.0, "change": -30.0, "change_percent": -0.06, "contract_month": "202610", "session": "regular"},
    ]}), encoding="utf-8")
    result = {"last_probe": {
        "cash_quote": {"quote_date": "2026-10-05", "price": 49712.04, "change": 1236.3, "change_percent": 2.55},
        "futures_quote": {"quote_date": "2026-10-05", "price": 49949.0, "change": 1280.0, "change_percent": 2.63, "contract_month": "202610", "session": "regular"},
    }}
    assert watch_quotes_supersede_snapshot(result, str(snapshot)) is True

    same_day = {"cash_quote": {"quote_date": "2026-10-02", "price": 48475.74, "change": 123.0, "change_percent": 0.25}}
    assert watch_quotes_supersede_snapshot(same_day, str(snapshot)) is False

    corrected = {"cash_quote": {"quote_date": "2026-10-02", "price": 48476.0, "change": 123.0, "change_percent": 0.25}}
    assert watch_quotes_supersede_snapshot(corrected, str(snapshot)) is True

    incomplete = {"cash_quote": {"quote_date": "2026-10-02", "price": 48475.74}}
    assert watch_quotes_supersede_snapshot(incomplete, str(snapshot)) is False
