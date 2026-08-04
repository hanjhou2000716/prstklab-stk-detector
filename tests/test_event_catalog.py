from src.event_catalog import alert_source_is_allowed, get_source, source_catalog, sources_for_category, validate_catalog


def test_catalog_has_official_and_discovery_tiers():
    rows = source_catalog()
    assert any(row["tier"] == "official" for row in rows)
    assert any(row["tier"] == "discovery" for row in rows)
    assert validate_catalog() == []


def test_discovery_source_never_triggers_without_second_source():
    assert alert_source_is_allowed("gdelt", official_confirmed=False, second_source_confirmed=False) is False
    assert alert_source_is_allowed("gdelt", official_confirmed=False, second_source_confirmed=True) is True
    assert alert_source_is_allowed("fed", official_confirmed=True, second_source_confirmed=False) is True


def test_category_lookup_and_unknown_source():
    assert get_source("ECB").source_id == "ecb"
    assert len(sources_for_category("central-bank", alert_only=True)) == 2
    assert get_source("unknown") is None