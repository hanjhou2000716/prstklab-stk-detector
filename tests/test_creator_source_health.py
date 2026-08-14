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
    assert by_provider["haojiao"]["observability"]["observations"] == 1
    assert by_provider["gooaye"]["observability"]["parser_error_count"] == 1


def test_creator_health_observability_keeps_timestamps_and_delivery_state_public_safe():
    rows = build_creator_source_health(
        [{
            "content_origin": "haojiao",
            "parse_status": "parsed",
            "fetched_at": "2026-08-14T01:02:03Z",
            "last_parsed_at": "2026-08-14T01:03:03Z",
            "last_receipt_at": "2026-08-14T01:04:03Z",
            "gmail_message_id": "must-not-be-published",
        }],
        checked_at=datetime(2026, 8, 14, tzinfo=UTC),
        enabled=True,
        configured=True,
    )
    metrics = next(row["observability"] for row in rows if row["provider"] == "haojiao")
    assert metrics["last_parsed_at"] == "2026-08-14T01:03:03+00:00"
    assert metrics["last_delivery_at"] == "2026-08-14T01:04:03+00:00"
    assert "gmail_message_id" not in metrics


def test_merge_creator_sources_keeps_core_failure_and_optional_config_separate():
    base = {
        "status": "critical",
        "sources": [{"key": "market_quotes", "semantic_state": "failed", "status": "failed"}],
        "data_gaps": [{"source": "market", "key": "market_quotes", "issues": ["timeout"]}],
        "runtime_failure_count": 1,
    }
    rows = build_creator_source_health([], checked_at=datetime.now(UTC), enabled=False, configured=False)
    merged = merge_creator_sources(base, rows)
    assert merged["runtime_failure_count"] == 1
    assert merged["configuration_missing_count"] == 3
    assert merged["status"] == "critical"
