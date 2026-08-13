from src.railway_health_contract import normalize_railway_health


def test_healthy_recent_heartbeat_is_not_restartable():
    result = normalize_railway_health(
        {"last_heartbeat_at": "2026-08-13T05:00:00Z", "components": {"poller": {"status": "healthy"}}},
        now="2026-08-13T05:02:00Z",
    )
    assert result["status"] == "healthy"
    assert result["restart_recommended"] is False


def test_403_is_configuration_missing_and_not_restart():
    result = normalize_railway_health(
        {"last_heartbeat_at": "2026-08-13T05:00:00Z", "components": {"callback": {"error_code": "http_403"}}},
        now="2026-08-13T05:01:00Z",
    )
    assert result["status"] == "configuration_missing"
    assert result["restart_recommended"] is False


def test_429_is_retryable_degraded_with_bounded_hint():
    result = normalize_railway_health(
        {
            "last_heartbeat_at": "2026-08-13T05:00:00Z",
            "components": {"callback": {"error_code": "http_429", "retry_after_seconds": 99999}},
        },
        now="2026-08-13T05:01:00Z",
    )
    assert result["status"] == "degraded"
    assert result["retryable"] is True
    assert result["components"]["callback"]["retry_after_seconds"] == 3600


def test_old_heartbeat_is_stale_and_restart_recommendation_is_explicit():
    result = normalize_railway_health(
        {"last_heartbeat_at": "2026-08-13T00:00:00Z", "components": {"poller": {"status": "healthy"}}},
        now="2026-08-13T05:00:00Z",
    )
    assert result["status"] == "stale"
    assert result["restart_recommended"] is True
    assert result["secret_values_exposed"] is False
