import json

import pytest

from src import scheduled_delivery
from src.release_gate import ReleaseGateResult
from src.scheduled_delivery import _creator_records_from_observations, _load_creator_records
from src.telegram_client import TextDeliveryReceipt, alert_mini_app_url


def test_creator_observations_are_projected_into_release_records() -> None:
    rows = _creator_records_from_observations([{
        "observation_id": "jenny-1", "source": "jenny", "content_origin": "jenny",
        "episode_title": "Public episode", "public_safe": True, "parse_status": "normalized",
    }, {
        "observation_id": "private", "source": "jenny", "content_origin": "jenny",
        "public_safe": False,
    }])
    assert len(rows) == 1
    assert rows[0]["creator_id"] == "jenny"
    assert rows[0]["episode_key"] == "jenny-1"


def test_scheduled_brief_prioritises_eligible_financialjuice_event() -> None:
    event = {"source_key": "financialjuice", "notification_status": "eligible", "title": "FJ"}
    snapshot = {
        "financialjuice_priority_events": [event],
        "events": {"items": [{"kind": "market_signal", "title": "TAIEX"}]},
    }
    assert scheduled_delivery._pick_event(snapshot, "morning") == event


def test_financialjuice_history_flattens_redacted_recipient_receipts() -> None:
    history = scheduled_delivery._financialjuice_delivery_history([
        {
            "notification_key": "financialjuice:event-1",
            "delivery_receipts": [
                {"recipient_hash": "abc", "delivery_status": "delivered"},
                {"recipient_hash": "def", "delivery_status": "failed"},
            ],
        },
        {"notification_key": "financialjuice:event-2", "recipient_hash": "ghi", "status": "delivered"},
    ])
    assert history == [
        {"notification_key": "financialjuice:event-1", "recipient_hash": "abc", "delivery_status": "delivered"},
        {"notification_key": "financialjuice:event-1", "recipient_hash": "def", "delivery_status": "failed"},
        {"notification_key": "financialjuice:event-2", "recipient_hash": "ghi", "delivery_status": "delivered"},
    ]


def _settings():
    return type(
        "Settings",
        (),
        {
            "telegram_ready": True,
            "telegram_bot_token": "token",
            "telegram_chat_ids": ("test",),
            "dashboard_url": "https://example.test/app",
        },
    )()


def _patch_ready(monkeypatch, output):
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    # Delivery claims are durable by design; keep each test's ledger isolated
    # so an intentional uncertain-delivery case cannot affect the next case.
    monkeypatch.setenv("EVENT_LEDGER_PATH", str(output.with_name("event-ledger.json")))
    monkeypatch.setattr(
        scheduled_delivery,
        "verify_release_for_delivery",
        lambda **_kwargs: ReleaseGateResult(True, release_id="release-1", snapshot_id="market-12345678"),
    )
    monkeypatch.setattr(scheduled_delivery, "get_settings", _settings)
    monkeypatch.setattr(scheduled_delivery, "_pick_event", lambda *_args: None)
    monkeypatch.setattr(
        scheduled_delivery,
        "briefing_correlation",
        lambda *_args: {"trace_id": "trace-1", "snapshot_id": "market-12345678", "observation_id": "obs-1"},
    )
    monkeypatch.setattr(scheduled_delivery, "build_brief", lambda *_args: "測試摘要")


def test_scheduled_delivery_blocks_when_manifest_is_not_ready(tmp_path, monkeypatch):
    snapshot_path = tmp_path / "market.json"
    manifest_path = tmp_path / "release-manifest.json"
    snapshot_path.write_text(json.dumps({"snapshot_id": "market-12345678", "quotes": [], "indices": []}), encoding="utf-8")
    manifest_path.write_text(json.dumps({"status": "invalid", "release_id": "release-old"}), encoding="utf-8")
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))

    def fail_if_called(**_kwargs):
        raise AssertionError("Telegram must not be called when release gate fails")

    monkeypatch.setattr(scheduled_delivery, "send_text_briefs_audited", fail_if_called)
    scheduled_delivery.send(snapshot_path, "morning", manifest_path)
    text = output.read_text(encoding="utf-8")
    assert "sent=false" in text
    assert "reason=release_gate_blocked" in text


