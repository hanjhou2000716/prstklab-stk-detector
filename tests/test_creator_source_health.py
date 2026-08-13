from datetime import UTC, datetime

from src.creator_source_health import build_creator_source_health, merge_creator_sources


def test_creator_health_distinguishes_missing_config_from_empty_scan():
    checked = datetime(2026, 8, 13, tzinfo=UTC)
    missing = build_creator_source_health([], checked_at=checked, enabled=False, configured=False)
    empty = build_creator_source_health([], checked_at=checked, enabled=True, configured=True)
    assert {row["semantic_state"] for row in missing} == {"configuration_missing"}
    assert {row["status"] for row in empty} == {"no_event"}
    assert all("source_url" in row and "raw_body" not in row for row in missing)


def test_creator_health_reports_provider_records_and_parse_failure():
    rows = build_creator_source_health(
        [
            {"content_origin": "haojiao", "episode_key": "ep-1", "parse_status": "parsed"},
            {"content_origin": "gooaye", "episode_key": "ep-2", "parse_status": "unsupported_template"},
        ],
        checked_at=datetime(2026, 8, 13, tzinfo=UTC),
        enabled=True,
        configured=True,
    )
    by_provider = {row["provider"]: row for row in rows}
    assert by_provider["haojiao"]["status"] == "healthy"
    assert by_provider["gooaye"]["creator_health"] == "parse_failed"


def test_merge_creator_sources_keeps_core_failure_and_optional_config_separate():
    base = {
        "status": "healthy",
        "sources": [{"key": "market_quotes", "semantic_state": "healthy", "status": "healthy"}],
        "data_gaps": [],
        "runtime_failure_count": 0,
    }
    rows = build_creator_source_health([], checked_at=datetime.now(UTC), enabled=False, configured=False)
    merged = merge_creator_sources(base, rows)
    assert merged["runtime_failure_count"] == 0
    assert merged["configuration_missing_count"] == 2
    assert merged["status"] == "healthy"
