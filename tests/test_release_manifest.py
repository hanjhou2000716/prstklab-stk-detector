import json

from src.release_manifest import build_release_manifest, verify_release_files, write_release_manifest


def _artifacts(tmp_path):
    site_data = tmp_path / "site" / "data"
    site_data.mkdir(parents=True)
    (site_data / "market.json").write_text(json.dumps({
        "generated_at": "2026-08-04T10:00:00+08:00",
        "snapshot_id": "market-12345678",
        "indices": [], "quotes": [], "source_health": {},
    }), encoding="utf-8")
    (site_data / "research-report.json").write_text(json.dumps({
        "schema_version": "2.0", "generated_at": "2026-08-04T10:00:00+08:00",
        "snapshot_id": "research-12345678", "sources": [], "candidates": [], "health": {},
    }), encoding="utf-8")
    (site_data / "event-ledger.json").write_text(json.dumps({"schema_version": 1, "retention_days": 30, "events": {}}), encoding="utf-8")


def test_manifest_is_ready_and_hashes_are_verifiable(tmp_path):
    _artifacts(tmp_path)
    manifest = build_release_manifest(root=tmp_path)
    assert manifest["status"] == "ready"
    assert manifest["artifact_paths"]["market.json"] == "data/market.json"
    assert verify_release_files(manifest, root=tmp_path / "site") == []


def test_manifest_fails_closed_for_missing_artifact(tmp_path):
    _artifacts(tmp_path)
    (tmp_path / "site" / "data" / "event-ledger.json").unlink()
    manifest = build_release_manifest(root=tmp_path)
    assert manifest["status"] == "invalid"
    assert any("missing artifact" in item for item in manifest["validation_errors"])


def test_manifest_detects_hash_tampering(tmp_path):
    _artifacts(tmp_path)
    manifest = build_release_manifest(root=tmp_path)
    write_release_manifest(manifest, tmp_path / "site" / "data" / "release-manifest.json")
    (tmp_path / "site" / "data" / "market.json").write_text("{}", encoding="utf-8")
    assert any("hash mismatch" in item for item in verify_release_files(manifest, root=tmp_path / "site"))


def test_manifest_normalizes_legacy_tpex_and_research_state(tmp_path):
    site_data = tmp_path / "site" / "data"
    site_data.mkdir(parents=True)
    (site_data / "market.json").write_text(json.dumps({
        "generated_at": "2026-08-04T10:00:00+08:00",
        "snapshot_id": "market-legacy01",
        "indices": [{
            "ticker": "TPEx", "price": 200, "quote_date": "2026-08-04",
            "source_label": "Yahoo", "quote_source": "Yahoo Finance",
            "source_url": "https://www.tpex.org.tw/example",
            "freshness": "recent", "technical_context": {"as_of": "2026-07-31"},
        }],
        "quotes": [], "source_health": {},
    }), encoding="utf-8")
    (site_data / "research-report.json").write_text(json.dumps({
        "schema_version": "2.0", "generated_at": "2026-08-04T10:00:00+08:00",
        "sources": [{
            "market": "taiwan", "strategy": "value", "scan_state": "complete",
            "candidates": 0, "data_gap_counts": {"universe": 0, "fundamentals": 0},
        }], "candidates": [], "health": {},
    }), encoding="utf-8")
    (site_data / "event-ledger.json").write_text(json.dumps({
        "schema_version": 1, "retention_days": 30, "events": {},
    }), encoding="utf-8")

    manifest = build_release_manifest(root=tmp_path)
    assert manifest["status"] == "ready"
    assert manifest["normalization_notes"]
    market = json.loads((site_data / "market.json").read_text(encoding="utf-8"))
    research = json.loads((site_data / "research-report.json").read_text(encoding="utf-8"))
    assert market["indices"][0]["source_label"] == "TPEx"
    assert market["indices"][0]["quote_source"] == "TPEx public quote"
    assert market["indices"][0]["technical_context_stale"] is True
    assert research["sources"][0]["candidate_state"] == "no_candidates"
    assert isinstance(research["sources"][0]["data_gap_counts"], int)
    assert research["snapshot_id"] == manifest["research_snapshot_id"]


