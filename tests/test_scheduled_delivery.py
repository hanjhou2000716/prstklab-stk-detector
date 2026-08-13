import json

from src import scheduled_delivery
from src.release_gate import ReleaseGateResult
from src.scheduled_delivery import _load_creator_records


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

    monkeypatch.setattr(scheduled_delivery, "send_photo_briefs", fail_if_called)
    scheduled_delivery.send(snapshot_path, "morning", manifest_path)
    text = output.read_text(encoding="utf-8")
    assert "sent=false" in text
    assert "reason=release_gate_blocked" in text


def test_scheduled_delivery_uses_photo_delivery_after_release_gate(tmp_path, monkeypatch):
    snapshot_path = tmp_path / "market.json"
    manifest_path = tmp_path / "release-manifest.json"
    snapshot_path.write_text(
        json.dumps({"snapshot_id": "market-12345678", "quotes": [], "indices": [], "briefing": {}}),
        encoding="utf-8",
    )
    manifest_path.write_text("{}", encoding="utf-8")
    output = tmp_path / "output"
    _patch_ready(monkeypatch, output)
    photo = tmp_path / "alert.png"
    photo.write_bytes(b"png")
    monkeypatch.setattr(scheduled_delivery, "render_alert_card", lambda *_args, **_kwargs: photo)
    monkeypatch.setattr(
        scheduled_delivery,
        "send_photo_briefs",
        lambda **_kwargs: (type("Delivery", (), {"status": "delivered", "chat_id_hash": "hash"})(),),
    )
    scheduled_delivery.send(snapshot_path, "morning", manifest_path)
    text = output.read_text(encoding="utf-8")
    assert "sent=true" in text
    assert "delivery_mode=photo" in text


def test_scheduled_delivery_blocks_photo_when_renderer_fails(tmp_path, monkeypatch):
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
        "render_alert_card",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(scheduled_delivery.RendererError("chromium_unavailable")),
    )
    monkeypatch.setattr(
        scheduled_delivery,
        "send_photo_briefs",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must not send when renderer fails")),
    )
    scheduled_delivery.send(snapshot_path, "morning", manifest_path)
    text = output.read_text(encoding="utf-8")
    assert "sent=false" in text
    assert "reason=renderer_failed" in text
    assert "renderer_error_type=chromium_unavailable" in text


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
    monkeypatch.setattr(
        scheduled_delivery,
        "render_alert_card",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("quality gate must run before renderer")),
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
        "gooaye": "creator_records_unavailable",
    }


def test_creator_filtered_records_are_reported_as_parse_failure(tmp_path, monkeypatch):
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
    monkeypatch.setattr(scheduled_delivery, "write_snapshot", lambda snapshot, path: path.write_text(json.dumps(snapshot), encoding="utf-8") is None)
    monkeypatch.setattr(scheduled_delivery, "_pick_event", lambda *_args: None)
    monkeypatch.setattr(scheduled_delivery, "briefing_correlation", lambda *_args: {"trace_id": "t", "snapshot_id": "m-1", "observation_id": ""})
    monkeypatch.setattr(scheduled_delivery, "merge_published_metadata", lambda *_args, **_kwargs: True)
    scheduled_delivery.prepare("morning", snapshot_path)
    published = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert published["creator_insights"][0]["source"] == "gooaye"
    assert published["source_health"]["sources"]
    assert {row["key"] for row in published["source_health"]["sources"]} == {
        "creator_haojiao",
        "creator_gooaye",
    }
