from __future__ import annotations

import json
from pathlib import Path

from src.creator_dispatch import dispatch


def _bundle(tmp_path: Path, *, include_morning_batch: bool = False) -> Path:
    site = tmp_path / "site" / "data"
    site.mkdir(parents=True)
    market = {"snapshot_id": "market-1"}
    research = {"snapshot_id": "research-1"}
    events = {"snapshot_id": "event-1"}
    for name, value in (("market.json", market), ("research-report.json", research), ("event-ledger.json", events)):
        (site / name).write_text(json.dumps(value), encoding="utf-8")
    insights = [{
            "episode_key": "haojiao:ep-1",
            "content_origin": "haojiao",
            "creator_id": "haojiao",
            "episode_title": "Market note",
            "public_safe": True,
            "verification_state": "unverified",
        }]
    if include_morning_batch:
        insights.append({
            "episode_key": "jenny:ep-1",
            "content_origin": "jenny",
            "creator_id": "jenny",
            "episode_title": "Second market note",
            "public_safe": True,
            "verification_state": "unverified",
        })
    creator = {
        "schema_version": "1.0",
        "parent_release_id": "release-1",
        "market_snapshot_id": "market-1",
        "event_snapshot_id": "event-1",
        "status": "ready",
        "public_safe": True,
        "creator_consensus": {"consensus_state": "insufficient_sources"},
        "insights": insights,
    }
    creator_path = site / "creator-release.json"
    creator_path.write_text(json.dumps(creator), encoding="utf-8")
    from src.release_manifest import sha256_file

    paths = {
        "market.json": "data/market.json",
        "research-report.json": "data/research-report.json",
        "event-ledger.json": "data/event-ledger.json",
        "creator-release.json": "data/creator-release.json",
    }
    hashes = {name: sha256_file(site / Path(path).name) for name, path in paths.items()}
    manifest = {
        "status": "ready",
        "release_id": "release-1",
        "market_snapshot_id": "market-1",
        "research_snapshot_id": "research-1",
        "event_snapshot_id": "event-1",
        "creator_release_id": "creator-1",
        "creator_snapshot_id": "creator-snapshot-1",
        "creator_status": "ready",
        "artifact_paths": paths,
        "artifact_hashes": hashes,
    }
    # The creator release contract only requires the parent/event IDs; the
    # test intentionally exercises dispatch independently of a full market
    # artifact contract.  The verification root is the Pages directory.
    creator["release_id"] = "creator-1"
    if include_morning_batch:
        creator["morning_batch"] = {
            "batch_key": "creator-morning:2026-08-14:batch-1",
            "state": "complete",
            "expected_count": 2,
            "received_count": 2,
            "late_arrivals": [],
            "records": [
                {"episode_key": "haojiao:ep-1", "creator_id": "haojiao"},
                {"episode_key": "jenny:ep-1", "creator_id": "jenny"},
            ],
        }
    creator_path.write_text(json.dumps(creator), encoding="utf-8")
    manifest["artifact_hashes"]["creator-release.json"] = sha256_file(creator_path)
    path = site / "release-manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def _enable_test_creator_lane(monkeypatch) -> None:
    """Keep delivery mechanics covered without re-enabling production sources."""
    monkeypatch.setattr("src.creator_dispatch.creator_ids", lambda *, enabled_only=False: ("haojiao", "jenny"))
    monkeypatch.setattr("src.creator_notification.creator_ids", lambda *, enabled_only=False: ("haojiao", "jenny"))
    monkeypatch.setattr("src.creator_delivery_contract.is_active_creator", lambda _creator: True)


def test_disabled_creator_dispatch_is_noop(tmp_path, monkeypatch):
    monkeypatch.delenv("CREATOR_NOTIFICATION_ENABLED", raising=False)
    result = dispatch(manifest_path=tmp_path / "missing.json", public_url="https://example.test/app")
    assert result["status"] == "disabled"
    assert result["reasons"] == ["retired_source_suppressed"]


