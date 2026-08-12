import json
from pathlib import Path

from src.release_gate import (
    _fetch_public_release_artifacts,
    _load_release_artifacts,
    verify_release_for_delivery,
)
from src.release_manifest import build_release_manifest, sha256_file, write_release_manifest


def _ready_release(tmp_path):
    data = tmp_path / "site" / "data"
    data.mkdir(parents=True)
    (data / "market.json").write_text(json.dumps({
        "generated_at": "2026-08-04T10:00:00+08:00",
        "snapshot_id": "market-12345678",
        "indices": [], "quotes": [], "source_health": {},
    }), encoding="utf-8")
    (data / "research-report.json").write_text(json.dumps({
        "schema_version": "2.0", "generated_at": "2026-08-04T10:00:00+08:00",
        "snapshot_id": "research-12345678", "sources": [], "candidates": [], "health": {},
        "scan_mode": "production", "scan_scope": "full", "publish_eligible": True,
        "production_eligible": True, "universe_expected": 1, "universe_scanned": 1,
        "universe_completed": 1, "universe_failed": 0,
        "run_id": "fixture-research-run",
        "research_run": {
            "run_id": "fixture-research-run",
            "source_commit_sha": "f" * 40,
            "scan_mode": "production", "scan_scope": "full",
            "run_started_at": "2026-08-04T09:59:00+00:00",
            "run_finished_at": "2026-08-04T10:00:00+00:00",
            "producer": "src.run_research_report",
        },
    }), encoding="utf-8")
    (data / "event-ledger.json").write_text(json.dumps({"schema_version": 1, "retention_days": 30, "events": {}}), encoding="utf-8")
    manifest = build_release_manifest(root=tmp_path)
    write_release_manifest(manifest, data / "release-manifest.json")
    return data / "release-manifest.json", manifest


def _public_response(body: bytes, value=None):
    class Response:
        content = body

        def raise_for_status(self):
            return None

        def json(self):
            return value if value is not None else json.loads(body.decode("utf-8"))

    return Response()


def _public_artifact_response(manifest, data, url):
    path = url.split("?", 1)[0]
    name = path.rstrip("/").rsplit("/", 1)[-1]
    if name == "release-manifest.json":
        body = json.dumps(manifest, ensure_ascii=False).encode("utf-8")
        return _public_response(body, manifest)
    return _public_response((data / name).read_bytes())


def test_release_gate_accepts_ready_matching_snapshot(tmp_path):
    path, manifest = _ready_release(tmp_path)
    result = verify_release_for_delivery(manifest_path=path, expected_snapshot_id="market-12345678")
    assert result.allowed is True
    assert result.release_id == manifest["release_id"]


def test_release_gate_accepts_ready_legacy_research_snapshot(tmp_path):
    """A valid rollback release may predate the production scan contract."""
    path, manifest = _ready_release(tmp_path)
    research_path = tmp_path / "site" / "data" / "research-report.json"
    legacy = {
        "schema_version": "1.0",
        "generated_at": "2026-08-04T10:00:00+08:00",
        "snapshot_id": "research-12345678",
        "sources": [],
        "candidates": [],
        "health": {},
    }
    research_path.write_text(json.dumps(legacy), encoding="utf-8")
    manifest["artifact_hashes"]["research-report.json"] = sha256_file(research_path)
    write_release_manifest(manifest, path)
    result = verify_release_for_delivery(manifest_path=path, expected_snapshot_id="market-12345678")
    assert result.allowed is True


def test_release_gate_blocks_snapshot_mismatch(tmp_path):
    path, _ = _ready_release(tmp_path)
    result = verify_release_for_delivery(manifest_path=path, expected_snapshot_id="market-other")
    assert result.allowed is False
    assert "does not match prepared snapshot" in ";".join(result.errors)


def test_release_gate_blocks_tampered_artifact(tmp_path):
    path, _ = _ready_release(tmp_path)
    (tmp_path / "site" / "data" / "market.json").write_text("{}", encoding="utf-8")
    result = verify_release_for_delivery(manifest_path=path, expected_snapshot_id="market-12345678")
    assert result.allowed is False
    assert any("hash mismatch" in error for error in result.errors)


