import json

from src.news_intelligence import build_news_intelligence
from src.release_manifest import (
    _gap_count,
    _normalize_market,
    _normalize_research,
    _read_object,
    build_release_manifest,
    content_snapshot_id,
    sha256_file,
    verify_release_files,
    write_release_manifest,
)


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


def test_manifest_publishes_release_bound_news_intelligence(tmp_path):
    _artifacts(tmp_path)
    market_path = tmp_path / "site" / "data" / "market.json"
    market = json.loads(market_path.read_text(encoding="utf-8"))
    market["news"] = {
        "provider_registry": build_news_intelligence([])["provider_registry"],
        "intelligence": build_news_intelligence(
            [{"title": "Fed statement", "url": "https://www.federalreserve.gov/a"}],
            market="us",
        ),
    }
    market_path.write_text(json.dumps(market), encoding="utf-8")

    manifest = build_release_manifest(root=tmp_path)

    assert manifest["status"] == "ready"
    assert manifest["artifact_paths"]["news.json"] == "data/news.json"
    assert manifest["schema_versions"]["news"] == "1.0"
    news = json.loads((tmp_path / "site" / "data" / "news.json").read_text(encoding="utf-8"))
    assert news["market_snapshot_id"] == manifest["market_snapshot_id"]
    assert verify_release_files(manifest, root=tmp_path / "site") == []


def test_manifest_records_external_observation_lineage(tmp_path):
    _artifacts(tmp_path)
    market_path = tmp_path / "site" / "data" / "market.json"
    market = json.loads(market_path.read_text(encoding="utf-8"))
    market["external_observations"] = [
        {"observation_id": "fj-2", "source": "FinancialJuice"},
        {"observation_id": "fj-1", "source": "financialjuice"},
    ]
    market_path.write_text(json.dumps(market), encoding="utf-8")

    manifest = build_release_manifest(root=tmp_path)

    assert manifest["external_observation_count"] == 2
    assert manifest["external_observation_sources"] == ["financialjuice"]
    assert manifest["external_observation_status"] == "ready"
    assert manifest["external_observation_ids_hash"]
    assert verify_release_files(manifest, root=tmp_path / "site") == []


def test_manifest_publishes_multi_market_news_release(tmp_path):
    _artifacts(tmp_path)
    market_path = tmp_path / "site" / "data" / "market.json"
    registry = build_news_intelligence([])["provider_registry"]
    market = json.loads(market_path.read_text(encoding="utf-8"))
    market["news"] = {
        "provider_registry": registry,
        "intelligence": {
            "taiwan": build_news_intelligence(
                [{"title": "TWSE filing", "url": "https://www.twse.com.tw/a"}],
                market="taiwan",
            ),
            "us": build_news_intelligence(
                [{"title": "Fed statement", "url": "https://www.federalreserve.gov/a"}],
                market="us",
            ),
        },
    }
    market_path.write_text(json.dumps(market), encoding="utf-8")
    manifest = build_release_manifest(root=tmp_path)
    assert manifest["status"] == "ready"
    news = json.loads((tmp_path / "site" / "data" / "news.json").read_text(encoding="utf-8"))
    assert set(news["markets"]) == {"taiwan", "us"}
    assert news["market_snapshot_id"] == manifest["market_snapshot_id"]
    assert verify_release_files(manifest, root=tmp_path / "site") == []


def test_multi_market_news_release_schema_rejects_missing_lineage(tmp_path):
    _artifacts(tmp_path)
    market_path = tmp_path / "site" / "data" / "market.json"
    market = json.loads(market_path.read_text(encoding="utf-8"))
    market["news"] = {
        "provider_registry": build_news_intelligence([])["provider_registry"],
        "intelligence": {"taiwan": build_news_intelligence([], market="taiwan")},
    }
    market_path.write_text(json.dumps(market), encoding="utf-8")
    manifest = build_release_manifest(root=tmp_path)
    news_path = tmp_path / "site" / "data" / "news.json"
    news = json.loads(news_path.read_text(encoding="utf-8"))
    news.pop("market_snapshot_id")
    news_path.write_text(json.dumps(news), encoding="utf-8")
    manifest["artifact_hashes"]["news.json"] = sha256_file(news_path)
    assert verify_release_files(manifest, root=tmp_path / "site") == []
    # The local release gate, unlike hash-only verification, rejects the
    # malformed envelope before delivery.
    from src.release_gate import _validate_news_artifact

    errors = _validate_news_artifact(news, manifest)
    assert any("market_snapshot_id" in error for error in errors)