def test_scheduled_delivery_uses_text_delivery_after_release_gate(tmp_path, monkeypatch):
    snapshot_path = tmp_path / "market.json"
    manifest_path = tmp_path / "release-manifest.json"
    snapshot_path.write_text(
        json.dumps({"snapshot_id": "market-12345678", "quotes": [], "indices": [], "briefing": {}}),
        encoding="utf-8",
    )
    manifest_path.write_text("{}", encoding="utf-8")
    output = tmp_path / "output"
    _patch_ready(monkeypatch, output)
    event = {
        "source_key": "official",
        "event_cluster_key": "event-1",
        "observation_id": "observation-1",
        "notification_status": "eligible",
        "title": "官方事件",
    }
    monkeypatch.setattr(scheduled_delivery, "_pick_event", lambda *_args: event)
    monkeypatch.setattr(scheduled_delivery, "write_event_lock_key", lambda *_args: None)
    captured = {}

    class FakeLedger:
        def delivery_history(self):
            return []

        def record_delivery(self, payload, **_kwargs):
            return payload

        def save(self):
            return None

    monkeypatch.setattr(scheduled_delivery, "EventLedger", FakeLedger)

    def sender(**kwargs):
        captured.update(kwargs)
        return (TextDeliveryReceipt(
            kwargs["alert_id"], kwargs["release_id"], kwargs["snapshot_id"],
            "hash", "delivered", message_id=1, observation_id=kwargs.get("observation_id", ""),
        ),)

    monkeypatch.setattr(
        scheduled_delivery,
        "send_text_briefs_audited",
        sender,
    )
    scheduled_delivery.send(snapshot_path, "morning", manifest_path)
    text = output.read_text(encoding="utf-8")
    assert "sent=true" in text
    assert "delivery_mode=text" in text
    assert captured["target_url"] == alert_mini_app_url(
        "https://example.test/app",
        alert_id="event-1",
        release_id="release-1",
        snapshot_id="market-12345678",
        observation_id="obs-1",
    )


def test_scheduled_market_delivery_does_not_require_fresh_research(tmp_path, monkeypatch):
    snapshot_path = tmp_path / "market.json"
    manifest_path = tmp_path / "release-manifest.json"
    snapshot_path.write_text(
        json.dumps({"snapshot_id": "market-12345678", "quotes": [], "indices": [], "briefing": {}}),
        encoding="utf-8",
    )
    manifest_path.write_text("{}", encoding="utf-8")
    output = tmp_path / "output"
    _patch_ready(monkeypatch, output)
    captured: dict[str, object] = {}

    def gate(**kwargs):
        captured.update(kwargs)
        return ReleaseGateResult(True, release_id="release-1", snapshot_id="market-12345678")

    monkeypatch.setattr(scheduled_delivery, "verify_release_for_delivery", gate)
    monkeypatch.setattr(
        scheduled_delivery,
        "send_text_briefs_audited",
        lambda **kwargs: (TextDeliveryReceipt(
            kwargs["alert_id"], kwargs["release_id"], kwargs["snapshot_id"],
            "hash", "delivered", message_id=3, observation_id=kwargs.get("observation_id", ""),
        ),),
    )
    scheduled_delivery.send(snapshot_path, "morning", manifest_path)
    assert captured["require_production_research"] is False
    text = output.read_text(encoding="utf-8")
    assert "notification_expected=true" in text
    assert "notification_status=ready" in text
    assert "notification_reason=no_trigger" in text