def test_release_gate_revalidates_artifact_semantics(tmp_path):
    path, manifest = _ready_release(tmp_path)
    event_path = tmp_path / "site" / "data" / "event-ledger.json"
    event_path.write_text(json.dumps({
        "schema_version": 1,
        "retention_days": 30,
        "events": {
            "event-12345678": {
                "canonical_key": "different-key",
                "event_type": "macro",
                "source_url": "https://example.com/event",
                "source_domain": "example.com",
                "first_discovered_at": "2026-08-04T10:00:00+00:00",
                "updated_at": "2026-08-04T10:05:00+00:00",
                "verified_sources": ["https://example.com/event"],
            }
        },
    }), encoding="utf-8")
    manifest["artifact_hashes"]["event-ledger.json"] = sha256_file(event_path)
    write_release_manifest(manifest, path)
    result = verify_release_for_delivery(manifest_path=path, expected_snapshot_id="market-12345678")
    assert result.allowed is False
    assert any("canonical_key" in error for error in result.errors)


def test_release_gate_retries_pages_propagation_until_release_matches(tmp_path, monkeypatch):
    path, manifest = _ready_release(tmp_path)
    data = tmp_path / "site" / "data"

    class Response:
        def __init__(self, release_id):
            self.release_id = release_id
            self.content = json.dumps({
                "status": "ready", "release_id": release_id,
                "market_snapshot_id": "market-12345678",
            }).encode("utf-8")

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "status": "ready",
                "release_id": self.release_id,
                "market_snapshot_id": "market-12345678",
            }

    calls = {"manifest": 0}

    def get(url, **kwargs):
        if url.split("?", 1)[0].endswith("release-manifest.json"):
            calls["manifest"] += 1
            if calls["manifest"] == 1:
                return Response("release-old")
            return _public_artifact_response(manifest, data, url)
        return _public_artifact_response(manifest, data, url)

    monkeypatch.setattr("src.release_gate.requests.get", get)
    monkeypatch.setattr("src.release_gate.time.sleep", lambda *_args: None)

    result = verify_release_for_delivery(
        manifest_path=path,
        expected_snapshot_id="market-12345678",
        public_url="https://example.test/",
        public_attempts=2,
        public_delay=0,
    )

    assert result.allowed is True


def test_release_gate_blocks_public_snapshot_mismatch(tmp_path, monkeypatch):
    path, manifest = _ready_release(tmp_path)

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "status": "ready",
                "release_id": manifest["release_id"],
                "market_snapshot_id": "market-old",
            }

    monkeypatch.setattr("src.release_gate.requests.get", lambda *args, **kwargs: Response())
    result = verify_release_for_delivery(
        manifest_path=path,
        expected_snapshot_id="market-12345678",
        public_url="https://example.test/",
        public_attempts=1,
        public_delay=0,
    )

    assert result.allowed is False
    assert "public manifest market snapshot does not match prepared snapshot" in ";".join(result.errors)


def test_release_gate_cache_busts_public_manifest_requests(tmp_path, monkeypatch):
    path, manifest = _ready_release(tmp_path)
    data = tmp_path / "site" / "data"
    seen = {"manifest_url": ""}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "status": "ready",
                "release_id": manifest["release_id"],
                "market_snapshot_id": "market-12345678",
            }

    def get(url, **kwargs):
        seen["headers"] = kwargs["headers"]
        if url.split("?", 1)[0].endswith("release-manifest.json"):
            seen["manifest_url"] = url
            return _public_artifact_response(manifest, data, url)
        return _public_artifact_response(manifest, data, url)

    monkeypatch.setattr("src.release_gate.requests.get", get)
    result = verify_release_for_delivery(
        manifest_path=path,
        expected_snapshot_id="market-12345678",
        public_url="https://example.test/",
        public_attempts=1,
        public_delay=0,
    )

    assert result.allowed is True
    assert "release_id=" in seen["manifest_url"]
    assert "attempt=1" in seen["manifest_url"]
    assert seen["headers"]["Cache-Control"] == "no-cache, no-store"


