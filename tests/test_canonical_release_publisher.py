from src import canonical_release_publisher as publisher


def _manifest(status="ready"):
    return {
        "status": status,
        "release_id": "release-12345678",
        "market_snapshot_id": "market-12345678",
        "validation_errors": [] if status == "ready" else ["broken"],
    }


def test_invalid_manifest_fails_closed_without_data_release_publish(tmp_path, monkeypatch):
    monkeypatch.setattr(publisher, "build_release_manifest", lambda **_: _manifest("invalid"))
    called = []
    monkeypatch.setattr(publisher, "publish_data_release", lambda **_: called.append(True))
    result = publisher.publish_canonical_release(root=tmp_path, manifest_path=tmp_path / "manifest.json")
    assert result["published"] is False
    assert result["reason"] == "manifest_invalid"
    assert not called


def test_dry_run_requires_local_gate_and_does_not_push(tmp_path, monkeypatch):
    monkeypatch.setattr(publisher, "build_release_manifest", lambda **_: _manifest())
    monkeypatch.setattr(publisher, "verify_release_for_delivery", lambda **_: type("Gate", (), {"allowed": True, "errors": ()})())
    monkeypatch.setattr(publisher, "publish_data_release", lambda **_: (_ for _ in ()).throw(AssertionError("must not push")))
    result = publisher.publish_canonical_release(root=tmp_path, manifest_path=tmp_path / "manifest.json", dry_run=True)
    assert result["dry_run"] is True
    assert result["reason"] == "dry_run"


def test_successful_publish_rechecks_gate(tmp_path, monkeypatch):
    monkeypatch.setattr(publisher, "build_release_manifest", lambda **_: _manifest())
    gates = iter([
        type("Gate", (), {"allowed": True, "errors": ()})(),
        type("Gate", (), {"allowed": True, "errors": ()})(),
    ])
    monkeypatch.setattr(publisher, "verify_release_for_delivery", lambda **_: next(gates))
    monkeypatch.setattr(publisher, "publish_data_release", lambda **_: {"published": True, "commit": "abc"})
    result = publisher.publish_canonical_release(root=tmp_path, manifest_path=tmp_path / "manifest.json")
    assert result["published"] is True
    assert result["reason"] == "published"
    assert result["commit"] == "abc"