def test_scheduled_delivery_emits_financialjuice_release_delivery_trace(tmp_path, monkeypatch):
    snapshot_path = tmp_path / "market.json"
    manifest_path = tmp_path / "release-manifest.json"
    snapshot_path.write_text(
        json.dumps({"snapshot_id": "market-12345678", "quotes": [], "indices": [], "briefing": {}}),
        encoding="utf-8",
    )
    manifest_path.write_text("{}", encoding="utf-8")
    output = tmp_path / "output"
    _patch_ready(monkeypatch, output)
    event = {
        "source_key": "financialjuice",
        "event_cluster_key": "cluster-1",
        "observation_id": "fj-observation-1",
        "observation_id_hash": "a" * 64,
        "item_id": "item-1",
        "title": "據《The...",
        "vendor_original_headline": "Iran says U.S. strikes telecommunications infrastructure.",
        "vendor_importance": 8,
        "notification_status": "eligible",
        "vendor_priority_notification": True,
        "prstk_risk": {"prstk_risk_level": "R2"},
        "notification_reason": "vendor_priority_importance_ge_8",
        "parser_version": "financialjuice-compound-v1",
        "received_at": "2026-08-21T01:01:00+00:00",
        "alert_eligible": True,
    }
    monkeypatch.setattr(scheduled_delivery, "_pick_event", lambda *_args: event)
    monkeypatch.setattr(
        scheduled_delivery,
        "decide_alert_budget",
        lambda *_args: {"allowed": True, "reason": "material_change", "event_key": "cluster-1"},
    )
    captured: dict[str, object] = {}

    def sender(**kwargs):
        captured.update(kwargs)
        return (TextDeliveryReceipt(
            kwargs["alert_id"], kwargs["release_id"], kwargs["snapshot_id"],
            "hash", "delivered", message_id=2, observation_id=kwargs.get("observation_id", ""),
        ),)

    monkeypatch.setattr(scheduled_delivery, "send_text_briefs_audited", sender)
    monkeypatch.setattr(scheduled_delivery, "write_event_lock_key", lambda *_args: None)
    recorded: dict = {}

    class FakeLedger:
        def delivery_history(self):
            return []

        def record_delivery(self, payload, **_kwargs):
            recorded.update(payload)
            return payload

        def save(self):
            return None

    monkeypatch.setattr(scheduled_delivery, "EventLedger", FakeLedger)
    scheduled_delivery.send(snapshot_path, "morning", manifest_path)
    text = output.read_text(encoding="utf-8")
    assert "financialjuice_delivery_trace=" in text
    assert "release-1" in text
    assert "market-12345678" in text
    assert "delivery_status=delivered" in text
    assert "failed_recipient_hashes=\n" in text or "failed_recipient_hashes=\r\n" in text
    assert recorded["release_id"] == "release-1"
    assert recorded["snapshot_id"] == "market-12345678"
    assert recorded["delivery_status"] == "delivered"
    assert recorded["observation_id_hash"] == "a" * 64
    assert recorded["notification_key"].startswith("financialjuice:")
    assert recorded["delivery_receipts"][0]["delivery_status"] == "delivered"
    assert "據《The" not in captured["text"]
    assert "…" not in captured["text"]
    assert "..." not in captured["text"]
    assert str(captured["text"]).count("｜") == 1
    assert len(captured["text"]) <= 40


def test_scheduled_financialjuice_all_recipient_failure_is_fail_closed(tmp_path, monkeypatch):
    snapshot_path = tmp_path / "market.json"
    manifest_path = tmp_path / "release-manifest.json"
    snapshot_path.write_text(
        json.dumps({"snapshot_id": "market-12345678", "quotes": [], "indices": [], "briefing": {}}),
        encoding="utf-8",
    )
    manifest_path.write_text("{}", encoding="utf-8")
    output = tmp_path / "output"
    _patch_ready(monkeypatch, output)
    event = {
        "source_key": "financialjuice",
        "event_cluster_key": "cluster-failed",
        "observation_id": "fj-observation-failed",
        "notification_status": "eligible",
        "vendor_priority_notification": True,
        "vendor_importance": 8,
        "title": "Oil supply risk",
    }
    monkeypatch.setattr(scheduled_delivery, "_pick_event", lambda *_args: event)
    monkeypatch.setattr(
        scheduled_delivery,
        "decide_alert_budget",
        lambda *_args: {"allowed": True, "reason": "budget_available", "event_key": "cluster-failed"},
    )
    monkeypatch.setattr(scheduled_delivery, "deliver_financialjuice_event", lambda *_args, **_kwargs: {
        "status": "failed",
        "receipts": [{"recipient_hash": "hash", "delivery_status": "failed"}],
        "reasons": ["delivery_exception"],
    })
    monkeypatch.setattr(scheduled_delivery, "write_event_lock_key", lambda *_args: None)

    class FakeLedger:
        def delivery_history(self):
            return []

        def record_delivery(self, *_args, **_kwargs):
            raise AssertionError("failed FJ delivery must not be recorded as delivered")

        def save(self):
            return None

    monkeypatch.setattr(scheduled_delivery, "EventLedger", FakeLedger)
    monkeypatch.setattr(scheduled_delivery, "get_settings", _settings)

    with pytest.raises(RuntimeError, match="FinancialJuice delivery failed"):
        scheduled_delivery.send(snapshot_path, "morning", manifest_path)
    text = output.read_text(encoding="utf-8")
    assert "sent=false" in text
    assert "delivery_status=failed" in text
    assert "reason=all_recipients_failed" in text


