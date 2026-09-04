from datetime import UTC, datetime, timedelta

from src.event_ledger import EventLedger, canonical_event_key, normalize_source_url


def test_url_normalization_drops_tracking_and_www():
    assert normalize_source_url("https://www.example.com/a/?utm_source=x&b=2#part") == "https://example.com/a?b=2"


def test_canonical_key_converges_syndicated_event_facts():
    first = {"source_key": "conflict", "title": "Trump statement on Iran", "url": "https://one.example/a", "released_at": "2026-08-01T10:00:00+00:00"}
    second = {"source_key": "conflict", "title": "Iran statement by Trump", "url": "https://two.example/b", "released_at": "2026-08-01T10:10:00+00:00"}
    assert canonical_event_key(first) == canonical_event_key(second)


def test_financialjuice_notification_identity_prevents_unrelated_cache_collision():
    first = {
        "source_key": "financialjuice",
        "notification_id": "fj-item-iran",
        "title": "Iran telecom attack",
    }
    second = {
        "source_key": "financialjuice",
        "notification_id": "fj-item-nscale",
        "title": "Nscale Anthropic contract",
    }
    assert canonical_event_key(first) != canonical_event_key(second)
    assert canonical_event_key(first) == canonical_event_key({**first, "title": "replayed title"})


def test_financialjuice_delivery_without_article_url_keeps_vendor_provenance(tmp_path):
    ledger = EventLedger(tmp_path / "ledger.json")
    ledger.record_delivery({
        "source_key": "financialjuice",
        "notification_id": "fj-without-article-url",
        "title": "FJ event",
    })
    record = next(iter(ledger.records.values()))
    assert record["source_url"] == "https://financialjuice.com/"
    assert record["source_domain"] == "financialjuice.com"


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


def test_notification_claim_is_atomic_and_retries_only_failed_recipients(tmp_path):
    path = tmp_path / "ledger.json"
    first = EventLedger(path)
    second = EventLedger(path)
    claimed = first.claim_notification("fj:event-1", recipient_hashes=("ok", "retry"), run_id="run-a")
    assert claimed["status"] == "claimed"
    assert second.claim_notification("fj:event-1", recipient_hashes=("ok", "retry"), run_id="run-b")["status"] == "in_flight"

    first.complete_notification_claim(
        "fj:event-1",
        delivered_recipient_hashes=("ok",),
        failed_recipient_hashes=("retry",),
    )
    retried = second.claim_notification("fj:event-1", recipient_hashes=("ok", "retry"), run_id="run-c")
    assert retried["status"] == "claimed"
    assert retried["pending_recipient_hashes"] == ["retry"]
    second.complete_notification_claim("fj:event-1", delivered_recipient_hashes=("retry",))
    assert first.claim_notification("fj:event-1", recipient_hashes=("ok", "retry"))["status"] == "already_delivered"


def test_unchanged_theme_stays_suppressed_after_two_hours(tmp_path):
    ledger = EventLedger(tmp_path / "ledger.json")
    event = {
        "notification_theme_key": "middle-east-conflict",
        "title": "Iran conflict update",
        "event_cluster_key": "cluster-1",
        "risk_level": "R2",
    }
    first = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
    assert ledger.theme_decision(event, now=first)["allowed"] is True
    ledger.mark_theme_notified(event, now=first)
    decision = ledger.theme_decision(event, now=first + timedelta(hours=12))
    assert decision["allowed"] is False
    assert decision["reason"] == "same_theme_unchanged"


def test_material_theme_replay_cases(tmp_path):
    ledger = EventLedger(tmp_path / "ledger.json")
    base = {
        "notification_theme_key": "nasdaq-price-move",
        "title": "Nasdaq move",
        "event_cluster_key": "cluster-1",
        "risk_level": "R2",
        "instrument": {"ticker": "NASDAQ", "change_percent": 1.6},
    }
    first = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
    assert ledger.theme_decision(base, now=first)["allowed"] is True
    ledger.mark_theme_notified(base, now=first)
    assert ledger.theme_decision({**base, "instrument": {"ticker": "NASDAQ", "change_percent": 1.8}}, now=first + timedelta(minutes=5))["allowed"] is False
    assert ledger.theme_decision({**base, "instrument": {"ticker": "NASDAQ", "change_percent": 4.0}}, now=first + timedelta(minutes=6))["allowed"] is True
    ledger.mark_theme_notified({**base, "instrument": {"ticker": "NASDAQ", "change_percent": 4.0}}, now=first + timedelta(minutes=6))
    assert ledger.theme_decision({**base, "risk_level": "R3"}, now=first + timedelta(minutes=7))["allowed"] is True
    ledger.mark_theme_notified({**base, "risk_level": "R3"}, now=first + timedelta(minutes=7))
    assert ledger.theme_decision({**base, "direction": "down", "instrument": {"ticker": "NASDAQ", "change_percent": -2.0}}, now=first + timedelta(minutes=8))["allowed"] is True


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


def test_delivery_history_preserves_release_bound_financialjuice_trace(tmp_path):
    path = tmp_path / "ledger.json"
    ledger = EventLedger(path)
    event = {
        "source_key": "financialjuice",
        "event_type": "energy",
        "title": "Oil supply risk",
        "event_cluster_key": "cluster-1",
        "observation_id_hash": "a" * 64,
        "item_id": "item-1",
        "vendor_importance": 8,
        "prstk_risk": {"prstk_risk_level": "R2"},
        "notification_reason": "vendor_priority_importance_ge_8",
        "parser_version": "financialjuice-compound-v1",
        "received_at": "2026-08-21T01:01:00+00:00",
        "release_id": "release-1",
        "snapshot_id": "snapshot-1",
        "delivery_status": "delivered",
    }
    ledger.record_delivery(event, trace_id="trace-fj", reason="scheduled_delivery")
    ledger.save()
    row = EventLedger(path).delivery_history()[0]
    assert row["release_id"] == "release-1"
    assert row["snapshot_id"] == "snapshot-1"
    assert row["delivery_status"] == "delivered"
    assert row["observation_id_hash"] == "a" * 64
    assert row["item_id"] == "item-1"


def test_event_ledger_keeps_compound_identity_and_pending_reason(tmp_path):
    path = tmp_path / "ledger.json"
    event = {
        "event_type": "energy",
        "compound_item_id": "fj-item-2",
        "compound_event_cluster_key": "fj-cluster-2",
        "pending_reasons": ["market_sync_missing"],
    }
    ledger = EventLedger(path)
    row = ledger.record_decision(event, {"allowed": False, "status": "pending", "reasons": ["market_sync_missing"]})
    ledger.save()
    record = EventLedger(path).records[canonical_event_key(event)]
    assert row["allowed"] is False
    assert row["reason"] == "market_sync_missing"
    assert record["compound_item_id"] == "fj-item-2"
    assert record["last_decision"]["reasons"] == ["market_sync_missing"]


def test_distinct_compound_clusters_do_not_collapse():
    first = {"compound_event_cluster_key": "fj-cluster-1", "event_type": "energy"}
    second = {"compound_event_cluster_key": "fj-cluster-2", "event_type": "energy"}
    assert canonical_event_key(first) != canonical_event_key(second)


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

