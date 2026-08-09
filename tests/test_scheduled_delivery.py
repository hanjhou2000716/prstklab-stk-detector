import json

from src import scheduled_delivery
from src.release_gate import ReleaseGateResult


def test_scheduled_delivery_blocks_when_manifest_is_not_ready(tmp_path, monkeypatch):
    snapshot_path = tmp_path / "market.json"
    manifest_path = tmp_path / "release-manifest.json"
    snapshot_path.write_text(json.dumps({"snapshot_id": "market-12345678", "quotes": [], "indices": []}), encoding="utf-8")
    manifest_path.write_text(json.dumps({"status": "invalid", "release_id": "release-old"}), encoding="utf-8")
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))

    def fail_if_called(**_kwargs):
        raise AssertionError("Telegram must not be called when release gate fails")

    monkeypatch.setattr(scheduled_delivery, "send_briefs", fail_if_called)
    scheduled_delivery.send(snapshot_path, "morning", manifest_path)
    text = output.read_text(encoding="utf-8")
    assert "sent=false" in text
    assert "reason=release_gate_blocked" in text


def test_scheduled_delivery_uses_text_delivery_after_release_gate(tmp_path, monkeypatch):
    snapshot_path = tmp_path / "market.json"
    manifest_path = tmp_path / "release-manifest.json"
    snapshot_path.write_text(json.dumps({"snapshot_id": "market-12345678", "quotes": [], "indices": [], "briefing": {}}), encoding="utf-8")
    manifest_path.write_text("{}", encoding="utf-8")
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr(scheduled_delivery, "verify_release_for_delivery", lambda **_kwargs: ReleaseGateResult(True, release_id="release-1", snapshot_id="market-12345678"))
    monkeypatch.setattr(scheduled_delivery, "get_settings", lambda: type("Settings", (), {"telegram_ready": True, "telegram_bot_token": "token", "telegram_chat_ids": ("test",), "dashboard_url": "https://example.test/app"})())
    monkeypatch.setattr(scheduled_delivery, "_pick_event", lambda *_args: None)
    monkeypatch.setattr(scheduled_delivery, "briefing_correlation", lambda *_args: {"trace_id": "trace-1", "snapshot_id": "market-12345678", "observation_id": "obs-1"})
    monkeypatch.setattr(scheduled_delivery, "build_brief", lambda *_args: "測試摘要")

    monkeypatch.setattr(
        scheduled_delivery,
        "send_briefs",
        lambda **_kwargs: (type("Delivery", (), {"delivered": True})(),),
    )
    scheduled_delivery.send(snapshot_path, "morning", manifest_path)
    text = output.read_text(encoding="utf-8")
    assert "sent=true" in text
    assert "delivery_mode=text" in text


def test_scheduled_delivery_does_not_require_renderer_for_production_text(tmp_path, monkeypatch):
    snapshot_path = tmp_path / "market.json"
    manifest_path = tmp_path / "release-manifest.json"
    snapshot_path.write_text(json.dumps({"snapshot_id": "market-12345678", "quotes": [], "indices": [], "briefing": {}}), encoding="utf-8")
    manifest_path.write_text("{}", encoding="utf-8")
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr(scheduled_delivery, "verify_release_for_delivery", lambda **_kwargs: ReleaseGateResult(True, release_id="release-1", snapshot_id="market-12345678"))
    monkeypatch.setattr(scheduled_delivery, "get_settings", lambda: type("Settings", (), {"telegram_ready": True, "telegram_bot_token": "token", "telegram_chat_ids": ("test",), "dashboard_url": "https://example.test/app"})())
    monkeypatch.setattr(scheduled_delivery, "_pick_event", lambda *_args: None)
    monkeypatch.setattr(scheduled_delivery, "briefing_correlation", lambda *_args: {"trace_id": "trace-1", "snapshot_id": "market-12345678", "observation_id": "obs-1"})
    monkeypatch.setattr(scheduled_delivery, "build_brief", lambda *_args: "測試摘要")
    monkeypatch.setattr(
        scheduled_delivery,
        "send_briefs",
        lambda **_kwargs: (type("Delivery", (), {"delivered": True})(),),
    )
    scheduled_delivery.send(snapshot_path, "morning", manifest_path)
    text = output.read_text(encoding="utf-8")
    assert "sent=true" in text
    assert "delivery_mode=text" in text