def test_manifest_downgrades_unproven_formal_candidates_to_data_gap(tmp_path):
    """A stale summary must not make an empty published file fail the release."""
    _artifacts(tmp_path)
    site_data = tmp_path / "site" / "data"
    (site_data / "research-report.json").write_text(json.dumps({
        "schema_version": "2.0", "generated_at": "2026-08-04T10:00:00+08:00",
        "sources": [{
            "market": "us", "strategy": "value", "scan_state": "complete",
            "candidates": 0, "visible_candidates": 0,
            "formal_candidates": 5, "observation_candidates": 0,
            "candidate_state": "no_candidates",
        }], "candidates": [], "health": {},
    }), encoding="utf-8")

    manifest = build_release_manifest(root=tmp_path)
    assert manifest["status"] == "ready"
    research = json.loads((site_data / "research-report.json").read_text(encoding="utf-8"))
    source = research["sources"][0]
    assert source["formal_candidates"] == 0
    assert source["candidate_state"] == "data_gap"
    assert source["data_gap_counts"] == 1
    assert any("count mismatch" in note for note in manifest["normalization_notes"])


def test_manifest_url_is_authoritative_when_fallback_domain_is_stale(tmp_path):
    site_data = tmp_path / "site" / "data"
    site_data.mkdir(parents=True)
    (site_data / "market.json").write_text(json.dumps({
        "generated_at": "2026-08-04T10:00:00+08:00",
        "snapshot_id": "market-url01",
        "indices": [{
            "ticker": "TAIEX", "price": 200, "quote_date": "2026-08-04",
            "source_label": "TPEx", "quote_source": "TPEx public quote",
            "source_domain": "tpex.org.tw",
            "source_url": "https://finance.yahoo.com/quote/^TWII",
            "freshness": "recent",
        }],
        "quotes": [], "source_health": {},
    }), encoding="utf-8")
    (site_data / "research-report.json").write_text(json.dumps({
        "schema_version": "2.0", "generated_at": "2026-08-04T10:00:00+08:00",
        "sources": [], "candidates": [], "health": {},
    }), encoding="utf-8")
    (site_data / "event-ledger.json").write_text(json.dumps({
        "schema_version": 1, "retention_days": 30, "events": {},
    }), encoding="utf-8")

    manifest = build_release_manifest(root=tmp_path)
    assert manifest["status"] == "ready"
    market = json.loads((site_data / "market.json").read_text(encoding="utf-8"))
    quote = market["indices"][0]
    assert quote["source_domain"] == "finance.yahoo.com"
    assert quote["source_label"] == "Yahoo"
    assert quote["quote_source"] == "Yahoo public quote"


def test_manifest_downgrades_stale_live_quote_and_blocks_alert(tmp_path):
    site_data = tmp_path / "site" / "data"
    site_data.mkdir(parents=True)
    (site_data / "market.json").write_text(json.dumps({
        "generated_at": "2026-08-04T10:00:00+08:00",
        "snapshot_id": "market-stale01",
        "indices": [{
            "ticker": "TAIEX", "price": 200, "quote_date": "2026-08-04",
            "source_label": "TWSE", "quote_source": "TWSE MIS",
            "source_url": "https://mis.twse.com.tw/stock/api/getStockInfo.jsp",
            "freshness": "live", "stale_used": True, "alert_eligible": True,
        }],
        "quotes": [], "source_health": {},
    }), encoding="utf-8")
    (site_data / "research-report.json").write_text(json.dumps({
        "schema_version": "2.0", "generated_at": "2026-08-04T10:00:00+08:00",
        "snapshot_id": "research-stale01", "sources": [], "candidates": [], "health": {},
    }), encoding="utf-8")
    (site_data / "event-ledger.json").write_text(json.dumps({
        "schema_version": 1, "retention_days": 30, "events": {},
    }), encoding="utf-8")

    manifest = build_release_manifest(root=tmp_path)
    assert manifest["status"] == "ready"
    quote = json.loads((site_data / "market.json").read_text(encoding="utf-8"))["indices"][0]
    assert quote["freshness"] == "recent_close"
    assert quote["alert_eligible"] is False
