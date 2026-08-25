from src.artifact_contract import (
    _parse_time,
    validate_events,
    validate_manifest,
    validate_market,
    validate_release,
    validate_research,
    validate_source_catalog,
    validate_source_health,
)


def test_source_catalog_contract_rejects_duplicate_and_policy_mismatch():
    catalog = [{
        "provider": "TWSE", "can_trigger_alert": True,
        "adapter_contract_version": 1,
        "provenance_fields": ["provider"], "health_fields": ["status"],
        "alert_policy": "display_only",
    }, {
        "provider": "twse", "can_trigger_alert": False,
        "adapter_contract_version": 1,
        "provenance_fields": ["provider"], "health_fields": ["status"],
        "alert_policy": "crosscheck_required",
    }]
    errors = validate_source_catalog(catalog)
    assert any("duplicated" in error for error in errors)
    assert any("requires crosscheck_required" in error for error in errors)
    assert any("conflicts with crosscheck_required" in error for error in errors)


def test_source_catalog_contract_accepts_catalogued_adapter():
    assert validate_source_catalog([{
        "provider": "TWSE", "can_trigger_alert": True,
        "adapter_contract_version": 1,
        "provenance_fields": ["provider", "source_url"],
        "health_fields": ["status", "freshness"],
        "alert_policy": "crosscheck_required",
    }]) == []


def test_invalid_timestamp_fails_closed_without_crashing():
    assert _parse_time("not-an-iso-timestamp") is None


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


def _manifest(**overrides):
    digest = "a" * 64
    return {"release_id": "release-12345678", "created_at": "2026-08-04T10:00:00+08:00", "market_snapshot_id": "market-12345678", "research_snapshot_id": "research-12345678", "event_snapshot_id": "event-12345678", "policy_version": "1.0", "schema_versions": {"market": "1.0"}, "artifact_paths": {"market.json": "data/market.json", "research-report.json": "data/research-report.json", "event-ledger.json": "data/event-ledger.json"}, "artifact_hashes": {"market.json": digest, "research-report.json": digest, "event-ledger.json": digest}, "status": "ready", **overrides}


def test_valid_release_passes_contract():
    research = _research(snapshot_id="research-12345678")
    assert validate_release(market=_market(), research=research, manifest=_manifest()) == []


def test_market_rejects_stale_live_and_source_mismatch():
    market = _market()
    market["indices"][0].update({"stale_used": True, "source_label": "TWSE", "source_url": "https://finance.yahoo.com/quote/%5ETWII"})
    errors = validate_market(market)
    assert any("stale_used" in error for error in errors)
    assert any("source_domain" in error for error in errors)


def test_market_schema_accepts_provenance_and_crosscheck_fields():
    market = _market()
    quote = market["indices"][0]
    quote.update({
        "quote_source": "TWSE MIS official close",
        "source_domain": "mis.twse.com.tw",
        "quote_time": "2026-08-04T09:59:00+08:00",
        "crosscheck_sources": [{"provider": "TAIFEX", "source_url": "https://www.taifex.com.tw", "status": "observed"}],
        "technical_context": {"as_of": "2026-08-04T00:00:00+08:00", "technical_context_stale": True},
    })
    assert validate_market(market) == []


def test_market_schema_rejects_crosscheck_without_provider():
    market = _market()
    market["indices"][0]["crosscheck_sources"] = [{"status": "observed"}]
    assert any("provider" in error for error in validate_market(market))


def _source_health(**overrides):
    document = {
        "status": "partial",
        "sources": [{"key": "official_events", "status": "healthy", "semantic_state": "healthy"}],
        "event_scan": {"status": "no_event", "has_events": False},
        "observability": {"failure_count": 0, "no_event_count": 1},
    }
    document.update(overrides)
    return document


def test_source_health_accepts_explicit_scan_failed_state():
    health = _source_health(
        event_scan={"status": "scan_failed", "has_events": False, "detail": "timeout"},
        sources=[{"key": "official_events", "status": "scan_failed", "semantic_state": "failed"}],
    )
    assert not any("event_scan" in error for error in validate_source_health(health))


