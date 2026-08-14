"""P0-20 Railway health callback/restart safety contract tests."""

from src.railway_health_contract import normalize_railway_health


def test_p0_20_configuration_failures_are_not_restart_commands() -> None:
    result = normalize_railway_health(
        {"last_heartbeat_at": "2026-08-13T05:00:00Z", "components": {"callback": {"error_code": "http_403"}}},
        now="2026-08-13T05:01:00Z",
    )
    assert result["status"] == "configuration_missing"
    assert result["restart_recommended"] is False
    assert result["secret_values_exposed"] is False


def test_p0_20_rate_limit_is_bounded_retry_without_restart() -> None:
    result = normalize_railway_health(
        {
            "last_heartbeat_at": "2026-08-13T05:00:00Z",
            "components": {"callback": {"error_code": "http_429", "retry_after_seconds": 99999}},
        },
        now="2026-08-13T05:01:00Z",
    )
    assert result["status"] == "degraded"
    assert result["retryable"] is True
    assert result["restart_recommended"] is False
    assert result["components"]["callback"]["retry_after_seconds"] == 3600


def test_p0_20_stale_heartbeat_is_explicit_and_secret_free() -> None:
    result = normalize_railway_health(
        {"last_heartbeat_at": "2026-08-13T00:00:00Z", "components": {"poller": {"status": "healthy"}}},
        now="2026-08-13T05:00:00Z",
    )
    assert result["status"] == "stale"
    assert result["restart_recommended"] is True
    assert result["raw_error_included"] is False
