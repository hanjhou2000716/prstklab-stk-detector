from src.event_source_catalog import catalog_health, source_for


def test_discovery_source_cannot_trigger_alone():
    source = source_for("gdelt")
    assert source is not None
    assert source.can_trigger_alone is False


def test_catalog_keeps_unscanned_source_gap_visible():
    rows = catalog_health([{"key": "fed", "status": "healthy"}])
    gdelt = next(row for row in rows if row["key"] == "gdelt")
    assert gdelt["observed_status"] == "not_scanned"
    assert gdelt["data_gap"] == "source_not_scanned"

