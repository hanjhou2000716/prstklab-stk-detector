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

