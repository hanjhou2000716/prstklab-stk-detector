from src.adapters.catalog import build_adapter, build_adapter_catalog


def test_catalog_has_allowlisted_primary_and_discovery_sources():
    providers = {item["provider"] for item in build_adapter_catalog()}
    assert {"TWSE", "TAIFEX", "TPEx", "SEC", "GDELT"}.issubset(providers)


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