def test_source_health_rejects_no_event_when_core_scan_failed():
    health = _source_health(
        event_scan={"status": "no_event", "has_events": False},
        sources=[{"key": "official_events", "status": "partial", "semantic_state": "failed"}],
    )
    errors = validate_source_health(health)
    assert any("cannot coexist" in error for error in errors)


def test_source_health_allows_no_event_when_only_optional_source_failed():
    health = _source_health(
        event_scan={"status": "no_event", "has_events": False},
        sources=[
            {"key": "official_events", "role": "required_for_core", "status": "healthy", "semantic_state": "healthy"},
            {"key": "external_financialjuice", "role": "optional", "status": "failed", "semantic_state": "failed"},
        ],
    )
    errors = validate_source_health(health)
    assert not any("cannot coexist" in error for error in errors)


def test_source_health_rejects_scan_failed_with_events():
    health = _source_health(
        event_scan={"status": "scan_failed", "has_events": True},
    )
    errors = validate_source_health(health)
    assert any("has_events=true" in error for error in errors)


def test_source_health_history_rejects_inconsistent_sample_counts():
    health = _source_health(observability={
        "failure_count": 0,
        "no_event_count": 1,
        "history": {
            "retention_hours": 168,
            "max_samples": 2,
            "sample_count": 1,
            "windows": {
                "24h": {"sample_count": 2, "failure_count": 0, "no_event_count": 0, "stale_count": 0, "parser_error_count": 0, "state": "healthy"},
                "7d": {"sample_count": 1, "failure_count": 0, "no_event_count": 0, "stale_count": 0, "parser_error_count": 0, "state": "healthy"},
            },
            "samples": [],
        },
    })
    errors = validate_source_health(health)
    assert any("sample_count does not match" in error for error in errors)
    assert any("24h.sample_count exceeds" in error for error in errors)


def test_source_health_accepts_external_observability_contract():
    health = _source_health()
    health["sources"].append({
        "key": "external_financialjuice",
        "status": "partial",
        "semantic_state": "partial",
        "observability": {
            "last_received_at": "2026-08-14T01:02:03+00:00",
            "last_parsed_at": "2026-08-14T01:02:03+00:00",
            "parser_error_count": 1,
            "last_importance_ge8_at": "2026-08-14T01:02:03+00:00",
            "qualifying_item_count": 1,
            "pending_cluster_count": 1,
            "last_notification_decision": "pending_confirmation",
            "last_delivery_at": None,
        },
    })
    assert validate_source_health(health) == []


def test_source_health_accepts_railway_creator_and_financialjuice_lineage_fields():
    health = _source_health()
    health["sources"] = [
        {
            "key": "creator_public",
            "status": "partial",
            "semantic_state": "partial",
            "observability": {
                "morning_batch_count": 1,
                "daily_coverage_count": 2,
                "coverage_status": "partial",
                "morning_batch_state": "ready",
                "morning_batch_key": "creator-20260821-1030",
                "consensus_status": "ready",
                "last_release_id": "release-1",
                "last_snapshot_id": "creator-snapshot-1",
                "last_observation_id": "creator-observation-1",
                "last_telegram_delivery_at": "2026-08-21T01:02:03+00:00",
                "last_telegram_delivery_status": "delivered",
            },
        },
        {
            "key": "external_financialjuice",
            "status": "partial",
            "semantic_state": "partial",
            "observability": {
                "importance_gte_8_count": 1,
                "last_importance_gte_8_at": "2026-08-21T01:02:03+00:00",
                "decision": "pending_confirmation",
                "last_release_id": "release-1",
                "last_snapshot_id": "fj-snapshot-1",
                "last_observation_id": "fj-observation-1",
                "last_telegram_delivery_at": None,
                "last_telegram_delivery_status": "not_checked",
            },
        },
    ]
    assert validate_source_health(health) == []


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