def test_manifest_publishes_release_bound_source_health_artifact(tmp_path):
    _artifacts(tmp_path)
    health_path = tmp_path / "site" / "data" / "source-health.json"
    # Minimal legacy source_health is intentionally not promoted; the
    # producer must provide the canonical health envelope before publication.
    assert not health_path.exists()
    market_path = tmp_path / "site" / "data" / "market.json"
    market = json.loads(market_path.read_text(encoding="utf-8"))
    market["source_health"] = {"status": "healthy", "sources": [], "event_scan": {"status": "no_event"}}
    market_path.write_text(json.dumps(market), encoding="utf-8")
    manifest = build_release_manifest(root=tmp_path)
    assert manifest["artifact_paths"]["source-health.json"] == "data/source-health.json"
    health = json.loads(health_path.read_text(encoding="utf-8"))
    assert health["market_snapshot_id"] == manifest["market_snapshot_id"]
    assert verify_release_files(manifest, root=tmp_path / "site") == []


def test_manifest_carries_backtest_release_state_without_unlocking_advice(tmp_path):
    _artifacts(tmp_path)
    data = tmp_path / "site" / "data"
    research_path = data / "research-report.json"
    research = json.loads(research_path.read_text(encoding="utf-8"))
    research["backtest_release_contract"] = {
        "backtest_release": "backtest-12345678",
        "publication_state": "blocked",
        "publish_eligible": False,
        "blocking_reasons": ["survivorship audit did not pass"],
        "strategy_registry": [{"strategy_id": "value", "strategy_version": "v1"}],
    }
    research_path.write_text(json.dumps(research), encoding="utf-8")

    manifest = build_release_manifest(root=tmp_path)

    assert manifest["status"] == "ready"
    assert manifest["backtest_release"] == "backtest-12345678"
    assert manifest["backtest_publication_state"] == "blocked"
    assert manifest["strategy_registry"][0]["strategy_id"] == "value"


def test_manifest_fails_closed_for_missing_artifact(tmp_path):
    _artifacts(tmp_path)
    (tmp_path / "site" / "data" / "event-ledger.json").unlink()
    manifest = build_release_manifest(root=tmp_path)
    assert manifest["status"] == "invalid"
    assert any("missing artifact" in item for item in manifest["validation_errors"])


def test_strict_manifest_rejects_legacy_research_artifact(tmp_path):
    _artifacts(tmp_path)
    manifest = build_release_manifest(root=tmp_path, require_production_research=True)
    assert manifest["status"] == "invalid"
    assert any("not a production scan" in item for item in manifest["validation_errors"])


def test_routine_manifest_computes_freshness_for_complete_production_research(tmp_path):
    _artifacts(tmp_path)
    data = tmp_path / "site" / "data"
    research_path = data / "research-report.json"
    research = json.loads(research_path.read_text(encoding="utf-8"))
    research.update({
        "generated_at": "2026-08-04T09:55:00+08:00",
        "scan_mode": "production", "scan_scope": "full",
        "publish_eligible": True, "production_eligible": True,
        "universe_expected": 1, "universe_scanned": 1,
        "universe_completed": 1, "universe_failed": 0,
        "research_run": {
            "run_id": "run-12345678", "scan_mode": "production",
            "scan_scope": "full", "source_commit_sha": "a" * 40,
            "producer": "pytest", "run_started_at": "2026-08-04T10:00:00+08:00",
            "run_finished_at": "2026-08-04T10:05:00+08:00",
        },
        "run_id": "run-12345678",
    })
    research_path.write_text(json.dumps(research), encoding="utf-8")
    manifest = build_release_manifest(root=tmp_path)
    assert manifest["status"] == "ready"
    assert manifest["research_freshness"] == "fresh"


