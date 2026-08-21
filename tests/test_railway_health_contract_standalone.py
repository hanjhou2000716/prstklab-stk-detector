from __future__ import annotations

from datetime import UTC, datetime
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "railway-monitor" / "health_contract.py"
SPEC = spec_from_file_location("railway_health_contract_standalone", MODULE_PATH)
assert SPEC and SPEC.loader
health = module_from_spec(SPEC)
SPEC.loader.exec_module(health)


def test_counter_parser_is_fail_closed():
    assert health.non_negative_int("3") == 3
    assert health.non_negative_int(True) is None
    assert health.non_negative_int(-1) is None
    assert health.non_negative_int("not-a-number") is None


def test_age_seconds_normalizes_naive_and_zulu_timestamps():
    now = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
    assert health.age_seconds("2026-08-14T11:59:00Z", now=now) == 60
    assert health.age_seconds("2026-08-14T11:59:00", now=now) == 60
    assert health.age_seconds("invalid", now=now) is None


def test_heartbeat_reports_stale_completed_cycle():
    now = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
    result = health.monitor_heartbeat(
        {
            "poll_interval_seconds": 120,
            "last_cycle_started_at": "2026-08-14T11:54:00Z",
            "last_cycle_completed_at": "2026-08-14T11:54:00Z",
        },
        now=now,
    )
    assert result["heartbeat_status"] == "stale"
    assert result["heartbeat_timeout_seconds"] == 300


def test_health_path_ignores_cache_busting_query():
    assert health.health_request_path("/health?ts=123") == "/health"
    assert health.health_request_path("") == "/"


def test_gmail_projection_excludes_transport_cursor():
    result = health.gmail_health_fields(
        {
            "watch": {
                "status": "healthy",
                "history_id": "private-history",
                "missing": [],
                "observability": {"last_received_at": "2026-08-14T11:59:00Z", "parser_error_count": 0},
            }
        }
    )
    assert result == {
        "watch_status": "healthy",
        "missing": [],
        "observability": {"last_received_at": "2026-08-14T11:59:00Z", "parser_error_count": 0},
    }
    assert "history_id" not in result


def test_gmail_projection_exposes_only_missing_configuration_names():
    result = health.gmail_health_fields(
        {"watch": {"status": "configuration_missing", "missing": ["GMAIL_WATCH_TOPIC", "", 7], "history_id": "private"}}
    )
    assert result["watch_status"] == "configuration_missing"
    assert result["missing"] == ["GMAIL_WATCH_TOPIC", "7"]
    assert "private" not in str(result)


def test_gmail_projection_keeps_operational_counters_without_transport_ids():
    result = health.gmail_health_fields(
        {
            "watch": {
                "status": "healthy",
                "watch_expiration": "2099-01-01T00:00:00+00:00",
                "observability": {
                    "queue_pending_count": 3,
                    "dead_letter_count": 2,
                    "history_cursor_present": True,
                    "last_ingress_at": "2026-08-14T11:59:00Z",
                    "last_sync_at": "2026-08-14T12:00:00Z",
                    "gmail_message_id": "must-not-leak",
                },
            }
        }
    )
    assert result["watch_expiration"] == "2099-01-01T00:00:00+00:00"
    assert result["observability"]["queue_pending_count"] == 3
    assert result["observability"]["dead_letter_count"] == 2
    assert result["observability"]["history_cursor_present"] is True
    assert "must-not-leak" not in str(result)
