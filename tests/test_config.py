from src import config
from src.config import parse_chat_ids


def test_parse_chat_ids_prefers_multi_recipient_value_and_deduplicates():
    assert parse_chat_ids("100, 200\n100", "300") == ("100", "200", "300")


def test_production_settings_read_active_subscriptions_instead_of_legacy_ids(monkeypatch):
    monkeypatch.setenv("TELEGRAM_SUBSCRIPTIONS_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_CHAT_IDS", "legacy-id")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setattr(config, "fetch_active_chat_ids", lambda: ("100", "200"))

    settings = config.get_settings()

    assert settings.telegram_subscriptions_enabled is True
    assert settings.telegram_chat_ids == ("100", "200")
