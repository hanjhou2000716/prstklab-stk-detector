from pathlib import Path

from src.public_release_smoke import run_public_release_smoke


def test_public_release_smoke_never_performs_delivery(monkeypatch, tmp_path):
    seen = {}

    class Result:
        allowed = True
        release_id = "release-test"
        snapshot_id = "market-test"
        errors = ()

    def verify(**kwargs):
        seen.update(kwargs)
        return Result()

    monkeypatch.setattr("src.public_release_smoke.verify_release_for_delivery", verify)
    report = run_public_release_smoke(
        manifest=tmp_path / "manifest.json",
        public_url="https://example.test/",
        expected_snapshot_id="market-test",
        attempts=1,
        delay=0,
    )
    assert report["ok"] is True
    assert report["delivery_performed"] is False
    assert seen["public_url"] == "https://example.test/"


def test_public_release_smoke_returns_gate_errors(monkeypatch, tmp_path):
    class Result:
        allowed = False
        release_id = ""
        snapshot_id = ""
        errors = ("public manifest unavailable",)

    monkeypatch.setattr("src.public_release_smoke.verify_release_for_delivery", lambda **_: Result())
    report = run_public_release_smoke(manifest=Path(tmp_path / "manifest.json"), public_url="https://example.test/")
    assert report["ok"] is False
    assert report["errors"] == ["public manifest unavailable"]
