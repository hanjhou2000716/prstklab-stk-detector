from src.artifact_contract import validate_market, validate_manifest, validate_release, validate_research


def _market(**overrides):
    quote = {
        "ticker": "TAIEX", "price": 100.0, "quote_date": "2026-08-04",
        "source_label": "TWSE", "quote_source": "TWSE MIS",
        "source_url": "https://mis.twse.com.tw/stock/api/getStockInfo.jsp",
        "fetched_at": "2026-08-04T10:00:00+08:00", "published_at": "2026-08-04T09:59:00+08:00",
        "freshness": "live", "stale_used": False, "quote_delayed": False,
    }
    return {"generated_at": "2026-08-04T10:00:00+08:00", "snapshot_id": "market-12345678", "indices": [quote], "quotes": [], "source_health": {}, **overrides}


def _research(**overrides):
    return {"schema_version": "2.0", "generated_at": "2026-08-04T10:00:00+08:00", "sources": [{"market": "taiwan", "strategy": "value", "scan_state": "complete", "status": "可用", "candidate_state": "available", "candidates": 5, "formal_candidates": 5}], "candidates": [], "health": {}, **overrides}


def _manifest():
    return {"release_id": "release-12345678", "created_at": "2026-08-04T10:00:00+08:00", "market_snapshot_id": "market-12345678", "research_snapshot_id": "research-12345678", "event_snapshot_id": "event-12345678", "policy_version": "1.0", "schema_versions": {"market": "1.0"}, "artifact_hashes": {"market.json": "abc"}, "status": "ready"}


def test_valid_release_passes_contract():
    research = _research(snapshot_id="research-12345678")
    assert validate_release(market=_market(), research=research, manifest=_manifest()) == []


def test_market_rejects_stale_live_and_source_mismatch():
    market = _market()
    market["indices"][0].update({"stale_used": True, "source_label": "TWSE", "source_url": "https://finance.yahoo.com/quote/%5ETWII"})
    errors = validate_market(market)
    assert any("stale_used" in error for error in errors)
    assert any("source_domain" in error for error in errors)


def test_research_rejects_formal_candidates_exceeding_candidates():
    errors = validate_research(_research(sources=[{"market": "us", "strategy": "value", "scan_state": "complete", "status": "可用", "candidates": 0, "formal_candidates": 5}]))
    assert any("formal_candidates" in error for error in errors)


def test_research_rejects_complete_scan_with_data_gap():
    errors = validate_research(_research(sources=[{
        "market": "us", "strategy": "value", "scan_state": "complete",
        "candidate_state": "data_gap", "data_gap": True,
        "candidates": 0, "formal_candidates": 0,
    }]))
    assert any("data_unavailable/data_gap" in error for error in errors)
    assert any("no_candidates and data_gap" in error for error in errors) is False


def test_release_rejects_mismatched_snapshot_ids():
    research = _research(snapshot_id="research-other")
    errors = validate_release(market=_market(), research=research, manifest=_manifest())
    assert any("research snapshot_id" in error for error in errors)


def test_manifest_requires_release_envelope():
    errors = validate_manifest({"release_id": "short"})
    assert errors
