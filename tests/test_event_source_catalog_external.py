from src.event_source_catalog import catalog_health, source_for, validate_catalog


def test_external_sources_are_registered_without_alert_authority():
    assert validate_catalog() == []
    assert source_for("financialjuice").can_trigger_alone is False
    assert source_for("gmail").tier == "transport"
    assert source_for("haojiao").tier == "editorial"


def test_missing_external_source_stays_not_scanned_not_no_event():
    rows = {row["key"]: row for row in catalog_health([], now=None)}
    assert rows["financialjuice"]["observed_status"] == "not_scanned"
    assert rows["financialjuice"]["data_gap"] == "source_not_scanned"