def test_retired_creator_dispatch_never_calls_sender(tmp_path, monkeypatch):
    monkeypatch.setenv("CREATOR_NOTIFICATION_ENABLED", "true")
    calls: list[dict] = []
    monkeypatch.setattr("src.creator_notification.send_briefs", lambda **kwargs: calls.append(kwargs))
    result = dispatch(
        manifest_path=tmp_path / "missing.json",
        public_url="https://example.test/app",
        token="token",
        chat_ids=("test-chat",),
    )
    assert result["status"] == "disabled"
    assert result["reasons"] == ["retired_source_suppressed"]
    assert calls == []


def test_creator_dispatch_blocks_invalid_release(tmp_path, monkeypatch):
    monkeypatch.setenv("CREATOR_NOTIFICATION_ENABLED", "true")
    _enable_test_creator_lane(monkeypatch)
    result = dispatch(manifest_path=tmp_path / "missing.json", public_url="https://example.test/app")
    assert result["status"] == "blocked"
    assert "manifest_unreadable" in result["reasons"]


def test_creator_dispatch_sends_once_and_persists_receipt(tmp_path, monkeypatch):
    monkeypatch.setenv("CREATOR_NOTIFICATION_ENABLED", "true")
    _enable_test_creator_lane(monkeypatch)
    manifest = _bundle(tmp_path)
    receipt_path = tmp_path / "private" / "receipts.json"
    calls: list[dict] = []

    def fake_text_sender(**kwargs):
        calls.append(kwargs)
        class Result:
            message_id = 17
        class Delivery:
            chat_id = kwargs["chat_ids"][0]
            result = Result()
            error = None
            @property
            def delivered(self):
                return True
        return (Delivery(),)

    monkeypatch.setattr("src.creator_notification.send_briefs", fake_text_sender)
    result = dispatch(
        manifest_path=manifest,
        public_url="https://example.test/app",
        receipt_path=receipt_path,
        token="token",
        chat_ids=("test-chat",),
    )
    assert result["status"] == "delivered"
    assert calls
    assert receipt_path.exists()
    assert "test-chat" not in receipt_path.read_text(encoding="utf-8")


def test_creator_dispatch_rejects_invalid_media_before_photo_sender(tmp_path, monkeypatch):
    monkeypatch.setenv("CREATOR_NOTIFICATION_ENABLED", "true")
    _enable_test_creator_lane(monkeypatch)
    manifest = _bundle(tmp_path)
    media_root = tmp_path / "private-media"
    media_root.mkdir()
    (media_root / "haojiao_ep-1.png").write_bytes(b"not-a-png")
    photo_calls: list[dict] = []
    text_calls: list[dict] = []

    def fake_photo_sender(**kwargs):
        photo_calls.append(kwargs)
        raise AssertionError("invalid media must not reach photo sender")

    def fake_text_sender(**kwargs):
        text_calls.append(kwargs)

        class Result:
            message_id = 19

        class Delivery:
            chat_id = kwargs["chat_ids"][0]
            result = Result()
            error = None

            @property
            def delivered(self):
                return True

        return (Delivery(),)

    monkeypatch.setattr("src.creator_notification.send_photo_briefs", fake_photo_sender)
    monkeypatch.setattr("src.creator_notification.send_briefs", fake_text_sender)
    result = dispatch(
        manifest_path=manifest,
        public_url="https://example.test/app",
        media_root=media_root,
        token="token",
        chat_ids=("test-chat",),
    )
    assert result["status"] == "delivered"
    assert photo_calls == []
    assert text_calls
    assert result["receipts"][0]["media_mode"] == "text_only"


def test_creator_dispatch_fails_closed_when_configured_remote_history_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.setenv("CREATOR_NOTIFICATION_ENABLED", "true")
    _enable_test_creator_lane(monkeypatch)
    monkeypatch.setenv("RAILWAY_STATUS_URL", "https://railway.example")
    monkeypatch.setenv("RAILWAY_STATUS_SHARED_SECRET", "secret")
    manifest = _bundle(tmp_path)
    monkeypatch.setattr(
        "src.creator_dispatch.load_remote_creator_delivery_history",
        lambda *_args, **_kwargs: ([], "unavailable"),
    )
    result = dispatch(manifest_path=manifest, public_url="https://example.test/app", token="token", chat_ids=("test-chat",))
    assert result["status"] == "blocked"
    assert result["reasons"] == ["creator_delivery_history_unavailable"]