def test_routine_manifest_marks_old_production_research_stale(tmp_path):
    _artifacts(tmp_path)
    data = tmp_path / "site" / "data"
    research_path = data / "research-report.json"
    research = json.loads(research_path.read_text(encoding="utf-8"))
    research.update({
        "generated_at": "2026-08-01T10:05:00+08:00",
        "scan_mode": "production", "scan_scope": "full",
        "publish_eligible": True, "production_eligible": True,
        "universe_expected": 1, "universe_scanned": 1,
        "universe_completed": 1, "universe_failed": 0,
        "research_run": {
            "run_id": "run-12345678", "scan_mode": "production",
            "scan_scope": "full", "source_commit_sha": "a" * 40,
            "producer": "pytest", "run_started_at": "2026-08-01T10:00:00+08:00",
            "run_finished_at": "2026-08-01T10:05:00+08:00",
        },
        "run_id": "run-12345678",
    })
    research_path.write_text(json.dumps(research), encoding="utf-8")
    manifest = build_release_manifest(root=tmp_path)
    assert manifest["status"] == "ready"
    assert manifest["research_freshness"] == "stale_fallback"


def test_strict_manifest_marks_explicit_stale_fallback(tmp_path):
    _artifacts(tmp_path)
    data = tmp_path / "site" / "data"
    research = json.loads((data / "research-report.json").read_text(encoding="utf-8"))
    research.update({
        "scan_mode": "production", "scan_scope": "full", "publish_eligible": True,
        "production_eligible": True, "universe_expected": 1, "universe_scanned": 1,
        "universe_completed": 1,
    })
    (data / "research-report.json").write_text(json.dumps(research), encoding="utf-8")
    manifest = build_release_manifest(
        root=tmp_path,
        require_production_research=True,
        allow_stale_research=True,
        research_fallback_reason="last-known-good research snapshot",
    )
    assert manifest["status"] == "invalid"
    assert manifest["research_fallback_used"] is True
    assert any("stale research fallback" in item for item in manifest["validation_errors"])


def test_allow_stale_research_converts_incomplete_scan_to_explicit_fallback(tmp_path):
    _artifacts(tmp_path)
    data = tmp_path / "site" / "data"
    research = json.loads((data / "research-report.json").read_text(encoding="utf-8"))
    research.update({
        "scan_mode": "production", "scan_scope": "bounded",
        "publish_eligible": False, "production_eligible": False,
        "universe_expected": 10, "universe_scanned": 3,
        "universe_completed": 3,
    })
    (data / "research-report.json").write_text(json.dumps(research), encoding="utf-8")
    manifest = build_release_manifest(
        root=tmp_path,
        allow_stale_research=True,
        research_fallback_reason="scan incomplete",
    )
    assert manifest["status"] == "invalid"
    assert manifest["research_fallback_used"] is True
    assert any("stale research fallback" in item for item in manifest["validation_errors"])
    stored = json.loads((data / "research-report.json").read_text(encoding="utf-8"))
    assert stored["publication_state"] == "fallback"
    assert stored["research_fallback_used"] is True


def test_strict_manifest_rejects_missing_production_timestamps(tmp_path):
    _artifacts(tmp_path)
    data = tmp_path / "site" / "data"
    research = json.loads((data / "research-report.json").read_text(encoding="utf-8"))
    research.update({
        "scan_mode": "production", "scan_scope": "full", "publish_eligible": True,
        "production_eligible": True, "universe_expected": 1, "universe_scanned": 1,
        "universe_completed": 1,
    })
    research.pop("generated_at", None)
    (data / "research-report.json").write_text(json.dumps(research), encoding="utf-8")
    manifest = build_release_manifest(root=tmp_path, require_production_research=True)
    assert manifest["status"] == "invalid"
    assert any("generated_at" in item for item in manifest["validation_errors"])


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


