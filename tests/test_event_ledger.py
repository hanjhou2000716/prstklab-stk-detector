from datetime import UTC, datetime, timedelta

from src.event_ledger import EventLedger, canonical_event_key, normalize_source_url


def test_url_normalization_drops_tracking_and_www():
    assert normalize_source_url("https://www.example.com/a/?utm_source=x&b=2#part") == "https://example.com/a?b=2"


def test_canonical_key_converges_syndicated_event_facts():
    first = {"source_key": "conflict", "title": "Trump statement on Iran", "url": "https://one.example/a", "released_at": "2026-08-01T10:00:00+00:00"}
    second = {"source_key": "conflict", "title": "Iran statement by Trump", "url": "https://two.example/b", "released_at": "2026-08-01T10:10:00+00:00"}
    assert canonical_event_key(first) == canonical_event_key(second)


def test_ledger_retains_reminder_fields_and_prunes_after_thirty_days(tmp_path):
    path = tmp_path / "ledger.json"
    ledger = EventLedger(path)
    event = {"source_key": "fed", "title": "FOMC statement", "url": "https://fed.example/x", "released_at": "2026-08-01T10:00:00+00:00"}
    now = datetime(2026, 8, 1, tzinfo=UTC)
    record = ledger.observe(event, now=now)
    assert record["first_discovered_at"].startswith("2026-08-01")
    ledger.mark_reminded(event, now=now)
    ledger.save()
    reloaded = EventLedger(path)
    assert reloaded.records[canonical_event_key(event)]["last_reminded_at"].startswith("2026-08-01")
    assert reloaded.prune(now + timedelta(days=31)) == 1


def test_default_event_cooldown_is_thirty_minutes(tmp_path):
    path = tmp_path / "ledger.json"
    ledger = EventLedger(path)
    event = {"source_key": "fed", "title": "FOMC statement", "url": "https://fed.example/x", "released_at": "2026-08-01T10:00:00+00:00"}
    first = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
    ledger.mark_reminded(event, now=first)
    assert ledger.should_remind(event, now=first + timedelta(minutes=29)) is False
    assert ledger.should_remind(event, now=first + timedelta(minutes=30)) is True


def test_delivery_history_records_each_material_send(tmp_path):
    path = tmp_path / "ledger.json"
    ledger = EventLedger(path)
    event = {
        "source_key": "energy",
        "title": "Oil supply disruption",
        "url": "https://energy.example/oil",
        "released_at": "2026-08-01T10:00:00+00:00",
        "risk_level": "警戒",
    }
    first = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
    second = datetime(2026, 8, 1, 10, 40, tzinfo=UTC)
    ledger.record_delivery(event, sent_at=first, trace_id="trace-1", reason="official_event_monitor")
    ledger.record_delivery(event, sent_at=second, trace_id="trace-2", reason="official_event_monitor")
    ledger.save()
    rows = EventLedger(path).delivery_history()
    assert [row["trace_id"] for row in rows] == ["trace-1", "trace-2"]
    assert all(row["event_key"] == canonical_event_key(event) for row in rows)


def test_save_merges_two_instances_loaded_before_either_save(tmp_path):
    path = tmp_path / "ledger.json"
    first = EventLedger(path)
    second = EventLedger(path)
    event_one = {
        "source_key": "fed",
        "title": "FOMC statement",
        "url": "https://fed.example/fomc",
        "released_at": "2026-08-01T10:00:00+00:00",
    }
    event_two = {
        "source_key": "energy",
        "title": "Oil supply disruption",
        "url": "https://energy.example/oil",
        "released_at": "2026-08-01T10:05:00+00:00",
    }
    first.observe(event_one, now=datetime(2026, 8, 1, 10, 0, tzinfo=UTC))
    second.observe(event_two, now=datetime(2026, 8, 1, 10, 5, tzinfo=UTC))
    first.save()
    second.save()
    reloaded = EventLedger(path)
    assert set(reloaded.records) == {canonical_event_key(event_one), canonical_event_key(event_two)}


def test_save_recovers_stale_lock(tmp_path):
    path = tmp_path / "ledger.json"
    ledger = EventLedger(path, lock_timeout_seconds=0.2, lock_stale_after_seconds=1)
    lock = path.with_suffix(path.suffix + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("stale", encoding="utf-8")
    import os
    import time
    old = time.time() - 10
    os.utime(lock, (old, old))
    ledger.observe({"source_key": "fed", "title": "FOMC"})
    ledger.save()
    assert path.exists()
    assert not lock.exists()

