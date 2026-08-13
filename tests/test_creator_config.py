from src.creator_config import CreatorRuntimeConfig


def _env() -> dict[str, str]:
    return {
        "GMAIL_WATCH_LABEL_IDS": "Label_A, Label_B",
        "GOOGLE_CLOUD_PROJECT": "project-1",
        "PUBSUB_AUDIENCE": "https://railway.example/gmail/push",
        "PUBSUB_EXPECTED_SERVICE_ACCOUNT": "pubsub@example.iam.gserviceaccount.com",
        "CREATOR_MEDIA_ROOT": "/data/creator-media",
    }


def test_config_health_is_secret_safe_and_accepts_multiple_labels():
    config = CreatorRuntimeConfig.from_env(_env())
    health = config.health()
    assert health["status"] == "healthy"
    assert health["watch_label_count"] == 2
    assert health["secret_values_exposed"] is False


def test_oauth_and_dispatch_are_optional_until_runtime_is_enabled():
    config = CreatorRuntimeConfig.from_env(_env())
    assert "GMAIL_REFRESH_TOKEN" not in config.missing()
    assert "GMAIL_REFRESH_TOKEN" in config.missing(require_oauth=True)
    assert "CREATOR_DISPATCH_SHARED_SECRET" in config.missing(require_dispatch=True)


def test_missing_configuration_is_explicit():
    health = CreatorRuntimeConfig.from_env({}).health()
    assert health["status"] == "configuration_missing"
    assert "PUBSUB_AUDIENCE" in health["missing"]