def test_manifest_helpers_cover_invalid_objects_and_gap_types(tmp_path):
    missing, error = _read_object(tmp_path / "missing.json")
    assert missing is None and "missing artifact" in error
    bad = tmp_path / "bad.json"
    bad.write_text("[]", encoding="utf-8")
    value, error = _read_object(bad)
    assert value is None and "must be an object" in error
    assert _gap_count(True) == 1
    assert _gap_count(2.0) == 2
    assert _gap_count({"a": 2, "b": 1.5}) == 3
    assert _gap_count("not-a-count") is None
    assert content_snapshot_id({}, "market").startswith("market-")
    payload = tmp_path / "payload"
    payload.write_bytes(b"abc")
    assert len(sha256_file(payload)) == 64


def test_manifest_normalizers_reconcile_provider_and_candidate_fields():
    market = {
        "indices": [{
            "ticker": "TPEx", "source_url": "https://www.tpex.org.tw/q",
            "source_label": "Yahoo", "quote_source": "Yahoo", "source_domain": "old.example",
            "quote_date": "2026-08-09", "technical_context": {"as_of": "2026-08-01"},
            "freshness": "live", "stale_used": True, "alert_eligible": True,
        }],
        "quotes": [],
    }
    notes = _normalize_market(market)
    quote = market["indices"][0]
    assert notes and quote["source_label"] == "TPEx"
    assert quote["source_domain"] == "tpex.org.tw"
    assert quote["freshness"] == "recent_close"
    assert quote["technical_context_stale"] is True
    research = {"sources": [{"candidates": 2, "formal_candidates": 3, "data_gap_counts": {"a": 1}}]}
    notes = _normalize_research(research)
    source = research["sources"][0]
    assert notes and source["visible_candidates"] == 2
    assert source["candidate_state"] == "data_gap"
    assert source["formal_candidates"] == 0


def test_verify_release_files_reports_missing_hash_and_path(tmp_path):
    errors = verify_release_files({"artifact_hashes": {"market.json": "x", "event.json": "y"}, "artifact_paths": {"market.json": "missing.json"}}, root=tmp_path)
    assert any("artifact missing" in item for item in errors)
    assert any("artifact missing" in item for item in errors)
    assert verify_release_files({"artifact_hashes": None, "artifact_paths": None}, root=tmp_path)


def test_verify_release_files_requires_all_core_artifacts(tmp_path):
    errors = verify_release_files(
        {
            "artifact_hashes": {"market.json": "a" * 64},
            "artifact_paths": {"market.json": "data/market.json"},
        },
        root=tmp_path,
    )
    assert "manifest hash missing: research-report.json" in errors
    assert "manifest path missing: research-report.json" in errors
    assert "manifest hash missing: event-ledger.json" in errors
    assert "manifest path missing: event-ledger.json" in errors


def test_manifest_read_object_rejects_invalid_json(tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text("{", encoding="utf-8")
    value, error = _read_object(path)
    assert value is None and "JSONDecodeError" in error


def test_manifest_normalizer_handles_non_lists_and_unknown_provider():
    market = {"indices": "invalid", "quotes": [{"source_url": "https://example.test/q", "source_label": ""}]}
    assert _normalize_market(market)
    assert market["quotes"][0].get("source_label") == ""
    assert _normalize_research({"sources": "invalid"}) == []


def test_manifest_normalizer_uses_declared_provider_when_url_is_absent():
    market = {
        "indices": [{
            "ticker": "TAIEX", "source_label": "TWSE",
            "quote_source": "TWSE MIS", "source_domain": "twse.com.tw",
        }],
        "quotes": [{"ticker": "BTC", "quote_source": "Yahoo Finance"}],
    }
    notes = _normalize_market(market)
    assert notes
    assert market["indices"][0]["source_label"] == "TWSE"
    assert market["quotes"][0]["source_label"] == "Yahoo"