def test_creator_dispatch_prefers_worker_history_and_uses_worker_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("CREATOR_NOTIFICATION_ENABLED", "true")
    _enable_test_creator_lane(monkeypatch)
    monkeypatch.setenv("RECEIPT_CALLBACK_URL", "https://worker.example/api/delivery-receipt")
    monkeypatch.setenv("DELIVERY_RECEIPT_SHARED_SECRET", "worker-secret")
    monkeypatch.setenv("RAILWAY_STATUS_URL", "https://railway.example")
    monkeypatch.setenv("RAILWAY_STATUS_SHARED_SECRET", "railway-secret")
    manifest = _bundle(tmp_path)
    calls: list[tuple[str | None, str | None]] = []

    def fake_history(url, secret, **_kwargs):
        calls.append((url, secret))
        return [{"notification_key": "creator:haojiao:ep-1:initial", "delivery_status": "delivered"}], "healthy"

    monkeypatch.setattr("src.creator_dispatch.load_remote_creator_delivery_history", fake_history)
    result = dispatch(manifest_path=manifest, public_url="https://example.test/app", token="token", chat_ids=("test-chat",))
    assert result["status"] == "no_new_content"
    assert calls == [("https://worker.example/api/delivery-receipt", "worker-secret")]


def test_complete_morning_batch_sends_episode_notifications_and_one_digest(tmp_path, monkeypatch):
    monkeypatch.setenv("CREATOR_NOTIFICATION_ENABLED", "true")
    _enable_test_creator_lane(monkeypatch)
    manifest = _bundle(tmp_path, include_morning_batch=True)
    calls: list[dict] = []

    def fake_text_sender(**kwargs):
        calls.append(kwargs)

        class Result:
            message_id = 17 + len(calls)

        class Delivery:
            chat_id = kwargs["chat_ids"][0]
            result = Result()
            error = None

            @property
            def delivered(self):
                return True

        return (Delivery(),)

    monkeypatch.setattr("src.creator_notification.send_briefs", fake_text_sender)
    result = dispatch(
        manifest_path=manifest,
        public_url="https://example.test/app",
        token="token",
        chat_ids=("test-chat",),
    )
    assert result["status"] == "delivered"
    assert result["sent"] == 3
    assert len(calls) == 3
    assert calls[-1]["text"].startswith("Creator morning 2/2")
    assert "target_url" in calls[-1]


def test_morning_digest_is_idempotent_after_receipt_is_persisted(tmp_path, monkeypatch):
    monkeypatch.setenv("CREATOR_NOTIFICATION_ENABLED", "true")
    _enable_test_creator_lane(monkeypatch)
    manifest = _bundle(tmp_path, include_morning_batch=True)
    receipt_path = tmp_path / "private" / "receipts.json"
    calls: list[dict] = []

    def fake_text_sender(**kwargs):
        calls.append(kwargs)

        class Result:
            message_id = 42

        class Delivery:
            chat_id = kwargs["chat_ids"][0]
            result = Result()
            error = None

            @property
            def delivered(self):
                return True

        return (Delivery(),)

    monkeypatch.setattr("src.creator_notification.send_briefs", fake_text_sender)
    first = dispatch(
        manifest_path=manifest,
        public_url="https://example.test/app",
        receipt_path=receipt_path,
        token="token",
        chat_ids=("test-chat",),
    )
    second = dispatch(
        manifest_path=manifest,
        public_url="https://example.test/app",
        receipt_path=receipt_path,
        token="token",
        chat_ids=("test-chat",),
    )
    assert first["sent"] == 3
    assert second["status"] == "no_new_content"
    assert second["sent"] == 0
    assert len(calls) == 3
