from src.adapters.catalog import build_adapter, build_adapter_catalog


def test_catalog_has_allowlisted_primary_and_discovery_sources():
    providers = {item["provider"] for item in build_adapter_catalog()}
    assert {"TWSE", "TAIFEX", "TPEx", "SEC", "GDELT"}.issubset(providers)


def test_catalog_publishes_shared_provenance_and_health_contract():
    specs = {item["provider"]: item for item in build_adapter_catalog()}
    twse = specs["TWSE"]
    assert twse["adapter_contract_version"] == 1
    assert {"provider", "source_url", "fetched_at", "observation_id"}.issubset(twse["provenance_fields"])
    assert {"status", "freshness", "data_quality_score", "alert_eligible"}.issubset(twse["health_fields"])
    assert twse["alert_policy"] == "crosscheck_required"
    assert specs["Yahoo"]["alert_policy"] == "display_only"


def test_catalog_declares_independent_secondary_market_sources():
    providers = {item["provider"] for item in build_adapter_catalog()}
    assert {"CoinGecko", "Stooq", "Nasdaq", "KOFIA"}.issubset(providers)
    specs = {item["provider"]: item for item in build_adapter_catalog()}
    assert specs["KOFIA"]["source_tier"] == "official"
    assert specs["Stooq"]["can_trigger_alert"] is False


def test_fred_and_eia_are_retired_but_historically_identifiable():
    specs = {item["provider"]: item for item in build_adapter_catalog()}
    assert specs["FRED"]["active"] is False
    assert specs["EIA"]["active"] is False
    assert specs["FRED"]["retired_reason"]
    assert specs["EIA"]["retired_reason"]


def test_sec_adapter_uses_repository_identifying_user_agent(monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    adapter = build_adapter("SEC", transport=lambda *args, **kwargs: None)
    assert "github.com/hanjhou2000716/prstklab-stk-detector" in adapter.config.user_agent


def test_unknown_provider_is_rejected_without_network_call():
    try:
        build_adapter("not-allowlisted")
    except KeyError as exc:
        assert "unknown public provider" in str(exc)
    else:
        raise AssertionError("unknown provider must be rejected")


def test_catalog_adapter_uses_opt_in_raw_observation_store(tmp_path, monkeypatch):
    monkeypatch.setenv("RAW_OBSERVATION_ROOT", str(tmp_path / "raw"))
    adapter = build_adapter("TWSE", transport=lambda *args, **kwargs: None)
    assert adapter.raw_store is not None
    assert adapter.raw_store.root == tmp_path / "raw"


def test_catalog_adapter_does_not_create_store_without_configuration(tmp_path, monkeypatch):
    monkeypatch.delenv("RAW_OBSERVATION_ROOT", raising=False)
    adapter = build_adapter("TWSE", transport=lambda *args, **kwargs: None)
    assert adapter.raw_store is None
    assert not (tmp_path / "raw").exists()
