from __future__ import annotations

from railway_monitor_runtime_config import configuration_health, delivery_shared_secret


def test_canonical_name_wins_during_migration() -> None:
    env = {
        "RAILWAY_STATUS_SHARED_SECRET": "canonical",
        "DELIVERY_STATUS_SHARED_SECRET": "legacy",
    }
    assert delivery_shared_secret(env) == "canonical"
    health = configuration_health(env)
    assert health["status"] == "healthy"
    assert health["active_name"] == "RAILWAY_STATUS_SHARED_SECRET"
    assert health["migration_required"] is False
    assert health["secret_values_exposed"] is False


def test_legacy_secret_is_supported_during_migration() -> None:
    env = {"DELIVERY_STATUS_SHARED_SECRET": "legacy"}
    assert delivery_shared_secret(env) == "legacy"
    health = configuration_health(env)
    assert health["status"] == "healthy"
    assert health["active_name"] == "DELIVERY_STATUS_SHARED_SECRET"
    assert health["migration_required"] is True


def test_missing_secret_fails_closed_without_secret_fields() -> None:
    health = configuration_health({})
    assert health == {
        "status": "configuration_missing",
        "delivery_secret_configured": False,
        "canonical_name_present": False,
        "legacy_name_present": False,
        "active_name": None,
        "migration_required": False,
        "secret_values_exposed": False,
    }


def test_blank_secret_is_not_treated_as_configured() -> None:
    env = {
        "RAILWAY_STATUS_SHARED_SECRET": "  ",
        "DELIVERY_STATUS_SHARED_SECRET": "\t",
    }
    assert configuration_health(env)["status"] == "configuration_missing"