def test_research_rejects_complete_scan_with_failed_records_or_incomplete_universe():
    errors = validate_research(_research(sources=[{
        "market": "taiwan", "strategy": "value", "scan_state": "complete",
        "candidate_state": "available", "candidates": 1, "visible_candidates": 1,
        "formal_candidates": 1, "requested_records": 10, "complete_records": 9,
        "failed_records": 1, "data_gap_counts": {"history": 1},
    }]))
    assert any("failed records" in error for error in errors)
    assert any("data gaps" in error for error in errors)
    assert any("universe is incomplete" in error for error in errors)


def test_research_accepts_structured_data_gap_counts_for_partial_scan():
    errors = validate_research(_research(sources=[{
        "market": "taiwan", "strategy": "value", "scan_state": "building",
        "candidate_state": "available_from_completed_records", "candidates": 1,
        "visible_candidates": 1, "formal_candidates": 1, "requested_records": 10,
        "complete_records": 9, "failed_records": 1,
        "data_gap_counts": {"history": 1},
    }]))
    assert errors == []


def test_research_publication_flags_require_production_full_scan():
    errors = validate_research(_research(
        scan_mode="smoke", scan_scope="bounded", publish_eligible=True,
        production_eligible=True,
    ))
    assert any("scan_mode=production" in error for error in errors)
    assert any("scan_scope=full" in error for error in errors)
    assert any("production_eligible=true" in error for error in errors)


def test_research_fallback_cannot_be_production_eligible():
    errors = validate_research(_research(
        scan_mode="production", scan_scope="full", publish_eligible=False,
        production_eligible=True, research_fallback_used=True,
    ))
    assert any("fallback cannot be production_eligible" in error for error in errors)


def _backtest_contract(**overrides):
    value = {
        "backtest_release": "backtest-12345678",
        "market": "taiwan",
        "publication_state": "ready",
        "publish_eligible": True,
        "strategy_registry": [{"strategy_id": "value"}],
        "research_only": True,
    }
    value.update(overrides)
    return value


def test_research_backtest_contract_requires_matching_ready_state():
    research = _research(
        backtest_release_status="ready",
        backtest_release_contract=_backtest_contract(publish_eligible=False),
    )
    errors = validate_research(research)
    assert any("ready backtest contract requires publish_eligible=true" in error for error in errors)


def test_ready_backtest_contract_requires_strategy_registry():
    research = _research(
        backtest_release_status="ready",
        backtest_release_contract=_backtest_contract(strategy_registry=[]),
    )
    errors = validate_research(research)
    assert any("ready backtest contract requires strategy_registry" in error for error in errors)


def test_ready_backtest_registry_requires_complete_provenance():
    document = _research(
        backtest_release_status="ready",
        backtest_release_contract=_backtest_contract(
            strategy_registry=[{"strategy_id": "value"}],
        ),
    )
    errors = validate_research(document)
    assert any("ready backtest strategy_registry.strategy_version is missing" in error for error in errors)


def test_candidate_strategy_must_be_present_in_ready_registry():
    research = _research(
        backtest_release_status="ready",
        backtest_release_contract=_backtest_contract(strategy_registry=[{"strategy_id": "momentum"}]),
        candidates=[{
            "ticker": "2330",
            "strategy": "value",
            "backtest_release": "backtest-12345678",
        }],
    )
    errors = validate_research(research)
    assert any("strategy is absent from ready backtest registry" in error for error in errors)


def test_research_backtest_contract_rejects_candidate_release_mismatch():
    research = _research(
        backtest_release_status="ready",
        backtest_release_contract=_backtest_contract(),
        candidates=[{
            "ticker": "2330",
            "backtest_release": "backtest-other",
            "backtest_release_contract": _backtest_contract(backtest_release="backtest-other"),
        }],
    )
    errors = validate_research(research)
    assert any("backtest_release does not match research contract" in error for error in errors)
    assert any("candidate contract release does not match research contract" in error for error in errors)