def test_release_gate_blocks_public_artifact_hash_mismatch(tmp_path, monkeypatch):
    path, manifest = _ready_release(tmp_path)
    data = tmp_path / "site" / "data"

    def get(url, **kwargs):
        if url.split("?", 1)[0].endswith("release-manifest.json"):
            return _public_artifact_response(manifest, data, url)
        if url.split("?", 1)[0].endswith("market.json"):
            return _public_response(b"{\"tampered\":true}")
        return _public_artifact_response(manifest, data, url)

    monkeypatch.setattr("src.release_gate.requests.get", get)
    result = verify_release_for_delivery(
        manifest_path=path,
        expected_snapshot_id="market-12345678",
        public_url="https://example.test/",
        public_attempts=1,
        public_delay=0,
    )

    assert result.allowed is False
    assert "public artifact hash mismatch: market.json" in ";".join(result.errors)


def test_release_gate_writes_actions_output_as_key_value_lines(tmp_path, monkeypatch):
    path, _ = _ready_release(tmp_path)
    output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    # Importing the module entry point directly keeps this test independent
    # from a shell and verifies the format consumed by workflow expressions.
    from src import release_gate

    monkeypatch.setattr("sys.argv", ["release_gate", "--manifest", str(path)])
    assert release_gate.main() == 0
    text = Path(output).read_text(encoding="utf-8")
    assert "allowed=true" in text
    assert "release_id=" in text
    assert text.count("{") == 0


def test_release_gate_blocks_unreadable_and_invalid_manifest(tmp_path):
    missing = verify_release_for_delivery(manifest_path=tmp_path / "missing.json")
    assert not missing.allowed and "manifest unreadable" in missing.errors[0]
    invalid = tmp_path / "invalid.json"
    invalid.write_text("[]", encoding="utf-8")
    result = verify_release_for_delivery(manifest_path=invalid)
    assert not result.allowed and "manifest must be a JSON object" in result.errors


def test_release_gate_reports_unreadable_artifact(tmp_path):
    path, _ = _ready_release(tmp_path)
    (tmp_path / "site" / "data" / "event-ledger.json").unlink()
    result = verify_release_for_delivery(manifest_path=path, expected_snapshot_id="market-12345678")
    assert result.allowed is False
    assert any("artifact unreadable event-ledger.json" in error for error in result.errors)


def test_release_gate_defensive_artifact_loaders_fail_closed(tmp_path):
    """Malformed public manifests must produce explicit errors, not partial success."""
    loaded, errors = _load_release_artifacts({}, site_root=tmp_path)
    assert loaded == {}
    assert errors == ["manifest artifact paths are missing"]

    (tmp_path / "bad.json").write_text("{", encoding="utf-8")
    (tmp_path / "list.json").write_text("[]", encoding="utf-8")
    loaded, errors = _load_release_artifacts(
        {"artifact_paths": {
            "market.json": "bad.json",
            "research-report.json": "list.json",
            "event-ledger.json": "missing.json",
        }},
        site_root=tmp_path,
    )
    assert loaded == {}
    assert any("JSONDecodeError" in error for error in errors)
    assert any("must be an object" in error for error in errors)
    assert any("FileNotFoundError" in error for error in errors)

    _, errors = _fetch_public_release_artifacts(
        {"artifact_paths": {}, "artifact_hashes": {}},
        public_url="https://example.test/",
        timeout=1,
    )
    assert errors == [
        "public manifest path missing: market.json",
        "public manifest path missing: research-report.json",
        "public manifest path missing: event-ledger.json",
    ]
    _, errors = _fetch_public_release_artifacts(
        {"artifact_paths": {}, "artifact_hashes": {}},
        public_url="http://example.test/",
        timeout=1,
    )
    assert errors == ["public release URL must use HTTPS"]
