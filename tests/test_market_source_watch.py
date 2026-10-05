from datetime import datetime, timedelta

from src.market_source_watch import TAIPEI, run_watch, watch_until


def test_watch_until_performs_final_check_at_fixed_twenty_minute_cutoff():
    current = [datetime(2026, 10, 5, 14, 20, tzinfo=TAIPEI)]
    probes = []

    def probe():
        probes.append(current[0])
        return {"cash_target_available": False, "futures_target_available": False}

    def sleep(seconds):
        current[0] += timedelta(seconds=seconds)

    result = watch_until(
        deadline=current[0] + timedelta(minutes=20),
        probe=probe,
        now=lambda: current[0],
        sleep=sleep,
    )
    assert result["status"] == "source_watch_cutoff_reached"
    assert result["attempts"] == 11
    assert probes[-1] == datetime(2026, 10, 5, 14, 40, tzinfo=TAIPEI)


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
    from src import market_data, taifex_calendar

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

    result = run_watch("2026-10-05T14:20:00+08:00", probe=probe)
    assert result["status"] == "both_official_closes_available"
    assert seen == [("2026-10-05", "2026-10-05")]
    assert result["cutoff_at"] == "2026-10-05T14:40:00+08:00"