def test_scheduled_delivery_records_text_delivery_failure(tmp_path, monkeypatch):
    snapshot_path = tmp_path / "market.json"
    manifest_path = tmp_path / "release-manifest.json"
    snapshot_path.write_text(
        json.dumps({"snapshot_id": "market-12345678", "quotes": [], "indices": [], "briefing": {}}),
        encoding="utf-8",
    )
    manifest_path.write_text("{}", encoding="utf-8")
    output = tmp_path / "output"
    _patch_ready(monkeypatch, output)
    monkeypatch.setattr(
        scheduled_delivery,
        "send_text_briefs_audited",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError("text failure")),
    )
    scheduled_delivery.send(snapshot_path, "morning", manifest_path)
    text = output.read_text(encoding="utf-8")
    assert "sent=false" in text
    assert "reason=text_delivery_failed" in text


def test_scheduled_delivery_blocks_quality_ineligible_event_before_renderer(tmp_path, monkeypatch):
    snapshot_path = tmp_path / "market.json"
    manifest_path = tmp_path / "release-manifest.json"
    snapshot_path.write_text(
        json.dumps({"snapshot_id": "market-12345678", "quotes": [], "indices": [], "briefing": {}}),
        encoding="utf-8",
    )
    manifest_path.write_text("{}", encoding="utf-8")
    output = tmp_path / "output"
    _patch_ready(monkeypatch, output)
    monkeypatch.setattr(
        scheduled_delivery,
        "_pick_event",
        lambda *_args: {
            "event_key": "stale-event",
            "title": "stale event",
            "alert_eligible": False,
            "quality_reasons": ["quote_stale"],
        },
    )
    scheduled_delivery.send(snapshot_path, "morning", manifest_path)
    text = output.read_text(encoding="utf-8")
    assert "sent=false" in text
    assert "delivery_status=suppressed" in text
    assert "reason=quote_stale" in text
def test_creator_records_are_loaded_only_from_sanitized_external_path(tmp_path, monkeypatch):
    records = tmp_path / "creator-records.json"
    records.write_text(json.dumps({"records": [{"source": "haojiao", "title": "public"}]}), encoding="utf-8")
    monkeypatch.setenv("CREATOR_RECORDS_PATH", str(records))
    assert _load_creator_records() == [{"source": "haojiao", "title": "public"}]


