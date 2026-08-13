from __future__ import annotations

import json
from pathlib import Path

from src.creator_dispatch import dispatch


def _bundle(tmp_path: Path) -> Path:
    site = tmp_path / "site" / "data"
    site.mkdir(parents=True)
    market = {"snapshot_id": "market-1"}
    research = {"snapshot_id": "research-1"}
    events = {"snapshot_id": "event-1"}
    for name, value in (("market.json", market), ("research-report.json", research), ("event-ledger.json", events)):
        (site / name).write_text(json.dumps(value), encoding="utf-8")
    creator = {
        "schema_version": "1.0",
        "parent_release_id": "release-1",
        "market_snapshot_id": "market-1",
        "event_snapshot_id": "event-1",
        "status": "ready",
        "public_safe": True,
        "creator_consensus": {"consensus_state": "insufficient_sources"},
        "insights": [{
            "episode_key": "haojiao:ep-1",
            "content_origin": "haojiao",
            "creator_id": "haojiao",
            "episode_title": "Market note",
            "public_safe": True,
            "verification_state": "unverified",
        }],
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
    creator_path.write_text(json.dumps(creator), encoding="utf-8")
    manifest["artifact_hashes"]["creator-release.json"] = sha256_file(creator_path)
    path = site / "release-manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_disabled_creator_dispatch_is_noop(tmp_path, monkeypatch):
    monkeypatch.delenv("CREATOR_NOTIFICATION_ENABLED", raising=False)
    result = dispatch(manifest_path=tmp_path / "missing.json", public_url="https://example.test/app")
    assert result["status"] == "disabled"


def test_creator_dispatch_blocks_invalid_release(tmp_path, monkeypatch):
    monkeypatch.setenv("CREATOR_NOTIFICATION_ENABLED", "true")
    result = dispatch(manifest_path=tmp_path / "missing.json", public_url="https://example.test/app")
    assert result["status"] == "blocked"
    assert "manifest_unreadable" in result["reasons"]


def test_creator_dispatch_sends_once_and_persists_receipt(tmp_path, monkeypatch):
    monkeypatch.setenv("CREATOR_NOTIFICATION_ENABLED", "true")
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