def test_research_blocked_backtest_cannot_unlock_candidate():
    research = _research(
        backtest_release_status="blocked",
        backtest_release_contract=_backtest_contract(
            publication_state="blocked", publish_eligible=False,
        ),
        candidates=[{
            "ticker": "2330",
            "backtest_release": "backtest-12345678",
            "backtest_release_contract": _backtest_contract(
                publication_state="blocked", publish_eligible=True,
            ),
        }],
    )
    errors = validate_research(research)
    assert any("candidate cannot be publish_eligible" in error for error in errors)


def test_research_unavailable_status_can_omit_contract_for_legacy_report():
    research = _research(backtest_release_status="unavailable")
    assert validate_research(research) == []


def test_release_rejects_mismatched_snapshot_ids():
    research = _research(snapshot_id="research-other")
    errors = validate_release(market=_market(), research=research, manifest=_manifest())
    assert any("research snapshot_id" in error for error in errors)


def test_research_rejects_candidate_count_semantic_mismatch():
    errors = validate_research(_research(sources=[{
        "market": "us", "strategy": "value", "scan_state": "complete",
        "candidate_state": "no_candidates", "candidates": 2,
        "visible_candidates": 1, "formal_candidates": 0,
    }]))
    assert any("candidates must equal visible_candidates" in error for error in errors)
    assert any("no_candidates requires" in error for error in errors)


def test_manifest_requires_release_envelope():
    errors = validate_manifest({"release_id": "short"})
    assert errors


def test_manifest_schema_requires_core_artifact_lineage():
    errors = validate_manifest({
        "release_id": "release-12345678",
        "created_at": "2026-08-04T10:00:00+00:00",
        "market_snapshot_id": "market-12345678",
        "research_snapshot_id": "research-12345678",
        "event_snapshot_id": "event-12345678",
        "policy_version": "1.0",
        "schema_versions": {},
        "artifact_hashes": {"market.json": "a" * 64},
        "status": "ready",
    })
    assert any("artifact_paths" in error for error in errors)
    assert any("research-report.json" in error for error in errors)


def test_manifest_rejects_absolute_or_escaping_artifact_paths():
    manifest = _manifest()
    manifest["artifact_paths"]["market.json"] = "../market.json"
    manifest["artifact_paths"]["research-report.json"] = "C:/outside/research.json"
    errors = validate_manifest(manifest)
    assert any("escapes release root" in error for error in errors)
    assert any("must be relative" in error for error in errors)


def test_manifest_rollback_requires_previous_release_identity():
    manifest = _manifest(status="rolled_back")
    assert any("rollback_release_id" in error for error in validate_manifest(manifest))
    manifest["rollback_release_id"] = "release-previous"
    assert validate_manifest(manifest) == []


def test_market_audit_normalizes_naive_and_aware_timestamps():
    market = _market()
    # A timezone-less timestamp is interpreted conservatively as UTC.
    market["indices"][0]["published_at"] = "2026-08-04T01:58:00"
    assert validate_market(market) == []


def _events():
    return {
        "schema_version": 1,
        "retention_days": 30,
        "events": {
            "event-12345678": {
                "canonical_key": "event-12345678",
                "event_type": "macro",
                "source_url": "https://www.federalreserve.gov/feeds/press_all.xml",
                "source_domain": "federalreserve.gov",
                "first_discovered_at": "2026-08-04T10:00:00+00:00",
                "updated_at": "2026-08-04T10:05:00+00:00",
                "last_reminded_at": None,
                "verified_sources": ["https://www.federalreserve.gov/feeds/press_all.xml"],
            }
        },
    }


def test_event_ledger_passes_contract():
    assert validate_events(_events()) == []


def test_event_ledger_rejects_provenance_and_time_conflicts():
    events = _events()
    item = events["events"]["event-12345678"]
    item["source_domain"] = "example.com"
    item["updated_at"] = "2026-08-04T09:00:00+00:00"
    errors = validate_events(events)
    assert any("source_domain" in error for error in errors)
    assert any("updated_at precedes" in error for error in errors)