def test_creator_records_inside_site_are_rejected(tmp_path, monkeypatch):
    site = tmp_path / "site"
    site.mkdir()
    records = site / "creator.json"
    records.write_text("[]", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CREATOR_RECORDS_PATH", str(records))
    assert _load_creator_records() == []


def test_creator_records_with_private_body_or_parser_failure_are_rejected(tmp_path, monkeypatch):
    records = tmp_path / "creator-records.json"
    records.write_text(
        json.dumps({"records": [
            {"source": "gooaye", "title": "private", "body": "raw"},
            {"source": "gooaye", "title": "unsupported", "parse_status": "unsupported_template"},
            {"source": "gooaye", "title": "safe", "parse_status": "parsed"},
        ]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CREATOR_RECORDS_PATH", str(records))
    assert _load_creator_records() == [{"source": "gooaye", "title": "safe", "parse_status": "parsed"}]


def test_creator_input_failure_is_not_reported_as_no_event(tmp_path, monkeypatch):
    from src.scheduled_delivery import _creator_input_failures

    monkeypatch.setenv("CREATOR_NOTIFICATION_ENABLED", "true")
    monkeypatch.setenv("CREATOR_RECORDS_PATH", str(tmp_path / "missing.json"))
    assert _creator_input_failures() == {
        "haojiao": "creator_records_unavailable",
        "jenny": "creator_records_unavailable",
        "gooaye": "creator_records_unavailable",
    }


def test_creator_filtered_records_are_reported_as_parse_failure(tmp_path, monkeypatch):
    from src.scheduled_delivery import _creator_input_failures

    records = tmp_path / "creator-records.json"
    records.write_text(json.dumps({"records": [{
        "source": "haojiao",
        "parse_status": "unsupported_template",
    }]}), encoding="utf-8")
    monkeypatch.setenv("CREATOR_NOTIFICATION_ENABLED", "true")
    monkeypatch.setenv("CREATOR_RECORDS_PATH", str(records))
    assert _creator_input_failures() == {"haojiao": "creator_records_parse_failed"}


def test_prepare_binds_creator_records_to_the_published_snapshot(tmp_path, monkeypatch):
    records = tmp_path / "creator-records.json"
    records.write_text(json.dumps([{"source": "gooaye", "title": "public"}]), encoding="utf-8")
    snapshot_path = tmp_path / "market.json"
    monkeypatch.setenv("CREATOR_RECORDS_PATH", str(records))
    monkeypatch.setattr(scheduled_delivery, "build_market_snapshot", lambda: {"snapshot_id": "m-1", "quotes": [], "indices": []})
    monkeypatch.setattr(scheduled_delivery, "build_briefing_snapshot", lambda snapshot, _slot: {"creator_release": snapshot.get("creator_insights")})
    monkeypatch.setattr(scheduled_delivery, "write_snapshot", lambda snapshot, path: (path.write_text(json.dumps(snapshot), encoding="utf-8"), True)[1])
    monkeypatch.setattr(scheduled_delivery, "_pick_event", lambda *_args: None)
    monkeypatch.setattr(scheduled_delivery, "briefing_correlation", lambda *_args: {"trace_id": "t", "snapshot_id": "m-1", "observation_id": ""})
    monkeypatch.setattr(scheduled_delivery, "merge_published_metadata", lambda *_args, **_kwargs: True)
    scheduled_delivery.prepare("morning", snapshot_path)
    published = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert published["creator_insights"][0]["source"] == "gooaye"
    assert published["source_health"]["sources"]
    assert {row["key"] for row in published["source_health"]["sources"]} == {
        "creator_haojiao",
        "creator_jenny",
        "creator_gooaye",
    }


def test_prepare_binds_sanitized_external_observations_to_snapshot(tmp_path, monkeypatch):
    records = tmp_path / "external.json"
    records.write_text(json.dumps({"observations": [{
        "observation_id": "fj-1", "source": "financialjuice",
        "headline": "Public headline", "source_identity_verified": True, "public_safe": True,
    }]}), encoding="utf-8")
    snapshot_path = tmp_path / "market.json"
    monkeypatch.setenv("EXTERNAL_OBSERVATIONS_PATH", str(records))
    monkeypatch.setattr(scheduled_delivery, "build_market_snapshot", lambda: {
        "snapshot_id": "m-1", "quotes": [], "indices": [],
        "source_health": {"status": "healthy", "sources": [], "data_gaps": [],
                           "missing_source_count": 0, "runtime_failure_count": 0,
                           "configuration_missing_count": 0, "state_counts": {},
                           "observability": {}},
    })
    monkeypatch.setattr(scheduled_delivery, "build_briefing_snapshot", lambda snapshot, _slot: {
        "external_observations": snapshot.get("external_observations"),
    })
    monkeypatch.setattr(scheduled_delivery, "write_snapshot", lambda snapshot, path: path.write_text(json.dumps(snapshot), encoding="utf-8") is None)
    monkeypatch.setattr(scheduled_delivery, "_pick_event", lambda *_args: None)
    monkeypatch.setattr(scheduled_delivery, "briefing_correlation", lambda *_args: {"trace_id": "t", "snapshot_id": "m-1", "observation_id": ""})
    monkeypatch.setattr(scheduled_delivery, "merge_published_metadata", lambda *_args, **_kwargs: True)
    scheduled_delivery.prepare("morning", snapshot_path)
    published = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert published["external_observations"][0]["observation_id"] == "fj-1"
    assert published["briefing"]["external_observations"][0]["source"] == "financialjuice"
    assert published["external_source_health"]["status"] == "healthy"


def test_prepare_projects_qualifying_financialjuice_into_release_event_lane(tmp_path, monkeypatch):
    records = tmp_path / "external.json"
    records.write_text(json.dumps({"observations": [{
        "observation_id": "fj-8", "item_id": "item-8", "source": "financialjuice",
        "original_headline": "Oil supply risk", "event_type": "energy", "vendor_importance": 8,
        "source_url": "https://financialjuice.com/item/8", "source_identity_verified": True, "public_safe": True,
    }]}), encoding="utf-8")
    snapshot_path = tmp_path / "market.json"
    monkeypatch.setenv("EXTERNAL_OBSERVATIONS_PATH", str(records))
    monkeypatch.setattr(scheduled_delivery, "build_market_snapshot", lambda: {
        "snapshot_id": "m-1", "quotes": [], "indices": [], "events": {"items": []},
        "source_health": {"status": "healthy", "sources": [], "data_gaps": [],
                           "missing_source_count": 0, "runtime_failure_count": 0,
                           "configuration_missing_count": 0, "state_counts": {},
                           "observability": {}},
    })
    monkeypatch.setattr(scheduled_delivery, "build_briefing_snapshot", lambda snapshot, _slot: {
        "external_event_notifications": snapshot.get("financialjuice_priority_decisions"),
    })
    def write_snapshot(snapshot, path):
        path.write_text(json.dumps(snapshot), encoding="utf-8")
        return True
    monkeypatch.setattr(scheduled_delivery, "write_snapshot", write_snapshot)
    monkeypatch.setattr(scheduled_delivery, "_pick_event", lambda *_args: None)
    monkeypatch.setattr(scheduled_delivery, "briefing_correlation", lambda *_args: {"trace_id": "t", "snapshot_id": "m-1", "observation_id": ""})
    monkeypatch.setattr(scheduled_delivery, "merge_published_metadata", lambda *_args, **_kwargs: True)
    scheduled_delivery.prepare("morning", snapshot_path)
    published = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert published["financialjuice_priority_decisions"][0]["vendor_priority_notification"] is True
    assert published["financialjuice_priority_events"][0]["notification_status"] == "eligible"
    assert published["events"]["items"][0]["source_key"] == "financialjuice"


def test_prepare_removes_stale_blocked_financialjuice_event_rows(tmp_path, monkeypatch):
    records = tmp_path / "external.json"
    records.write_text(json.dumps({"observations": []}), encoding="utf-8")
    snapshot_path = tmp_path / "market.json"
    monkeypatch.setenv("EXTERNAL_OBSERVATIONS_PATH", str(records))
    monkeypatch.setattr(scheduled_delivery, "build_market_snapshot", lambda: {
        "snapshot_id": "m-clean-1", "quotes": [], "indices": [],
        "events": {"items": [
            {"kind": "external_event", "source": "FinancialJuice", "source_key": "financialjuice",
             "observation_id": "stale-fj", "public_signal_eligible": False,
             "title": "PR run failed: FinancialJuice semantics"},
            {"kind": "market_signal", "title": "Keep official signal"},
        ]},
        "source_health": {"status": "healthy", "sources": [], "data_gaps": [],
                           "missing_source_count": 0, "runtime_failure_count": 0,
                           "configuration_missing_count": 0, "state_counts": {},
                           "observability": {}},
    })
    monkeypatch.setattr(scheduled_delivery, "build_briefing_snapshot", lambda snapshot, _slot: {
        "external_event_notifications": snapshot.get("financialjuice_priority_decisions"),
    })
    monkeypatch.setattr(scheduled_delivery, "write_snapshot", lambda snapshot, path: path.write_text(json.dumps(snapshot), encoding="utf-8") or True)
    monkeypatch.setattr(scheduled_delivery, "_pick_event", lambda *_args: None)
    monkeypatch.setattr(scheduled_delivery, "briefing_correlation", lambda *_args: {"trace_id": "t", "snapshot_id": "m-clean-1", "observation_id": ""})
    monkeypatch.setattr(scheduled_delivery, "merge_published_metadata", lambda *_args, **_kwargs: True)
    scheduled_delivery.prepare("morning", snapshot_path)
    published = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert published["events"]["items"] == [{"kind": "market_signal", "title": "Keep official signal"}]


def test_prepare_fetches_sanitized_railway_observations_into_release(tmp_path, monkeypatch):
    snapshot_path = tmp_path / "market.json"
    monkeypatch.delenv("EXTERNAL_OBSERVATIONS_PATH", raising=False)
    monkeypatch.setenv("RAILWAY_STATUS_URL", "https://railway.example/status")
    monkeypatch.setenv("RAILWAY_STATUS_SHARED_SECRET", "test-secret")
    monkeypatch.setattr(scheduled_delivery, "load_railway_observations", lambda: ([{
        "observation_id": "fj-remote", "source": "financialjuice", "content_origin": "financialjuice",
        "headline": "Public remote headline", "public_safe": True,
    }, {
        "observation_id": "jenny-remote", "source": "jenny", "content_origin": "jenny",
        "headline": "Public creator headline", "public_safe": True,
    }], {"status": "ready", "count": 2, "rejected_count": 0}))
    monkeypatch.setattr(scheduled_delivery, "build_market_snapshot", lambda: {
        "snapshot_id": "m-1", "quotes": [], "indices": [],
        "source_health": {"status": "healthy", "sources": [], "data_gaps": [],
                           "missing_source_count": 0, "runtime_failure_count": 0,
                           "configuration_missing_count": 0, "state_counts": {},
                           "observability": {}},
    })
    monkeypatch.setattr(scheduled_delivery, "build_briefing_snapshot", lambda snapshot, _slot: {
        "external_observations": snapshot.get("external_observations"),
    })
    monkeypatch.setattr(scheduled_delivery, "write_snapshot", lambda snapshot, path: path.write_text(json.dumps(snapshot), encoding="utf-8") is None)
    monkeypatch.setattr(scheduled_delivery, "_pick_event", lambda *_args: None)
    monkeypatch.setattr(scheduled_delivery, "briefing_correlation", lambda *_args: {"trace_id": "t", "snapshot_id": "m-1", "observation_id": ""})
    monkeypatch.setattr(scheduled_delivery, "merge_published_metadata", lambda *_args, **_kwargs: True)
    scheduled_delivery.prepare("morning", snapshot_path)
    published = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert published["external_observations"][0]["observation_id"] == "fj-remote"
    assert {row["observation_id"] for row in published["external_observations"]} == {"fj-remote", "jenny-remote"}
    assert [row["observation_id"] for row in published["financialjuice_observations"]] == ["fj-remote"]
    assert published["external_source_health"]["provider_status"] == "ready"
    assert published["external_source_health"]["status"] == "healthy"


def test_prepare_keeps_local_fallback_when_railway_export_fails(tmp_path, monkeypatch):
    records = tmp_path / "external.json"
    records.write_text(json.dumps({"observations": [{
        "observation_id": "fj-local", "source": "financialjuice", "original_headline": "Local oil update", "source_identity_verified": True, "public_safe": True,
    }]}), encoding="utf-8")
    snapshot_path = tmp_path / "market.json"
    monkeypatch.setenv("EXTERNAL_OBSERVATIONS_PATH", str(records))
    monkeypatch.setenv("RAILWAY_STATUS_URL", "https://railway.example/status")
    monkeypatch.setenv("RAILWAY_STATUS_SHARED_SECRET", "test-secret")
    monkeypatch.setattr(scheduled_delivery, "load_railway_observations", lambda: ([], {"status": "failed", "reason": "http_503", "rejected_count": 0}))
    monkeypatch.setattr(scheduled_delivery, "build_market_snapshot", lambda: {
        "snapshot_id": "m-1", "quotes": [], "indices": [],
        "source_health": {"status": "healthy", "sources": [], "data_gaps": [],
                           "missing_source_count": 0, "runtime_failure_count": 0,
                           "configuration_missing_count": 0, "state_counts": {},
                           "observability": {}},
    })
    monkeypatch.setattr(scheduled_delivery, "build_briefing_snapshot", lambda snapshot, _slot: {
        "external_observations": snapshot.get("external_observations"),
    })
    monkeypatch.setattr(scheduled_delivery, "write_snapshot", lambda snapshot, path: path.write_text(json.dumps(snapshot), encoding="utf-8") is None)
    monkeypatch.setattr(scheduled_delivery, "_pick_event", lambda *_args: None)
    monkeypatch.setattr(scheduled_delivery, "briefing_correlation", lambda *_args: {"trace_id": "t", "snapshot_id": "m-1", "observation_id": ""})
    monkeypatch.setattr(scheduled_delivery, "merge_published_metadata", lambda *_args, **_kwargs: True)
    scheduled_delivery.prepare("morning", snapshot_path)
    published = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert published["external_observations"][0]["observation_id"] == "fj-local"
    assert published["external_source_health"]["status"] == "partial"
    assert published["external_source_health"]["issues"] == ["http_503"]
