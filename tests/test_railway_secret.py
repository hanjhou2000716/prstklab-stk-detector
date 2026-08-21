from src.railway_secret import delivery_secret_health, delivery_shared_secret


def test_canonical_secret_wins_over_legacy():
    env = {
        "RAILWAY_STATUS_SHARED_SECRET": "canonical",
        "DELIVERY_STATUS_SHARED_SECRET": "legacy",
    }
    assert delivery_shared_secret(env) == "canonical"
    assert delivery_secret_health(env) == {
        "configured": True,
        "canonical_name_present": True,
        "legacy_name_present": True,
        "active_name": "RAILWAY_STATUS_SHARED_SECRET",
        "migration_required": False,
    }


def test_legacy_secret_remains_compatible_without_exposing_value():
    env = {"DELIVERY_STATUS_SHARED_SECRET": "legacy"}
    assert delivery_shared_secret(env) == "legacy"
    health = delivery_secret_health(env)
    assert health["configured"] is True
    assert health["active_name"] == "DELIVERY_STATUS_SHARED_SECRET"
    assert "secret_value" not in health
    assert health["legacy_name_present"] is True


def test_missing_or_blank_secrets_fail_closed():
    env = {"RAILWAY_STATUS_SHARED_SECRET": "  ", "DELIVERY_STATUS_SHARED_SECRET": "\t"}
    assert delivery_shared_secret(env) == ""
    assert delivery_secret_health(env)["configured"] is False
